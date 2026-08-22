#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The ``partcad-json-rpc`` executable.

Serves PartCAD over JSON-RPC 2.0. By default it runs the per-workspace **socket
daemon**: it prints the socket path to stdout and, if none is running, starts a
detached daemon serving a warm context. ``--stdio`` serves over stdin/stdout
(LSP-style framing) in the foreground; ``--http [ADDR]`` serves over HTTP
(JSON-RPC at ``/rpc``, notifications over SSE at ``/events``; no auth). The
option names mirror ``partcad-cli`` globals so the service is driven the way the
CLI is.
"""

import argparse
import os
import sys

from . import __version__
from .core.session import Session
from .rpc.methods import build_registry
from .transport.stdio import serve_stdio

DEFAULT_HTTP_ADDRESS = "127.0.0.1:8017"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="partcad-json-rpc",
        description="JSON-RPC service interface to PartCAD.",
    )
    parser.add_argument("--version", action="version", version=f"partcad-json-rpc {__version__}")
    # Channel selection (default: the per-workspace socket daemon).
    parser.add_argument("--socket", action="store_true", help="Use the per-workspace socket daemon (default).")
    parser.add_argument("--stdio", action="store_true", help="Serve over stdin/stdout in the foreground.")
    parser.add_argument(
        "--http",
        nargs="?",
        const=DEFAULT_HTTP_ADDRESS,
        default=None,
        metavar="ADDR",
        help="Serve over HTTP at ADDR (default %s) in the foreground." % DEFAULT_HTTP_ADDRESS,
    )
    # Internal: serve a specific named pipe (used by the detached Windows child).
    parser.add_argument("--serve-pipe", default=None, help=argparse.SUPPRESS)
    # Output options (mirror `pc --verbose/--quiet`).
    parser.add_argument("-v", "--verbose", action="store_true", help="Increase logging verbosity.")
    parser.add_argument("-q", "--quiet", action="store_true", help="Decrease logging verbosity.")
    # Dependency management options.
    parser.add_argument("--offline", action="store_true", help="Do not fetch anything from the network.")
    parser.add_argument("--force-update", action="store_true", help="Force refresh of cached dependencies.")
    parser.add_argument(
        "--devel-index",
        action="store_true",
        help="Use the 'devel' branch of the public index instead of the released one.",
    )
    # Sandbox options.
    parser.add_argument("--python-sandbox", default=None, help="Python sandbox runtime for CAD scripts.")
    parser.add_argument("--javascript-sandbox", default=None, help="JavaScript sandbox runtime for CAD scripts.")
    return parser


def parse_args(argv=None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def build_settings(args: argparse.Namespace) -> dict:
    """Map CLI flags onto the setting keys the operations core understands."""
    settings = {}
    if args.python_sandbox:
        settings["pythonSandbox"] = args.python_sandbox
    if args.javascript_sandbox:
        settings["javascriptSandbox"] = args.javascript_sandbox
    if args.force_update:
        settings["forceUpdate"] = "true"
    if args.devel_index:
        settings["develIndex"] = "true"
    if args.offline:
        settings["offline"] = "true"
    if args.verbose:
        settings["verbosity"] = "debug"
    elif args.quiet:
        settings["verbosity"] = "error"
    else:
        settings["verbosity"] = "info"
    return settings


def parse_host_port(address: str) -> tuple[str, int]:
    """Parse ``HOST:PORT`` or a bare ``PORT`` into ``(host, port)``."""
    if ":" in address:
        host, _, port = address.rpartition(":")
        return host or "127.0.0.1", int(port)
    return "127.0.0.1", int(address)


def _build_session(args: argparse.Namespace, log_dir: str = None) -> Session:
    session = Session(settings=build_settings(args))
    # The per-workspace daemon keeps a rotating log file next to its socket; the
    # foreground channels (stdio/HTTP) stream to the client without a file.
    log_file = os.path.join(log_dir, "partcad.log") if log_dir else None
    session.start_remote_log(log_file=log_file)
    return session


def main(argv=None) -> int:
    args = parse_args(argv)

    # Internal: the detached Windows child serves a specific named pipe.
    if args.serve_pipe is not None:  # pragma: no cover - Windows only
        from .win_pipe import serve_pipe

        serve_pipe(_build_session(args), build_registry(), args.serve_pipe)
        return 0

    if args.http is not None:
        from .transport.http import serve_http  # imported lazily to keep startup light

        host, port = parse_host_port(args.http)
        serve_http(_build_session(args), build_registry(), host, port)
        return 0

    if args.stdio:
        serve_stdio(_build_session(args), build_registry())
        return 0

    # Default: the per-workspace socket daemon. The session is built only in the
    # daemon child (after fork), so the fast path (a live daemon) stays cheap.
    from . import daemon

    daemon.ensure_daemon(lambda wdir: _build_session(args, wdir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
