#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A recording HTTP proxy, for the tests that ask what went through one.

"Does this downloader respect ``HTTPS_PROXY``" has one honest answer: point the
variable at something and see whether the request arrives. Mocking the client
library answers a different question -- whether it was called the way the test
expected -- and that is exactly the question that was never wrong about
``aiohttp``, whose default is to read the variable and then ignore it.

So this is a real proxy on a private loopback port, and what a test asserts is
what it was asked to reach. It answers every request with a 502 and hangs up:
the point is never to complete a transfer -- the hosts in these tests do not
exist -- but to record the attempt, and refusing is what makes the two outcomes
tell themselves apart quickly. A client that dialled the proxy gets a prompt
proxy error; a client that ignored the variable gets a name resolution failure
for a host under ``.invalid``, which RFC 2606 reserves for exactly this and
which therefore resolves nowhere.

Binding to port 0 keeps each proxy private to its test, so tests still run in
parallel.
"""

import contextlib
import socketserver
import threading


class _Handler(socketserver.StreamRequestHandler):
    """Record what the first request line asks for, then refuse it."""

    # A client that has given up on an unreachable proxy is not this proxy's
    # problem, but a handler thread stuck on a socket that says nothing would
    # hold up 'shutdown()' at the end of the test.
    timeout = 30

    def handle(self):
        # Whichever way a client reaches a proxy, it says where it is going in
        # its first line: 'CONNECT host:port' for a tunnel, which is what an
        # https:// URL becomes, and an absolute-form 'GET http://host/path' for
        # plain HTTP.
        try:
            request_line = self.rfile.readline(65536).decode("latin-1")
        except OSError:
            return
        if not request_line.strip():
            return

        method, _, rest = request_line.strip().partition(" ")
        # "<target> HTTP/1.1" -- the version is dropped, the target may itself
        # contain spaces in nothing this test suite sends.
        target = rest.rsplit(" ", 1)[0].strip() if " " in rest else rest.strip()
        self.server.requests.append((method.upper(), target))

        with contextlib.suppress(OSError):
            self.wfile.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")


class _Proxy(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, *args, **kwargs):
        self.requests: list[tuple[str, str]] = []
        super().__init__(*args, **kwargs)

    @property
    def url(self) -> str:
        return "http://127.0.0.1:%d" % self.server_address[1]

    def reached(self, host: str, port: int = 443) -> bool:
        """Whether something asked this proxy to reach 'host:port'."""
        return ("CONNECT", "%s:%d" % (host, port)) in self.requests


@contextlib.contextmanager
def serve_proxy():
    """Run a recording proxy on a private loopback port, yielding the server."""
    server = _Proxy(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=30)
