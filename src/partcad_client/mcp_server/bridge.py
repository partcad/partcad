#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The MCP server's connection to the workspace daemon.

`pc` opens a connection per command and closes it when the command ends. A
server lives as long as the agent's session, so this one keeps its connection
and reconnects when it has gone away -- which it does on purpose: the daemon
restarts itself when `~/.partcad/config.yaml` changes and cuts idle connections
off, and on Windows `partcad_client.client.connect` starts a one-shot stdio
service that this server would otherwise be paying to start on every call.

What it does not do is resend a request that may have run. A connection that
dies while the daemon is working on a request leaves no way to know whether the
work happened -- an `add.object` may have written its file, a render may have
filled the cache -- so that is reported as exactly that, and the agent decides.
What is resent is ``context.create``, which is idempotent and is how a dead
connection is discovered in the first place, and the handful of context-free
questions that change nothing (``_RESENDABLE``), which have no
``context.create`` ahead of them to find out for them.
"""

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from partcad_client import client as _client
from partcad_utils.workspace import determine_root_path

# The bare-string notifications a daemon sends besides the structured `log`
# ones (`emitter.info()` and friends), and the level each is reported at.
_LEVELS = {"info": logging.INFO, "warn": logging.WARNING, "error": logging.ERROR}

# The markers that say the daemon has started a piece of work, which is what is
# worth telling a client that asked for progress. Their ends, and the timeout
# windows, are not: an end is followed by the next start or by the answer.
_STARTS = ("process_start", "action_start")

# The context-free requests that only ask, and so may be sent again on a new
# connection when the one they went out on turns out to have died while the
# server sat idle: whatever the first attempt did or did not do, there is no
# effect to check.
_RESENDABLE = frozenset({"rpc.discover", "version", "daemon.status", "daemon.status.config", "daemon.status.env"})


@dataclass
class Outcome:
    """What one daemon request produced: its result, and what it said meanwhile.

    ``log`` is every log line, ``LEVEL: message``; ``errors`` the messages of the
    ones at ERROR or above, which is how PartCAD reports most failures -- an
    object that does not build is an error line and a ``None`` result, not a
    JSON-RPC error. ``events`` is every other notification, which is where the
    older IDE methods put their answers (``list.all`` sends ``items``).
    """

    method: str
    result: object = None
    log: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    events: list = field(default_factory=list)


class CallFailed(Exception):
    """A request that ended without a result, and what it had said by then.

    ``code`` and ``data`` are the daemon's when it answered with an error, and
    ``None`` when it did not answer at all.
    """

    def __init__(self, message: str, outcome: Outcome, code=None, data=None):
        super().__init__(message)
        self.outcome = outcome
        self.code = code
        self.data = data


class Bridge:
    """One daemon connection, shared by every tool call, one call at a time.

    ``workspace`` is what ``pc -p`` takes: a package directory or its
    ``partcad.yaml``. The daemon serving it is the one for the workspace root
    above it, and that root is also what :class:`.sandbox.PathScope` confines
    files to.

    ``connect`` and ``user_config`` are there for the tests, which drive this
    against a daemon of their own; left out, they are the CLI's.
    """

    def __init__(self, workspace: str, connect: Optional[Callable] = None, user_config=None):
        self.workspace = str(Path(workspace).resolve())
        self.root = determine_root_path(self.workspace)
        self._connect = connect or (lambda: _client.connect(cwd=self.root))
        self._user_config = user_config
        self._conn = None
        # The daemon serves one request at a time anyway (its socket server
        # holds a lock across connections), and a DaemonClient matches a
        # response to the one request it has in flight -- so two tool calls the
        # client sent at once queue here rather than interleave on the wire.
        self._lock = threading.Lock()

    @property
    def url(self) -> str:
        return Path(self.workspace).as_uri()

    def call(
        self,
        method: str,
        params: Optional[dict] = None,
        needs_context: bool = True,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> Outcome:
        """Make one daemon request; return what it produced or raise :class:`CallFailed`.

        Blocking, and meant to be run in a worker thread. ``needs_context``
        prefixes the request with ``context.create`` for this workspace and
        passes the context along, as `pc` does for every package command.
        ``on_progress`` is called, on this thread, with a line for each piece of
        work the daemon starts.
        """
        outcome = Outcome(method)

        def on_event(name, payload):
            self._collect(outcome, name, payload, on_progress)

        with self._lock:
            conn = self._connection(outcome)
            request = dict(params or {})
            if needs_context:
                conn, request["context"] = self._context(conn, outcome, on_event)
            # A request with a context has just had `context.create` go before it
            # on this connection, which is what found out whether it was alive. One
            # without has nothing ahead of it, so a dead connection is found by the
            # request itself -- and a question that changes nothing is simply asked
            # again on a new one, where anything else is reported instead.
            resendable = not needs_context and method in _RESENDABLE
            for attempt in (1, 2):
                try:
                    outcome.result = conn.call(method, request, on_event=on_event)
                    return outcome
                except _client.DaemonError as e:
                    raise CallFailed(str(e), outcome, e.code, e.data) from e
                except _client.DaemonStalled as e:
                    self._drop()
                    raise CallFailed(str(e), outcome) from e
                except (RuntimeError, OSError) as e:
                    self._drop()
                    if resendable and attempt == 1:
                        conn = self._connection(outcome)
                        continue
                    if resendable:
                        raise CallFailed("The PartCAD daemon closed the connection: %s" % e, outcome) from e
                    raise CallFailed(
                        "The connection to the PartCAD daemon was lost while it was running '%s' (%s). It may or "
                        "may not have finished: check its effect before sending it again." % (method, e),
                        outcome,
                    ) from e

    def close(self) -> None:
        with self._lock:
            self._drop()

    def _connection(self, outcome: Outcome):
        if self._conn is None:
            try:
                self._conn = self._connect()
            except Exception as e:  # pylint: disable=broad-except
                raise CallFailed("Could not start or reach the PartCAD daemon for %s: %s" % (self.root, e), outcome)
        return self._conn

    def _context(self, conn, outcome: Outcome, on_event):
        """Create (or reuse) the daemon's context for this workspace.

        Asked before every request rather than once, as `pc` does: the daemon
        answers a known workspace from memory, this request carries the user
        configuration as it is *now*, and it is the cheapest way to find out
        that the connection died while the server sat idle -- in which case
        there is a new connection, and the request is made again on it.
        """
        params = {"url": self.url, "userConfig": self._config()}
        for attempt in (1, 2):
            try:
                return conn, conn.call("context.create", params, on_event=on_event)["context"]
            except _client.DaemonError as e:
                raise CallFailed(str(e), outcome, e.code, e.data) from e
            except _client.DaemonStalled as e:
                self._drop()
                raise CallFailed(str(e), outcome) from e
            except (RuntimeError, OSError) as e:
                self._drop()
                if attempt == 2:
                    raise CallFailed("The PartCAD daemon closed the connection: %s" % e, outcome) from e
                conn = self._connection(outcome)

    def _config(self) -> dict:
        if self._user_config is None:
            from partcad_utils.user_config import user_config

            self._user_config = user_config
        return self._user_config.to_dict()

    def _drop(self) -> None:
        if self._conn is not None:
            conn, self._conn = self._conn, None
            conn.close()

    @staticmethod
    def _collect(outcome: Outcome, name: str, payload, on_progress) -> None:
        if name == "log" and isinstance(payload, dict):
            kind = payload.get("kind")
            if kind == "log":
                levelno = payload.get("levelno", logging.INFO)
                message = str(payload.get("message", ""))
                outcome.log.append("%s: %s" % (logging.getLevelName(levelno), message))
                if levelno >= logging.ERROR:
                    outcome.errors.append(message)
            elif kind in _STARTS and on_progress is not None:
                on_progress(" ".join(str(payload[k]) for k in ("op", "package", "item") if payload.get(k)))
        elif name in _LEVELS:
            message = payload if isinstance(payload, str) else str(payload)
            outcome.log.append("%s: %s" % (logging.getLevelName(_LEVELS[name]), message))
            if _LEVELS[name] >= logging.ERROR:
                outcome.errors.append(message)
        else:
            outcome.events.append({"method": name, "params": payload})
