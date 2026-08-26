#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Server-side logging backend that forwards events to a remote client.

This is the daemon's counterpart to :mod:`partcad_utils.logging_ansi_terminal`.
Instead of rendering to a terminal, it forwards **structured** events — plain
log records and process/action start/end — to a hook registered by the service
layer. The hook ships them over the JSON-RPC notification channel to whichever
client is currently being served, and :mod:`partcad_utils.logging_remote_client`
renders them on the far side.

It also optionally tees every real log record into a rotating log file (the
daemon's persistent per-workspace log), independent of what any client asked
for. The pc_event control records (process/action markers) are filtered out of
that file — they are transport events, not log lines.
"""

import logging
from logging.handlers import RotatingFileHandler

from .logging import ops

# The process/action markers PartCAD emits as log records carrying a `pc_event`
# extra (identical to what the ANSI terminal backend consumes).
PC_EVENTS = ("process_start", "process_end", "action_start", "action_end")

# Rotating file defaults: enough to keep a useful history without unbounded growth.
FILE_MAX_BYTES = 10 * 1024 * 1024
FILE_BACKUP_COUNT = 5


def _emit_event(kind: str, op: str, package: str, item: str = None) -> None:
    """Emit a pc_event record so it flows through the forwarding handler.

    Mirrors :mod:`partcad_utils.logging_ansi_terminal`'s ops functions: the event
    is carried as ``extra`` on a CRITICAL record (CRITICAL so it is never dropped
    by the logger level), which the handler recognizes and forwards structurally.
    """
    logging.getLogger("partcad").critical(
        "%s: %s: %s: %s" % (kind, op, package, item),
        extra={"pc_event": kind, "op": op, "package": package, "item": item},
    )


def _process_start(op: str, package: str, item: str = None) -> None:
    _emit_event("process_start", op, package, item)


def _process_end(op: str, package: str, item: str = None) -> None:
    _emit_event("process_end", op, package, item)


def _action_start(op: str, package: str, item: str = None) -> None:
    _emit_event("action_start", op, package, item)


def _action_end(op: str, package: str, item: str = None) -> None:
    _emit_event("action_end", op, package, item)


def record_to_event(record: logging.LogRecord) -> dict:
    """Turn a log record into the structured event dict sent to the client."""
    pc_event = getattr(record, "pc_event", None)
    if pc_event is not None:
        return {
            "kind": pc_event,
            "op": getattr(record, "op", None),
            "package": getattr(record, "package", None),
            "item": getattr(record, "item", None),
        }
    return {
        "kind": "log",
        "levelno": record.levelno,
        "levelname": record.levelname,
        "message": record.getMessage(),
    }


class _ForwardHandler(logging.Handler):
    """Serializes each PartCAD log record and hands it to the registered hook."""

    def __init__(self, hook):
        super().__init__()
        self._hook = hook

    def set_hook(self, hook) -> None:
        self._hook = hook

    def emit(self, record: logging.LogRecord) -> None:
        try:
            hook = self._hook
            if hook is not None:
                hook(record_to_event(record))
        except Exception:  # pylint: disable=broad-except
            self.handleError(record)


class _PcEventFilter(logging.Filter):
    """Keeps the pc_event control records out of the rotating file."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not hasattr(record, "pc_event")


_forward_handler: _ForwardHandler = None
_file_handler: RotatingFileHandler = None
_saved_handlers: list = []


def init(hook, log_file: str = None, file_level: int = logging.DEBUG) -> None:
    """Route PartCAD's logging to ``hook`` (and, optionally, a rotating file).

    ``hook`` is any callable taking one structured event dict. ``log_file``, if
    given, receives every real log record (not pc_event markers) at
    ``file_level`` regardless of what the client requested.
    """
    global _forward_handler, _file_handler, _saved_handlers

    logger = logging.getLogger("partcad")

    if _forward_handler is None:
        # Take over the logger the way logging_ansi_terminal.init does: set aside
        # any pre-existing handlers so records go only where we route them.
        _saved_handlers = list(logger.handlers)
        for handler in _saved_handlers:
            logger.removeHandler(handler)
        _forward_handler = _ForwardHandler(hook)
        logger.addHandler(_forward_handler)
    else:
        _forward_handler.set_hook(hook)

    if log_file is not None and _file_handler is None:
        _file_handler = RotatingFileHandler(
            log_file, maxBytes=FILE_MAX_BYTES, backupCount=FILE_BACKUP_COUNT
        )
        _file_handler.setLevel(file_level)
        _file_handler.addFilter(_PcEventFilter())
        _file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(_file_handler)

    ops.process_start = _process_start
    ops.process_end = _process_end
    ops.action_start = _action_start
    ops.action_end = _action_end


def fini() -> None:
    """Detach the handlers and restore the default process/action ops."""
    global _forward_handler, _file_handler, _saved_handlers

    logger = logging.getLogger("partcad")

    if _forward_handler is not None:
        logger.removeHandler(_forward_handler)
        _forward_handler = None
    if _file_handler is not None:
        logger.removeHandler(_file_handler)
        try:
            _file_handler.close()
        except Exception:  # pylint: disable=broad-except
            pass
        _file_handler = None

    for handler in _saved_handlers:
        logger.addHandler(handler)
    _saved_handlers = []

    # Drop the instance overrides so ops falls back to the class-level defaults.
    for attr in ("process_start", "process_end", "action_start", "action_end"):
        try:
            delattr(ops, attr)
        except AttributeError:
            pass
