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

``daemon.stop`` is handled at the transport level (it controls the server, not
the PartCAD context): the server answers, then stops accepting, closes, and
unlinks the socket.
"""

import os
import socket
import threading
from typing import Callable, Mapping, Optional

from ..rpc.dispatcher import Dispatcher, Handler
from .framing import read_message, write_message

STOP_METHOD = "daemon.stop"


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

        def sink(event, payload):
            with write_lock:
                write_message(wfile, {"jsonrpc": "2.0", "method": event, "params": payload})

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
