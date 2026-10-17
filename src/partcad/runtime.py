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
import threading

import docker

from partcad_utils import container_service

from . import logging as pc_logging
from . import sandbox_lock
from .process_crash import describe_termination
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


def kill_process_tree(p, from_thread=False) -> None:
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
    is then signalled by its id rather than through ``p.kill()``, which polls
    the process first and could reap it under the loop's own child watcher.

    What is outside this machine is outside its reach: in the `docker` sandbox
    ``p`` is the `docker exec` client, and the interpreter it started lives in
    the container. That one is stopped from the inside, by the wrapper that runs
    it (see `wrappers/process_tree.py`), which is why a bound is passed to the
    wrapper as well as enforced out here.
    """
    pid = getattr(p, "pid", None)
    if pid is None:
        return
    children = []
    try:
        import psutil

        children = psutil.Process(pid).children(recursive=True)
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
        with contextlib.suppress(ProcessLookupError, OSError):
            if from_thread and os.name != "nt":
                os.kill(pid, signal.SIGKILL)
            elif not from_thread:
                p.kill()
    for child in children:
        with contextlib.suppress(Exception):
            child.kill()


async def communicate(p, stdin: bytes, timeout=None):
    """``p.communicate(stdin)``, bounded by ``timeout`` and never orphaning ``p``.

    Two things asyncio does not do for a subprocess it stops waiting for, and
    both have cost this project a wedged CI job.

    It does not bound the wait, so a sandbox interpreter that never finishes
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
    try:
        if timeout is None:
            return await p.communicate(input=stdin)
        fired = threading.Event()

        def backstop():
            fired.set()
            kill_process_tree(p, from_thread=True)

        timer = threading.Timer(timeout + BACKSTOP, backstop)
        timer.daemon = True
        timer.start()
        try:
            out = await asyncio.wait_for(p.communicate(input=stdin), timeout)
        finally:
            timer.cancel()
        if fired.is_set():
            # Killed by the backstop, which the loop may have seen as an exit
            # before it saw its own timer: it is the bound all the same.
            raise asyncio.TimeoutError()
        return out
    except BaseException:
        if p.returncode is None:
            kill_process_tree(p)
        raise


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
        params = {
            "stdin": base64.b64encode(stdin.encode("utf-8")).decode("utf-8") if stdin else None,
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
            pc_logging.debug("Output of %s: %s" % (cmd, stdout))
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
            returncode, stdout, stderr = self.endpoint.run(
                cmd,
                stdin=stdin,
                cwd=cwd,
                input_files=input_files,
                output_files=output_files,
                input_dirs=input_dirs,
            )
        else:
            argv, spawn_cwd, spawn_env = self._spawn(cmd, cwd, env)
            with sandbox_lock.process_slots.slot():
                p = subprocess.Popen(
                    argv,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=False,
                    encoding="utf-8",
                    # TODO(clairbee): creationflags=subprocess.CREATE_NO_WINDOW,
                    cwd=spawn_cwd,
                    env=spawn_env,
                )
                stdout, stderr = p.communicate(
                    input=stdin,
                    # TODO(clairbee): add timeout
                )
            returncode = p.returncode
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
            returncode, stdout, stderr = await self.endpoint.run_async(
                cmd,
                stdin=stdin,
                cwd=cwd,
                input_files=input_files,
                output_files=output_files,
                input_dirs=input_dirs,
                timeout=timeout,
            )
        else:
            argv, spawn_cwd, spawn_env = self._spawn(cmd, cwd, env)
            async with sandbox_lock.process_slots.slot_async():
                p = await asyncio.create_subprocess_exec(
                    *argv,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=False,
                    # TODO(clairbee): creationflags=subprocess.CREATE_NO_WINDOW,
                    cwd=spawn_cwd,
                    env=spawn_env,
                    **bounded_spawn_options(timeout),
                )
                stdout, stderr = await communicate(p, stdin.encode(), timeout)

            stdout = decode_output(stdout)
            stderr = decode_output(stderr)
            returncode = p.returncode
            return self._finished(cmd, stdout, stderr, returncode)

        return self._finished(cmd, stdout, stderr, returncode)
