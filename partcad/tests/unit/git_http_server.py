#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A throwaway smart-HTTP git server, for tests that need a real remote.

file:// transport does not enforce the server side of the protocol, so it
cannot express a server that refuses to serve a commit id by name: over file://
such a fetch succeeds no matter how the served repository is configured.
Serving over HTTP through git-http-backend does enforce it, because upload-pack
then runs against the served repository's own config, so
uploadpack.allowReachableSHA1InWant decides whether the fetch is answered or
refused exactly as it would on a real remote.

Each server binds to port 0 on the loopback interface, so tests get a private
port and can run in parallel.
"""

import os
import subprocess
import threading
from contextlib import contextmanager

import pygit2
from flask import Flask, Response, request
from werkzeug.serving import make_server


def mirror(source, target, default_branch="main") -> None:
    """Make 'target' a bare repository serving everything 'source' has.

    A bare clone made with pygit2 still files the branches it took under
    refs/remotes/origin/*, which is not where a served repository keeps them:
    upload-pack offers refs/heads/*, and that is what a client's refspec
    matches. Left as they are, every branch but the default one would be
    invisible to anything cloning from here, so they are moved.
    """
    pygit2.clone_repository(str(source), str(target), bare=True)

    repo = pygit2.Repository(str(target))
    for name in list(repo.references):
        if not name.startswith("refs/remotes/origin/"):
            continue
        ref = repo.references[name]
        short = name.removeprefix("refs/remotes/origin/")
        if short != "HEAD":
            repo.references.create("refs/heads/%s" % short, ref.target, force=True)
        repo.references.delete(name)

    repo.set_head("refs/heads/%s" % default_branch)


def _make_app(project_root: str, protocol_v2: bool) -> Flask:
    app = Flask(__name__)

    @app.route("/<path:path>", methods=["GET", "POST"])
    def git_http_backend(path):
        body = request.get_data()

        # git-http-backend is a CGI program, so the request arrives as
        # environment variables and stdin rather than as arguments.
        env = dict(os.environ)
        env.update(
            {
                "GIT_PROJECT_ROOT": project_root,
                "GIT_HTTP_EXPORT_ALL": "1",
                "REQUEST_METHOD": request.method,
                "PATH_INFO": "/" + path,
                "QUERY_STRING": request.query_string.decode(),
                "CONTENT_TYPE": request.content_type or "",
                "CONTENT_LENGTH": str(len(body)),
                "REMOTE_ADDR": request.remote_addr or "127.0.0.1",
                "SERVER_PROTOCOL": "HTTP/1.1",
            }
        )
        # Protocol v2 is negotiated through this header. Dropping it is how a
        # server that predates v2 is modelled: the client then falls back to
        # v0, where uploadpack.allowReachableSHA1InWant actually decides
        # whether an unadvertised object may be requested. Under v2 it is
        # served regardless of that setting.
        if protocol_v2 and request.headers.get("Git-Protocol"):
            env["GIT_PROTOCOL"] = request.headers["Git-Protocol"]
        if request.headers.get("Content-Encoding"):
            env["HTTP_CONTENT_ENCODING"] = request.headers["Content-Encoding"]

        proc = subprocess.run(
            ["git", "http-backend"],
            input=body,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )

        raw_headers, _, payload = proc.stdout.partition(b"\r\n\r\n")
        status = 200
        headers = []
        for line in raw_headers.decode("utf-8", "replace").splitlines():
            name, sep, value = line.partition(":")
            if not sep:
                continue
            if name.strip().lower() == "status":
                status = int(value.split()[0])
            else:
                headers.append((name.strip(), value.strip()))

        return Response(payload, status=status, headers=headers)

    return app


@contextmanager
def serve_git(project_root, protocol_v2=True):
    """Serve every repository under 'project_root' over smart HTTP.

    Yields the base URL. A repository at <project_root>/<name> is then
    reachable at <base_url>/<name>. Pass protocol_v2=False to model a server
    old enough not to speak v2.
    """
    server = make_server("127.0.0.1", 0, _make_app(str(project_root), protocol_v2), threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:%d" % server.server_port
    finally:
        server.shutdown()
        thread.join(timeout=10)
