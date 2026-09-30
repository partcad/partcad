#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A private HTTP server for the tests that download something.

Downloads go through 'aiohttp' and 'requests', so a file:// URL is not an
option: a test that exercises a fetch needs something that actually speaks
HTTP. Binding to port 0 keeps each server private to its test, so tests still
run in parallel.
"""

import contextlib
import functools
import http.server
import os
import threading

# Both clients read the proxy environment -- 'requests' by default and
# 'aiohttp' because PartCAD builds its session with trust_env=True -- so on a
# machine that exports one, a fetch from the server below would be handed to a
# proxy that cannot reach a port on this host. A developer behind a proxy
# normally exempts loopback already; this makes the tests not depend on that.
NO_PROXY_HOSTS = "127.0.0.1,localhost,::1"


@contextlib.contextmanager
def _loopback_is_never_proxied():
    """Add loopback to 'no_proxy' for the duration, restoring what was there."""
    saved = {name: os.environ.get(name) for name in ("no_proxy", "NO_PROXY")}
    for name, value in saved.items():
        os.environ[name] = "%s,%s" % (NO_PROXY_HOSTS, value) if value else NO_PROXY_HOSTS
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@contextlib.contextmanager
def serve(directory):
    """Serve 'directory' over HTTP on a private loopback port, yielding its URL."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with _loopback_is_never_proxied():
            yield "http://127.0.0.1:%d" % server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
