#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""An S3-compatible object store, in Python, for the tests of the 'cacheS3' tier.

Enough of the S3 REST API for a client to put and get objects: PUT, GET, HEAD
and DELETE of '/{bucket}/{key}'. That is the whole of what the cache backend
uses, and serving it over a real socket is what lets the test suite exercise the
real boto3 client - its signing, its retries, its response parsing - rather than
a stub of it.

Signatures are accepted without being checked: the point here is the transfer,
not the authentication, and a test hands the client throwaway credentials. What
is faithful is the part the cache depends on - a missing object answers 404 with
the 'NoSuchKey' error document boto3 turns into a miss, and a body is returned
as the exact bytes it arrived as, so the zstd-compressed BREP frame travels
through this server untouched.

Each server binds to port 0 on the loopback interface, so tests get a private
port and can run in parallel.
"""

import hashlib
import threading
from contextlib import contextmanager

from flask import Flask, Response, request
from werkzeug.serving import make_server

# The error document S3 answers a GET of a missing key with. boto3 parses it
# into ClientError.response["Error"]["Code"], which is what the backend reads to
# tell a cache miss from a failure.
NO_SUCH_KEY = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    "<Error><Code>NoSuchKey</Code>"
    "<Message>The specified key does not exist.</Message>"
    "<Key>%s</Key></Error>"
)


class Storage(dict):
    """The objects the server holds, keyed '<bucket>/<key>'."""

    def bodies(self) -> dict:
        return dict(self)


def _make_app(storage: Storage, requests: list) -> Flask:
    app = Flask(__name__)

    @app.route("/<bucket>/<path:key>", methods=["PUT", "GET", "HEAD", "DELETE"])
    def object_endpoint(bucket, key):
        name = "%s/%s" % (bucket, key)
        requests.append((request.method, name))

        if request.method == "PUT":
            body = request.get_data()
            storage[name] = body
            return Response(status=200, headers={"ETag": '"%s"' % hashlib.md5(body).hexdigest()})

        body = storage.get(name)
        if body is None:
            return Response(NO_SUCH_KEY % key, status=404, mimetype="application/xml")

        if request.method == "DELETE":
            del storage[name]
            return Response(status=204)

        return Response(
            b"" if request.method == "HEAD" else body,
            status=200,
            headers={"Content-Length": str(len(body)), "ETag": '"%s"' % hashlib.md5(body).hexdigest()},
            mimetype="application/octet-stream",
        )

    return app


@contextmanager
def serve_s3():
    """Run the server for the duration of the block, yielding (url, storage).

    'storage' is the live object map, so a test can look at what the client
    actually sent rather than only at what reading it back returns.
    """
    storage = Storage()
    requests = []
    server = make_server("127.0.0.1", 0, _make_app(storage, requests), threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        storage.requests = requests
        yield "http://127.0.0.1:%d" % server.server_port, storage
    finally:
        server.shutdown()
        thread.join(timeout=10)
