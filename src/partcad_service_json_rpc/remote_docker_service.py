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
this machine.** A request names the image, the requirements and the command,
and the sandbox interpreter runs whatever Python it is handed -- so on a
reachable address this is a remote shell for anybody who can reach the port.

Two things stand between that and a mistake. It binds loopback by default, the
same posture the per-workspace daemon takes and resting on the same assumption:
it is reachable from where you chose to bind it and nowhere else. And it
**refuses to start** on any other address without ``--token`` (or
``PC_REMOTE_SANDBOX_TOKEN``), which every request must then carry as
``Authorization: Bearer <token>``; clients send it by setting
``remoteSandboxToken``. Refused at start-up rather than warned about, because
somebody who passed ``--host 0.0.0.0`` is not going to read the log of a
service that came up and appeared to work.
"""

import argparse
import hmac
import ipaddress
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from partcad import remote_docker, remote_sandbox
from partcad.remote_sandbox import execute
from partcad.remote_sandbox import forward as _forward
from partcad_utils import logging as pc_logging

# The stdlib rather than a web framework, like the service inside every
# container (`partcad_utils.container_service`): this one ships in the wheel,
# and a wheel dependency is also a thing the frozen bundles have to carry and
# PyInstaller has to be told about (see `dev-tools/pyinstaller/README.md`).
# What is needed here is one JSON-RPC method over HTTP POST, which is smaller
# than the paperwork of adding a framework to a CAD tool.


class Handler(BaseHTTPRequestHandler):
    """One JSON-RPC method, over POST, at any path.

    ``pool`` and ``environments`` are set on the server rather than reached
    through module globals, so that the handler is testable against a pool that
    starts nothing.
    """

    protocol_version = "HTTP/1.1"

    def _authenticated(self) -> bool:
        """Whether this request carries the secret the service was started with.

        No token configured means none is asked for, which is the loopback
        default: nothing off this machine can reach the port, and a secret
        between a machine and itself protects nothing. `main()` is what makes
        that safe -- it refuses to bind anything but loopback without one.

        `compare_digest` rather than `==` because the comparison is against a
        secret and a caller can retry: the natural comparison stops at the first
        differing byte, and the time it takes says how much of the token was
        right.
        """
        token = getattr(self.server, "token", None)
        if not token:
            return True
        offered = self.headers.get("Authorization") or ""
        scheme, _, value = offered.partition(" ")
        if scheme.lower() != "bearer":
            return False
        # Bytes, not text: `compare_digest` refuses two `str` operands unless
        # both are ASCII, and what arrives in a header is whatever the caller
        # sent. This runs before the handler's `try`, so a `TypeError` here is
        # not a 401 -- it is the connection closing with nothing said.
        return hmac.compare_digest(value.strip().encode("utf-8", "replace"), token.encode("utf-8"))

    def do_POST(self):  # noqa: N802 - the name BaseHTTPRequestHandler dispatches to
        length = int(self.headers.get("Content-Length") or 0)
        request_id = None
        if not self._authenticated():
            # Read and discard the body first: this connection is keep-alive
            # (HTTP/1.1), so a body left unread is the next request as far as
            # the parser is concerned.
            self.rfile.read(length)
            pc_logging.warning("Refused an unauthenticated request from %s" % self.address_string())
            self._reply(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32001, "message": "Authentication required"},
                },
                status=401,
            )
            return
        try:
            request = json.loads(self.rfile.read(length) or b"{}")
            request_id = request.get("id")
            if request.get("method") != "execute":
                raise ValueError("Unknown method: %r. This service serves 'execute'." % request.get("method"))
            result = execute(self.server.pool, self.server.environments, request.get("params") or {})
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


def _sweep(pool, environments, every: float) -> None:
    """Retire what nothing is using, forever, in the background."""
    while True:
        time.sleep(every)
        try:
            for lease in pool.retire():
                # The volume stays; what is forgotten is only what this process
                # believed was installed in it, so the next request re-checks.
                environments.forget(lease.image)
                pc_logging.info("Retired the idle container for %s" % lease.image)
        except Exception as e:
            pc_logging.warning("Could not retire containers: %s" % e)


def _loopback(host: str) -> bool:
    """Whether an address reaches this machine and nothing else.

    Every loopback address, not just "127.0.0.1": the whole of 127.0.0.0/8 is
    loopback, "::1" is its IPv6 spelling, and "localhost" is what a person
    actually types. An empty host, or "0.0.0.0", or "::" means *every*
    interface, which is the case this exists to catch, so anything that does
    not parse as a loopback address is treated as reachable.
    """
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host.lower() in ("localhost", "localhost.localdomain")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="partcad-service-remote-docker",
        description="Run PartCAD sandbox containers on this machine for clients elsewhere.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Address to serve on. The default is loopback, deliberately: this service runs commands. "
        "Any other address requires --token.",
    )
    parser.add_argument("--port", type=int, default=5050, help="Port to serve on.")
    parser.add_argument(
        "--token",
        default=os.environ.get("PC_REMOTE_SANDBOX_TOKEN") or None,
        help="A shared secret every request must carry as 'Authorization: Bearer <token>'. "
        "Required to serve on anything but loopback. Defaults to PC_REMOTE_SANDBOX_TOKEN, so it "
        "need not appear in the process arguments, where anybody on the machine can read it.",
    )
    parser.add_argument(
        "--idle-timeout",
        type=float,
        default=remote_docker.DEFAULT_IDLE_SECONDS,
        help="Seconds a container may go unused before it is retired.",
    )
    args = parser.parse_args(argv)

    pool = remote_docker.ContainerPool(remote_docker.start, idle_seconds=args.idle_timeout)
    # Provisioning reaches a container the same way a forwarded request does,
    # so there is one path to a container and not two.
    environments = remote_sandbox.Environments(
        lambda image, command, lock: _forward(pool, image, command, {"lock": lock})
    )

    # A service that starts containers and runs commands in them, reachable
    # from the network and asking nothing of its callers, is a remote shell for
    # whoever can reach the port: a request names the image, the requirements
    # and the command, and the sandbox interpreter runs whatever Python it is
    # given. Loopback is the default for that reason, and anything wider has to
    # come with a way of telling callers apart.
    #
    # Refused at start-up rather than warned about, because the person who
    # passed '--host 0.0.0.0' is not going to be reading the log of a service
    # that came up and appeared to work.
    if not _loopback(args.host) and not args.token:
        pc_logging.error(
            "Refusing to serve on %s without --token (or PC_REMOTE_SANDBOX_TOKEN): this service runs "
            "commands in containers, so a reachable address with no authentication is a shell for "
            "anybody who can reach the port. Serve on 127.0.0.1, or set a token and give it to the "
            "clients as 'remoteSandboxToken'." % args.host
        )
        return 1

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.pool = pool
    server.environments = environments
    server.token = args.token

    # A floor as well as a ceiling: '--idle-timeout 0' made the sweep a
    # 'time.sleep(0)' loop that took the pool lock as fast as it could, which is
    # one core for as long as the service runs.
    sweeper = threading.Thread(
        target=_sweep, args=(pool, environments, max(1.0, min(60.0, args.idle_timeout))), daemon=True
    )
    sweeper.start()

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
