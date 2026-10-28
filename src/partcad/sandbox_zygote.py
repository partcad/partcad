#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Wrappers forked from an interpreter that has imported the CAD stack already: the runtime's half.

Every wrapper call used to start a fresh interpreter, and that start is most of
what a small call costs: in a provisioned sandbox a bare interpreter is 28 ms,
OCP takes it to 1.45 s and build123d to 5 s or more, while the request and the
answer of a 2.3 MB part take 13 ms between them. So a local Python sandbox keeps
one interpreter per environment that has done those imports once
(`wrappers/zygote.py`, which documents the protocol and what a child is), and a
call is a fork of it: "build a box, write its BREP" is 57 ms that way, against
5.6 s fresh.

What stays as it was is everything the runtime does around a process. The
child's standard streams are pipes this module makes and the runtime reads,
exactly as it reads a process it started -- the wire format of a wrapper is not
this module's business. `ZygoteProcess` stands in for the
`asyncio.subprocess.Process` there would have been, with as much of its
interface as `runtime.communicate` uses: its pid, its exit status (the zygote
reports it, signal included, which `process_crash` then describes), `kill()`,
and its pipes for `container_service.pipe_holders`. A bounded run still leads a
session of its own, so `runtime.kill_process_tree` still takes the whole of it;
`runtime.process_owner` checks the child's parent is the zygote rather than this
process. And the child is a descendant of this process, so whatever counts what
a daemon started -- `psutil`'s children, recursively -- counts it, with the
zygote itself beside it.

**One zygote per environment, interpreter, flags and environment variables**
(`_key`), process-wide like `sandbox_lock`'s locks: it is the environment that
is expensive to import, not a runtime object, and a daemon makes runtimes afresh.
Each variable is part of the key because a child cannot change what its
interpreter was started with -- the hash seed, a library path, a locale.

**Started in the background, and never waited for.** An environment's
`WARM_AFTER`-th call starts one, in a thread of its own that takes the
environment's lock for reading and a process slot, as a call would; that call,
and every call until the zygote is ready, starts the ordinary way. So no call
is slower than it was, and a command that makes a single call never pays for
the zygote's larger import. An environment that cannot have one -- something
in `PRELOAD` fails to import, or starts a thread -- is said so once, and runs a
fresh interpreter per call as before until its files change or `RETRY` has
passed.

**Retired** whenever what it imported may have changed under it, because a
zygote holding an OCP module that has since been overwritten on disk is exactly
what the install guards in `runtime_python` exist to prevent: by `retire()`,
which every install into an environment calls (`PythonRuntime.record_install`),
and by `Zygote.stale()`, which every call asks -- a stat of each directory and
file the zygote imported from, which is how an install by *another* process, or
an edited wrapper module, retires it too. It also goes on its own after `IDLE`
seconds without a request, and with the process that started it: its control
socket is the one thing it inherits, and an end of file there is its signal.
The next call starts another.

**Any failure is a fresh interpreter for that call.** No zygote, a dead one, a
refusal, a message that never comes: the call starts the ordinary way, and the
only cost is the time a zygote did not save. Nothing is run twice, because the
zygote's "pid" message is the line: before it nothing was started, and the
request's socket closing kills whatever was.

**Linux only** (`supported`). macOS forbids, in effect, a fork that is not
followed by an exec once some system frameworks are loaded -- they abort, or
deadlock, in the child -- and the CAD stack loads them; Windows has no fork.
Both start a fresh interpreter per call, as they always did. `pythonSandboxZygote`
(`PC_PYTHON_SANDBOX_ZYGOTE`) turns it off on Linux too. Container sandboxes are
not served by one either: in `docker` every call is a `docker exec`, and a
zygote inside the container is a change of its own (see `src/partcad/AGENTS.md`).
"""

import asyncio
import contextlib
import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time

from . import logging as pc_logging
from . import sandbox_lock

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wrappers", "zygote.py")

# Must match 'wrappers/zygote.py'. Both are this release's, except in a checkout
# whose files moved under a daemon that is still running the old code.
PROTOCOL = 1

# How long a zygote waits for a request before it exits, in seconds. What it
# holds is memory: the CAD stack, imported, a few hundred megabytes of which its
# children share rather than copy.
IDLE = 600.0

# How long a zygote may take to import its stack, in seconds: a fresh
# interpreter takes five or six on a warm disk, and a cold one many times that.
START_TIMEOUT = 300.0

# How long a request may wait for the zygote to say it has forked, in seconds.
# A fork takes milliseconds; this is for a zygote that has stopped answering.
SPAWN_TIMEOUT = 60.0

# How many calls an environment has before a zygote is started for it. The
# second, so that a command making one call -- 'pc info' of a part, a test of
# one -- never pays for a zygote it would not use: starting one imports more
# than any one wrapper does.
WARM_AFTER = 2

# How many zygotes one process keeps: one per environment it runs wrappers in,
# and most commands use one or two -- the sandbox's own and a package's v-env.
# Each holds the CAD stack resident: some 700 MB, 400 MB of it its own and the
# rest shared with its children.
MAX_ZYGOTES = 2

# How long a zygote has to have gone unused before it gives way to another
# environment's, in seconds.
EVICT_AFTER = 60.0

# How long an environment that could not have a zygote goes without being
# asked again, in seconds, when none of its files have changed in between.
RETRY = 600.0

# How long a reply socket's message may be.
_MAX_MESSAGE = 1 << 16

# How long a zygote that was not started is given to exit by itself, in seconds.
_REFUSED_EXIT = 5.0

# What a zygote imports, when not its own 'PRELOAD'. Only ever set by a test,
# whose interpreter is not a sandbox's and has no business importing a CAD stack.
PRELOAD = None


def supported() -> bool:
    """Whether wrappers can be forked from a zygote on this machine at all.

    Linux, and an interpreter that can pass descriptors over a socket. See the
    module docstring for why nowhere else.
    """
    return sys.platform.startswith("linux") and hasattr(socket, "send_fds") and hasattr(os, "fork")


def script_index(argv, flags):
    """Where the script is in ``argv`` when ``argv`` is ``<interpreter> <flags> <script.py> ...``, else None.

    Only that form is forked: a ``-m`` or ``-c`` command, or one with flags of
    its own, is not a wrapper, and is started the ordinary way.
    """
    index = 1 + len(flags)
    if len(argv) <= index or list(argv[1:index]) != list(flags):
        return None
    script = str(argv[index])
    if script.startswith("-") or not script.endswith(".py"):
        return None
    return index


def _key(environment, interpreter, flags, env, preload=None):
    digest = hashlib.sha256()
    for name, value in sorted(env.items()):
        digest.update(name.encode("utf-8", "surrogateescape") + b"\0")
        digest.update(value.encode("utf-8", "surrogateescape") + b"\0")
    return (
        os.path.normpath(environment),
        interpreter,
        tuple(flags),
        digest.hexdigest(),
        None if preload is None else tuple(preload),
    )


def _stamp(paths):
    """What 'paths' are on disk now, as one comparable value."""
    stamp = []
    for path in paths:
        try:
            status = os.stat(path)
        except OSError:
            stamp.append(None)
            continue
        stamp.append((status.st_mtime_ns, status.st_ino, status.st_size))
    return tuple(stamp)


def _as_stamp(value):
    """A stamp as `wrappers/zygote.py` sends it -- a list, or null -- as `_stamp` makes one."""
    return None if value is None else tuple(value)


def _send(sock, message, fds=()):
    data = json.dumps(message).encode("utf-8")
    if fds:
        socket.send_fds(sock, [data], list(fds))
    else:
        sock.send(data)


def _receive(sock, max_fds=1):
    """One message and its descriptors; ``(None, [])`` at the end of the stream."""
    data, fds, flags, _ = socket.recv_fds(sock, _MAX_MESSAGE, max_fds)
    if not data or flags & (getattr(socket, "MSG_TRUNC", 0) | getattr(socket, "MSG_CTRUNC", 0)):
        for fd in fds:
            _close(fd)
        return None, []
    return json.loads(data.decode("utf-8")), fds


def _close(fd):
    if fd is None:
        return
    with contextlib.suppress(OSError):
        os.close(fd)


async def _readable(loop, fd, timeout=None):
    """Until ``fd`` can be read, or ``timeout`` seconds (raising `asyncio.TimeoutError`)."""
    ready = loop.create_future()

    def wake():
        if not ready.done():
            ready.set_result(None)

    loop.add_reader(fd, wake)
    try:
        await asyncio.wait_for(ready, timeout)
    finally:
        loop.remove_reader(fd)


class Zygote:
    """One zygote: the process, its control socket, and what it was imported from."""

    def __init__(self, key, environment, interpreter, flags, env, preload=None):
        self.key = key
        self.environment = os.path.normpath(environment)
        self.command = [interpreter, *flags, SCRIPT]
        self.env = env
        self.preload = preload
        # Set once the start is over, however it went; 'usable' says how.
        self.ready = threading.Event()
        self.usable = False
        self.reason = None
        self.popen = None
        self.pid = None
        self.control = None
        self.preloaded = []
        self.watch = []
        self.stamp = None
        self.last_used = time.monotonic()
        self.retired = False
        # Set when a failed start is worth trying again at once.
        self.retry = False
        # Sends on the control socket, and closing it, one at a time: calls
        # arrive from several threads, each running an event loop of its own.
        self._guard = threading.Lock()
        self._log = None

    # ------------------------------------------------------------- start --

    def start(self) -> None:
        """Start the zygote and wait for it to say whether it is ready. Blocking; never raises."""
        try:
            self._start()
        except Exception as e:  # pylint: disable=broad-except
            self._failed("could not start it: %s" % e)
        finally:
            with self._guard:
                self.ready.set()
                # Retired while it started: nothing will use it.
                abandoned = self.retired and self.usable
                if abandoned:
                    self.usable = False
                    control, self.control = self.control, None
            if abandoned:
                with contextlib.suppress(OSError):
                    control.close()
                self._stop()

    def _start(self):
        if self.retired:
            # Retired while it waited for its turn -- by an install, which is
            # what it waited behind: what it would import has just changed.
            self.reason = "retired before it started"
            return
        mine, theirs = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        try:
            # Its own output goes to a file nothing has to keep reading: what
            # its imports print, and a traceback if it dies, which is what
            # '_failed' quotes.
            self._log = tempfile.TemporaryFile()
            args = [*self.command, str(theirs.fileno()), repr(IDLE)]
            if self.preload is not None:
                args.append(",".join(self.preload))
            self.popen = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=self._log,
                stderr=self._log,
                pass_fds=(theirs.fileno(),),
                env=self.env,
            )
        except BaseException:
            mine.close()
            raise
        finally:
            theirs.close()
        self.pid = self.popen.pid
        mine.settimeout(START_TIMEOUT)
        try:
            message, _ = _receive(mine)
        except (OSError, ValueError) as e:
            mine.close()
            self._failed("it did not answer: %s" % e)
            return
        if message is None or not message.get("ready"):
            mine.close()
            reason = (message or {}).get("reason") or "it exited before it was ready"
            self._failed(reason, watch=(message or {}).get("watch"))
            return
        if message.get("protocol") != PROTOCOL:
            mine.close()
            self._failed("it speaks protocol %s, and this is %s" % (message.get("protocol"), PROTOCOL))
            return
        self.watch = list(message.get("watch") or [])
        self.stamp = _stamp(self.watch)
        moved = [path for path, before in message.get("before") or [] if _stamp([path])[0] != _as_stamp(before)]
        if moved:
            # Something was installed while it imported, by another process:
            # it holds some of each. Not a reason to stop trying -- the next
            # call starts another, once whatever it was has finished.
            mine.close()
            self.retry = True
            self._failed("%s changed while it imported from it" % ", ".join(moved))
            return
        # Sends are bounded too: a zygote that stopped reading would otherwise
        # hold the call that is sending to it.
        mine.settimeout(SPAWN_TIMEOUT)
        self.control = mine
        self.preloaded = list(message.get("preloaded") or [])
        self.usable = True

    def _failed(self, reason, watch=None):
        tail = self._log_tail()
        self.reason = reason + ("\n" + tail if tail else "")
        self.watch = list(watch or [])
        self.stamp = _stamp(self.watch) if self.watch else None
        self._stop()

    def _log_tail(self, limit=2000):
        if self._log is None:
            return ""
        with contextlib.suppress(Exception):
            self._log.seek(0)
            text = self._log.read().decode("utf-8", "replace").strip()
            return text[-limit:]
        return ""

    # ---------------------------------------------------------- lifetime --

    def stale(self) -> bool:
        """Whether this zygote can no longer serve a call: gone, or out of date with its files."""
        if self.retired or self.popen is None or self.popen.poll() is not None:
            return True
        return _stamp(self.watch) != self.stamp

    def retire(self) -> None:
        """Take no more calls; let the ones running finish; let the process go. Never raises."""
        with self._guard:
            if self.retired:
                return
            self.retired = True
            starting = not self.ready.is_set()
            control = None
            if not starting:
                control, self.control = self.control, None
        if starting:
            # What it is importing nothing will use, and it has no child yet.
            # 'start' lets the process go once it is over -- and closes its
            # control socket, which is why that is left where 'start' looks.
            with contextlib.suppress(Exception):
                if self.popen is not None:
                    self.popen.kill()
            return
        if control is not None:
            with contextlib.suppress(OSError):
                control.close()
        self._stop(wait=False)

    def _stop(self, wait=True):
        """Reap the process once it has gone, and kill it if it does not go by itself in time."""
        popen = self.popen
        log = self._log
        if popen is None:
            if log is not None:
                log.close()
            return

        def reap():
            # With its control socket closed it exits by itself, once its
            # children have. One that never became usable has no child: it
            # exits by itself too once it has said why, and is killed if it
            # does not -- stuck in an import, say.
            with contextlib.suppress(Exception):
                if not self.usable:
                    try:
                        popen.wait(timeout=_REFUSED_EXIT)
                    except subprocess.TimeoutExpired:
                        popen.kill()
                popen.wait()
            if log is not None:
                with contextlib.suppress(Exception):
                    log.close()

        if wait:
            reap()
        else:
            threading.Thread(target=reap, name="partcad-zygote-reaper", daemon=True).start()

    # ------------------------------------------------------------- spawn --

    async def spawn_async(self, argv, script, cwd, new_session):
        """Fork ``argv`` off this zygote. A `ZygoteProcess`, or None when nothing was started."""
        loop = asyncio.get_running_loop()
        stdin_r, stdin_w = os.pipe()
        stdout_r, stdout_w = os.pipe()
        stderr_r, stderr_w = os.pipe()
        mine, theirs = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        request = {"argv": [str(a) for a in argv], "script": script, "cwd": cwd, "session": bool(new_session)}
        sent = False
        try:
            with self._guard:
                if self.control is not None:
                    _send(self.control, request, [stdin_r, stdout_w, stderr_w, theirs.fileno()])
                    sent = True
        except OSError as e:
            self.reason = "it did not take a request: %s" % e
        finally:
            # The child's ends are the child's now, or nobody's.
            for fd in (stdin_r, stdout_w, stderr_w):
                _close(fd)
            theirs.close()
        message, fds = None, []
        handed = False
        try:
            if sent:
                mine.setblocking(False)
                try:
                    while True:
                        try:
                            message, fds = _receive(mine)
                            break
                        except BlockingIOError:
                            await _readable(loop, mine.fileno(), SPAWN_TIMEOUT)
                except (OSError, ValueError, asyncio.TimeoutError) as e:
                    message = None
                    self.reason = "it did not answer a request: %s" % (e or type(e).__name__)
            if message is None or "pid" not in message:
                if message is not None:
                    # Refused, and said why: the call is started the ordinary
                    # way and fails or succeeds there.
                    pc_logging.debug("The zygote for %s did not fork: %s" % (self.environment, message.get("error")))
                else:
                    # Gone, or not answering: of no use to the next call either.
                    self.retire()
                return None
            self.last_used = time.monotonic()
            process = ZygoteProcess(
                loop,
                pid=int(message["pid"]),
                parent_pid=self.pid,
                pidfd=fds[0] if fds else None,
                reply=mine,
                stdin=stdin_w,
                stdout=stdout_r,
                stderr=stderr_r,
            )
            handed = True
            return process
        finally:
            if not handed:
                # Whatever was asked for is not wanted any more -- refused, or
                # the call cancelled while it waited. Closing the request's
                # socket kills a child that was forked all the same.
                mine.close()
                for fd in [stdin_w, stdout_r, stderr_r, *fds]:
                    _close(fd)


class ZygoteProcess:
    """A wrapper forked from a zygote, as much of an `asyncio.subprocess.Process` as `runtime.communicate` uses.

    Its pid and its exit status (``returncode``, None while it runs, negative
    for a signal); `communicate()`, which feeds the request and reads both
    streams to their end and then waits for the exit; `kill()` and
    `send_signal()`, through a pidfd where the kernel has them, which cannot
    reach a process that has taken the pid since; ``parent_pid``, which is what
    `runtime.process_owner` checks a pid against; and `output_pipes()` and
    `close_output()`, which are how `runtime._watch` finds what holds the output
    of a child that died and lets go of it.

    A zygote that dies while a child runs takes the child with it (the child
    asked the kernel for that as it started), and nothing is left to say how it
    ended: it is then reported as killed, with ``zygote_lost`` set so that the
    runtime can say why.
    """

    def __init__(self, loop, pid, parent_pid, pidfd, reply, stdin, stdout, stderr):
        self.pid = pid
        self.parent_pid = parent_pid
        self.returncode = None
        self.zygote_lost = False
        self._loop = loop
        self._pidfd = pidfd
        self._reply = reply
        self._stdin = stdin
        self._stdout = stdout
        self._stderr = stderr
        # The descriptors this end still has open.
        self._open = {stdin, stdout, stderr}
        # The readiness each pending read or write is waiting for, by descriptor.
        self._waiting = {}
        self._exited = loop.create_future()
        loop.add_reader(reply.fileno(), self._on_reply)

    # ------------------------------------------------------- exit status --

    def _on_reply(self):
        try:
            message, fds = _receive(self._reply)
        except BlockingIOError:
            return
        except (OSError, ValueError):
            message, fds = None, []
        for fd in fds:
            _close(fd)
        if message is not None and "exit" in message:
            self._end(int(message["exit"]))
            return
        if message is not None:
            return
        # The zygote went without saying how this child ended.
        self.zygote_lost = True
        self._loop.remove_reader(self._reply.fileno())
        if self._pidfd is None:
            self._end(-int(signal.SIGKILL))
            return
        with contextlib.suppress(OSError):
            signal.pidfd_send_signal(self._pidfd, signal.SIGKILL)
        # Over when the child is: a pidfd reads as ready once it has exited.
        self._loop.add_reader(self._pidfd, self._end, -int(signal.SIGKILL))

    def _end(self, returncode):
        if self.returncode is not None:
            return
        self.returncode = returncode
        with contextlib.suppress(Exception):
            self._loop.remove_reader(self._reply.fileno())
        if self._pidfd is not None:
            with contextlib.suppress(Exception):
                self._loop.remove_reader(self._pidfd)
            _close(self._pidfd)
            self._pidfd = None
        with contextlib.suppress(OSError):
            self._reply.close()
        if not self._exited.done():
            self._exited.set_result(returncode)

    async def wait(self):
        return await asyncio.shield(self._exited)

    def __del__(self):
        # What a call that was abandoned -- timed out, cancelled, its loop
        # closed before the exit was heard of -- still held. The sockets close
        # themselves; a pidfd and the pipes are plain descriptors.
        pidfd, self._pidfd = getattr(self, "_pidfd", None), None
        _close(pidfd)
        for fd in list(getattr(self, "_open", ())):
            _close(fd)

    # ----------------------------------------------------------- signals --

    def send_signal(self, sig):
        if self.returncode is not None:
            return
        with contextlib.suppress(ProcessLookupError, OSError):
            if self._pidfd is not None:
                signal.pidfd_send_signal(self._pidfd, sig)
            else:
                os.kill(self.pid, sig)

    def terminate(self):
        self.send_signal(signal.SIGTERM)

    def kill(self):
        self.send_signal(signal.SIGKILL)

    # ------------------------------------------------------------- pipes --

    async def communicate(self, input=None):
        _, stdout, stderr = await asyncio.gather(
            self._feed(input), self._drain(self._stdout), self._drain(self._stderr)
        )
        await self.wait()
        return stdout, stderr

    def output_pipes(self):
        """The reading ends of the child's standard output and error, while this end has them open."""
        return [fd for fd in (self._stdout, self._stderr) if fd in self._open]

    def close_output(self):
        """Let go of the child's pipes, keeping what has been read: each read ends as if at the end of its pipe.

        Standard input too, as closing an asyncio transport closes it: what
        still holds its other end may never read, and a request waiting to be
        written to it would wait as long.
        """
        for fd in (self._stdin, self._stdout, self._stderr):
            self._release(fd)

    def _release(self, fd):
        if fd not in self._open:
            return
        self._open.discard(fd)
        waiting = self._waiting.pop(fd, None)
        if waiting is not None:
            with contextlib.suppress(Exception):
                self._loop.remove_reader(fd)
            with contextlib.suppress(Exception):
                self._loop.remove_writer(fd)
            if not waiting.done():
                waiting.set_result(None)
        _close(fd)

    async def _ready(self, fd, write=False):
        ready = self._loop.create_future()
        self._waiting[fd] = ready

        def wake():
            if not ready.done():
                ready.set_result(None)

        (self._loop.add_writer if write else self._loop.add_reader)(fd, wake)
        try:
            await ready
        finally:
            if self._waiting.get(fd) is ready:
                del self._waiting[fd]
                with contextlib.suppress(Exception):
                    (self._loop.remove_writer if write else self._loop.remove_reader)(fd)

    async def _feed(self, data):
        fd = self._stdin
        try:
            if data:
                os.set_blocking(fd, False)
                view = memoryview(data)
                while view and fd in self._open:
                    try:
                        view = view[os.write(fd, view) :]
                    except BlockingIOError:
                        await self._ready(fd, write=True)
                    except (BrokenPipeError, ConnectionResetError):
                        # Gone without reading all of it, as asyncio's own
                        # 'communicate' lets a child do.
                        break
        finally:
            self._release(fd)

    async def _drain(self, fd):
        read = bytearray()
        try:
            if fd in self._open:
                os.set_blocking(fd, False)
            while fd in self._open:
                try:
                    chunk = os.read(fd, 1 << 16)
                except BlockingIOError:
                    await self._ready(fd)
                    continue
                if not chunk:
                    break
                read += chunk
        finally:
            self._release(fd)
        return bytes(read)


# --------------------------------------------------------------------------- #
# The zygotes of this process                                                  #
# --------------------------------------------------------------------------- #

_zygotes: dict = {}
# Environments that could not have one, by key: (until when, the files whose
# change is worth another try, what they were, and why).
_unusable: dict = {}
# How many calls each key has had, which is what decides when one is started.
_calls: dict = {}
_registry_lock = threading.Lock()


def _zygote_for(environment, interpreter, flags, env, preload=None, lock=None):
    """The ready zygote for these, or None -- and, when it is time, one is started for the calls after this one."""
    effective = dict(os.environ) if env is None else env
    key = _key(environment, interpreter, flags, effective, preload)
    with _registry_lock:
        zygote = _zygotes.get(key)
        if zygote is not None:
            if not zygote.ready.is_set():
                # Starting. This call is not made to wait for it.
                return None
            if not zygote.stale():
                return zygote
            del _zygotes[key]
            zygote.retire()
        blocked = _unusable.get(key)
        refused = None
        if blocked is not None:
            until, watch, stamp, reason = blocked
            if time.monotonic() < until and (not watch or _stamp(watch) == stamp):
                refused = reason or "it gave no reason"
            else:
                del _unusable[key]
        if refused is None:
            _calls[key] = _calls.get(key, 0) + 1
            if _calls[key] < WARM_AFTER or not _make_room_locked():
                return None
            zygote = Zygote(key, environment, interpreter, flags, env, preload=preload)
            _zygotes[key] = zygote
    if refused is not None:
        # Said by a call rather than by the thread that found it out, so that
        # it reaches whoever made the call.
        pc_logging.info_once(
            ("zygote", key),
            "Wrappers in %s start a fresh interpreter each: the one they would have been forked from "
            "could not be started (%s)" % (os.path.normpath(environment), refused),
        )
        return None
    threading.Thread(target=_start, args=(zygote, lock), name="partcad-zygote-start", daemon=True).start()
    return None


def _start(zygote, lock):
    """Start ``zygote`` the way a call starts an interpreter: reading its environment, in a process slot of its own.

    The environment's lock, because an install must not rewrite what it is
    importing; and a slot, because it is an interpreter importing a CAD stack,
    which is what the slots count -- it waits its turn behind the calls already
    running rather than adding itself to them.
    """
    try:
        with lock.acquire() if lock is not None else contextlib.nullcontext():
            with sandbox_lock.process_slots.slot():
                zygote.start()
    except Exception as e:  # pylint: disable=broad-except
        # The lock or the slot, which 'start' never reached.
        zygote.reason = zygote.reason or "could not start it: %s" % e
        zygote.ready.set()
    if zygote.usable:
        return
    with _registry_lock:
        if _zygotes.get(zygote.key) is zygote:
            del _zygotes[zygote.key]
        if not zygote.retry and not zygote.retired:
            _unusable[zygote.key] = (time.monotonic() + RETRY, zygote.watch, zygote.stamp, zygote.reason)


def _make_room_locked() -> bool:
    """Whether there is room for one more zygote, retiring the one used least recently if that makes it.

    Only one nobody has used for `EVICT_AFTER` seconds gives way. Two
    environments in use by turns would otherwise take each other's place on
    every call, each start costing what a zygote saves; one of them runs a fresh
    interpreter per call instead.
    """
    while len(_zygotes) >= MAX_ZYGOTES:
        now = time.monotonic()
        idle = [z for z in _zygotes.values() if z.ready.is_set() and now - z.last_used >= EVICT_AFTER]
        if not idle:
            return False
        oldest = min(idle, key=lambda z: z.last_used)
        del _zygotes[oldest.key]
        oldest.retire()
    return True


async def process_async(environment, argv, script, cwd=None, env=None, new_session=False, preload=None, lock=None):
    """``argv`` forked from the zygote for its environment, or None: then start it the ordinary way.

    ``environment`` is the environment the call runs out of, and ``lock`` the
    lock over it (`PythonRuntime.environment_lock`), which a zygote is started
    under; ``script`` is the index of the script in ``argv`` (`script_index`);
    ``env`` is the environment variables the child is to have, None for this
    process's own; ``new_session`` is `runtime.bounded_spawn_options` asking for
    a session. ``preload`` replaces the zygote's `PRELOAD`, for a test that has
    no CAD stack to import.

    Never waits for a zygote to start: the first `WARM_AFTER` calls of an
    environment, and every call while its zygote is importing, are started the
    ordinary way. So no call is slower than it was -- a command that makes one
    call never pays for a zygote -- and a zygote is there for the calls that
    follow.
    """
    interpreter, flags = str(argv[0]), [str(a) for a in argv[1:script]]
    zygote = _zygote_for(
        environment, interpreter, flags, env, preload=PRELOAD if preload is None else preload, lock=lock
    )
    if zygote is None:
        return None
    if cwd is None:
        try:
            cwd = os.getcwd()
        except OSError:
            # Gone from under this process. A fresh interpreter can still be
            # started in it; a forked one has nowhere to change to.
            return None
    zygote.last_used = time.monotonic()
    process = await zygote.spawn_async(argv, script, cwd, new_session)
    if process is None and zygote.retired:
        with _registry_lock:
            if _zygotes.get(zygote.key) is zygote:
                del _zygotes[zygote.key]
    return process


def _within(path, environment) -> bool:
    return path == environment or path.startswith(environment.rstrip(os.sep) + os.sep)


def retire(environment) -> None:
    """Retire every zygote of ``environment``: something has just been installed into it.

    And every zygote of a layer inside it (`runtime_python.VENV_PREFIX`): a
    layer sees the sandbox's own packages after its own, so what was installed
    there is what its zygote imported too. Its 'Zygote.stale' would say so on
    the next call, as it does for an install by another process; this says it
    at once.

    And forget that it could not have one, since what was installed may be what
    it lacked.
    """
    environment = os.path.normpath(environment)
    with _registry_lock:
        retiring = [z for z in _zygotes.values() if _within(z.environment, environment)]
        for zygote in retiring:
            del _zygotes[zygote.key]
        for key in [key for key in _unusable if _within(key[0], environment)]:
            del _unusable[key]
    for zygote in retiring:
        zygote.retire()


def zygotes() -> list:
    """The zygotes this process has now, ready or starting."""
    with _registry_lock:
        return list(_zygotes.values())
