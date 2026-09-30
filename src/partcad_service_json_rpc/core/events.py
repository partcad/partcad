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
