#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Restarting the daemon when the user configuration changes.

The daemon reads ``~/.partcad/config.yaml`` once, when it starts, and then stays
warm for as long as anyone uses it. So an edit to that file -- the sandbox to
build Python environments in, a proxy, a cache directory -- reached nothing that
went through the daemon until somebody thought to run ``pc daemon stop``, and
nothing said so. The editor extension never sends a configuration of its own
(see ``operations._caller_user_config``), which made it the client that stayed
wrong the longest.

"Restart" here is the daemon *leaving*, and nothing more. It stops listening
first, so the next client to look finds nothing answering and starts a fresh
daemon, the way it would have if none had ever run -- and that one reads the
file as it is now. The daemon does not start its own successor: starting and
finding daemons is a client's business (see ``partcad_client``), and the client
starting it is the one whose flags it should be started with.

What it owes the clients already connected is not to pull the floor out from
under them, and that is what :class:`Connections` is for:

* A connection in the middle of a request is left to finish it. An analysis
  that took ten minutes is not thrown away because somebody fixed a typo in
  their configuration.
* A connection that is idle is told, with the ``doRestart`` notification the
  editor extension already answers by reconnecting. It is told only while idle,
  because the extension answers it by dropping this connection, and one it
  dropped mid-request would lose the answer it was waiting for.
* A connection that neither finishes nor goes away is cut off once it has been
  idle for :data:`GRACE_SECONDS` after being told. ``pc`` opens one connection
  per command and closes it, so it never gets there; a client that keeps a
  connection open and ignores ``doRestart`` is the one this is for.

The file is polled rather than watched. One ``stat`` a second costs nothing, it
works the same on every platform the daemon runs on, and it needs no dependency
-- whereas the platforms' own notification APIs are three different things, and
a watch on a file that an editor replaces by renaming another over it is lost
the first time it is saved.
"""

import hashlib
import os
import sys
import threading
import time
from typing import Callable, Optional

from .core import events

# "Are you running with these settings? If not, make way." Asked by a launcher
# that was told to start the daemon a particular way (`pc daemon start`, which
# is how the editor extension starts it) and found one already serving. Without
# it the live daemon was simply reused, and the flags of every launch after the
# first were dropped without a word -- a changed sandbox setting in the editor
# reached nothing until somebody stopped the daemon by hand.
#
# Handled by the transports, like `daemon.stop`, because the answer is about the
# process and what it does next is the restart below. Settings are compared as
# the launcher flags `__main__.settings_argv` writes them, since that is the
# one spelling both ends already produce.
SETTINGS_METHOD = "daemon.settings"


def settings_differ(params, own) -> bool:
    """Whether a ``daemon.settings`` request asks for something this daemon is not."""
    wanted = (params or {}).get("settings") if isinstance(params, dict) else None
    return wanted is not None and list(wanted) != list(own or ())


# How often the configuration file is looked at, in seconds.
POLL_SECONDS = 1.0

# How long a connection that has been told to reconnect may sit idle before the
# daemon leaves without it, in seconds.
GRACE_SECONDS = 10.0


def _fingerprint(path: str) -> Optional[bytes]:
    """What the file says, or ``None`` if there is no file to say it.

    The content rather than the modification time: an editor saving an
    unchanged buffer, or a ``touch``, is not a change of configuration and is
    not worth dropping every warm context for.
    """
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).digest()
    except FileNotFoundError:
        return None


class ConfigWatcher:
    """Calls ``on_change`` once, the first time ``path`` says something new.

    A change is acted on only once the file has held still for one more poll.
    An editor that truncates and then writes, or writes a temporary file and
    renames it into place, is otherwise caught half-way -- and a daemon started
    from half a configuration is the thing this exists to prevent.

    Fires at most once: what it triggers is the end of this process.
    """

    def __init__(self, path: str, on_change: Callable[[], None], interval: float = POLL_SECONDS, baseline=None):
        self.path = path
        self._on_change = on_change
        self._interval = interval
        self._stop = threading.Event()
        # What the daemon actually started from, when it was taken then (see
        # 'remember'): read here instead, an edit made while the session was
        # being built would become the baseline, and the daemon would go on
        # serving the configuration from before it without ever restarting.
        self._baseline = baseline if baseline is not None else self._read()
        self._thread = threading.Thread(target=self._run, name="partcad-config-watch", daemon=True)

    def _read(self):
        try:
            return ("ok", _fingerprint(self.path))
        except OSError:
            # Unreadable for the moment -- mid-rename on Windows, say. That is
            # "no news" rather than "gone": a missing file is a change, and a
            # transient error must not look like one.
            return ("unreadable", None)

    def start(self) -> "ConfigWatcher":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        pending = None
        while not self._stop.wait(self._interval):
            current = self._read()
            if current[0] == "unreadable" or current == self._baseline:
                pending = None
                continue
            if current != pending:
                # New, but not yet known to be finished.
                pending = current
                continue
            self._stop.set()
            try:
                self._on_change()
            except Exception as e:  # pylint: disable=broad-except
                # Nothing to hand this to: the watcher is its own thread. Say
                # it where the daemon's own output goes.
                print("PartCAD daemon: failed to restart after %s changed: %s" % (self.path, e), file=sys.stderr)
            return


class Connections:
    """The live connections of a daemon, as much as a restart needs to know.

    Every transport registers each connection with a way to send it a
    notification, and brackets each request with :meth:`begin` and :meth:`end`.
    Thread-safe: the socket server runs a thread per connection, the pipe
    server a thread per request.
    """

    class _Entry:
        __slots__ = ("send", "busy", "told", "idle_since")

        def __init__(self, send):
            self.send = send
            self.busy = 0
            self.told = False
            self.idle_since = time.monotonic()

    def __init__(self):
        self._lock = threading.Lock()
        self._entries: dict = {}
        self._next = 0
        self.draining = threading.Event()

    def add(self, send: Optional[Callable[[str, object], None]] = None) -> int:
        """Count a connection; ``send`` may follow, through :meth:`ready`.

        One without it yet is owed a wait: it has been accepted and has not had
        the chance to say anything, and it cannot be told to reconnect.
        """
        with self._lock:
            self._next += 1
            self._entries[self._next] = self._Entry(send)
            return self._next

    def ready(self, token: int, send: Callable[[str, object], None]) -> None:
        with self._lock:
            entry = self._entries.get(token)
            if entry is not None:
                entry.send = send
                entry.idle_since = time.monotonic()
        if self.draining.is_set():
            self.tell_idle()

    def remove(self, token: int) -> None:
        with self._lock:
            self._entries.pop(token, None)

    def begin(self, token: int) -> None:
        with self._lock:
            entry = self._entries.get(token)
            if entry is not None:
                entry.busy += 1

    def end(self, token: int) -> None:
        with self._lock:
            entry = self._entries.get(token)
            if entry is not None:
                entry.busy = max(0, entry.busy - 1)
                entry.idle_since = time.monotonic()
        if self.draining.is_set():
            # Told as soon as it can be, rather than at the next drain tick.
            self.tell_idle()

    def tell_idle(self) -> None:
        """Send ``doRestart`` to every idle connection that has not had it yet."""
        with self._lock:
            due = [e for e in self._entries.values() if e.send is not None and not e.busy and not e.told]
            for entry in due:
                entry.told = True
                entry.idle_since = time.monotonic()
        for entry in due:
            try:
                entry.send(events.DO_RESTART, None)
            except Exception:  # pylint: disable=broad-except
                # Gone already; its own thread will remove it.
                pass

    def settled(self, grace: float = GRACE_SECONDS) -> bool:
        """Whether the daemon may leave: nobody is left who is owed a wait."""
        now = time.monotonic()
        with self._lock:
            return all(e.told and not e.busy and now - e.idle_since >= grace for e in self._entries.values())

    def drain(self, grace: float = GRACE_SECONDS, until: Optional[threading.Event] = None, tick: float = 0.1) -> None:
        """Tell everyone, then wait until :meth:`settled`. Call after the listener is gone.

        ``until`` ends the wait early: a ``daemon.stop`` sent over a connection
        the daemon is still serving is a request to stop now, drained or not.
        """
        self.draining.set()
        while until is None or not until.is_set():
            self.tell_idle()
            if self.settled(grace):
                return
            time.sleep(tick)


# What the configuration file said when this process started reading it, by
# path -- see 'remember'.
_REMEMBERED = {}


def remember(path: Optional[str] = None) -> None:
    """Note what the configuration says *now*, before anything reads it.

    Called first thing by every serving process, so that the watcher started
    later compares against what the daemon was configured from rather than
    against whatever the file says by the time it gets round to looking.
    """
    path = path or config_path()
    try:
        _REMEMBERED[path] = ("ok", _fingerprint(path))
    except OSError:
        _REMEMBERED[path] = ("unreadable", None)


def config_path() -> str:
    """The file whose edits restart the daemon: the one ``UserConfig`` reads."""
    from partcad_utils.user_config import UserConfig

    return UserConfig.get_config_path()


def announce(path: str) -> None:
    """Say why the daemon is leaving, in the daemon's own log."""
    print(
        "PartCAD daemon: %s changed; restarting (the next client starts a daemon that reads it)" % path,
        file=sys.stderr,
        flush=True,
    )


def watch(on_change: Callable[[], None], path: Optional[str] = None) -> Optional[ConfigWatcher]:
    """Start watching the configuration file; ``None`` if it cannot be watched.

    ``PC_DAEMON_RESTART_ON_CONFIG=0`` turns it off, for a daemon somebody is
    stepping through in a debugger and does not want to lose.
    """
    from partcad_utils.booleans import to_bool

    if not to_bool(os.environ.get("PC_DAEMON_RESTART_ON_CONFIG", "1")):
        return None
    path = path or config_path()

    def fire():
        announce(path)
        on_change()

    return ConfigWatcher(path, fire, baseline=_REMEMBERED.get(path)).start()
