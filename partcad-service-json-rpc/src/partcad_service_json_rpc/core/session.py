#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Per-connection PartCAD session.

A :class:`Session` owns the loaded ``partcad`` module and context, the resolved
settings, an :class:`~partcad_service_json_rpc.core.events.EventEmitter`, the
and the optional log-streaming thread. Operations
receive a session and never touch a protocol library, so the same operations
run under the JSON-RPC transports and under the legacy LSP adapter.
"""

import copy
import importlib
import logging
import sys
import threading

from .events import EventEmitter

_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "warn": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}


def _resolve_level(name, default):
    """Map a user_config log-level name onto a ``logging`` level int."""
    if not name:
        return default
    return _LEVELS.get(str(name).lower(), default)


def _as_bool(value) -> bool:
    """Read a setting that may arrive as a JSON boolean or as its string form.

    The two clients spell the same setting differently: the daemon's own command
    line turns a flag into ``"true"``, while the VS Code extension forwards its
    configuration values with their JSON types intact, so a boolean setting
    arrives as ``True``.
    """
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


class Session:
    """Holds the state one PartCAD connection needs."""

    def __init__(self, emitter: EventEmitter = None, settings: dict = None):
        self.emitter = emitter if emitter is not None else EventEmitter()
        self.settings = settings or {}

        # Loaded lazily by load_partcad().
        self.partcad = None
        self.partcad_ctx = None
        self.package_path = None

        # Context registry: context id -> PartCAD context, created by
        # context.create(url) and persisted indefinitely so later commands reuse
        # the warm context by passing the id back.
        # TODO: expire contexts (evict idle/old ones) so this never grows unbounded.
        self.contexts: dict = {}

        self._load_lock = threading.RLock()

        # Legacy LSP log streaming: an externally-owned ANSI write stream, bound
        # via bind_log_stream() (the bundled VS Code LSP adapter uses this).
        self._log_write = None

        # Remote structured-log forwarding, opt-in via start_remote_log(), used
        # by the JSON-RPC transports (socket daemon, stdio, HTTP).
        self._use_remote_log = False
        self._log_file = None
        self._log_file_level = None

    # ---- log streaming ------------------------------------------------------

    def start_remote_log(self, log_file: str = None, file_level=None) -> None:
        """Forward PartCAD's logs to the connected client as structured events.

        Used by the JSON-RPC transports. Log records and process/action markers
        travel over the notification channel (the same reliable path as RPC
        responses, which is what makes this work inside the frozen bundle where
        the old ANSI pipe did not), and, if ``log_file`` is given, are also teed
        into a rotating file. ``file_level`` overrides the file verbosity;
        otherwise it comes from ``user_config`` (default: full detail).
        """
        self._use_remote_log = True
        self._log_file = log_file
        self._log_file_level = file_level

    def _log_hook(self, event) -> None:
        """Route one structured log event to the current client via the emitter.

        The emitter's sink is (re)bound per request, so events reach whichever
        client is currently being served and are dropped between requests.
        """
        self.emitter.emit("log", event)

    @property
    def log_write_stream(self):
        return self._log_write

    def bind_log_stream(self, write_stream) -> None:
        """Use an externally-managed write stream for PartCAD's ANSI logger.

        The legacy VS Code LSP adapter owns its own log pipe and reader thread
        (set up before this session exists, so install-time output can stream);
        it binds that write stream here instead of using start_remote_log().
        """
        self._log_write = write_stream

    # ---- partcad lifecycle --------------------------------------------------

    def ensure_partcad(self):
        """Import PartCAD once if it has not been loaded yet, and return it.

        Double-checked under ``_load_lock`` (an RLock, so the nested
        ``load_partcad()`` acquisition is fine): the HTTP transport dispatches
        from a thread pool, so two concurrent requests could both see
        ``partcad is None`` and both call ``load_partcad()`` -- the second one
        tearing down and reloading the module while the first is still using it.
        """
        if self.partcad is None:
            with self._load_lock:
                if self.partcad is None:
                    self.load_partcad()
        return self.partcad

    def load_partcad(self) -> None:
        """Import (or reload) ``partcad`` and apply the session settings.

        Mirrors the legacy LSP server's ``load_partcad``: a reload resets
        PartCAD's global state between package loads.
        """
        with self._load_lock:
            self.partcad_ctx = None
            if self.partcad is None:
                self.partcad = importlib.import_module("partcad")
            else:
                try:
                    self.partcad.fini()
                    self.partcad.logging_ansi_terminal_fini()
                except Exception as e:  # pylint: disable=broad-except
                    self.emitter.error("Failed to de-initialize PartCAD: %s." % e)
                for module_name in sorted(sys.modules.keys()):
                    # Reset PartCAD (and ocp_vscode) module state between loads,
                    # but never this shared service package: the session and the
                    # operations calling load_partcad live in it.
                    if module_name.startswith("partcad_service_json_rpc"):
                        continue
                    if (
                        module_name == "partcad"
                        or module_name.startswith("partcad.")
                        or module_name.startswith("partcad_cli")
                        or module_name.startswith("ocp_vscode")
                    ):
                        del sys.modules[module_name]
                self.partcad = importlib.reload(importlib.import_module("partcad"))

            settings = copy.deepcopy(self.settings)
            user_config = self.partcad.user_config
            if settings.get("pythonSandbox"):
                user_config.python_runtime = settings["pythonSandbox"]
            if settings.get("forceUpdate"):
                user_config.force_update = settings["forceUpdate"] == "true"
            if "develPub" in settings:
                user_config.devel_pub = _as_bool(settings["develPub"])

            logging.basicConfig()
            logging.getLogger("partcad").propagate = False
            verbosity = settings.get("verbosity")
            if verbosity == "debug":
                logging.getLogger("partcad").setLevel(logging.DEBUG)
            elif verbosity == "info":
                logging.getLogger("partcad").setLevel(logging.INFO)
            elif verbosity == "error":
                logging.getLogger("partcad").setLevel(logging.ERROR)

            if self._use_remote_log:
                level = self._log_file_level
                if level is None:
                    level = _resolve_level(getattr(user_config, "log_level", None), logging.DEBUG)
                self.partcad.logging_remote_server.init(
                    hook=self._log_hook,
                    log_file=self._log_file,
                    file_level=level,
                )
            elif self._log_write is not None:
                self.partcad.logging_ansi_terminal.init(stream=self._log_write)
