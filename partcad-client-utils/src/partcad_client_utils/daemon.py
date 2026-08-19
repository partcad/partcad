#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Finding a PartCAD daemon, checking it is alive, and stopping it.

Everything a *client* does with a daemon, in one place, so that the CLI and the
VS Code extension do it identically -- the extension by running `pc daemon
start`/`pc daemon stop` rather than by reimplementing any of it in TypeScript.

The address itself (which socket serves which workspace) and the liveness probe
come from ``partcad_utils.workspace``: they are the rendezvous both ends agree
on, so the daemon reads them from the same place. What is added here are the
things only a client does -- stopping a daemon, waiting for it to actually be
gone, and enumerating the ones running on this machine.

Enumeration and stopping *all* of them exists for one caller: `pc update`, which
is about to replace the files every one of them is executing. It belongs to a
client for the same reason the update does -- a daemon can be remote, and a
daemon that went looking for its neighbours would be racing every client on the
machine. A client is a single process acting on the machine it runs on.
"""

import contextlib
import glob
import os
import socket
import time
from typing import Callable, List, Optional

from partcad_utils.framing import read_message, write_message
from partcad_utils.workspace import (
    LIVENESS_TIMEOUT,
    determine_root_path,
    is_alive,
    pid_path,
    socket_path,
    workspace_dir,
    workspace_hash,
    workspaces_dir,
)

# Re-exported so a client has one import for "everything about daemons".
__all__ = [
    "LIVENESS_TIMEOUT",
    "STOP_TIMEOUT",
    "determine_root_path",
    "is_alive",
    "live_daemon_dirs",
    "socket_path",
    "stop_all_daemons",
    "stop_daemon",
    "wait_until_stopped",
    "workspace_dir",
    "workspace_hash",
    "workspaces_dir",
]

# How long to wait for a daemon that acknowledged `daemon.stop` to actually be
# gone. Generous on purpose: the caller that waits is an update about to replace
# the files the daemon runs from, and being slow there beats being wrong.
STOP_TIMEOUT = 30.0


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

    # The AF_UNIX path below does not exist on Windows.
    if os.name == "nt":  # pragma: no cover - exercised only on Windows
        from partcad_utils.win_pipe import is_pipe_alive, pipe_name

        pipe = pipe_name(root)
        stopped = stop_pipe_daemon(pipe, timeout)
        if stopped and wait:
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
        with open(pid_path(wdir), encoding="utf-8") as f:
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
    it -- and the caller that needs this is about to replace the installation,
    which concerns every daemon on the machine and not just its own.
    """
    if os.name == "nt":  # pragma: no cover - exercised only on Windows
        return _live_pipe_names(liveness_timeout)
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

    Returns the endpoints that stopped. One that does not go away within
    ``timeout`` is left out of the result, so the caller can decide what to do:
    it is the one that knows what it is about to do to the files that daemon is
    running from.

    Snapshot-then-act, deliberately. A daemon started after the snapshot is a
    daemon started by a client that has not been told about the update yet, and
    chasing it would mean never terminating; it runs the previous version until
    it is next restarted, which is exactly what the side-by-side install makes
    safe.
    """
    stopped = []
    if os.name == "nt":  # pragma: no cover - exercised only on Windows
        from partcad_utils.win_pipe import is_pipe_alive

        for pipe in live_daemon_dirs(liveness_timeout):
            # `name=pipe` binds this iteration's pipe into the predicate rather
            # than leaving it to read whatever the loop variable holds later.
            def gone(name=pipe):
                return not is_pipe_alive(name, liveness_timeout)

            if stop_pipe_daemon(pipe, liveness_timeout) and _wait_until(gone, timeout):
                stopped.append(pipe)
        return stopped

    for wdir in live_daemon_dirs(liveness_timeout):
        if _stop_socket_daemon(os.path.join(wdir, "socket"), liveness_timeout) and wait_until_stopped(
            wdir, timeout, liveness_timeout
        ):
            stopped.append(wdir)
    return stopped


def stop_pipe_daemon(name: str, timeout: float = LIVENESS_TIMEOUT) -> bool:  # pragma: no cover - Windows only
    """Ask the named-pipe daemon to stop. True if it acknowledged.

    The Windows counterpart of :func:`_stop_socket_daemon`; the pipe server
    honors ``STOP_METHOD`` in `partcad_service_json_rpc.win_pipe`.
    """
    from partcad_utils.win_pipe import STOP_METHOD, pipe_request

    reply = pipe_request(name, STOP_METHOD, timeout)
    return isinstance(reply, dict) and "result" in reply


def _live_pipe_names(liveness_timeout: float = LIVENESS_TIMEOUT) -> List[str]:  # pragma: no cover - Windows only
    """PartCAD named pipes that answer. Windows exposes them as a directory."""
    from partcad_utils.win_pipe import PIPE_BASENAME_PREFIX, PIPE_PREFIX, is_pipe_alive

    try:
        names = os.listdir(PIPE_PREFIX)
    except OSError:
        return []
    pipes = ["%s\\%s" % (PIPE_PREFIX, name) for name in sorted(names) if name.startswith(PIPE_BASENAME_PREFIX)]
    return [pipe for pipe in pipes if is_pipe_alive(pipe, liveness_timeout)]
