#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Serving the Windows named-pipe daemon (the AF_UNIX counterpart for Windows).

Windows has no ``fork``, so the launcher spawns a *detached* server process
instead of daemonizing in place, and the transport is a named pipe served with
the asyncio Proactor event loop. The same ``Content-Length`` framing and JSON-RPC
dispatcher are reused, and requests are served as the socket daemon serves them:
one at a time, on a thread of their own (``transport.dispatch``), with each
connection read on the loop while its requests wait or run -- so a
``$/cancelRequest`` reaches them -- and written by a writer of its own
(:class:`PipeWriter`) that does not let one client that stopped reading cost
the daemon its memory. Frames are encoded on the thread that produced them, not
on the loop, which every connection shares.

The pipe's name, and the client side of talking to it, are in
``partcad_utils.win_pipe`` -- the rendezvous both ends have to agree on.

NOTE: serving is Windows-only, and Windows-specific APIs are reached only inside
functions so the module still imports on POSIX. `test_win_pipe.py` drives
:func:`spawn_pipe_daemon` with a stand-in ``Popen`` and pins the argv and the
redirection the daemon is started with: neither is a Windows API, both have been
wrong, and pinning them without one means a POSIX run catches it too. What one
connection is served by (:func:`_connection_handler`, :class:`PipeWriter`) is
not Windows-specific either, only the pipe is, and `test_win_pipe_serving.py`
serves it over a socket.
"""

import asyncio
import collections
import contextlib
import faulthandler
import os
import subprocess
import sys
import threading
from typing import Callable, Optional

from partcad_utils.framing import Peer, encode_message
from partcad_utils.win_pipe import STOP_METHOD, pipe_name, read_frame
from partcad_utils.workspace import LIVENESS_METHOD, workspace_dir

from . import config_restart
from .core.cancellation import CANCEL_METHOD
from .rpc.dispatcher import Dispatcher
from .rpc.methods import build_registry
from .transport.dispatch import Dispatch, Job, Requests
from .transport.writer import MAX_BACKLOG, WRITE_TIMEOUT, backlog_behind, frame_size

# How long a closing connection waits for what it still has to send, and how
# long `daemon.stop` waits for its answer to leave before the daemon does.
_FLUSH_SECONDS = 5.0

# How much is written before waiting for the client to take it. A drain waits
# for the transport's buffer to empty, so this is what bounds the wait a reading
# client causes: WRITE_TIMEOUT is then "nothing taken", not "a big file slowly".
_PIECE = 1024 * 1024

# Frames smaller than this are written together, as the socket daemon joins them.
_JOIN_BELOW = 64 * 1024

# How long after it stops serving the daemon is expected to be gone, and how
# often from then on it writes where every thread of it is, into 'daemon.log',
# for as long as it is not. Below the 30 s a client waits for a stopped daemon
# to go ('partcad_client.daemon.STOP_TIMEOUT') before it kills it: a daemon
# that cannot exit is otherwise killed with nothing to say what held it.
STOPPED_STACKS_SECONDS = 10.0


def report_stacks_until_exit() -> None:
    """Have every thread's stack written to stderr every ``STOPPED_STACKS_SECONDS`` from now on.

    Until the process exits, or until ``faulthandler.cancel_dump_traceback_later``.
    Nothing happens when stderr is not a file faulthandler can write to.
    """
    with contextlib.suppress(AttributeError, OSError, RuntimeError, ValueError):
        faulthandler.dump_traceback_later(STOPPED_STACKS_SECONDS, repeat=True)


def _launcher_argv() -> list:
    """How to run this service again as a new process.

    The standalone bundle is a single executable that takes the service's own
    options, so `sys.executable -m partcad_service_json_rpc` -- right for a
    source checkout -- is exactly what it rejects: `-m` is not one of its
    arguments, argparse exits, and the daemon that was supposed to serve the
    pipe was never there. That bundle is what the editor extension downloads and
    runs, which is who asks for this daemon.

    `partcad_client.launcher_argv` answers the same question for a client and is
    deliberately not imported here: this package does not depend on the client
    (see AGENTS.md). Two lines are the price of that.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "partcad_service_json_rpc"]


def spawn_pipe_daemon(root_path: str, extra_args=()) -> "subprocess.Popen":
    """Start a detached server process serving the workspace's named pipe.

    ``extra_args`` are the launcher's own settings flags (`--python-sandbox`,
    `--offline`, ...), from `partcad_service_json_rpc.__main__.settings_argv`.
    They have to be repeated here because this daemon is a *new process*: the
    POSIX daemon is a fork of the launcher and keeps whatever it was told, while
    without this the Windows one served every workspace with the defaults --
    `pc --python-sandbox conda daemon start` printed a pipe, and the daemon
    behind it had no idea conda had been asked for.

    Returns the process, so that the launcher waiting for it to serve can tell
    one that is starting from one that has already died.
    """
    creationflags = 0
    creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
    creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    with _daemon_log(root_path) as log:
        return subprocess.Popen(
            _launcher_argv() + ["--serve-pipe", pipe_name(root_path), *extra_args],
            close_fds=True,
            creationflags=creationflags,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            cwd=_daemon_cwd(),
        )


def _daemon_cwd() -> str:
    r"""Where the daemon runs: the root of the drive its launcher runs on.

    Not the launcher's own directory: Windows will not delete or rename a
    directory some process is running in, and the launcher's is wherever its
    client was -- the package a `pc` command ran in, a test's temporary
    directory -- which this process would hold for as long as it serves. The
    POSIX daemon leaves its own for "/" (`daemon._serve_detached`), and this is
    the same move on Windows.

    The same *drive*, though, and that is not a detail. A path with a root and
    no drive -- ``\tmp\home``, which is what a `HOME` written POSIX-style is
    on Windows -- names a directory on the current drive, so a daemon running on
    another one resolves every such path somewhere its client never looks. Run in
    its workspace's state directory under the user's profile, on C:, it built
    the sandbox of every behave scenario on a Windows runner -- whose temporary
    `HOME` is ``/tmp/sandbox/home\...``, on D: for the harness that makes and
    removes it -- in C:\tmp\sandbox\home\...: gigabytes each, which nothing
    removed, until C: was full.
    """
    drive = os.path.splitdrive(os.getcwd())[0]
    return drive + os.sep if drive else os.sep


@contextlib.contextmanager
def _daemon_log(root_path: str):
    """The file the detached daemon's own output goes to; ``None`` if there is none.

    ``DETACHED_PROCESS`` leaves the child with no console, so everything it says
    on its way out -- the traceback of a daemon that dies before it serves, which
    is the only account of why the pipe never appeared -- goes nowhere unless it
    is redirected. The POSIX daemon writes the same file name from inside itself
    (``daemon._redirect_std_fds``), which it can because it is a fork and gets to
    run code before it serves; this one is a new process and cannot.

    Yields ``None`` when the file cannot be opened. Somewhere to log is worth
    having, and not worth refusing to start a daemon over.
    """
    wdir = workspace_dir(root_path)
    try:
        os.makedirs(wdir, exist_ok=True)
        log = open(os.path.join(wdir, "daemon.log"), "ab", buffering=0)
    except OSError:
        yield None
        return
    try:
        yield log
    finally:
        # The child holds its own copy of the handle from here on.
        log.close()


def serve_pipe(session, registry=None, name: str = None, settings=()) -> None:
    """Serve the shared session over a Windows named pipe until stopped.

    Restarts when the user configuration changes, exactly as the POSIX daemon
    does (see ``config_restart``): no new pipe instances, so the next client
    spawns a fresh daemon, while the connections already here finish and are
    told to reconnect.

    ``settings`` are the launcher flags it was started with, which is what it
    answers ``daemon.settings`` with (see ``config_restart.SETTINGS_METHOD``).
    """
    registry = registry if registry is not None else build_registry()
    dispatcher = Dispatcher(registry)
    # One request at a time, whichever connection it came from, as the socket
    # daemon serves them (see 'transport.dispatch').
    dispatch = Dispatch(dispatcher, session)

    loop = asyncio.ProactorEventLoop()  # type: ignore[attr-defined]
    asyncio.set_event_loop(loop)
    stop_event = asyncio.Event()
    # The same fact for the threads: the drain runs on one.
    stopped = threading.Event()
    restarting = threading.Event()
    connections = config_restart.Connections()
    servers = []

    def stop():
        stopped.set()
        stop_event.set()
        dispatch.stop()

    def begin_restart():
        # Closing the server stops it offering new pipe instances; the ones
        # already connected are not closed with it.
        for server in servers:
            server.close()

        async def drain():
            await loop.run_in_executor(None, connections.drain, config_restart.GRACE_SECONDS, stopped)
            stop()

        loop.create_task(drain())

    def restart():
        if not restarting.is_set() and not stopped.is_set():
            restarting.set()
            loop.call_soon_threadsafe(begin_restart)

    handle = _connection_handler(
        dispatcher=dispatcher,
        dispatch=dispatch,
        session=session,
        connections=connections,
        settings=settings,
        stop=stop,
        restart=restart,
        stopping=stop_event.is_set,
    )

    async def _serve():
        [server] = await loop.start_serving_pipe(  # type: ignore[attr-defined]
            lambda: _connection_protocol(handle), name
        )
        servers.append(server)
        await stop_event.wait()
        server.close()

    watcher = config_restart.watch(restart)
    try:
        loop.run_until_complete(_serve())
    finally:
        # Armed before anything below, which is where a daemon on its way out
        # can stop: closing the loop waits for its pipes' pending reads and
        # writes to be cancelled. And put away once that is done, because the
        # process may have more to do -- the daemon goes on to exit, which is
        # watched the same way ('__main__'), and a test goes on to its next.
        report_stacks_until_exit()
        try:
            if watcher is not None:
                watcher.stop()
            dispatch.stop()
            loop.close()
        finally:
            faulthandler.cancel_dump_traceback_later()


def _connection_handler(
    *,
    dispatcher: Dispatcher,
    dispatch: Dispatch,
    session,
    connections: config_restart.Connections,
    settings=(),
    stop: Callable[[], None],
    restart: Callable[[], None],
    stopping: Callable[[], bool],
):
    """What each pipe connection is served by: ``handle(reader, writer)``, a coroutine.

    Apart from :func:`serve_pipe` so that it can be served over something that
    is not a named pipe -- a socket, on any platform -- by the tests.
    """

    async def handle(reader, writer):
        loop = asyncio.get_running_loop()
        # Whether this client reads attachments, kept per connection as the
        # socket server keeps it (see 'partcad_utils.framing').
        peer = Peer()
        # This client's requests that are queued or running, as the socket
        # server keeps them: what '$/cancelRequest' looks in.
        requests = Requests()

        def dropped(why):
            print("PartCAD daemon: dropped a connection: %s" % why, file=sys.stderr, flush=True)
            requests.cancel_all()

        out = PipeWriter(writer, on_drop=dropped)

        def encoded(message):
            return encode_message(message, peer.attachments)

        def notify(event, payload):
            # From another thread -- the dispatch thread, or the drain's -- and
            # encoded there, so that the loop only ever writes bytes. Onto the
            # loop rather than written here: an asyncio transport is not
            # thread-safe. The proactor's write transport keeps its state in
            # plain attributes and carries each write on from a callback on the
            # loop's thread, so a worker writing while that callback ran left
            # the two disagreeing about which write was in flight, and the
            # connection was not safe to use after that.
            out.put_threadsafe(encoded({"jsonrpc": "2.0", "method": event, "params": payload}))

        def respond(response):
            # Through the same queue onto the loop as the request's events,
            # behind them: callbacks a thread hands the loop run in the order
            # they were handed over, so the events go out before the answer,
            # as the POSIX server sends them.
            out.put_threadsafe(encoded(response))

        token = connections.add(notify)

        def finish(job):
            requests.untrack(job)
            connections.end(token)

        try:
            while not stopping():
                request = await read_frame(reader, peer)
                if request is None:
                    break
                if isinstance(request, dict) and request.get("method") == STOP_METHOD:
                    if "id" in request:
                        out.put(encoded({"jsonrpc": "2.0", "id": request["id"], "result": {"stopped": True}}))
                        await out.sent(_FLUSH_SECONDS)
                    stop()
                    break
                if isinstance(request, dict) and request.get("method") == config_restart.SETTINGS_METHOD:
                    differ = config_restart.settings_differ(request.get("params"), settings)
                    if differ:
                        restart()
                    if "id" in request:
                        out.put(
                            encoded(
                                {
                                    "jsonrpc": "2.0",
                                    "id": request["id"],
                                    "result": {"restarting": differ, "settings": list(settings)},
                                }
                            )
                        )
                    continue

                if isinstance(request, dict) and request.get("method") == LIVENESS_METHOD:
                    # Answered now, not queued, as the socket server answers it
                    # (see 'workspace.LIVENESS_METHOD').
                    response = dispatcher.dispatch(request, session)
                    if response is not None:
                        out.put(encoded(response))
                    continue

                if isinstance(request, dict) and request.get("method") == CANCEL_METHOD:
                    # Answered by the request it names (see 'core.cancellation'),
                    # and with nothing itself if it was sent as a request.
                    requests.cancel(request.get("params"))
                    if "id" in request:
                        out.put(encoded({"jsonrpc": "2.0", "id": request["id"], "result": None}))
                    continue

                job = Job(request, notify, respond, finish)
                requests.track(job)
                connections.begin(token)
                dispatch.submit(job, requests)
        finally:
            # What this client asked for is still answered after it stops
            # sending, as on the socket; a client that has gone is found out by
            # the writer, and what it asked for is cancelled then.
            await loop.run_in_executor(None, requests.wait_idle)
            await out.close(_FLUSH_SECONDS)
            connections.remove(token)
            # Ours to close: asyncio's stream protocol keeps a connection open
            # past the client's end of it, for a handler that has more to write.
            writer.close()

    return handle


class PipeWriter:
    """What one pipe connection is sent, written in order by a task of its own.

    The pipe's counterpart of ``transport.writer.SocketWriter``, and bounded by
    the same policy for the same reasons (see that module): a client that takes
    nothing for ``WRITE_TIMEOUT`` seconds, or lets more than ``MAX_BACKLOG``
    bytes pile up behind the frame being written, is dropped -- the transport
    aborted, which the client sees as its connection closing. Before this the
    events of a request were written with no ``drain()`` at all, and one client
    that stopped reading had the transport buffer everything sent to it.

    :meth:`put` is for the loop's thread, :meth:`put_threadsafe` for any other;
    a frame is a list of chunks, as ``framing.encode_message`` makes them.
    """

    def __init__(
        self,
        writer,
        on_drop: Optional[Callable[[str], None]] = None,
        timeout: float = WRITE_TIMEOUT,
        max_backlog: int = MAX_BACKLOG,
    ):
        self._writer = writer
        self._on_drop = on_drop
        self._timeout = timeout
        self._max_backlog = max_backlog
        self._loop = asyncio.get_running_loop()
        self._frames: collections.deque = collections.deque()
        self._backlog = 0
        self._writing = False
        self._closing = False
        self._dropped: Optional[str] = None
        self._wake = asyncio.Event()
        self._idle = asyncio.Event()
        self._idle.set()
        self._task = self._loop.create_task(self._run())

    @property
    def dropped(self) -> Optional[str]:
        return self._dropped

    def put(self, frame: list) -> None:
        if self._closing or self._dropped is not None:
            return
        size = frame_size(frame)
        # As the socket daemon counts it: what is behind the frame being
        # written, or behind the next one when none is (see 'writer').
        behind = backlog_behind(self._frames, self._backlog, self._writing, size)
        if behind > self._max_backlog:
            self._drop("it stopped reading, and %d MB were waiting for it" % (behind // (1024 * 1024)))
            return
        self._frames.append((frame, size))
        self._backlog += size
        self._idle.clear()
        self._wake.set()

    def put_threadsafe(self, frame: list) -> None:
        with contextlib.suppress(RuntimeError):
            # The loop has closed: the daemon is on its way out, and there is
            # nobody left to tell.
            self._loop.call_soon_threadsafe(self.put, frame)

    async def sent(self, timeout: Optional[float] = None) -> None:
        """Wait until everything queued so far has been written (or dropped)."""
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._idle.wait(), timeout)

    async def close(self, timeout: Optional[float] = None) -> None:
        """Write what is queued, then end. Gives up after ``timeout``."""
        self._closing = True
        self._wake.set()
        try:
            await asyncio.wait_for(asyncio.shield(self._task), timeout)
        except asyncio.TimeoutError:
            self._task.cancel()

    def _take(self) -> list:
        frame, size = self._frames.popleft()
        self._backlog -= size
        if size >= _JOIN_BELOW:
            return frame
        pieces, total = list(frame), size
        while self._frames and total < _JOIN_BELOW and self._frames[0][1] < _JOIN_BELOW:
            more, more_size = self._frames.popleft()
            self._backlog -= more_size
            pieces.extend(more)
            total += more_size
        return [b"".join(pieces)]

    async def _run(self) -> None:
        while True:
            while not self._frames:
                self._idle.set()
                if self._closing or self._dropped is not None:
                    return
                self._wake.clear()
                await self._wake.wait()
            frame = self._take()
            self._writing = True
            try:
                for chunk in frame:
                    view = memoryview(chunk).cast("B")
                    for start in range(0, max(len(view), 1), _PIECE):
                        self._writer.write(view[start : start + _PIECE])
                        await asyncio.wait_for(self._writer.drain(), self._timeout or None)
            except asyncio.TimeoutError:
                self._drop("it accepted nothing it was sent for %gs" % self._timeout)
            except (ConnectionError, OSError, RuntimeError) as e:
                self._drop("it went away (%s)" % e)
            finally:
                self._writing = False

    def _drop(self, why: str) -> None:
        if self._dropped is not None:
            return
        self._dropped = why
        self._frames.clear()
        self._backlog = 0
        self._idle.set()
        self._wake.set()
        with contextlib.suppress(Exception):
            # Ends the connection at once; its reader sees the end of it.
            self._writer.transport.abort()
        if self._on_drop is not None:
            with contextlib.suppress(Exception):
                self._on_drop(why)


def _connection_protocol(handler) -> asyncio.Protocol:
    """The protocol one pipe connection is served by: ``handler(reader, writer)`` runs as its task.

    asyncio's own, rather than an ``asyncio.Protocol`` of this module's. A
    ``StreamWriter`` asks its protocol to wait out a full write buffer, and
    ``drain()`` does so through ``_drain_helper``, which only asyncio's stream
    protocols have. The one this replaces lacked it, so the first ``drain()``
    after an answer raised AttributeError and ended the connection's task:
    every client got exactly one answer and then lost the connection -- the
    editor, which keeps one open, on every Windows run of "IDE (end to end)".
    """
    return asyncio.StreamReaderProtocol(asyncio.StreamReader(), handler)
