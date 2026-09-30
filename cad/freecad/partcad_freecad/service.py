#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The PartCAD operations this addon needs, over JSON-RPC.

One :class:`PartCadService` owns one connection to the standalone service and
speaks the CLI-shaped method names (``package.load``, ``list.all``,
``export.part``, ...). It also unwraps the service's notification stream, which
is where the interesting output actually arrives:

* ``items`` carries a package's contents -- there is no *result* to read, so the
  tree is built from the notifications collected during the call;
* ``log`` / ``info`` / ``error`` carry the operation's log lines, which are
  forwarded to a sink (the FreeCAD report view) and remembered, so a failure
  that the protocol reports only as "nothing happened" can still be explained.
"""

import logging
import os
from typing import Callable, Optional

from . import client as _client
from .model import PackageContents, parse_items

LogSink = Callable[[int, str], None]

# Notifications that carry a bare string message, and the level to log it at.
_MESSAGE_EVENTS = {"info": logging.INFO, "warn": logging.WARNING, "error": logging.ERROR}

# Lifecycle signals that mean the operation did not do what was asked.
_FAILURE_EVENTS = {
    "packageLoadFailed": "the package could not be loaded",
    "activateFailed": "PartCAD could not be activated",
    "needsUpdate": "the package needs 'pc update' before it can be loaded",
}


class ServiceFailure(RuntimeError):
    """An operation reported failure through its log/lifecycle events.

    The JSON-RPC layer reports these as a successful call returning ``None``
    (the operations core logs and moves on), so this is raised by the facade
    rather than by the client.
    """


class PartCadService:
    """A connection to the PartCAD service, scoped to one package directory."""

    def __init__(self, executable: str, package_dir: str, log: Optional[LogSink] = None, client=None):
        self.executable = executable
        self.package_dir = package_dir
        self.root = "//"
        self.config_path: Optional[str] = None
        self._log = log
        # An already-connected client, when the caller has one; otherwise
        # connect() makes its own.
        self._conn = client
        # Filled in by the notification handler for the duration of one call.
        self._items: dict = {}
        self._failures: list = []
        self._errors: list = []

    # ---- lifecycle ----------------------------------------------------------

    def connect(self) -> None:
        """Connect to (starting if needed) the daemon for this package directory."""
        if self._conn is None:
            self._conn = _client.connect(self.executable, self.package_dir)

    def close(self) -> None:
        """Drop this client's connection. The shared daemon keeps running, so the
        CLI and the VS Code extension stay served by the same warm context."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @property
    def connected(self) -> bool:
        return self._conn is not None

    # ---- plumbing -----------------------------------------------------------

    def _on_event(self, method: str, params) -> None:
        if method == "items":
            contents = parse_items(params or {})
            self._items[contents.name] = contents
        elif method == "log":
            event = params or {}
            if event.get("kind") != "log":
                return  # a process/action progress marker; nothing to render
            level = event.get("levelno", logging.INFO)
            message = event.get("message", "")
            if level >= logging.ERROR:
                self._errors.append(message)
            self._emit(level, message)
        elif method in _MESSAGE_EVENTS:
            level = _MESSAGE_EVENTS[method]
            message = params if isinstance(params, str) else str(params)
            if level >= logging.ERROR:
                self._errors.append(message)
            self._emit(level, message)
        elif method in _FAILURE_EVENTS:
            self._failures.append(_FAILURE_EVENTS[method])
        elif method == "packageLoaded":
            payload = params or {}
            self.root = payload.get("root") or self.root
            self.config_path = payload.get("configPath")

    def _emit(self, level: int, message: str) -> None:
        if self._log is not None and message:
            self._log(level, message)

    def call(self, method: str, params: Optional[dict] = None):
        """Send one request, collecting the notifications it produces."""
        self.connect()
        self._items = {}
        self._failures = []
        self._errors = []
        return self._conn.call(method, params or {}, on_event=self._on_event)

    def _check(self, what: str) -> None:
        """Raise if the call just made reported a failure through its events."""
        if self._failures:
            raise ServiceFailure("%s: %s" % (what, "; ".join(self._failures)))

    @property
    def last_errors(self) -> list:
        """Error messages logged by the most recent call."""
        return list(self._errors)

    # ---- operations ---------------------------------------------------------

    def ensure_loaded(self) -> None:
        """Import PartCAD in the daemon, if it has not been imported already.

        Deliberately not ``activate``: that *reloads* the module and re-runs the
        health checks, which would throw away the warm context this daemon may
        be serving to a CLI or a VS Code window at the same time.
        """
        self.call("ensure_loaded", {"path": self.package_dir})

    def load_package(self) -> PackageContents:
        """Load the package at this service's directory and return its contents."""
        self.call("package.load", {"path": self.package_dir})
        self._check("failed to load the package at %s" % self.package_dir)
        contents = self._items.get(self.root)
        if contents is None and self._items:
            # package.load reports the contents under the loaded package's own
            # name, which is only known once `packageLoaded` has arrived.
            contents = next(iter(self._items.values()))
        if contents is None:
            raise ServiceFailure(
                "no package was loaded from %s%s"
                % (self.package_dir, (": " + "; ".join(self._errors)) if self._errors else "")
            )
        self.root = contents.name
        return contents

    def list_package(self, name: str) -> PackageContents:
        """The contents of one package (``pc list all`` for a single package)."""
        self.call("list.all", {"name": name})
        self._check("failed to list %s" % name)
        return self._items.get(name) or PackageContents(name, [])

    def refresh(self) -> None:
        """Re-fetch every imported package, then reload the contents."""
        self.call("package.refresh", {})
        self._check("failed to refresh the packages")

    def init_package(self) -> None:
        """Create a package in this service's directory."""
        self.call("init", {"path": self.package_dir})
        self._check("failed to create a package in %s" % self.package_dir)

    def export(self, item, path: str, params: Optional[dict] = None, format_name: str = "step") -> str:
        """Render a part, an assembly or a scene to ``path``; return the path.

        ``export.part``/``export.assembly``/``export.scene`` report a failed
        render through the log stream and still return successfully, so the file
        itself is the verdict.
        """
        method = {"assembly": "export.assembly", "scene": "export.scene"}.get(item.kind, "export.part")
        self.call(
            method,
            {
                "package": item.package,
                "name": item.name,
                "params": params or {},
                "type": format_name,
                "path": path,
            },
        )
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            detail = "; ".join(self._errors) if self._errors else "the service produced no output"
            raise ServiceFailure("failed to export %s: %s" % (item.qualified_name, detail))
        return path
