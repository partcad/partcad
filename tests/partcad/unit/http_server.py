#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A private HTTP server for the tests that download something.

Downloads go through 'aiohttp', so a file:// URL is not an option: a test that
exercises a fetch needs something that actually speaks HTTP. Binding to port 0
keeps each server private to its test, so tests still run in parallel.
"""

import contextlib
import functools
import http.server
import threading


@contextlib.contextmanager
def serve(directory):
    """Serve 'directory' over HTTP on a private loopback port, yielding its URL."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:%d" % server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
