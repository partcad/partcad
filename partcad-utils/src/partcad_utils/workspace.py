#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Where a workspace's daemon listens, and whether anything is listening there.

This is the rendezvous between a PartCAD client and the daemon serving its
workspace: the daemon binds the address these functions compute, and the client
looks for it at the same address. Neither side owns it, which is why it lives
here rather than in `partcad-client-utils` or `partcad-service-json-rpc` -- a
copy on each side is a copy that can disagree, and a disagreement is a client
that silently starts a second daemon.

A daemon serves one workspace, keyed by a hash of its root path, over an AF_UNIX
socket at ``~/.partcad/workspaces/<hash>/socket`` (a named pipe on Windows).

Root discovery replicates PartCAD's ``Context`` walk-up deliberately, so the hot
path -- a CLI command that only needs to find and connect to a live daemon --
never imports the heavy ``partcad`` module.
"""

import contextlib
import hashlib
import os
import socket
from typing import Optional

from .framing import read_message, write_message

# How long to wait for a daemon to answer a liveness probe.
LIVENESS_TIMEOUT = 1.0


def determine_root_path(start: Optional[str] = None) -> str:
    """Find the workspace root the way ``partcad.Context`` does, without importing
    partcad. Walks up while a parent ``partcad.yaml`` exists."""
    root = os.path.abspath(start or os.getcwd())
    if os.path.isfile(root):
        root = os.path.dirname(root)
    while os.path.exists(os.path.join(root, "..", "partcad.yaml")):
        root = os.path.abspath(os.path.join(root, ".."))
    return root


def workspace_hash(root_path: str) -> str:
    # Truncated so the AF_UNIX socket path stays under the ~108-char limit.
    return hashlib.sha256(root_path.encode("utf-8")).hexdigest()[:16]


def workspaces_dir() -> str:
    """The directory holding every workspace's daemon state on this machine."""
    return os.path.join(os.path.expanduser("~"), ".partcad", "workspaces")


def workspace_dir(root_path: str) -> str:
    return os.path.join(workspaces_dir(), workspace_hash(root_path))


def socket_path(root_path: str) -> str:
    return os.path.join(workspace_dir(root_path), "socket")


def pid_path(wdir: str) -> str:
    """The daemon's pid file, written by the daemon and read by whoever waits."""
    return os.path.join(wdir, "pid")


def is_alive(path: str, timeout: float = LIVENESS_TIMEOUT) -> bool:
    """True if a daemon answers ``rpc.discover`` on the socket within ``timeout``.

    A probe, not a file check: a socket file outlives a daemon that was killed,
    and connecting to a stale one is how a client hangs instead of starting a
    replacement.
    """
    if not os.path.exists(path):
        return False
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout)
    try:
        client.connect(path)
        stream = client.makefile("rwb")
        write_message(stream, {"jsonrpc": "2.0", "id": 0, "method": "rpc.discover", "params": {}})
        response = read_message(stream)
        return isinstance(response, dict) and response.get("id") == 0 and "result" in response
    except OSError:
        return False
    finally:
        with contextlib.suppress(OSError):
            client.close()
