#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Client-side rendering of structured log events forwarded by a daemon.

The counterpart to :mod:`partcad_utils.logging_remote_server`. A thin client
(the CLI, or any other consumer) receives the structured ``log`` events the
server forwards and replays them locally:

* under ANSI, into :mod:`partcad_utils.logging_ansi_terminal`, so the colours and
  the process/action progress footer are rendered on the client;
* otherwise, as plain ``<UTC time> LEVEL:name:message`` lines on the given
  stream.

Log records are replayed the same way in both modes — through the ``partcad``
logger, so whichever handler ``init`` installed does the rendering. Process and
action markers are replayed through ``ops`` under ANSI, where they drive the
progress footer.

Plain mode has no footer and drops the markers: the daemon logs a ``DONE`` line,
with its duration, for every process that finishes, and for every action too
when it runs verbose. It is what a CI log and an agent read, so every line
carries the UTC time the daemon logged it.
"""

import logging
import sys
import time

from . import logging as _pc_logging
from . import logging_ansi_terminal
from .logging import ops
from .logging_remote_server import PC_EVENTS

_want_ansi: bool = False
_plain_handler: logging.Handler = None


def plain_formatter() -> logging.Formatter:
    """``2026-10-02T14:31:01.816Z INFO:partcad:message`` -- UTC, to the millisecond.

    UTC because the reader is as likely to be a CI log as a terminal, and a log
    compared against another machine's (the daemon's ``partcad.log``, a runner's
    own timestamps) has to agree on what time it is.
    """
    formatter = logging.Formatter(
        "%(asctime)s.%(msecs)03dZ %(levelname)s:%(name)s:%(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    formatter.converter = time.gmtime
    return formatter


def init(want_ansi: bool = True, stream=None) -> None:
    """Prepare local rendering of forwarded events.

    ``want_ansi`` selects the ANSI terminal renderer (default, to stdout) versus
    plain lines (to stderr, matching ``pc --no-ansi``). ``stream`` overrides the
    destination (used by tests).
    """
    global _want_ansi, _plain_handler

    _want_ansi = want_ansi
    logger = logging.getLogger("partcad")
    # The server already applied its own verbosity filter before forwarding, so
    # render everything that arrives.
    logger.setLevel(logging.DEBUG)

    if want_ansi:
        # logging_ansi_terminal.init() guards against a second setup itself.
        logging_ansi_terminal.init(stream=stream or sys.stdout)
    elif _plain_handler is None:
        _plain_handler = logging.StreamHandler(stream or sys.stderr)
        _plain_handler.setFormatter(plain_formatter())
        logger.addHandler(_plain_handler)


def handle(event: dict) -> None:
    """Render one structured event forwarded by the server."""
    kind = event.get("kind")
    if kind == "log":
        levelno = event.get("levelno", logging.INFO)
        # Mirror the in-process error tracking: an error forwarded from the daemon
        # must make the CLI exit non-zero (command.py checks logging.had_errors).
        if levelno >= logging.ERROR:
            _pc_logging.had_errors = True
            if _pc_logging.first_error is None:
                _pc_logging.first_error = event.get("message", "")
        _replay(levelno, event.get("message", ""), event.get("created"))
    elif kind in PC_EVENTS:
        if _want_ansi:
            getattr(ops, kind)(event.get("op"), event.get("package"), event.get("item"))


def _replay(levelno: int, message: str, created) -> None:
    """Log a forwarded record locally, dated when the daemon made it.

    The time on a plain line is the time of the event, not of its rendering: a
    line can reach the client a moment late, and a log that is read for where
    the time went has to say when things happened in the daemon.
    """
    logger = logging.getLogger("partcad")
    if not logger.isEnabledFor(levelno):
        return
    # The message is passed as an argument so any '%' in it is never treated as
    # a format specifier.
    record = logger.makeRecord(logger.name, levelno, "(daemon)", 0, "%s", (message,), None)
    if created is not None:
        # Rounded to the millisecond the line shows, rather than truncated: a
        # float a hair under .816 would otherwise print as .815.
        millis = round(created * 1000)
        record.created = millis / 1000
        record.msecs = float(millis % 1000)
    logger.handle(record)


def fini() -> None:
    """Flush and detach whatever renderer ``init`` installed."""
    global _plain_handler

    if _want_ansi:
        logging_ansi_terminal.fini()
    if _plain_handler is not None:
        logging.getLogger("partcad").removeHandler(_plain_handler)
        _plain_handler = None
