#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Connecting to the PartCAD service.

Used by the CLI (a thin client), by the VS Code extension through
`pc daemon start`/`pc daemon stop`, and available to any other Python caller.

On POSIX, :func:`connect` uses the shared per-workspace **daemon** (a warm
context): ``start_daemon`` runs the ``partcad-json-rpc`` launcher and returns the
endpoint it printed. On Windows it falls back to launching a one-shot
``partcad-json-rpc --stdio`` service and talking to it over its pipes -- not
because there is no daemon there (the service serves a named pipe, and
``start_daemon`` starts it for `pc daemon start` and the editor extension) but
because the CLI has not been moved onto it yet. Either way the caller stays a
thin client that does not import ``partcad``; :class:`DaemonClient` speaks framed
JSON-RPC and delivers server notifications to an optional callback while waiting
for the matching response.
"""

import logging
import math
import os
import socket
import subprocess
import sys
import threading
import time
from typing import Callable, Optional

from partcad_utils.framing import read_message, write_message
from partcad_utils.workspace import pid_path

_logger = logging.getLogger(__name__)

# How long the service may say *nothing at all* before the client stops waiting
# for it.
#
# A bound on silence, not on the operation. A recursive render or test runs for
# many minutes and is meant to; what it also does is stream a log event for
# every action it takes, so a healthy command is never quiet for long. A daemon
# that has stopped -- deadlocked, or waiting on something that is not coming --
# is quiet forever, and until this bound existed so was the client: in CI that
# cost the job's own 40-minute watchdog and a run reported as cancelled with the
# log ending mid-sentence, and at a terminal it cost the session.
#
# Five minutes, because the quiet stretch to beat is one big shape being built
# in a sandbox, which says nothing between starting and finishing.
DEFAULT_IDLE_TIMEOUT = 300.0

# How often the stdio watchdog looks at the clock. Only the coarseness of the
# bound, not its length -- see '_watch_for_stall'.
_STALL_POLL_SECONDS = 1.0


class DaemonError(RuntimeError):
    """A JSON-RPC error returned by the service."""

    def __init__(self, error: dict):
        super().__init__(error.get("message", "service error"))
        self.code = error.get("code")
        self.data = error.get("data")


class DaemonStalled(RuntimeError):
    """The service stopped saying anything before it answered.

    Distinct from :class:`DaemonError`, which is the service answering with an
    error, and from a closed connection, which is it going away. This is it
    still being there and no longer talking.
    """


def idle_timeout() -> float:
    """The silence bound in seconds, or ``0`` to wait as long as it takes.

    Normalized here so that every caller has one thing to test. "No bound" is
    ``0``, and never anything ``socket.settimeout()`` would reject: it raises
    ``ValueError`` on a negative number and ``OverflowError`` on an infinite one
    (which is what ``float()`` makes of both ``inf`` and an overflowing literal
    like ``1e309``). Either would be raised inside :func:`_connect_socket`, where
    :func:`connect` catches everything and quietly falls back to a one-shot
    stdio service -- so a setting written to make the client wait *longer* would
    instead have stopped it using the daemon at all, with no sign of why.

    ``nan`` needs no special case: it fails ``> 0`` like every comparison.
    """
    raw = os.environ.get("PC_DAEMON_IDLE_TIMEOUT")
    if raw is None or not raw.strip():
        return DEFAULT_IDLE_TIMEOUT
    try:
        seconds = float(raw)
    except ValueError:
        _logger.warning("PC_DAEMON_IDLE_TIMEOUT is not a number of seconds (%r); using %gs.", raw, DEFAULT_IDLE_TIMEOUT)
        return DEFAULT_IDLE_TIMEOUT
    return seconds if seconds > 0 and math.isfinite(seconds) else 0.0


def launcher_argv() -> list:
    """Command that runs the ``partcad-json-rpc`` executable for this install."""
    if getattr(sys, "frozen", False):
        # The bundle's own service executable, beside whichever of its
        # executables is running -- resolved, because `pc` is normally reached
        # through the launcher symlink `install.sh` puts on PATH.
        exe = "partcad-json-rpc" + (".exe" if os.name == "nt" else "")
        return [os.path.join(os.path.dirname(os.path.realpath(sys.executable)), exe)]
    return [sys.executable, "-m", "partcad_service_json_rpc"]


def start_daemon(cwd: Optional[str] = None, extra_args=()) -> str:
    r"""Ensure a daemon serves the workspace at ``cwd``; return its endpoint.

    An AF_UNIX socket path on POSIX, a ``\\.\pipe\...`` name on Windows: the
    service implements both (``partcad_service_json_rpc.daemon``) and prints
    whichever it served. The endpoint it prints is live -- the launcher waits
    for the daemon to answer before naming it -- so a caller can connect to it
    straight away.

    :func:`connect` below still runs a one-shot stdio service on Windows; this
    is what `pc daemon start` and the editor extension use.
    """
    argv = launcher_argv() + ["--socket", *extra_args]
    # check=False: the returncode is handled below, so that the error can
    # carry what the launcher printed rather than only its exit status.
    result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            "%s exited with status %d:\n%s" % (" ".join(argv), result.returncode, _launcher_output(result))
        )
    path = next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")
    if not path:
        raise RuntimeError("partcad-json-rpc did not print a socket path:\n%s" % _launcher_output(result))
    return path


def _launcher_output(result: subprocess.CompletedProcess) -> str:
    """Everything the launcher said, for an error that would otherwise say nothing.

    This used to be ``check=True``, whose ``CalledProcessError`` names the argv
    and the exit status and then discards both captured streams -- so a launcher
    that died on a traceback reached the user as "returned non-zero exit status
    1" with the traceback caught and thrown away. The editor extension shows
    this error verbatim in its output channel, and that is where the reason has
    to be.
    """
    said = [stream.strip() for stream in (result.stderr, result.stdout) if stream and stream.strip()]
    return "\n".join(said) if said else "(no output)"


class DaemonClient:
    """A framed JSON-RPC client over a single service connection.

    ``timeout`` is how long the service may say nothing before the client gives
    up on it; see :data:`DEFAULT_IDLE_TIMEOUT`. ``endpoint`` is how it is
    reached, and is only used to say so when it stops answering -- a socket path
    there is also where its logs and its pid file are.

    How the wait is bounded depends on what the connection is made of, so the
    connector says. A socket can simply be given a timeout, and a read that
    reaches it raises. A pipe cannot -- ``select`` does not take one on Windows,
    which is the platform the stdio channel exists for -- so the connector
    passes ``interrupt``, a way to unblock a read that is never going to return,
    and a watchdog calls it. Neither is offered for the Windows named pipe,
    which nothing reaches this class through today.
    """

    def __init__(
        self,
        read_stream,
        write_stream,
        closer: Optional[Callable[[], None]] = None,
        timeout: Optional[float] = None,
        endpoint: Optional[str] = None,
        interrupt: Optional[Callable[[], None]] = None,
    ):
        self._read = read_stream
        self._write = write_stream
        self._closer = closer
        self._next_id = 0
        # Clamped, so that only '> 0' has to be tested everywhere below. Zero
        # and anything below it mean the same thing: no bound.
        self._timeout = max(timeout or 0.0, 0.0)
        self._endpoint = endpoint
        self._interrupt = interrupt
        # Written by the request thread on every message and read by the
        # watchdog. A float assignment is atomic under the GIL and the watchdog
        # only ever compares it against the clock, so this needs no lock.
        self._last_heard = 0.0
        self._stall: Optional[str] = None

    def call(self, method: str, params=None, on_event: Optional[Callable[[str, object], None]] = None):
        """Send a request; forward notifications to ``on_event`` until the response.

        Raises :class:`DaemonStalled` if the service says nothing for longer
        than this client's timeout, :class:`DaemonError` if it answers with an
        error, and ``RuntimeError`` if it closes the connection.
        """
        self._next_id += 1
        request_id = self._next_id
        # Only default when params is absent: an explicit [] or {} is a valid
        # (empty positional / empty named) parameter list and must be preserved.
        request = {"jsonrpc": "2.0", "id": request_id, "method": method}
        request["params"] = {} if params is None else params
        self._stall = None
        self._last_heard = time.monotonic()

        stop = threading.Event()
        watchdog = None
        if self._timeout > 0 and self._interrupt is not None:
            watchdog = threading.Thread(
                target=self._watch_for_stall, args=(method, stop), name="partcad-service-watchdog", daemon=True
            )
            watchdog.start()
        try:
            try:
                write_message(self._write, request)
            except TimeoutError as e:
                # The service is not reading. Rare -- a request is small enough
                # to fit in the socket buffer whatever the service is doing --
                # but it is the same stall seen from the other end.
                raise self._stalled(method, "sending") from e

            while True:
                try:
                    message = read_message(self._read)
                except TimeoutError as e:
                    raise self._stalled(method, "waiting for an answer") from e
                self._last_heard = time.monotonic()
                if message is None:
                    # The watchdog closes the connection to break the read, so
                    # an end of stream it caused is a stall rather than the
                    # service having gone away of its own accord.
                    if self._stall is not None:
                        raise DaemonStalled(self._stall)
                    raise RuntimeError("the PartCAD service closed the connection")
                if message.get("id") == request_id and ("result" in message or "error" in message):
                    if "error" in message:
                        raise DaemonError(message["error"])
                    return message.get("result")
                if "method" in message and "id" not in message and on_event is not None:
                    on_event(message["method"], message.get("params"))
        finally:
            stop.set()
            if watchdog is not None:
                watchdog.join(timeout=_STALL_POLL_SECONDS * 2)

    def _watch_for_stall(self, method: str, stop: threading.Event) -> None:
        """Unblock a read that the service is never going to satisfy.

        Polls rather than arming a timer for the deadline, because the deadline
        moves: every notification the service sends is a sign of life and pushes
        it out again. The poll interval is how late the report can be, not how
        long the wait is.
        """
        while not stop.wait(_STALL_POLL_SECONDS):
            silent_for = time.monotonic() - self._last_heard
            if silent_for < self._timeout:
                continue
            self._stall = self._stall_report(method, silent_for, "waiting for an answer")
            try:
                self._interrupt()
            except Exception:  # pylint: disable=broad-except
                # Nothing left to try: the read stays blocked and the caller
                # waits, but the report above has already been made.
                pass
            return

    def _stalled(self, method: str, doing: str) -> "DaemonStalled":
        """Report the stall loudly and return the error to raise for it."""
        return DaemonStalled(self._stall_report(method, self._timeout, doing))

    def _stall_report(self, method: str, silent_for: float, doing: str) -> str:
        """Say what stopped, for how long, and where to look -- to the log and
        to the caller.

        Written to the log as well as carried by the exception because the two
        are read in different places: the exception ends the command, while the
        log line lands in the output stream at the moment it happened, which in
        a CI job is directly under the last thing the service managed to say.
        """
        summary = "The PartCAD service stopped responding: nothing for %gs while %s for '%s'." % (
            silent_for,
            doing,
            method,
        )
        _logger.error("%s\n%s", summary, self._where_to_look())
        return summary

    def _where_to_look(self) -> str:
        """Where the stalled service is, and what it left behind.

        Its endpoint, its process, and the directory it logs into -- named
        rather than read, so that this stays a few stat() calls and says
        something useful even when the service is too wedged to have written
        anything recently.
        """
        lines = []
        if self._endpoint:
            lines.append("  endpoint:  %s" % self._endpoint)
        # The logs and the pid file sit beside the socket; a named pipe has no
        # directory to look in, so there is nothing to point at there.
        if self._endpoint and not self._endpoint.startswith("\\\\.\\pipe\\"):
            wdir = os.path.dirname(self._endpoint)
            if wdir:
                lines.append("  logs:      %s" % wdir)
                try:
                    with open(pid_path(wdir), encoding="utf-8") as f:
                        pid = f.read().strip()
                except OSError:
                    pid = ""
                if pid:
                    lines.append("  process:   %s (its stacks say where it stopped)" % pid)
        lines.append("  'pc daemon stop' clears it; PC_DAEMON_IDLE_TIMEOUT=<seconds> waits longer, 0 forever.")
        return "\n".join(lines)

    def close(self) -> None:
        if self._closer is not None:
            try:
                self._closer()
            except Exception:  # pylint: disable=broad-except
                pass


def _connect_socket(cwd: Optional[str], extra_args) -> DaemonClient:
    path = start_daemon(cwd, extra_args)
    if path.startswith("\\\\.\\pipe\\"):  # Windows named pipe
        stream = open(path, "r+b", buffering=0)  # pragma: no cover - Windows only
        return DaemonClient(stream, stream, closer=stream.close, endpoint=path)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(path)
    timeout = idle_timeout()
    # 'None', not the 0 that means "no bound" here: 'settimeout(0)' does not
    # make a socket wait forever, it makes it *non-blocking*, and the first read
    # then fails immediately with BlockingIOError -- an OSError, but not the
    # TimeoutError 'call' reports a stall from. Turning the bound off would have
    # broken every call instead of restoring the wait it used to make.
    #
    # Set before makefile(): a socket may carry a timeout under a file object
    # and only a non-blocking one may not, which is the other reason the line
    # above matters. A read that reaches the timeout raises TimeoutError, which
    # is what 'call' turns into the report; it also leaves the buffer in an
    # undefined state, which costs nothing here because a client that has given
    # up on this connection closes it.
    sock.settimeout(timeout if timeout > 0 else None)
    stream = sock.makefile("rwb")

    def closer():
        try:
            stream.close()
        finally:
            sock.close()

    return DaemonClient(stream, stream, closer=closer, timeout=timeout, endpoint=path)


def _connect_stdio(cwd: Optional[str], extra_args) -> DaemonClient:
    proc = subprocess.Popen(
        launcher_argv() + ["--stdio", *extra_args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        cwd=cwd,
    )

    def closer():
        try:
            proc.stdin.close()
        except Exception:  # pylint: disable=broad-except
            pass
        try:
            proc.wait(timeout=5)
        except Exception:  # pylint: disable=broad-except
            try:
                proc.kill()
            except Exception:  # pylint: disable=broad-except
                pass

    def interrupt():
        # Killing it is what ends the read: a pipe takes no timeout, and this
        # service is a child of this process and serves nobody else, so there is
        # nothing here to take away from anyone. The socket daemon is the
        # opposite on both counts, which is why it is bounded with a timeout
        # instead of being stopped from under whoever else is using it.
        proc.kill()

    return DaemonClient(
        proc.stdout,
        proc.stdin,
        closer=closer,
        timeout=idle_timeout(),
        # Not a path: this service listens nowhere and logs to this process's
        # stderr, so its pid is the whole of what there is to point at.
        endpoint="stdio, pid %d" % proc.pid,
        interrupt=interrupt,
    )


def connect(cwd: Optional[str] = None, extra_args=()) -> DaemonClient:
    """Connect to the PartCAD service for this workspace.

    POSIX: the shared per-workspace socket daemon (warm context), falling back to
    a one-shot stdio service if it cannot be started. Windows: a one-shot stdio
    service. The named-pipe daemon there works -- `pc daemon start` starts one
    and the editor extension connects to it -- but this has not been moved onto
    it, and the cost of trying and failing is paid by every `pc` invocation.
    """
    if os.name != "nt":
        try:
            return _connect_socket(cwd, extra_args)
        except Exception:  # pylint: disable=broad-except
            pass  # fall back to a one-shot stdio service
    return _connect_stdio(cwd, extra_args)
