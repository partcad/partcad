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
import glob
import hashlib
import os
import signal
import socket
import sys
import time
from typing import Callable, List, Optional

from .rpc.methods import build_registry
from .transport.framing import read_message, write_message
from .transport.socket_server import SocketServer

LIVENESS_TIMEOUT = 1.0

# How long to wait for a daemon that acknowledged `daemon.stop` to actually be
# gone. Generous on purpose: the caller that waits is an update about to replace
# the files the daemon runs from, and being slow there beats being wrong.
STOP_TIMEOUT = 30.0


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
    return os.path.join(os.path.expanduser("~"), ".partcad", "workspaces")


def workspace_dir(root_path: str) -> str:
    return os.path.join(workspaces_dir(), workspace_hash(root_path))


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
    """Ensure a daemon serves the workspace and return (and print) its endpoint.

    On POSIX, starts a detached daemon on a Unix socket when none is alive; on
    Windows, a named-pipe daemon. ``build_session`` is a callable taking the
    workspace directory and returning the warm :class:`Session` the daemon
    serves (the directory is where its rotating log file lives).
    """
    root = root_path or determine_root_path()

    # Windows first: everything below is POSIX-only (fcntl in _flock,
    # socket.AF_UNIX), so it must not run here -- it used to raise
    # ModuleNotFoundError before this branch could ever be reached, and the
    # printed endpoint has to be the pipe the client will connect to.
    if os.name == "nt":  # pragma: no cover - exercised only on Windows
        from .win_pipe import is_pipe_alive, pipe_name, spawn_pipe_daemon

        pipe = pipe_name(root)
        if not is_pipe_alive(pipe, liveness_timeout):
            spawn_pipe_daemon(root)
        print(pipe, flush=True)
        return pipe

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

    session = build_session(wdir)
    server = SocketServer(session, build_registry(), on_shutdown=lambda: _cleanup(wdir))

    def _terminate(_signum, _frame):
        server.stop()

    signal.signal(signal.SIGTERM, _terminate)
    signal.signal(signal.SIGINT, _terminate)

    try:
        server.serve_accepted(server_sock, sock)
    finally:
        _cleanup(wdir)
        # Exit through the interpreter rather than os._exit(): the daemon has
        # done its own cleanup above, and everything else that wants to run at
        # shutdown -- buffered writers, atexit handlers registered by whatever
        # this process loaded -- should get the chance to. The intermediate
        # child above still leaves with os._exit(), because that one must not
        # flush buffers it shares with its parent.
        sys.exit(0)


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


def stop_daemon(
    root_path: Optional[str] = None,
    timeout: float = LIVENESS_TIMEOUT,
    wait: float = 0.0,
) -> bool:
    """Ask the workspace daemon to stop. True only if it acknowledged the stop.

    An acknowledgement means the daemon has *decided* to stop, not that it has
    finished doing so. Pass ``wait`` (seconds) to also block until the process is
    actually gone -- required before anything replaces the files it runs from.
    """
    root = root_path or determine_root_path()

    # As in ensure_daemon: the AF_UNIX path below does not exist on Windows.
    if os.name == "nt":  # pragma: no cover - exercised only on Windows
        from .win_pipe import pipe_name, stop_pipe_daemon

        pipe = pipe_name(root)
        stopped = stop_pipe_daemon(pipe, timeout)
        if stopped and wait:
            from .win_pipe import is_pipe_alive

            _wait_until(lambda: not is_pipe_alive(pipe, timeout), wait)
        return stopped

    sock = socket_path(root)
    stopped = _stop_socket_daemon(sock, timeout)
    if stopped and wait:
        wait_until_stopped(os.path.dirname(sock), timeout=wait, liveness_timeout=timeout)
    return stopped


def _stop_socket_daemon(sock: str, timeout: float = LIVENESS_TIMEOUT) -> bool:
    """Send ``daemon.stop`` to the daemon listening on ``sock``; True if acked."""
    if not is_alive(sock, timeout):
        return False
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout)
    try:
        client.connect(sock)
        stream = client.makefile("rwb")
        write_message(stream, {"jsonrpc": "2.0", "id": 0, "method": "daemon.stop", "params": {}})
        # Report success only on an acknowledged stop, so the CLI does not
        # claim "stopped" for a daemon that never answered.
        reply = read_message(stream)
        return isinstance(reply, dict) and "result" in reply
    except OSError:
        return False
    finally:
        with contextlib.suppress(OSError):
            client.close()


def _wait_until(predicate: Callable[[], bool], timeout: float, interval: float = 0.1) -> bool:
    """Poll ``predicate`` until it is true or ``timeout`` seconds have passed."""
    deadline = time.monotonic() + timeout
    while True:
        if predicate():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


def _daemon_pid(wdir: str) -> Optional[int]:
    try:
        with open(os.path.join(wdir, "pid"), encoding="utf-8") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def _pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Somebody else's process holds the pid; not our daemon, but not proof
        # it is gone either. Treat it as running rather than declare success.
        return True
    except OSError:
        return False
    return True


def wait_until_stopped(
    wdir: str,
    timeout: float = STOP_TIMEOUT,
    liveness_timeout: float = LIVENESS_TIMEOUT,
) -> bool:
    """Block until the daemon serving ``wdir`` is really gone. True if it is.

    A daemon that acknowledged ``daemon.stop`` still has to unwind: finish the
    in-flight call, tear the warm context down, and exit. Both signals are
    checked, because either one alone can lie -- the socket stops answering
    before the process exits, and the pid file is removed by a cleanup handler
    that a crashed daemon never reaches.
    """
    sock = os.path.join(wdir, "socket")
    pid = _daemon_pid(wdir)

    def gone() -> bool:
        if is_alive(sock, liveness_timeout):
            return False
        return pid is None or not _pid_is_running(pid)

    return _wait_until(gone, timeout)


def live_daemon_dirs(liveness_timeout: float = LIVENESS_TIMEOUT) -> List[str]:
    """Workspace directories whose daemon is answering right now.

    Enumerated from the filesystem rather than from workspace roots: the
    directory name is a hash of the root, so the roots cannot be recovered from
    it -- and a caller that is about to replace the installation needs *every*
    daemon on this machine, not the one for its own workspace.
    """
    if os.name == "nt":  # pragma: no cover - exercised only on Windows
        return []
    dirs = []
    for sock in sorted(glob.glob(os.path.join(workspaces_dir(), "*", "socket"))):
        if is_alive(sock, liveness_timeout):
            dirs.append(os.path.dirname(sock))
    return dirs


def stop_all_daemons(
    timeout: float = STOP_TIMEOUT,
    liveness_timeout: float = LIVENESS_TIMEOUT,
) -> List[str]:
    """Stop every daemon running on this machine and wait for them to be gone.

    Returns the workspace directories of the daemons that stopped. A daemon that
    does not go away within ``timeout`` is left out of the result, so the caller
    can decide whether to proceed -- it is the one that knows what it is about to
    do to the files that daemon is running from.
    """
    stopped = []
    if os.name == "nt":  # pragma: no cover - exercised only on Windows
        from .win_pipe import is_pipe_alive, stop_pipe_daemon

        for pipe in _live_pipe_names(liveness_timeout):
            # `name=pipe` binds this iteration's pipe into the predicate rather
            # than leaving it to read whatever the loop variable holds later.
            gone = lambda name=pipe: not is_pipe_alive(name, liveness_timeout)  # noqa: E731
            if stop_pipe_daemon(pipe, liveness_timeout) and _wait_until(gone, timeout):
                stopped.append(pipe)
        return stopped

    for wdir in live_daemon_dirs(liveness_timeout):
        if _stop_socket_daemon(os.path.join(wdir, "socket"), liveness_timeout) and wait_until_stopped(
            wdir, timeout, liveness_timeout
        ):
            stopped.append(wdir)
    return stopped


def _live_pipe_names(liveness_timeout: float = LIVENESS_TIMEOUT) -> List[str]:  # pragma: no cover - Windows only
    """PartCAD named pipes that answer. Windows exposes them as a directory."""
    from .win_pipe import is_pipe_alive

    try:
        names = os.listdir(r"\\.\pipe")
    except OSError:
        return []
    pipes = [r"\\.\pipe\%s" % name for name in sorted(names) if name.startswith("partcad-")]
    return [pipe for pipe in pipes if is_pipe_alive(pipe, liveness_timeout)]
