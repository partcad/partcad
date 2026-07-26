#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Per-connection PartCAD session.

A :class:`Session` owns the loaded ``partcad`` module and context, the resolved
settings, an :class:`~partcad_service_json_rpc.core.events.EventEmitter`, the
interactive-prompt plumbing, and the optional log-streaming thread. Operations
receive a session and never touch a protocol library, so the same operations
run under the JSON-RPC transports and under the legacy LSP adapter.
"""

import base64
import copy
import importlib
import logging
import os
import queue
import sys
import threading

from .events import TERMINAL, EventEmitter

_LOG_BUFSIZE = 4096


class Session:
    """Holds the state one PartCAD connection needs."""

    def __init__(self, emitter: EventEmitter = None, settings: dict = None):
        self.emitter = emitter if emitter is not None else EventEmitter()
        self.settings = settings or {}

        # Loaded lazily by load_partcad().
        self.partcad = None
        self.partcad_ctx = None
        self.package_path = None

        self._load_lock = threading.RLock()
        self._prompt_queue: "queue.Queue[str]" = queue.Queue()

        # Active telemetry spans, keyed by the id handed back to clients.
        self.spans: dict = {}

        # Log streaming (opt-in via start_log_stream()).
        self._log_read = None
        self._log_write = None
        self._log_thread = None
        self._log_die = False

    # ---- interactive prompts ------------------------------------------------

    def _interactive_prompt(self, _key: str, prompt: str) -> str:
        """Callback installed as ``partcad.interactive.prompt``."""
        self.emitter.emit("prompt", {"prompt": prompt})
        return self._prompt_queue.get().strip()

    def provide_prompt_response(self, response: str) -> None:
        """Unblock a pending interactive prompt with the user's answer."""
        self._prompt_queue.put(response)

    # ---- log streaming ------------------------------------------------------

    def start_log_stream(self) -> None:
        """Route PartCAD's ANSI terminal logger to TERMINAL events.

        Cross-platform: a background thread does a blocking read on the pipe and
        forwards each chunk, base64-encoded, exactly as the legacy LSP server
        did over the ``?/partcad/terminal`` notification.
        """
        if self._log_thread is not None:
            return
        read_fd, write_fd = os.pipe()
        self._log_read = os.fdopen(read_fd, "rb", buffering=0)
        self._log_write = os.fdopen(write_fd, "w", buffering=1)
        self._log_die = False
        self._log_thread = threading.Thread(target=self._pump_log, name="partcad-json-rpc-log", daemon=True)
        self._log_thread.start()

    @property
    def log_write_stream(self):
        return self._log_write

    def bind_log_stream(self, write_stream) -> None:
        """Use an externally-managed write stream for PartCAD's ANSI logger.

        The legacy VS Code LSP adapter owns its own log pipe and reader thread
        (set up before this session exists, so install-time output can stream);
        it binds that write stream here instead of calling start_log_stream().
        """
        self._log_write = write_stream

    def _pump_log(self) -> None:
        while not self._log_die:
            chunk = self._log_read.read(_LOG_BUFSIZE)
            if not chunk:
                break
            chunk = chunk.replace(b"\n", b"\r\n")
            self.emitter.emit(TERMINAL, {"line": base64.b64encode(chunk).decode()})

    def stop_log_stream(self) -> None:
        self._log_die = True
        if self._log_write is not None:
            try:
                self._log_write.close()
            except Exception:  # pylint: disable=broad-except
                pass
        if self._log_thread is not None and self._log_thread.is_alive():
            self._log_thread.join(timeout=1.0)
        self._log_thread = None

    # ---- partcad lifecycle --------------------------------------------------

    def ensure_partcad(self):
        """Import PartCAD once if it has not been loaded yet, and return it."""
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

            self.partcad.interactive.prompt = self._interactive_prompt

            settings = copy.deepcopy(self.settings)
            user_config = self.partcad.user_config
            if settings.get("pythonSandbox"):
                user_config.python_runtime = settings["pythonSandbox"]
            if settings.get("forceUpdate"):
                user_config.force_update = settings["forceUpdate"] == "true"
            if settings.get("googleApiKey"):
                user_config.google_api_key = settings["googleApiKey"]
            if settings.get("openaiApiKey"):
                user_config.openai_api_key = settings["openaiApiKey"]

            logging.basicConfig()
            logging.getLogger("partcad").propagate = False
            verbosity = settings.get("verbosity")
            if verbosity == "debug":
                logging.getLogger("partcad").setLevel(logging.DEBUG)
            elif verbosity == "info":
                logging.getLogger("partcad").setLevel(logging.INFO)
            elif verbosity == "error":
                logging.getLogger("partcad").setLevel(logging.ERROR)

            if self._log_write is not None:
                self.partcad.logging_ansi_terminal.init(stream=self._log_write)
