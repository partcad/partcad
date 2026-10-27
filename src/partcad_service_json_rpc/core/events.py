#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Transport-agnostic event emitter for the operations core.

Operations never talk to a protocol directly. They push named events to an
:class:`EventEmitter`, and each transport (or the legacy LSP adapter) binds a
sink that serializes those events into its own notification format. The event
names below mirror the legacy ``?/partcad/*`` notifications one-to-one, so the
VS Code extension's behavior is preserved on both backends.
"""

import base64
from typing import Any, Callable, Optional

# Event names (mirror the legacy ?/partcad/<name> notification suffixes).
INFO = "info"
# The VS Code extension listens on "?/partcad/warn"; keep the event name aligned
# with that listener (the legacy server emitted "warning", which never matched).
WARNING = "warn"
ERROR = "error"
TERMINAL = "terminal"
EXECUTE = "execute"
STATS = "stats"
ITEMS = "items"
SHOW_PART_DONE = "showPartDone"
EXPORT_PART_DONE = "exportPartDone"
LOADED = "loaded"
ACTIVATE_FAILED = "activateFailed"
PACKAGE_LOADED = "packageLoaded"
PACKAGE_LOAD_FAILED = "packageLoadFailed"
NEEDS_UPDATE = "needsUpdate"
DO_RESTART = "doRestart"
INSTALLED = "installed"
INSTALL_FAILED = "installFailed"

# What a TERMINAL event carries: one piece of the log display a connection's
# renderer drew (see `log.mode` in `transport/socket_server.py`), which the
# client writes into its terminal as it is. Under TERMINAL_TEXT it is the text
# itself -- JSON carries any string, terminal control characters included, so
# there is nothing to encode. It used to be the base64 of its UTF-8 under
# TERMINAL_LINE, which is no smaller on the wire (base64 adds a third, and JSON
# spells an escape character in six, so a display that is mostly footer redraws
# comes out about even) and costs an encode here and a decode on the editor's
# extension host for every piece. That is still what a connection gets unless
# it asked for the text (`log.mode {"ansi": true, "text": true}`): the extension
# and the daemon are versioned apart, and one from before reads only
# TERMINAL_LINE.
TERMINAL_TEXT = "text"
TERMINAL_LINE = "line"


def terminal_params(text: str, as_text: bool) -> dict:
    """The params of the TERMINAL notification carrying ``text``: as it is, or as base64 for an older client."""
    if as_text:
        return {TERMINAL_TEXT: text}
    return {TERMINAL_LINE: base64.b64encode(text.encode("utf-8")).decode("ascii")}


def log_mode_result(rendering: bool, as_text: bool) -> dict:
    """The answer to `log.mode`: whether the connection gets the drawing now, and whether as text.

    TERMINAL_TEXT is there only when it does, so an answer to a client that did
    not ask is the one it always got.
    """
    result = {"ansi": rendering}
    if rendering and as_text:
        result[TERMINAL_TEXT] = True
    return result


Sink = Callable[[str, Any], None]


class EventEmitter:
    """Delivers named events to a bound sink.

    A ``sink`` is any callable accepting ``(event_name, payload)``. When no sink
    is bound, emitting is a no-op, which keeps operations callable in tests and
    in contexts that do not care about notifications.
    """

    def __init__(self, sink: Optional[Sink] = None):
        self._sink = sink

    def set_sink(self, sink: Optional[Sink]) -> None:
        """Bind (or replace) the sink after construction.

        Transports build a session first and attach their notification sink once
        the output stream and its write lock exist.
        """
        self._sink = sink

    def emit(self, event: str, payload: Any = None) -> None:
        if self._sink is not None:
            self._sink(event, payload)

    def signal(self, event: str) -> None:
        """Emit a lifecycle event that carries no payload."""
        self.emit(event, None)

    # Convenience methods for the common log-style notifications.
    def info(self, message: str) -> None:
        self.emit(INFO, message)

    def warning(self, message: str) -> None:
        self.emit(WARNING, message)

    def error(self, message: str) -> None:
        self.emit(ERROR, message)
