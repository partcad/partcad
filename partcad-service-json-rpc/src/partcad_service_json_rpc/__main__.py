#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The ``partcad-json-rpc`` executable.

Serves PartCAD over JSON-RPC 2.0. By default it serves over stdin/stdout with
LSP-style framing; ``--http [ADDR]`` serves over HTTP instead (JSON-RPC at
``/rpc`` and a Server-Sent-Events notification stream at ``/events``; no auth).
The option names mirror ``partcad-cli`` globals so the service is driven the way
the CLI is.
"""

import argparse
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
    parser.add_argument(
        "--http",
        nargs="?",
        const=DEFAULT_HTTP_ADDRESS,
        default=None,
        metavar="ADDR",
        help="Serve over HTTP at ADDR (default %s) instead of stdin/stdout." % DEFAULT_HTTP_ADDRESS,
    )
    # Output options (mirror `pc --verbose/--quiet`).
    parser.add_argument("-v", "--verbose", action="store_true", help="Increase logging verbosity.")
    parser.add_argument("-q", "--quiet", action="store_true", help="Decrease logging verbosity.")
    # Dependency management options.
    parser.add_argument("--offline", action="store_true", help="Do not fetch anything from the network.")
    parser.add_argument("--force-update", action="store_true", help="Force refresh of cached dependencies.")
    # API keys.
    parser.add_argument("--google-api-key", default=None, help="Google Generative AI API key.")
    parser.add_argument("--openai-api-key", default=None, help="OpenAI API key.")
    # Sandbox options.
    parser.add_argument("--python-sandbox", default=None, help="Python sandbox runtime for CAD scripts.")
    return parser


def parse_args(argv=None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def build_settings(args: argparse.Namespace) -> dict:
    """Map CLI flags onto the setting keys the operations core understands."""
    settings = {}
    if args.python_sandbox:
        settings["pythonSandbox"] = args.python_sandbox
    if args.force_update:
        settings["forceUpdate"] = "true"
    if args.offline:
        settings["offline"] = "true"
    if args.google_api_key:
        settings["googleApiKey"] = args.google_api_key
    if args.openai_api_key:
        settings["openaiApiKey"] = args.openai_api_key
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


def main(argv=None) -> int:
    args = parse_args(argv)
    session = Session(settings=build_settings(args))
    registry = build_registry()

    if args.http is not None:
        from .transport.http import (
            serve_http,  # imported lazily to keep stdio startup light
        )

        host, port = parse_host_port(args.http)
        serve_http(session, registry, host, port)
    else:
        session.start_log_stream()
        serve_stdio(session, registry)
    return 0


if __name__ == "__main__":
    sys.exit(main())
