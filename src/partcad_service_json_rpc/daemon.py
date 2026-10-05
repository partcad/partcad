#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Starting the per-workspace daemon, and serving from it.

This is the daemon's own half. Callers run :func:`ensure_daemon`, which prints
the endpoint to stdout and, if no live daemon is found, starts one (double-forked
and detached on POSIX) that serves a warm shared session.

Where that endpoint is, and whether something is answering on it, is the
rendezvous both ends have to agree on, so it is defined once in
``partcad_utils.workspace`` and imported here. Everything a *client* does with a
daemon -- finding it, connecting, stopping it and waiting for it to go -- lives
in ``partcad_client``; a daemon has no business doing any of that, least of
all to daemons other than itself.
"""

import contextlib
import os
import signal
import socket
import sys
import time
from typing import Callable, Optional

from partcad_utils.workspace import (
    LIVENESS_TIMEOUT,
    determine_root_path,
    is_listening,
    pid_path,
    socket_path,
)

from . import config_restart
from .rpc.methods import build_registry
from .transport.socket_server import SocketServer


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
    daemon_argv=(),
    replace_different: bool = False,
) -> str:
    """Ensure a daemon serves the workspace and return (and print) its endpoint.

    On POSIX, starts a detached daemon on a Unix socket when none is alive; on
    Windows, a named-pipe daemon. ``build_session`` is a callable taking the
    workspace directory and returning the warm :class:`Session` the daemon
    serves (the directory is where its rotating log file lives).

    ``daemon_argv`` is the service's own settings flags. A Windows daemon is a
    new process and is handed them; a POSIX one is a fork of this one and
    already has them. Either way they are what the daemon answers
    ``daemon.settings`` with.

    ``replace_different`` is "a daemon started *this* way": a live daemon
    started with other settings is asked to restart, and one is started with
    these. Without it any live daemon will do -- which is right for a client
    that sends its configuration with every request anyway (``pc``'s own
    commands), and wrong for the one that does not (the editor extension, which
    configures the daemon only through these flags, by way of ``pc daemon
    start``).
    """
    root = root_path or determine_root_path()

    # Windows first: everything below is POSIX-only (fcntl in _flock,
    # socket.AF_UNIX), so it must not run here -- it used to raise
    # ModuleNotFoundError before this branch could ever be reached, and the
    # printed endpoint has to be the pipe the client will connect to.
    if os.name == "nt":
        # Where the pipe is and whether anything answers on it comes from
        # `partcad_utils.win_pipe`, for the same reason the POSIX branch below
        # takes `socket_path`/`is_listening` from `partcad_utils.workspace`: it is
        # the rendezvous, and both ends have to read it from one place. Only
        # spawning the server is this package's own half.
        #
        # `is_pipe_alive` used to be imported from `.win_pipe`, which does not
        # define one -- so on Windows this raised ImportError on the first line
        # of the branch, before anything was spawned, and the launcher exited 1.
        # CI runs Windows, but `test_daemon.py` skips itself where there is no
        # `socket.AF_UNIX`, so the daemon's tests are skipped on the platform
        # this branch is for. `test_daemon_windows.py` has no such guard.
        from partcad_utils.win_pipe import is_pipe_alive, pipe_name

        from .win_pipe import spawn_pipe_daemon

        pipe = pipe_name(root)
        if replace_different and is_pipe_alive(pipe, liveness_timeout):
            if _settings_differ(lambda params: _pipe_ask(pipe, params, liveness_timeout), daemon_argv):
                # It stops offering the pipe on its own loop, a moment after
                # answering; starting the replacement before then would hand
                # out a name the old daemon still answers on -- with the old
                # settings, which is the one thing this launch was for.
                if not _wait_until(lambda: not is_pipe_alive(pipe, liveness_timeout), START_TIMEOUT):
                    raise RuntimeError(
                        "the PartCAD daemon serving %s was asked to restart with other settings and was still "
                        "answering after %ss; run 'pc daemon stop' and try again" % (pipe, START_TIMEOUT)
                    )
        if not is_pipe_alive(pipe, liveness_timeout):
            spawn_pipe_daemon(root, daemon_argv)
            # Wait for it to answer before saying where it is. The POSIX branch
            # below binds and listens in *this* process, so the socket is there
            # the moment it is printed and a client that arrives early simply
            # queues; the Windows daemon is a separate process that creates its
            # pipe once it is ready, and connecting to a pipe that does not
            # exist yet fails outright rather than waiting. Printing first
            # therefore handed every client a name it could not connect to.
            if not _wait_for_pipe(pipe, liveness_timeout):
                raise RuntimeError("the PartCAD daemon did not start serving %s in %ss" % (pipe, START_TIMEOUT))
        print(pipe, flush=True)
        return pipe

    sock = socket_path(root)
    wdir = os.path.dirname(sock)
    os.makedirs(wdir, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(wdir, 0o700)

    with _flock(os.path.join(wdir, "lock")):
        # Listening is enough, answering is not required: a daemon serves one
        # request at a time, so a busy one - or one still building its session
        # behind a socket it has already bound - does not answer a probe in
        # time, and replacing it would leave two daemons serving one workspace.
        # A daemon that is gone refuses the connection, and is replaced.
        #
        # And it is kept unless asked for with other settings *and* able to say
        # so: the settings question is asked only when it matters, inside the
        # lock (a second launcher arriving meanwhile must find either this one's
        # daemon or none), and a daemon too busy to answer it is kept, not
        # restarted, for the reason above.
        if is_listening(sock, liveness_timeout) and not (
            replace_different
            and _settings_differ(lambda params: _socket_ask(sock, params, liveness_timeout), daemon_argv)
        ):
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

    _serve_detached(server_sock, sock, wdir, build_session, daemon_argv)
    return sock


# How long to wait for a freshly spawned Windows daemon to answer. Generous:
# it has to start a process, import PartCAD and build the warm session before
# it can serve, and the alternative to waiting is telling the client to connect
# to a pipe that is not there.
START_TIMEOUT = 120.0


def _settings_differ(ask: Callable, settings) -> bool:
    """Ask a live daemon whether it runs with ``settings``; True if it is making way.

    A daemon that cannot answer -- one older than ``daemon.settings``, or one
    that went quiet -- is kept. There is no graceful way to move it aside, and
    stopping it outright would take the requests of every other client with it.
    """
    reply = ask({"settings": list(settings)})
    result = reply.get("result") if isinstance(reply, dict) else None
    restarting = isinstance(result, dict) and bool(result.get("restarting"))
    if restarting:
        print(
            "PartCAD daemon: the one running was started as %s; restarting it as %s"
            % (result.get("settings"), list(settings)),
            file=sys.stderr,
            flush=True,
        )
    return restarting


def _socket_ask(sock: str, params, timeout: float):
    from partcad_utils.framing import read_message, write_message

    from .config_restart import SETTINGS_METHOD

    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout)
    try:
        client.connect(sock)
        stream = client.makefile("rwb")
        try:
            write_message(stream, {"jsonrpc": "2.0", "id": 0, "method": SETTINGS_METHOD, "params": params})
            return read_message(stream)
        finally:
            stream.close()
    except OSError:
        return None
    finally:
        with contextlib.suppress(OSError):
            client.close()


def _pipe_ask(pipe: str, params, timeout: float):  # pragma: no cover - Windows only
    from partcad_utils.win_pipe import pipe_request

    from .config_restart import SETTINGS_METHOD

    return pipe_request(pipe, SETTINGS_METHOD, timeout, params)


def _wait_until(predicate: Callable[[], bool], timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)
    return True


def _wait_for_pipe(pipe: str, liveness_timeout: float) -> bool:
    """True once the named-pipe daemon answers, False if it never does."""
    from partcad_utils.win_pipe import is_pipe_alive

    deadline = time.monotonic() + START_TIMEOUT
    while time.monotonic() < deadline:
        if is_pipe_alive(pipe, liveness_timeout):
            return True
        time.sleep(0.1)
    return False


def _serve_detached(
    server_sock: socket.socket, sock: str, wdir: str, build_session: Callable, launch_settings=()
) -> None:
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
    server = SocketServer(
        session, build_registry(), on_shutdown=lambda: _cleanup(wdir), launch_settings=launch_settings
    )

    def _terminate(_signum, _frame):
        server.stop()

    signal.signal(signal.SIGTERM, _terminate)
    signal.signal(signal.SIGINT, _terminate)

    # The configuration was read once, above, and this process may now serve
    # for days. An edit to it restarts the daemon (see `config_restart`).
    watcher = config_restart.watch(server.restart)

    try:
        server.serve_accepted(server_sock, sock)
    finally:
        if watcher is not None:
            watcher.stop()
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
        with open(pid_path(wdir), "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))


def _cleanup(wdir: str) -> None:
    """Remove the pid file, if it is still this daemon's.

    After a restart it need not be: the daemon that replaced this one wrote its
    own pid there while this one was still finishing its last requests, and
    removing that would leave `pc daemon stop` unable to wait for the daemon
    that is actually serving.
    """
    path = pid_path(wdir)
    with contextlib.suppress(OSError, ValueError):
        with open(path, encoding="utf-8") as f:
            if int(f.read().strip()) != os.getpid():
                return
        os.unlink(path)
