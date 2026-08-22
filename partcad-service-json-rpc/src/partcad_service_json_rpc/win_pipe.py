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

NOTE: this module is Windows-only. It is not exercised in the Linux dev
container / CI; Windows-specific APIs are imported inside functions so the module
still byte-compiles on POSIX.
"""

import asyncio
import subprocess
import sys
import threading

from partcad_utils.win_pipe import STOP_METHOD, pipe_name, read_frame, write_frame

from .rpc.dispatcher import Dispatcher
from .rpc.methods import build_registry


def spawn_pipe_daemon(root_path: str) -> None:
    """Start a detached server process serving the workspace's named pipe."""
    creationflags = 0
    creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
    creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(
        [sys.executable, "-m", "partcad_service_json_rpc", "--serve-pipe", pipe_name(root_path)],
        close_fds=True,
        creationflags=creationflags,
    )


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
