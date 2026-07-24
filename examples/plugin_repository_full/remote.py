#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#
"""Repository plugin: forwards each key to the remote endpoint (server.py).

PartCAD runs this script in its sandbox for every data request, with the
generic key in ``request["key"]`` and ``__name__`` set to the API ("get"). It
returns ``{"result": <value>}``. The transport is factored into ``fetch`` so the
request/response mapping can be unit-tested against the server without a port
(see test_full_remote.py).
"""

import json
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_ENDPOINT = "http://127.0.0.1:5000"


def _http_fetch(endpoint, key):
    url = endpoint.rstrip("/") + "/data?key=" + urllib.parse.quote(key)
    try:
        with urllib.request.urlopen(url) as resp:
            return json.load(resp).get("result")
    except urllib.error.HTTPError:
        # An unknown key (404) means "no such data" - report it as empty.
        return None
    except urllib.error.URLError:
        # The endpoint is not reachable (e.g. the server is not running). Report
        # empty rather than crash, so listing a repository whose server is down
        # degrades gracefully.
        return None


def handle(request, fetch=_http_fetch):
    endpoint = request.get("parameters", {}).get("endpoint", DEFAULT_ENDPOINT)
    return {"result": fetch(endpoint, request["key"])}


if __name__ == "get":
    output = handle(request)  # noqa: F821 - 'request' is injected by the runtime
