#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Render the structured log events a daemon forwards into ANSI, server-side.

:mod:`partcad_utils.logging_remote_client` does this in the *client*: the CLI
receives the events a daemon sends and replays them through
:mod:`partcad_utils.logging_ansi_terminal`, which owns the colours and the
multi-line progress footer. A client that cannot host that state machine gets
nothing -- which is what left the VS Code extension printing ``LEVEL: message``
in one colour, having dropped every process/action marker on arrival, because
the alternative was a second implementation of the footer in TypeScript.

So run the same renderer here instead and ship the bytes. The daemon holds the
state machine once, in the language it is already written in, and the client
writes what it is given straight into its terminal.

Two things make this cheap:

* :class:`~partcad_utils.logging_ansi_terminal.AnsiTerminalProgressHandler` is an
  ordinary ``logging.Handler`` -- ``emit(record)`` builds a string and writes it
  to ``self.stream`` -- and keeps every piece of its state on the instance. So it
  can be constructed directly, driven synchronously, and there can be one per
  connection.
* It starts and stops its own ticking thread on ``process_start``/``process_end``,
  which is what advances the elapsed seconds in the footer between log lines.

**Never call** :func:`partcad_utils.logging_ansi_terminal.init` to get one. That
installs module-global state and takes the ``partcad`` logger away from whatever
holds it -- here, the forwarding handler in
:mod:`partcad_utils.logging_remote_server`, which is the thing producing the
events in the first place.

One renderer per connection, not per daemon: the footer is drawn by moving the
cursor up over the lines it wrote last time, so two clients sharing a renderer
would each erase lines from the other's terminal.
"""

import logging

from .logging_ansi_terminal import AnsiTerminalProgressHandler
from .logging_remote_server import PC_EVENTS


class _CallbackStream:
    """The 'terminal' the renderer writes to: a callable taking rendered text."""

    def __init__(self, write):
        self._write = write

    def write(self, text: str) -> None:
        self._write(text)

    def flush(self) -> None:
        # Nothing is buffered here; the callback delivers each write.
        pass


def event_to_record(event: dict):
    """Rebuild the log record an event was made from, or None if it is neither.

    The forwarding handler serialises records with ``record_to_event``; this is
    the inverse, as far as the renderer needs it. The message travels as an
    argument rather than in ``msg`` so that a ``%`` in it is never read as a
    format specifier -- the same care ``logging_remote_client.handle`` takes.
    """
    kind = event.get("kind")
    if kind == "log":
        return logging.LogRecord(
            "partcad",
            event.get("levelno", logging.INFO),
            "",
            0,
            "%s",
            (event.get("message", ""),),
            None,
        )
    if kind in PC_EVENTS:
        # CRITICAL for the same reason the server emits these at CRITICAL: a
        # marker must never be dropped by a level filter.
        record = logging.LogRecord("partcad", logging.CRITICAL, "", 0, "", (), None)
        record.pc_event = kind
        record.op = event.get("op")
        record.package = event.get("package")
        record.item = event.get("item")
        return record
    return None


class AnsiEventRenderer:
    """Renders one connection's event stream into ANSI text.

    ``write`` is called with each chunk the renderer produces, from the dispatch
    thread and from the handler's own ticking thread, so it must be safe to call
    from either.
    """

    def __init__(self, write):
        self._handler = AnsiTerminalProgressHandler(stream=_CallbackStream(write))

    def handle(self, event: dict) -> None:
        record = event_to_record(event)
        if record is not None:
            self._handler.emit(record)

    def close(self) -> None:
        """Stop the ticking thread, if a process was still open.

        A client that disconnects mid-operation leaves the handler with a live
        ``process`` and a thread redrawing a footer into a closed connection.
        ``run_thread`` loops on ``self.process``, so clearing it ends the thread
        within its 0.25s tick.
        """
        thread = self._handler.thread
        self._handler.process = None
        self._handler.thread = None
        if thread is not None:
            thread.join(timeout=5)
