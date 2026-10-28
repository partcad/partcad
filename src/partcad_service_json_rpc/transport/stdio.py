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

Requests are read on the calling thread and served on another, one at a time
and in order (``dispatch.Dispatch``), as the socket daemon serves them: the
reader goes on reading while a request runs, which is how a ``$/cancelRequest``
reaches it (see ``core.cancellation``). Writing stays on whichever thread has
something to write: this channel has one client, and a client that does not
read its own answers delays nobody else.
"""

import os
import sys
import threading
from typing import BinaryIO, Mapping

from partcad_utils.framing import Peer, encode_message, read_message, write_message
from partcad_utils.logging_ansi_render import AnsiEventRenderer

from ..core.cancellation import CANCEL_METHOD
from ..core.events import TERMINAL, TERMINAL_TEXT, log_mode_result, terminal_params
from ..rpc.dispatcher import INVALID_PARAMS, Dispatcher, Handler
from .dispatch import Dispatch, Job, Requests

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
        # Read once: the reader may swap it while a request is emitting.
        rendering = renderer[0]
        if rendering is not None and event == "log":
            rendering.handle(payload)
            return
        send(event, payload)

    def respond(response):
        # Encoded outside the guard below: an answer JSON cannot carry raises,
        # and 'Dispatch._answer' answers the request with that instead. Only a
        # write to a client that has gone is nobody's to hear about - and a
        # ValueError is both a closed stream and a circular answer.
        chunks = encode_message(response, peer.attachments)
        try:
            with lock:
                for chunk in chunks:
                    write_stream.write(chunk)
                write_stream.flush()
        except (OSError, ValueError):
            # The client has closed its end: nobody is left to answer.
            pass

    session.emitter.set_sink(sink)
    dispatcher = Dispatcher(registry)
    # No sink of its own for each request: the one bound above stays bound.
    dispatch = Dispatch(dispatcher, session)
    requests = Requests()

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

            if isinstance(request, dict) and request.get("method") == CANCEL_METHOD:
                # Answered by the request it names, and with nothing itself if
                # it was sent as a request (see 'socket_server').
                requests.cancel(request.get("params"))
                if "id" in request:
                    with lock:
                        write_message(write_stream, {"jsonrpc": "2.0", "id": request["id"], "result": None})
                continue

            job = Job(request, None, respond, requests.untrack)
            requests.track(job)
            dispatch.submit(job, requests)
    finally:
        # Everything that was asked is answered before this returns, as it was
        # when each request was answered before the next was read: the end of
        # the input is the client done *sending*, and it may still be reading.
        requests.wait_idle()
        dispatch.stop()
        if renderer[0] is not None:
            renderer[0].close()
            renderer[0] = None


def serve_stdio(session, registry: Mapping[str, Handler]) -> None:
    """Serve over the process's real stdin/stdout (binary buffers)."""
    serve(_private_input(), sys.stdout.buffer, session, registry)


def _private_input() -> BinaryIO:
    """The requests' stream: standard input, moved off fd 0, which becomes the null device.

    The reader waits on it while a request runs, and the request starts
    processes -- git, a sandbox's wrappers -- that inherit standard input
    unless told otherwise. On Windows that is the same pipe, and a synchronous
    read pending on a pipe holds up whatever else touches it: the child sat
    waiting on its own standard input for as long as this one waited for the
    client's next request, which was forever (every `pc test` over this
    channel). Anywhere, a child reading it would take the client's requests.
    Moved to a descriptor no child inherits, it is this reader's alone, as the
    detached daemon's is (`daemon._serve_detached`).
    """
    fd = os.dup(sys.stdin.fileno())
    with open(os.devnull, "rb") as devnull:
        os.dup2(devnull.fileno(), sys.stdin.fileno())
    return open(fd, "rb")
