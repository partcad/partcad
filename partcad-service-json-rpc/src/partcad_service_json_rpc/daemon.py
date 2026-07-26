#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Per-workspace daemon lifecycle for the socket channel.

A daemon serves one workspace (keyed by a hash of its root path) over an AF_UNIX
socket at ``~/.partcad/workspaces/<hash>/socket``. Callers run
:func:`ensure_daemon`, which prints the socket path to stdout and, if no live
daemon is found, starts one (double-forked and detached on POSIX) that serves a
warm shared session.

Root discovery here replicates PartCAD's ``Context`` walk-up deliberately, so the
hot path (a CLI command that only needs to find and connect to a live daemon)
never imports the heavy ``partcad`` module.
"""

import contextlib
import hashlib
import os
import signal
import socket
import sys
from typing import Callable, Optional

from .rpc.methods import build_registry
from .transport.framing import read_message, write_message
from .transport.socket_server import SocketServer

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


def workspace_dir(root_path: str) -> str:
    return os.path.join(os.path.expanduser("~"), ".partcad", "workspaces", workspace_hash(root_path))


def socket_path(root_path: str) -> str:
    return os.path.join(workspace_dir(root_path), "socket")


def is_alive(path: str, timeout: float = LIVENESS_TIMEOUT) -> bool:
    """True if a daemon answers ``rpc.discover`` on the socket within ``timeout``."""
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


@contextlib.contextmanager
def _flock(lock_path: str):
    import fcntl

    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def ensure_daemon(
    build_session: Callable,
    root_path: Optional[str] = None,
    liveness_timeout: float = LIVENESS_TIMEOUT,
) -> str:
    """Ensure a daemon serves the workspace and return (and print) its socket path.

    On POSIX, starts a detached daemon when none is alive. ``build_session`` is a
    zero-arg callable returning the warm :class:`Session` the daemon serves.
    """
    root = root_path or determine_root_path()
    sock = socket_path(root)
    wdir = os.path.dirname(sock)
    os.makedirs(wdir, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(wdir, 0o700)

    with _flock(os.path.join(wdir, "lock")):
        if is_alive(sock, liveness_timeout):
            print(sock, flush=True)
            return sock
        if os.path.exists(sock):
            with contextlib.suppress(OSError):
                os.unlink(sock)

        server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server_sock.bind(sock)
        os.chmod(sock, 0o600)
        server_sock.listen(64)
        print(sock, flush=True)

    if os.name == "nt":  # pragma: no cover - exercised only on Windows
        from .win_pipe import spawn_pipe_daemon

        server_sock.close()
        spawn_pipe_daemon(root)
        return sock

    _serve_detached(server_sock, sock, wdir, build_session)
    return sock


def _serve_detached(server_sock: socket.socket, sock: str, wdir: str, build_session: Callable) -> None:
    """Double-fork; the launcher returns, the detached grandchild serves."""
    if os.fork() > 0:
        # Launcher: hand the socket path back to whoever invoked us and exit
        # the ensure step (main() will return). The grandchild keeps the socket.
        server_sock.close()
        return

    os.setsid()
    if os.fork() > 0:
        os._exit(0)

    # Grandchild = daemon.
    os.chdir("/")
    _redirect_std_fds(os.path.join(wdir, "daemon.log"))
    _write_pid(wdir)

    session = build_session()
    server = SocketServer(session, build_registry(), on_shutdown=lambda: _cleanup(wdir))

    def _terminate(_signum, _frame):
        server.stop()

    signal.signal(signal.SIGTERM, _terminate)
    signal.signal(signal.SIGINT, _terminate)

    try:
        server.serve_accepted(server_sock, sock)
    finally:
        _cleanup(wdir)
        os._exit(0)


def _redirect_std_fds(log_path: str) -> None:
    with open(os.devnull, "rb") as devnull:
        os.dup2(devnull.fileno(), sys.stdin.fileno())
    log = open(log_path, "ab", buffering=0)
    os.dup2(log.fileno(), sys.stdout.fileno())
    os.dup2(log.fileno(), sys.stderr.fileno())


def _write_pid(wdir: str) -> None:
    with contextlib.suppress(OSError):
        with open(os.path.join(wdir, "pid"), "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))


def _cleanup(wdir: str) -> None:
    with contextlib.suppress(OSError):
        os.unlink(os.path.join(wdir, "pid"))


def stop_daemon(root_path: Optional[str] = None, timeout: float = LIVENESS_TIMEOUT) -> bool:
    """Ask the workspace daemon to stop. Returns True if one was contacted."""
    root = root_path or determine_root_path()
    sock = socket_path(root)
    if not is_alive(sock, timeout):
        return False
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout)
    try:
        client.connect(sock)
        stream = client.makefile("rwb")
        write_message(stream, {"jsonrpc": "2.0", "id": 0, "method": "daemon.stop", "params": {}})
        read_message(stream)
        return True
    except OSError:
        return False
    finally:
        with contextlib.suppress(OSError):
            client.close()
