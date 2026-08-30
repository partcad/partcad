#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Threaded JSON-RPC server over an AF_UNIX socket.

This is what the per-workspace daemon serves. Every connection is a bidirectional
JSON-RPC endpoint using the same ``Content-Length`` framing as the stdio channel.
A single shared warm :class:`Session` backs all connections; a lock serializes
dispatch, and while a request is handled the session emitter is bound to the
calling connection's writer, so events (logs, items, stats, prompts) are routed
back to that client only.

``daemon.stop`` and ``log.mode`` are handled at the transport level rather than
by the dispatcher: they are properties of the *connection*, and the dispatcher
only ever sees ``(request, session)`` -- and the session is shared by every
client of this daemon, so a setting stored there would be one client deciding
for all of them.
"""

import base64
import os
import socket
import threading
from typing import Callable, Mapping, Optional

from ..rpc.dispatcher import INVALID_PARAMS, Dispatcher, Handler
from partcad_utils.framing import read_message, write_message
from partcad_utils.logging_ansi_render import AnsiEventRenderer

STOP_METHOD = "daemon.stop"

# "Send me the display, not the records." A client that cannot host the ANSI
# progress state machine -- the VS Code extension, which is TypeScript -- asks
# for this once, right after connecting, and from then on its log events arrive
# as rendered bytes on the ``terminal`` notification instead of as structured
# records on ``log``. Instead of, not as well as: the two carry the same
# information, and sending both would double the traffic to no end.
LOG_MODE_METHOD = "log.mode"


class SocketServer:
    """Serves the shared session over a stream socket, one thread per connection."""

    def __init__(self, session, registry: Mapping[str, Handler], on_shutdown: Optional[Callable] = None):
        self._session = session
        self._dispatcher = Dispatcher(registry)
        self._on_shutdown = on_shutdown
        self._dispatch_lock = threading.Lock()
        self._server_sock: Optional[socket.socket] = None
        self._path: Optional[str] = None
        self._stop = threading.Event()

    def serve_unix(self, path: str) -> None:
        """Bind an AF_UNIX socket at ``path`` and serve until stopped."""
        if os.path.exists(path):
            # The caller has already determined no live daemon owns it.
            os.unlink(path)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(path)
        os.chmod(path, 0o600)
        server.listen(64)
        self._server_sock = server
        self._path = path
        self._accept_loop()

    def serve_accepted(self, server_sock: socket.socket, path: str) -> None:
        """Serve on an already-bound/listening socket (used after daemonizing)."""
        self._server_sock = server_sock
        self._path = path
        self._accept_loop()

    def _accept_loop(self) -> None:
        # A poll timeout lets the loop notice stop(): closing the listening
        # socket from another thread does not reliably interrupt a blocked
        # accept().
        self._server_sock.settimeout(0.5)
        while not self._stop.is_set():
            try:
                conn, _ = self._server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            conn.settimeout(None)
            threading.Thread(target=self._handle_connection, args=(conn,), daemon=True).start()

    def _handle_connection(self, conn: socket.socket) -> None:
        rfile = conn.makefile("rb")
        wfile = conn.makefile("wb")
        write_lock = threading.Lock()
        # Per connection, because the ANSI footer is drawn by moving the cursor
        # back over the lines it last wrote: one renderer shared between two
        # clients would have each erasing lines from the other's terminal.
        renderer: list = [None]

        def send(event, payload):
            try:
                with write_lock:
                    write_message(wfile, {"jsonrpc": "2.0", "method": event, "params": payload})
            except (OSError, ValueError):
                # The client went away. The renderer's ticking thread outlives
                # the read loop by up to one tick, so this is reached in normal
                # operation, not only on a crash.
                pass

        def sink(event, payload):
            if renderer[0] is not None and event == "log":
                # Rendered instead of forwarded. The renderer writes through
                # `send` itself -- from this thread and from its own ticking
                # thread -- so nothing is emitted here.
                renderer[0].handle(payload)
                return
            send(event, payload)

        def start_rendering():
            renderer[0] = AnsiEventRenderer(
                # base64 because this is a text field carrying terminal control
                # bytes, and the client writes it into a pty verbatim.
                lambda text: send("terminal", {"line": base64.b64encode(text.encode("utf-8")).decode("ascii")})
            )

        try:
            while not self._stop.is_set():
                request = read_message(rfile)
                if request is None:
                    break

                if isinstance(request, dict) and request.get("method") == STOP_METHOD:
                    if "id" in request:
                        with write_lock:
                            write_message(wfile, {"jsonrpc": "2.0", "id": request["id"], "result": {"stopped": True}})
                    self.stop()
                    break

                if isinstance(request, dict) and request.get("method") == LOG_MODE_METHOD:
                    # Handled here, so `Dispatcher` never sees it -- and neither
                    # does its parameter checking. JSON-RPC allows `params` to be
                    # an array, and `.get` on a list raises, which would take the
                    # connection down rather than answer the request.
                    params = request.get("params")
                    if params is not None and not isinstance(params, dict):
                        if "id" in request:
                            with write_lock:
                                write_message(
                                    wfile,
                                    {
                                        "jsonrpc": "2.0",
                                        "id": request["id"],
                                        "error": {
                                            "code": INVALID_PARAMS,
                                            "message": "Invalid params: expected an object",
                                        },
                                    },
                                )
                        continue
                    wants_ansi = bool((params or {}).get("ansi"))
                    if wants_ansi and renderer[0] is None:
                        start_rendering()
                    elif not wants_ansi and renderer[0] is not None:
                        renderer[0].close()
                        renderer[0] = None
                    if "id" in request:
                        with write_lock:
                            write_message(
                                wfile,
                                {"jsonrpc": "2.0", "id": request["id"], "result": {"ansi": renderer[0] is not None}},
                            )
                    continue

                with self._dispatch_lock:
                    self._session.emitter.set_sink(sink)
                    try:
                        response = self._dispatcher.dispatch(request, self._session)
                    finally:
                        self._session.emitter.set_sink(None)
                if response is not None:
                    with write_lock:
                        write_message(wfile, response)
        except OSError:
            pass
        finally:
            if renderer[0] is not None:
                # A client that disconnects mid-operation leaves a thread
                # redrawing a footer into a closed socket.
                renderer[0].close()
                renderer[0] = None
            try:
                conn.close()
            except OSError:
                pass

    def stop(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        # Remove the rendezvous point before tearing down the listener, not
        # after: a client that connects in between would otherwise reach a
        # socket that is about to stop accepting. It also makes the shutdown
        # observable in one order -- once the accept loop has exited, the socket
        # file is already gone, rather than being unlinked by whichever thread
        # called stop() some time later.
        if self._path and os.path.exists(self._path):
            try:
                os.unlink(self._path)
            except OSError:
                pass
        if self._server_sock is not None:
            try:
                self._server_sock.close()
            except OSError:
                pass
        if self._on_shutdown is not None:
            self._on_shutdown()
