#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Serving the Windows named-pipe daemon (the AF_UNIX counterpart for Windows).

Windows has no ``fork``, so the launcher spawns a *detached* server process
instead of daemonizing in place, and the transport is a named pipe served with
the asyncio Proactor event loop. The same ``Content-Length`` framing and JSON-RPC
dispatcher are reused, with dispatch offloaded to a worker thread (PartCAD
operations are blocking) and notifications routed back to the calling pipe.

The pipe's name, and the client side of talking to it, are in
``partcad_utils.win_pipe`` -- the rendezvous both ends have to agree on.

NOTE: serving is Windows-only, and Windows-specific APIs are reached only inside
functions so the module still imports on POSIX. `test_win_pipe.py` drives
:func:`spawn_pipe_daemon` with a stand-in ``Popen`` and pins the argv and the
redirection the daemon is started with: neither is a Windows API, both have been
wrong, and pinning them without one means a POSIX run catches it too.
"""

import asyncio
import contextlib
import os
import subprocess
import sys
import threading

from partcad_utils.win_pipe import STOP_METHOD, pipe_name, read_frame, write_frame
from partcad_utils.workspace import workspace_dir

from .rpc.dispatcher import Dispatcher
from .rpc.methods import build_registry


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


def spawn_pipe_daemon(root_path: str, extra_args=()) -> None:
    """Start a detached server process serving the workspace's named pipe.

    ``extra_args`` are the launcher's own settings flags (`--python-sandbox`,
    `--offline`, ...), from `partcad_service_json_rpc.__main__.settings_argv`.
    They have to be repeated here because this daemon is a *new process*: the
    POSIX daemon is a fork of the launcher and keeps whatever it was told, while
    without this the Windows one served every workspace with the defaults --
    `pc --python-sandbox conda daemon start` printed a pipe, and the daemon
    behind it had no idea conda had been asked for.
    """
    creationflags = 0
    creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
    creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    with _daemon_log(root_path) as log:
        subprocess.Popen(
            _launcher_argv() + ["--serve-pipe", pipe_name(root_path), *extra_args],
            close_fds=True,
            creationflags=creationflags,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
        )


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


def serve_pipe(session, registry=None, name: str = None) -> None:
    """Serve the shared session over a Windows named pipe until stopped."""
    registry = registry if registry is not None else build_registry()
    dispatcher = Dispatcher(registry)
    dispatch_lock = threading.Lock()

    loop = asyncio.ProactorEventLoop()  # type: ignore[attr-defined]
    asyncio.set_event_loop(loop)
    stop_event = asyncio.Event()

    async def handle(reader, writer):
        def sink(event, payload):
            write_frame(writer, {"jsonrpc": "2.0", "method": event, "params": payload})

        while not stop_event.is_set():
            request = await read_frame(reader)
            if request is None:
                break
            if isinstance(request, dict) and request.get("method") == STOP_METHOD:
                if "id" in request:
                    write_frame(writer, {"jsonrpc": "2.0", "id": request["id"], "result": {"stopped": True}})
                    await writer.drain()
                stop_event.set()
                break

            def _run():
                with dispatch_lock:
                    session.emitter.set_sink(sink)
                    try:
                        return dispatcher.dispatch(request, session)
                    finally:
                        session.emitter.set_sink(None)

            response = await loop.run_in_executor(None, _run)
            if response is not None:
                write_frame(writer, response)
                await writer.drain()

    async def _serve():
        [server] = await loop.start_serving_pipe(  # type: ignore[attr-defined]
            lambda: _PipeProtocol(handle, loop), name
        )
        await stop_event.wait()
        server.close()

    try:
        loop.run_until_complete(_serve())
    finally:
        loop.close()


class _PipeProtocol(asyncio.Protocol):
    """Adapts an incoming pipe connection to the StreamReader/Writer handler."""

    def __init__(self, handler, loop):
        self._handler = handler
        self._loop = loop
        self._reader = asyncio.StreamReader(loop=loop)

    def connection_made(self, transport):
        writer = asyncio.StreamWriter(transport, self, self._reader, self._loop)
        self._loop.create_task(self._handler(self._reader, writer))

    def data_received(self, data):
        self._reader.feed_data(data)

    def connection_lost(self, exc):
        self._reader.feed_eof()
