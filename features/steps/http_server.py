#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Serving a file over HTTP to a scenario that fetches one.

``pc add <kind> <url>`` fetches the file it is given so that the declaration can
be pinned with the ``fileHash`` of what came back, and a scenario that exercises
that has to have something to fetch. A ``file://`` URL is not an option -- the
download goes through ``aiohttp`` -- so the scenario needs something that
actually speaks HTTP, and reaching for a real host would make the scenario a
network test of somebody else's uptime.

Served out of a directory of its own rather than out of the package, so that the
package genuinely does not carry the file: what ``pc add`` writes is a
declaration that fetches it, and the scenario can then assert that nothing was
left behind.
"""

import functools
import http.server
import os
import tempfile
import threading

from behave import given, then
from behave.runner import Context


@given('"{filename}" is served over HTTP with content')
def file_is_served_over_http(context: Context, filename: str):
    """Serve one file on a private loopback port for the rest of the scenario.

    The base URL is exported as ``$PC_TEST_HTTP_URL``, which the ``I run`` step
    expands, so a scenario writes ``$PC_TEST_HTTP_URL/firmware.bin`` and never
    has to know which port it got. Binding to port 0 keeps each server private
    to its own scenario, so the behave shards still run in parallel.
    """
    directory = tempfile.mkdtemp(prefix="pc-behave-http-")
    # Written as bytes, because a scenario pins what is served with a 'fileHash'
    # it names literally. A text-mode handle translates '\n' to '\r\n' on
    # Windows, so the file the server served would not be the file the scenario
    # hashed, and the assertion would fail there and only there.
    with open(os.path.join(directory, filename), "wb") as served:
        served.write(context.text.encode("utf-8"))

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def stop_serving():
        server.shutdown()
        server.server_close()
        thread.join()

    context.add_cleanup(stop_serving)

    if not hasattr(context, "env"):
        context.env = {}
    context.env["PC_TEST_HTTP_URL"] = "http://127.0.0.1:%d" % server.server_address[1]


@then('a file named "{filename}" should contain "{text}"')
def file_should_contain(context: Context, filename: str, text: str):
    """Assert on one line of a file the command wrote.

    The sibling step that compares whole YAML documents cannot be used on a
    declaration written from a URL: the URL carries the port the server happened
    to get, so no expected document can be written down ahead of time.
    """
    path = os.path.join(context.test_dir, filename)
    with open(path, encoding="utf-8") as written:
        content = written.read()
    assert text in content, "'%s' does not contain %r:\n%s" % (filename, text, content)
