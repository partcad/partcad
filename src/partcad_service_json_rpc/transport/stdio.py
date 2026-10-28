#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Framed, bidirectional JSON-RPC over stdin/stdout.

This is the default transport. The extension talks to it with
``vscode-jsonrpc`` using the same ``Content-Length`` framing the Language Server
Protocol uses. Server-to-client notifications (the event stream) share the
output stream with responses, guarded by a lock so the log-streaming thread and
the dispatch loop never interleave a frame.
"""

import sys
import threading
from typing import BinaryIO, Mapping

from partcad_utils.framing import Peer, read_message, write_message
from partcad_utils.logging_ansi_render import AnsiEventRenderer

from ..core.events import TERMINAL, TERMINAL_TEXT, log_mode_result, terminal_params
from ..rpc.dispatcher import INVALID_PARAMS, Dispatcher, Handler

# The same opt-in the socket daemon answers; see the note on `LOG_MODE_METHOD`
# in `socket_server.py`. Kept working here so that `partcad.serviceChannel:
# stdio` is a transport choice and not also a change in what the terminal looks
# like. There is one connection here, so this is connection state either way.
LOG_MODE_METHOD = "log.mode"


def serve(read_stream: BinaryIO, write_stream: BinaryIO, session, registry: Mapping[str, Handler]) -> None:
    """Serve JSON-RPC over the given binary streams until end of input."""
    lock = threading.Lock()
    renderer = [None]
    # Whether the client reads attachments, as the socket server keeps it: the
    # editor runs this channel too (`partcad.serviceChannel: stdio`).
    peer = Peer()
    # Whether the client reads the drawing as text; see `socket_server.LOG_MODE_METHOD`.
    as_text = [False]

    def send(event, payload):
        try:
            with lock:
                write_message(
                    write_stream,
                    {"jsonrpc": "2.0", "method": event, "params": payload},
                    attachments=peer.attachments,
                )
        except (OSError, ValueError):
            # The renderer's ticking thread can outlive the stream by a tick.
            pass

    def sink(event, payload):
        if renderer[0] is not None and event == "log":
            renderer[0].handle(payload)
            return
        send(event, payload)

    session.emitter.set_sink(sink)
    dispatcher = Dispatcher(registry)

    try:
        while True:
            request = read_message(read_stream, peer)
            if request is None:
                break

            if isinstance(request, dict) and request.get("method") == LOG_MODE_METHOD:
                # See the note in `socket_server.py`: this bypasses `Dispatcher`,
                # so an array `params` would reach `.get` on a list and end the
                # serve loop instead of answering.
                params = request.get("params")
                if params is not None and not isinstance(params, dict):
                    if "id" in request:
                        with lock:
                            write_message(
                                write_stream,
                                {
                                    "jsonrpc": "2.0",
                                    "id": request["id"],
                                    "error": {"code": INVALID_PARAMS, "message": "Invalid params: expected an object"},
                                },
                            )
                    continue
                wants_ansi = bool((params or {}).get("ansi"))
                as_text[0] = bool((params or {}).get(TERMINAL_TEXT))
                if wants_ansi and renderer[0] is None:
                    renderer[0] = AnsiEventRenderer(lambda text: send(TERMINAL, terminal_params(text, as_text[0])))
                elif not wants_ansi and renderer[0] is not None:
                    renderer[0].close()
                    renderer[0] = None
                if "id" in request:
                    with lock:
                        write_message(
                            write_stream,
                            {
                                "jsonrpc": "2.0",
                                "id": request["id"],
                                "result": log_mode_result(renderer[0] is not None, as_text[0]),
                            },
                        )
                continue

            response = dispatcher.dispatch(request, session)
            if response is not None:
                with lock:
                    write_message(write_stream, response, attachments=peer.attachments)
    finally:
        if renderer[0] is not None:
            renderer[0].close()
            renderer[0] = None


def serve_stdio(session, registry: Mapping[str, Handler]) -> None:
    """Serve over the process's real stdin/stdout (binary buffers)."""
    serve(sys.stdin.buffer, sys.stdout.buffer, session, registry)
