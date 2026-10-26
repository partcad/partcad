#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-12-30
#
# Licensed under Apache License, Version 2.0.

import asyncio
import base64
import contextlib
import os
import signal
import subprocess
import tempfile
import threading

import docker

from partcad_utils import container_service, containers

from . import logging as pc_logging
from . import sandbox_lock
from .process_crash import describe_exit_code, describe_termination
from .process_output import decode as decode_output

# How long after its bound a run is killed from a thread of its own, in seconds,
# when the event loop has not done it by then (see `communicate`).
BACKSTOP = 5.0


def bounded_spawn_options(timeout=None) -> dict:
    """What to start a process with so that its bound can take down all of it.

    Nothing for a run with no bound, which starts as it always has. A run with
    one is started as a process group of its own -- a session on POSIX, a new
    process group on Windows -- because the bound is only as good as what it
    stops: a sandbox interpreter that started a simulator, and the simulator a
    server of its own, is three processes, and killing the first leaves the
    other two running with nothing left to stop them. In a group of its own,
    the whole of it is one thing to kill (see `kill_process_tree`), including a
    process its parent has already left behind.

    Only for a bounded run, deliberately. A process in a group of its own no
    longer receives the terminal's Ctrl-C directly; a bounded one does not need
    to, because the cancellation that Ctrl-C raises here is one of the ways out
    `communicate` kills it on.
    """
    if timeout is None:
        return {}
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}


def process_owner(p):
    """``p`` as `psutil` knows it -- its pid *and* when it started -- or ``None``.

    So that a kill later can tell ``p`` from a process that has been given its
    number since: a child watcher can reap ``p`` at any moment, and the pid,
    and with it the process group id it leads, is then free for the system to
    hand to anything else.

    That can already have happened by the time this is asked -- asyncio has
    its watcher on ``p`` before ``create_subprocess_exec`` returns, and
    ``p.returncode`` stays ``None`` until the loop hears of the exit -- so what
    is taken is checked to be a child of *this* process. A pid the system gave
    to somebody else since has another parent; until ``p`` is reaped, nothing
    else can have its pid.
    """
    if getattr(p, "returncode", None) is not None or getattr(p, "pid", None) is None:
        return None
    try:
        import psutil

        owner = psutil.Process(p.pid)
        # ppid() checks once more that the pid is still the process just read.
        return owner if owner.ppid() == os.getpid() else None
    except Exception:  # pylint: disable=broad-except
        return None


def kill_process_tree(p, from_thread=False, owner=None) -> None:
    """Kill ``p`` and everything it started, on every platform. Never raises.

    Three nets, because each catches what the others miss:

    * every descendant ``p`` has right now, found through `psutil` before
      anything is killed -- which is what reaches a child that moved itself
      into a process group of its own, as a simulator's server may;
    * the process group ``p`` leads, when it leads one (see
      `bounded_spawn_options`) -- which is what reaches a process whose parent
      has already exited, and which `psutil` can no longer place under ``p``;
    * and ``p`` itself, which on Windows is `taskkill /T` taking its tree.

    ``from_thread`` when called from a thread other than the event loop's: ``p``
    is then signalled through ``owner`` rather than through ``p.kill()``, which
    polls the process first and could reap it under the loop's own child watcher.

    ``owner`` is `process_owner` of ``p``, taken earlier. With it nothing is
    signalled unless it is still that process -- running, or exited and not yet
    reaped, which is what keeps its pid and its group id from being reused --
    because ``p.returncode`` does not say so: between a watcher reaping ``p``
    and the loop hearing of it, it is still ``None``, and a group id on its own
    is only a number. That leaves the instant between asking and signalling,
    which a reuse would need the whole pid space to wrap around in. (A Windows
    pid is not reused while ``p`` holds a handle to its process.)

    What is outside this machine is outside its reach: in the `docker` sandbox
    ``p`` is the `docker exec` client, and the interpreter it started lives in
    the container. That one is stopped from the inside, by the wrapper that runs
    it (see `wrappers/process_tree.py`), which is why a bound is passed to the
    wrapper as well as enforced out here.
    """
    pid = getattr(p, "pid", None)
    if pid is None:
        return
    with contextlib.suppress(Exception):
        if owner is not None and not owner.is_running():
            # Gone, and reaped: what has its number now is not ours.
            return
    children = []
    try:
        import psutil

        children = (owner or psutil.Process(pid)).children(recursive=True)
    except Exception:  # pylint: disable=broad-except
        # Gone already, or a psutil that cannot see it: the group is still there.
        pass
    if os.name == "nt":
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
    else:
        with contextlib.suppress(OSError):
            # Only a group it leads: an unbounded run shares PartCAD's own, and
            # killing that would be killing PartCAD.
            if os.getpgid(pid) == pid:
                os.killpg(pid, signal.SIGKILL)
    if getattr(p, "returncode", None) is None:
        # psutil's own errors are not OSErrors.
        with contextlib.suppress(Exception):
            if not from_thread:
                p.kill()
            elif owner is not None:
                # psutil checks once more that the pid is still this process.
                owner.kill()
    for child in children:
        with contextlib.suppress(Exception):
            child.kill()


def stdin_bytes(stdin) -> bytes:
    """What a sandbox process is handed on its standard input, as bytes.

    'stdin' is text, bytes, nothing, or a callable producing text or bytes. The
    callable is what a large request is passed as: it is called here, at the
    moment the process is started -- inside the process slot, after the
    environment lock and whatever was installed under it -- and not when the
    caller built the request. A render waiting for a slot then holds the request
    as the objects it is made of, which it holds anyway, rather than as a text of
    it beside them: four drawings of the LEGO car waiting their turn were 66 MB
    of text and 66 MB of bytes each, in the daemon, before any of them ran.
    """
    if callable(stdin):
        stdin = stdin()
    if not stdin:
        return b""
    if isinstance(stdin, str):
        return stdin.encode("utf-8")
    return bytes(stdin)


async def communicate(p, stdin: bytes, timeout=None):
    """``p.communicate(stdin)``, bounded by ``timeout``, never orphaning ``p``, and over when ``p`` is.

    Three things asyncio does not do for a subprocess it waits for, and a fourth
    that the bound needs; each has cost this project a wedged daemon or CI job.

    It waits for the *pipes* rather than for the process: ``communicate`` returns
    when standard output and standard error reach their end, and a pipe ends only
    when every process holding it has let go. Whatever a sandbox interpreter
    starts inherits both, so an interpreter killed by the out-of-memory killer
    while something it started lived on was waited for as long as that lived --
    forever, with no bound -- and with it the process slot, the environment's
    lock, the shape's lock and, in the daemon, the lock every request is served
    under. So the process is watched as well (`_watch`): once it has exited, its
    output is drained for `container_service.EXIT_GRACE`, whatever still holds
    it is stopped, and the pipes are closed from this end. The caller then sees
    the death -- ``p.returncode`` is the signal -- seconds after it happened,
    instead of a client giving up on a daemon that has stopped answering.

    Nor does it bound the wait, so a sandbox interpreter that never finishes
    holds its caller forever. ``timeout`` (seconds, ``None`` for no bound) is
    that bound, and raises ``asyncio.TimeoutError`` when it passes.

    And it does not kill the child when the await is cancelled -- by that
    timeout, by a Ctrl-C, or by a runner cancelling the job. The process keeps
    running, detached from anything that would reap it, which is what the
    "Terminate orphan process: pid (7107) (python)" lines at the end of a
    cancelled Actions run are. So kill it on the way out, whatever the way out
    is -- and with it everything it started, which outlives it otherwise (see
    `kill_process_tree`). The event loop's child watcher reaps it from there.

    And the bound must not need the event loop to be running, because a child
    can stop it: on macOS, CPython's threaded child watcher (3.14.8) takes a
    child that is *stopped* for one that has exited -- `waitid(WEXITED |
    WNOWAIT)` reports it -- and reaps it with a blocking `waitpid` in the loop's
    own thread, which then waits as long as the child stays stopped, timers and
    all. So a thread of its own kills the tree `BACKSTOP` seconds after the
    bound if nothing has by then; the child dies, the `waitpid` returns, and
    the run is reported as the timeout it is.
    """
    owner = process_owner(p)
    try:
        if timeout is None:
            return await _watch(p, stdin)
        fired = threading.Event()

        def backstop():
            fired.set()
            # Asked again when it could not be had at the start: it is checked
            # to be this process's child either way, so this cannot reach a
            # process that has been given the run's number since.
            current = owner or process_owner(p)
            if current is not None:
                kill_process_tree(p, from_thread=True, owner=current)

        timer = threading.Timer(timeout + BACKSTOP, backstop)
        timer.daemon = True
        timer.start()
        try:
            out = await _watch(p, stdin, timeout)
        finally:
            timer.cancel()
        if fired.is_set():
            # Killed by the backstop, which the loop may have seen as an exit
            # before it saw its own timer: it is the bound all the same.
            raise asyncio.TimeoutError()
        return out
    except BaseException:
        if p.returncode is None:
            kill_process_tree(p, owner=owner)
        raise


class OutputCapture:
    """Where a child's standard output and error go, and how they are read back. See 'output_capture'."""

    def __init__(self, stdout, stderr):
        self.stdout = stdout
        self.stderr = stderr

    def collect(self, stdout, stderr):
        """What the child wrote, given what 'communicate' returned: that, or the file's contents."""
        return self._read(self.stdout, stdout), self._read(self.stderr, stderr)

    @staticmethod
    def _read(target, read):
        if read is not None or target is subprocess.PIPE:
            return read
        target.seek(0)
        return target.read()


@contextlib.contextmanager
def output_capture(to_files: bool):
    """Pipes for a child's output, read as it arrives; or, 'to_files', two unnamed files read once it has gone.

    Pipes are what every runtime used, and they are fine for a child that writes
    to them itself. They are not for a 'docker exec' client, whose output is the
    end of a chain that Docker's daemon closes on its own clock: when the
    command in the container exits, the daemon gives the copying of what it
    wrote two seconds to finish, and then closes the streams, with whatever
    had not reached the client still in them. The command's exit status is
    still 0, and nothing is said on standard error.

    So the client has to be read promptly, and a pipe is read by whoever holds
    it -- for 'run_async', PartCAD's event loop, which a render or the decoding
    of another answer can keep busy for longer than that. Between the pipe,
    the sockets and the megabyte the daemon buffers before it makes the
    command wait, an answer of between about 1.4 and 2.4 MB is entirely
    written, and the command gone, before anybody has read any of it; one that
    is then not read for two seconds comes back cut off at a multiple of 8192
    bytes. A MuJoCo run reporting each body's loads in 799 samples is that
    size, and came back 1409024 bytes long. A file is written by the client as
    fast as the daemon sends, whatever PartCAD is doing.
    """
    if not to_files:
        yield OutputCapture(subprocess.PIPE, subprocess.PIPE)
        return
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        yield OutputCapture(stdout, stderr)


async def _watch(p, stdin: bytes, timeout=None):
    """``p.communicate(stdin)``, ended by ``p`` exiting as well as by its pipes ending.

    The asynchronous twin of `container_service.communicate`, and the same rule:
    a process that has exited gets `EXIT_GRACE` for its output to drain, what
    still holds that output then is stopped, and if the pipes have not ended
    after as long again they are closed from this end. Whatever had been read is
    the answer -- for a process that was killed, the traceback or the half an
    answer it got as far as, which is what says where it was.

    Polled, rather than awaiting ``p.wait()``: from Python 3.12 that resolves
    only once the pipes have closed, which is the very wait this is getting out
    of, while ``p.returncode`` is set the moment the child watcher reaps it.

    ``timeout`` raises `asyncio.TimeoutError` when it passes, as `wait_for` did.
    """
    loop = asyncio.get_running_loop()
    talking = asyncio.ensure_future(p.communicate(input=stdin))
    deadline = None if timeout is None else loop.time() + timeout
    exited = None
    try:
        while True:
            interval = container_service.WATCH_INTERVAL
            if deadline is not None:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise asyncio.TimeoutError()
                interval = min(interval, remaining)
            done, _ = await asyncio.wait({talking}, timeout=interval)
            if done:
                return talking.result()
            if p.returncode is None:
                continue
            if exited is None:
                exited = loop.time()
            elif loop.time() - exited >= container_service.EXIT_GRACE:
                break

        # Dead, and something it started is keeping its output open.
        popen = _popen_of(p)
        pipes = [getattr(popen, "stdout", None), getattr(popen, "stderr", None)] if popen is not None else []
        left = container_service.stop_holders(pipes)
        _report_left(p.pid, p.returncode, left)
        done, _ = await asyncio.wait({talking}, timeout=container_service.EXIT_GRACE)
        if not done:
            # Held by something this could not find or could not kill. Closing
            # the transport ends the pipes from this end: each reader is handed
            # the end of its stream, and 'communicate' returns what it read.
            transport = getattr(p, "_transport", None)
            if transport is not None:
                with contextlib.suppress(Exception):
                    transport.close()
            done, _ = await asyncio.wait({talking}, timeout=container_service.EXIT_GRACE)
        if done:
            return talking.result()
        return b"", b""
    finally:
        if not talking.done():
            talking.cancel()


def _popen_of(p):
    """The ``subprocess.Popen`` behind an asyncio process, whose pipes are the ones to look for; None if unreachable.

    asyncio keeps it on the transport, under the extra 'subprocess', and offers
    no public way to the transport; this is the one place that reaches for it.
    """
    transport = getattr(p, "_transport", None)
    if transport is None:
        return None
    try:
        return transport.get_extra_info("subprocess")
    except Exception:  # pylint: disable=broad-except
        return None


def _report_left(pid, returncode, left) -> None:
    """Say that a process ended and left something holding its output, once, as a warning.

    A warning rather than an error: what the process itself ended with is
    reported by whoever ran it, and that is the failure, if there is one. This
    is only where the wait went.
    """
    pc_logging.warning(
        "Process %s ended (%s), but %s it started kept its output open; %s, and the rest of its output is not "
        "waited for."
        % (
            pid,
            describe_exit_code(returncode),
            "%d process(es)" % len(left) if left else "something",
            "stopped " + ", ".join(str(held) for held in left) if left else "no longer reading it",
        )
    )


def communicate_sync(p, stdin: bytes = None):
    """``p.communicate(stdin)`` for a ``subprocess.Popen``, over when ``p`` is.

    The synchronous runs -- provisioning goes through them -- waited for the
    pipes exactly as the asynchronous ones did, and are held to the same rule
    (see `container_service.communicate`).
    """
    stdout, stderr, left = container_service.communicate(p, stdin)
    if left is not None:
        _report_left(p.pid, p.returncode, left)
    if getattr(p, "text_mode", False):
        # What was read before the wait was cut short is bytes even for a
        # text-mode Popen, which decodes only what it reads to the end; the
        # conda provisioning calls are text-mode, and expect text either way.
        return _text(stdout), _text(stderr)
    # Empty rather than None, which is what a pipe that was read to its end
    # gives and what every caller tests for -- but None where the output went
    # to a file rather than a pipe ('output_capture'), which is how
    # 'OutputCapture.collect' knows to read it from there.
    return _or_empty(stdout, p, "stdout"), _or_empty(stderr, p, "stderr")


def _or_empty(output, p, stream: str):
    """'output' as read from 'p''s 'stream': empty for nothing read, None where it was no pipe.

    A process that does not say what its stream was is taken to have had a pipe.
    """
    if output is None and getattr(p, stream, True) is not None:
        return b""
    return output


def _text(output) -> str:
    """Output as text, whichever of the two it arrived as."""
    if isinstance(output, bytes):
        return decode_output(output)
    return output or ""


def pack_directory(path: str) -> str:
    """A directory as a base64 gzipped tar, for sending to a container.

    What `input_files` cannot carry. Anything that runs *code* needs its
    siblings: an implementation script imports the module it shares with the
    rest of its package, and so does the wrapper that runs it, so sending the
    one file the command names leaves it unable to start.

    Deterministic where it can be: entries sorted, and the mtimes and ownership
    left out, so that packing the same directory twice produces the same bytes.
    That is not for reproducibility's sake -- nothing compares these -- but so
    that a diff between two runs is a difference in the package rather than in
    the clock.

    The gzip *wrapper* has an mtime of its own, and that is why this builds the
    two layers itself instead of asking `tarfile` for "w:gz": that mode hands
    `gzip.GzipFile` no mtime, so it stamps the current time into the header and
    two packs of one directory came out differing in bytes 4 through 8 and
    nowhere else. Every promise above was kept and the function was still not
    deterministic -- which `test_packing_is_deterministic` caught only when its
    two calls happened to straddle a second.
    """
    return container_service.pack_directory(path)


class SandboxUnavailable(Exception):
    """The sandbox mechanism an implementation asked for is not on this machine.

    Not a statement about the implementation, which may be perfectly good, nor
    about the part: it is the absence of a *runtime*, and PartCAD is the only
    thing that can tell, since the implementation never gets to run and so
    cannot report it itself.

    What `pc test` makes of it is not decided here but by the implementation:
    one that declares a `container:` or a `dockerImage` is saying that a
    container is how its dependencies arrive, so a machine with no container
    runtime is a machine that could never have run it, and the verdict is a
    skip. One that declares neither said it runs in an ordinary sandbox, and a
    machine with a working sandbox is a machine it was supposed to work on, so
    the verdict is a failure. What the type buys either way is the message:
    `CaeTest` and `SimTest` read it to add both remedies, which no other
    failure gets. See `partcad.test.implementation.ImplementationTest._verdict()`.
    """


def docker_available() -> bool:
    """Whether a container sandbox can be started here.

    Asked before an implementation that declares one is run, and again by
    `pc test` to decide whether it is looking at an unavailable runtime or a
    failing implementation. Cached: this shells out to the daemon, and a run
    over a package tree would otherwise ask once per part.

    Deliberately a real ping rather than "is the module importable" or "is
    /var/run/docker.sock there": the `docker` package installs with PartCAD on
    every platform, and a socket can exist with nothing behind it. The question
    is whether a container can be started, and only the daemon answers that.

    And not only that a container can be started -- that one of *ours* can.
    Every image PartCAD builds, pulls or documents is a Linux image, and a
    Docker daemon on Windows runs Windows containers unless it has been switched
    to the WSL2 backend. Such a daemon answers a ping perfectly happily and then
    fails every pull with "no matching manifest for windows/amd64", which is a
    container runtime by the letter of the question and not by its point. So the
    daemon is asked what it runs, once, in the same cached call.
    """
    global _docker_available
    if _docker_available is None:
        try:
            client = docker.from_env()
            client.ping()
            os_type = str(client.info().get("OSType", "")).lower()
            if os_type and os_type != "linux":
                pc_logging.debug(
                    "The container runtime on this machine runs %s containers, and every image PartCAD"
                    " uses is a Linux image." % os_type
                )
                _docker_available = False
            else:
                _docker_available = True
        except Exception as e:
            pc_logging.debug("No container runtime on this machine: %s" % e)
            _docker_available = False
    return _docker_available


# None until something asks. Not reset: a run that started without Docker and
# would have finished with it is not worth the ping per part.
_docker_available = None


def docker_enabled(config=None) -> bool:
    """Whether PartCAD may start a container here: allowed *and* possible.

    Two different questions, and everything that runs something in a container
    has to ask both. `useDocker` is the machine's owner saying whether PartCAD
    is to use containers at all -- a machine that has a daemon and should not
    be using it, or an image built without one, says so once here rather than
    failing per part. `docker_available` is whether one would start if PartCAD
    tried.

    Written once because the two were being combined by hand, in one place
    (`Context.preferred_python_sandbox`) and forgotten in the others, and a
    second spelling of "can we use Docker" is a second answer: the KiCad
    importer asked only the first half and went on to `docker.from_env()` on
    machines that had nothing to answer it, and `pc healthcheck` would have
    reported on a machine other than the one the parts render on.

    `config` is the user configuration to ask, for the callers that hold one --
    a daemon serves a context whose configuration is not this process's. The
    global one is the default, which is what a healthcheck and anything else
    outside a context wants.
    """
    if config is None:
        # Imported here rather than at the top of the module: `user_config`
        # builds the whole configuration on import, and `runtime` is imported
        # early enough that doing so from here would fix the order the two are
        # initialized in.
        from .user_config import user_config as config
    return bool(config.use_docker) and docker_available()


class Runtime:
    # Whether a child's output is collected in files rather than read from
    # pipes; see 'output_capture'.
    OUTPUT_TO_FILES = False

    @staticmethod
    def get_internal_state_dir(internal_state_dir):
        return os.path.join(
            internal_state_dir,
            "sandbox",
        )

    def __init__(self, ctx, name):
        self.ctx = ctx
        self.name = name
        self.sandbox_dir = "pc-" + name  # Leave "pc-" for UX (e.g. in VS Code)
        self.path = os.path.join(
            Runtime.get_internal_state_dir(self.ctx.user_config.internal_state_dir),
            self.sandbox_dir,
        )
        self.initialized = os.path.exists(self.path)

        # The container this runtime runs commands in, once it has one. See
        # 'use_container'.
        self.endpoint = None
        # Set when that container was found to have stopped, so the next
        # command starts it again first (see '_endpoint_ended').
        self._endpoint_stopped = False
        self._endpoint_guard = threading.Lock()

    def use_container(self, endpoint) -> None:
        """Run every command from now on in ``endpoint``'s container.

        Where that container came from -- its name, its image, whether files
        reach it by mount or by upload -- is `partcad_utils.containers`'s
        business and the caller's, not this class's. It used to be this class's:
        `use_docker()` found a container by a name it was handed and ran in
        whatever answered to it, which is how KiCad imports for one release ran
        in a container another release had made.
        """
        self.endpoint = endpoint

    def _endpoint_ended(self, endpoint, returncode, stderr):
        """A container command's ``(returncode, stderr)``, saying so when what failed was the container.

        A container is a sandbox process like any other: the out-of-memory
        killer takes the service in it as readily as an interpreter, and from
        then on every command sent to it comes back with no answer. So a failure
        asks whether the container still runs (`containers.stopped`); when it
        does not, how it stopped is added to the failure, and the next command
        starts it again instead of being sent to it (`_current_endpoint`).
        """
        if returncode == 0:
            return returncode, stderr
        why = containers.stopped(getattr(endpoint, "container", None))
        if why is None:
            return returncode, stderr
        with self._endpoint_guard:
            if self.endpoint is endpoint:
                self._endpoint_stopped = True
        note = "The '%s' container %s; it is started again for the next command." % (
            getattr(endpoint, "name", self.name),
            why,
        )
        return returncode, note if not stderr else stderr.rstrip() + "\n" + note

    def _current_endpoint(self):
        """The container to send a command to: the one in use, or -- if that one stopped -- it, started again.

        Started from the description it was made from, which is all
        `containers.acquire` needs: it finds the stopped container by name and
        starts it, or makes a new one where it is gone. Blocking, like every
        acquire, so the asynchronous run calls it off the event loop -- and only
        when there is something to start.
        """
        with self._endpoint_guard:
            if not self._endpoint_stopped:
                return self.endpoint
            stale = self.endpoint
        try:
            fresh = containers.acquire(stale.spec)
        except containers.ContainerUnavailable as e:
            raise SandboxUnavailable(str(e))
        with self._endpoint_guard:
            if self.endpoint is stale:
                self.endpoint = fresh
                self._endpoint_stopped = False
            return self.endpoint

    # ----------------------------------------------------------------- #
    # What 'run' and 'run_async' both do                                  #
    # ----------------------------------------------------------------- #
    #
    # They are the same command run two ways, and the parts that are not the
    # subprocess call are the same in both. They used to be written out twice,
    # and the copies had drifted: the container half of 'run_async' invented its
    # exit code from whether anything reached stderr, read 'p.returncode' where
    # 'p' does not exist, sent its standard input unencoded to a server that
    # decodes base64, and returned two values on one path out of three. None of
    # that was noticed because no implementation ran in a container until now.
    # One copy of each is what keeps them from drifting again.

    def _rpc_params(self, stdin, cwd, input_files, output_files, input_dirs, output_dirs=None):
        """The parameters a container is asked with.

        'stdin' is base64 because the server decodes it as base64, which is not
        obvious from either end: 'base64.b64decode' does not refuse text that is
        not base64 -- it drops every character outside the alphabet and decodes
        what is left -- so an unencoded request arrives as noise rather than as
        an error.
        """
        file_contents = {}
        for file_path in input_files:
            with open(file_path, "rb") as f:
                file_contents[file_path] = base64.b64encode(f.read()).decode("utf-8")
        data = stdin_bytes(stdin)
        params = {
            "stdin": base64.b64encode(data).decode("utf-8") if data else None,
            "cwd": cwd,
            "input_files": file_contents,
            "output_files": output_files,
            "input_dirs": {path: pack_directory(path) for path in input_dirs},
        }
        if output_dirs:
            params["output_dirs"] = list(output_dirs)
        return params

    def _rpc_result(self, response, output_files, output_dirs=None):
        """What a container answered, as (stdout, stderr, exit code).

        The output files it produced are written where the caller asked for
        them, which is the point of naming them: the file was written inside the
        container, under a name of the container's choosing. So are the output
        directories, for a command whose results are whatever it wrote into one
        -- a simulation plugin's pictures -- rather than a file it was told the
        name of.
        """
        result = response["result"]
        stdout = result["stdout"]
        stdout = base64.b64decode(stdout).decode("utf-8") if stdout else None
        stderr = result["stderr"]
        stderr = base64.b64decode(stderr).decode("utf-8") if stderr else None
        for file_name, file_contents in (result.get("output_files") or {}).items():
            if file_name in output_files:
                with open(file_name, "wb") as f:
                    f.write(base64.b64decode(file_contents))
            else:
                pc_logging.error(f"Unsolicited output file: {file_name}")
        for directory, archive in (result.get("output_dirs") or {}).items():
            if directory in (output_dirs or []):
                os.makedirs(directory, exist_ok=True)
                container_service.unpack_directory(archive, directory)
            else:
                pc_logging.error(f"Unsolicited output directory: {directory}")
        # What the command exited with, which the server reports. The fallback
        # is for an image built before it did, and is what this used to do for
        # every container: read any stderr at all as a failure.
        returncode = result.get("exit_code")
        return stdout, stderr, int(bool(stderr)) if returncode is None else returncode

    def _finished(self, cmd, stdout, stderr, returncode):
        """The triple every run returns, having reported what was written.

        Anything on stderr from a command that succeeded is a warning and is
        cleared: a library that prints is not a library that failed, and a
        wrapper's sandbox deliberately moves everything that prints onto stderr
        so that it cannot corrupt the response (see wrappers/wrapper_common.py).
        That makes the exit code the only thing that says whether a run worked.

        And when it says the process was killed rather than that it ended, that
        is said in words rather than left as the bare number the caller would
        otherwise report: which signal it was, and what that signal is called
        (see process_crash).
        """
        if stdout:
            pc_logging.debug("Output of %s: %s", cmd, stdout)
        if stderr:
            # TODO(azhar): remove this when the issue is fixed
            keywords = [
                "DEPRECATION: Wheel filename",
                "Invalid wheel filename (invalid version):",
                "pip 25.3 will enforce this behaviour change.",
            ]
            stderr_lines = [
                line.strip()
                for line in stderr.splitlines()
                if line.strip() and not any(keyword in line for keyword in keywords)
            ]
            if stderr_lines:
                stderr = "\n".join(stderr_lines)
                if returncode == 0:
                    pc_logging.warning("%s produced stderr: %s" % (cmd, stderr))
                    stderr = ""
                else:
                    pc_logging.error("Error in %s: %s" % (cmd, stderr))
            else:
                stderr = ""

        # [Temporary Fix] Ignore exit code 3221226356(0xc0000374) and 3221225477(0xc0000005)
        # This is a known and open issue on Windows related to the cadquery import
        # For more information, see: https://github.com/CadQuery/cadquery/issues/1564
        if returncode in [3221226356, 3221225477]:
            returncode = 0
        else:
            crash = describe_termination(
                cmd,
                returncode,
                where=self.path,
                silent=not stdout and not stderr,
            )
            if crash:
                stderr = crash if not stderr else stderr.rstrip() + "\n" + crash
        return returncode, stdout, stderr

    @staticmethod
    def _no_response(name):
        """Three values, like every other way out of a run.

        Two was an unpacking error at the call site rather than the report that
        a container answered nothing, which is a failure like any other.
        """
        return 1, None, "The container serving '%s' returned no response" % name

    def _spawn(self, cmd, cwd=None, env=None):
        """What to actually launch: the argv, the directory, the environment.

        The one seam a sandbox overrides when the process it wants is not the
        process it was handed. The 'docker' sandbox turns the argv into a
        'docker exec' of the same argv, and moves the working directory into a
        '-w' flag, because that directory belongs to the container rather than
        to whichever machine the 'docker' client runs on.

        It has to be here, and applied at every launch point, because there are
        two: this class runs a command with 'subprocess', and 'PythonRuntime'
        runs one with its own 'subprocess' call after prepending an interpreter.
        A sandbox that overrode a 'run' method instead would catch whichever of
        the two its caller happened to use -- which is how the 'docker' sandbox
        came to build its virtual environment with the host's interpreter while
        a container sat beside it doing nothing.
        """
        return cmd, cwd, env

    def _ended(self, returncode, stderr):
        """How a process this runtime launched ended, as the rest of PartCAD is to read it.

        The other seam a sandbox overrides when what it launched is not what
        ran: ``(returncode, stderr)`` back, unchanged here. The 'docker' sandbox
        launches a 'docker exec' client, which reports a death by signal inside
        the container the way a shell does, as 128 plus the signal, and whose
        failure can be the container itself having stopped -- both of which are
        for it to say, and both of which every launch point has to ask, the two
        here and the two in 'PythonRuntime'.
        """
        return returncode, stderr

    async def _ended_async(self, returncode, stderr):
        """'_ended', from a coroutine: off the event loop when the process failed.

        Asking whether a container has stopped is a synchronous request to
        Docker's daemon, and a slow or wedged one would hold every coroutine on
        the loop for as long as it takes. A success asks nothing, so it stays
        here.
        """
        if returncode == 0:
            return self._ended(returncode, stderr)
        return await asyncio.get_running_loop().run_in_executor(None, self._ended, returncode, stderr)

    def run(
        self,
        cmd: list[str],
        stdin: str = None,
        cwd: str = None,
        input_files: list[str] = None,
        output_files: list[str] = None,
        env: dict = None,
        input_dirs: list[str] = None,
    ):
        # 'env' replaces this process's environment for the child, and is only
        # ever passed by a runtime that has to place something of its own on it
        # (see JavaScriptRuntime._subprocess_env(), which puts the sandbox's
        # Node.js on PATH so that the 'npm' script's '#!/usr/bin/env node' finds
        # it). It has no counterpart in the RPC path below: what a remote
        # executor's environment should be is that executor's business.
        if input_files is None:
            input_files = []
        if output_files is None:
            output_files = []
        if input_dirs is None:
            input_dirs = []

        if self.endpoint is not None:
            endpoint = self._current_endpoint()
            # A call into a container is a wrapper call like any other, and takes
            # a process slot like any other (see 'partcad.admission'): without
            # one, a recursive render fanned out into the container unbounded.
            with sandbox_lock.process_slots.slot():
                returncode, stdout, stderr = endpoint.run(
                    cmd,
                    # Resolved here like at every other launch point: a container's
                    # request may be the callable that writes it (see 'stdin_bytes').
                    stdin=stdin_bytes(stdin) or None,
                    cwd=cwd,
                    input_files=input_files,
                    output_files=output_files,
                    input_dirs=input_dirs,
                )
            returncode, stderr = self._endpoint_ended(endpoint, returncode, stderr)
        else:
            argv, spawn_cwd, spawn_env = self._spawn(cmd, cwd, env)
            with sandbox_lock.process_slots.slot():
                # Bytes, decoded by 'process_output', like every other launch
                # point: what 'communicate_sync' hands back from a process it
                # stopped waiting for is the bytes read so far, and a text-mode
                # Popen would have mixed the two.
                p = subprocess.Popen(
                    argv,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=False,
                    # TODO(clairbee): creationflags=subprocess.CREATE_NO_WINDOW,
                    cwd=spawn_cwd,
                    env=spawn_env,
                )
                stdout, stderr = communicate_sync(p, stdin_bytes(stdin) or None)
            stdout = decode_output(stdout)
            stderr = decode_output(stderr)
            returncode, stderr = self._ended(p.returncode, stderr)
            return self._finished(cmd, stdout, stderr, returncode)

        return self._finished(cmd, stdout, stderr, returncode)

    async def run_async(
        self,
        cmd: list[str],
        stdin: str = None,
        cwd: str = None,
        input_files: list[str] = None,
        output_files: list[str] = None,
        env: dict = None,
        timeout: float = None,
        input_dirs: list[str] = None,
    ):
        if input_files is None:
            input_files = []
        if output_files is None:
            output_files = []
        if input_dirs is None:
            input_dirs = []

        if self.endpoint is not None:
            endpoint = self.endpoint
            if self._endpoint_stopped:
                endpoint = await asyncio.get_running_loop().run_in_executor(None, self._current_endpoint)
            # A slot, as in 'run'.
            async with sandbox_lock.process_slots.slot_async():
                returncode, stdout, stderr = await endpoint.run_async(
                    cmd,
                    stdin=stdin_bytes(stdin) or None,
                    cwd=cwd,
                    input_files=input_files,
                    output_files=output_files,
                    input_dirs=input_dirs,
                    timeout=timeout,
                )
            if returncode != 0:
                # Off the loop: '_endpoint_ended' asks Docker whether the
                # container stopped (see '_ended_async').
                returncode, stderr = await asyncio.get_running_loop().run_in_executor(
                    None, self._endpoint_ended, endpoint, returncode, stderr
                )
        else:
            argv, spawn_cwd, spawn_env = self._spawn(cmd, cwd, env)
            async with sandbox_lock.process_slots.slot_async():
                with output_capture(self.OUTPUT_TO_FILES) as capture:
                    p = await asyncio.create_subprocess_exec(
                        *argv,
                        stdin=subprocess.PIPE,
                        stdout=capture.stdout,
                        stderr=capture.stderr,
                        shell=False,
                        # TODO(clairbee): creationflags=subprocess.CREATE_NO_WINDOW,
                        cwd=spawn_cwd,
                        env=spawn_env,
                        **bounded_spawn_options(timeout),
                    )
                    stdout, stderr = capture.collect(*await communicate(p, stdin_bytes(stdin), timeout))

            stdout = decode_output(stdout)
            stderr = decode_output(stderr)
            returncode, stderr = await self._ended_async(p.returncode, stderr)
            return self._finished(cmd, stdout, stderr, returncode)

        return self._finished(cmd, stdout, stderr, returncode)
