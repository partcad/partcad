#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""``partcad-service-remote-docker``: containers on this machine, for a client elsewhere.

The ``docker`` sandbox mounts the caller's files into a container, which needs
the caller and the container to be on one machine. This service is what removes
that requirement: a client using the ``remote`` sandbox sends its directories and
its command over JSON-RPC, and this picks the container for the image named in
the request, forwards the call to the service inside it, and sends the answer
back.

So it is a proxy and a caretaker, and nothing else. It runs no PartCAD logic, it
holds no context, and it does not know what an analysis is -- it knows images,
containers and requests. The choosing and the retiring live in
``partcad.remote_docker``, where they can be tested without a daemon; what is
here is the wiring to Docker and to the network.

**It gives whoever can reach it the ability to run commands in containers on
this machine.** There is no authentication, which is the same posture the
per-workspace daemon takes and rests on the same assumption: it is reachable
from where you chose to bind it and nowhere else. Bind it to a loopback address
unless the machines that may use it are the ones that can route to it.
"""

import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from partcad import remote_docker
from partcad.runtime_json_rpc import RuntimeJsonRpcClient
from partcad_utils import logging as pc_logging

# Where the service inside every PartCAD image listens. Not configurable per
# request: it is part of the base image contract (see
# `tools/containers/README.md`), and a request naming a port would be a request
# choosing what to talk to inside somebody else's container.
CONTAINER_PORT = 5000

# The stdlib rather than flask, which is what the service *inside* an image
# uses. That one lives where flask is installed; this one ships in the wheel,
# and a wheel dependency is also a thing the frozen bundles have to carry and
# PyInstaller has to be told about (see `dev-tools/pyinstaller/README.md`).
# What is needed here is one JSON-RPC method over HTTP POST, which is smaller
# than the paperwork of adding a web framework to a CAD tool.


def _docker_start(image: str) -> remote_docker.Lease:
    """Start a container for ``image`` and wait for its service to answer.

    Pulled if this machine does not have it. The architecture-suffixed name is
    tried first, exactly as a client would try it, so an image published under
    the convention works here without the client having to know which
    architecture this machine is.
    """
    import docker

    from partcad import docker_image

    client = docker.from_env()

    chosen = None
    for candidate in docker_image.candidates(image):
        try:
            client.images.get(candidate)
            chosen = candidate
            break
        except docker.errors.ImageNotFound:
            continue
    if chosen is None:
        errors = []
        for candidate in docker_image.candidates(image):
            try:
                client.images.pull(candidate)
                chosen = candidate
                break
            except Exception as e:
                errors.append("%s: %s" % (candidate, e))
        if chosen is None:
            raise RuntimeError("Cannot get an image for '%s': %s" % (image, "; ".join(errors)))

    container = client.containers.run(
        chosen,
        detach=True,
        # A port of the host's choosing, so two images can be served at once.
        ports={"%d/tcp" % CONTAINER_PORT: None},
        labels=dict(remote_docker.LABELS),
        auto_remove=False,
    )

    # The port Docker picked, once it has picked one.
    endpoint = None
    for _ in range(60):
        container.reload()
        bindings = (container.attrs.get("NetworkSettings") or {}).get("Ports") or {}
        published = bindings.get("%d/tcp" % CONTAINER_PORT)
        if published:
            endpoint = "%s:%s" % (published[0]["HostIp"] or "127.0.0.1", published[0]["HostPort"])
            break
        time.sleep(0.5)
    if endpoint is None:
        container.remove(force=True)
        raise RuntimeError("The container for '%s' never published a port" % image)

    pc_logging.info("Serving %s from %s at %s" % (image, container.short_id, endpoint))
    return remote_docker.Lease(image, container, endpoint)


def execute(pool, params: dict) -> dict:
    """Run one command in the container for the image the request names.

    Every parameter but ``image`` is passed through untouched: this speaks the
    same protocol the service inside the container does, because a proxy that
    reshaped the request would be a second place for the protocol to be wrong.
    """
    image = params.get("image")
    if not image:
        raise ValueError("'image' is required: it is what decides which container runs this")
    command = params.get("command")
    if not command:
        raise ValueError("'command' is required")

    lease = pool.acquire(image)
    try:
        host, port = lease.endpoint.rsplit(":", 1)
        rpc = RuntimeJsonRpcClient(host, int(port))
        return rpc.execute(
            command,
            {
                "stdin": params.get("stdin"),
                "cwd": params.get("cwd"),
                "input_files": params.get("input_files") or {},
                "output_files": params.get("output_files") or [],
                "input_dirs": params.get("input_dirs") or {},
            },
        )
    finally:
        pool.release(lease)


class Handler(BaseHTTPRequestHandler):
    """One JSON-RPC method, over POST, at any path.

    ``pool`` is set on the server rather than reached through a module global,
    so that the handler is testable against a pool that starts nothing.
    """

    protocol_version = "HTTP/1.1"

    def do_POST(self):  # noqa: N802 - the name BaseHTTPRequestHandler dispatches to
        length = int(self.headers.get("Content-Length") or 0)
        request_id = None
        try:
            request = json.loads(self.rfile.read(length) or b"{}")
            request_id = request.get("id")
            if request.get("method") != "execute":
                raise ValueError("Unknown method: %r. This service serves 'execute'." % request.get("method"))
            result = execute(self.server.pool, request.get("params") or {})
            self._reply({"jsonrpc": "2.0", "id": request_id, "result": result})
        except Exception as e:
            pc_logging.warning("Request failed: %s" % e)
            self._reply(
                {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32603, "message": str(e)}},
                status=500,
            )

    def _reply(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        """Through PartCAD's logging rather than onto stderr directly."""
        pc_logging.debug("%s - %s" % (self.address_string(), fmt % args))


def _sweep(pool, every: float) -> None:
    """Retire what nothing is using, forever, in the background."""
    while True:
        time.sleep(every)
        try:
            for lease in pool.retire():
                pc_logging.info("Retired the idle container for %s" % lease.image)
        except Exception as e:
            pc_logging.warning("Could not retire containers: %s" % e)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="partcad-service-remote-docker",
        description="Run PartCAD sandbox containers on this machine for clients elsewhere.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Address to serve on. The default is loopback, deliberately: this service runs commands "
        "and has no authentication of its own.",
    )
    parser.add_argument("--port", type=int, default=5050, help="Port to serve on.")
    parser.add_argument(
        "--idle-timeout",
        type=float,
        default=remote_docker.DEFAULT_IDLE_SECONDS,
        help="Seconds a container may go unused before it is retired.",
    )
    args = parser.parse_args(argv)

    pool = remote_docker.ContainerPool(_docker_start, idle_seconds=args.idle_timeout)

    sweeper = threading.Thread(target=_sweep, args=(pool, min(60.0, args.idle_timeout)), daemon=True)
    sweeper.start()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.pool = pool

    pc_logging.info("Serving containers on %s:%d" % (args.host, args.port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        # The containers are this process's to clean up: nothing else knows
        # they were started on somebody's behalf.
        for lease in pool.shutdown():
            pc_logging.info("Stopped the container for %s" % lease.image)
    return 0


if __name__ == "__main__":
    sys.exit(main())
