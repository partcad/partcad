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
* otherwise, as plain ``LEVEL:name:message`` lines on the given stream.

Log records are replayed the same way in both modes — through the ``partcad``
logger, so whichever handler ``init`` installed does the rendering. Process and
action markers only make sense with the progress footer, so they are replayed
through ``ops`` under ANSI and dropped in plain mode.
"""

import logging
import sys

from . import logging_ansi_terminal
from .logging import ops
from .logging_remote_server import PC_EVENTS

_want_ansi: bool = False
_plain_handler: logging.Handler = None


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
        _plain_handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
        logger.addHandler(_plain_handler)


def handle(event: dict) -> None:
    """Render one structured event forwarded by the server."""
    kind = event.get("kind")
    if kind == "log":
        # Pass the message as an argument so any '%' in it is never treated as a
        # format specifier.
        logging.getLogger("partcad").log(event.get("levelno", logging.INFO), "%s", event.get("message", ""))
    elif kind in PC_EVENTS:
        if _want_ansi:
            getattr(ops, kind)(event.get("op"), event.get("package"), event.get("item"))


def fini() -> None:
    """Flush and detach whatever renderer ``init`` installed."""
    global _plain_handler

    if _want_ansi:
        logging_ansi_terminal.fini()
    if _plain_handler is not None:
        logging.getLogger("partcad").removeHandler(_plain_handler)
        _plain_handler = None
