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

from ..rpc.dispatcher import Dispatcher, Handler
from partcad_utils.framing import read_message, write_message


def _notification_sink(write_stream: BinaryIO, lock: threading.Lock):
    def sink(event, payload):
        with lock:
            write_message(write_stream, {"jsonrpc": "2.0", "method": event, "params": payload})

    return sink


def serve(read_stream: BinaryIO, write_stream: BinaryIO, session, registry: Mapping[str, Handler]) -> None:
    """Serve JSON-RPC over the given binary streams until end of input."""
    lock = threading.Lock()
    session.emitter.set_sink(_notification_sink(write_stream, lock))
    dispatcher = Dispatcher(registry)

    while True:
        request = read_message(read_stream)
        if request is None:
            break
        response = dispatcher.dispatch(request, session)
        if response is not None:
            with lock:
                write_message(write_stream, response)


def serve_stdio(session, registry: Mapping[str, Handler]) -> None:
    """Serve over the process's real stdin/stdout (binary buffers)."""
    serve(sys.stdin.buffer, sys.stdout.buffer, session, registry)
