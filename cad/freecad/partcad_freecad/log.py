#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Routing PartCAD's log stream into FreeCAD's report view.

The service forwards its logs as structured events (level + message); this maps
them onto ``FreeCAD.Console``, which is where a FreeCAD user looks when something
did not work. Without FreeCAD the same calls go to the standard ``logging``
module, so nothing in this package needs a GUI to run.
"""

import logging

_LOGGER = logging.getLogger("partcad.freecad")

PREFIX = "PartCAD: "


def _console():
    try:
        import FreeCAD  # pylint: disable=import-outside-toplevel

        return FreeCAD.Console
    except ImportError:
        return None


def log(level: int, message: str) -> None:
    """Report one message at a ``logging`` level."""
    console = _console()
    if console is None:
        _LOGGER.log(level, "%s", message)
        return
    line = PREFIX + message.rstrip() + "\n"
    if level >= logging.ERROR:
        console.PrintError(line)
    elif level >= logging.WARNING:
        console.PrintWarning(line)
    elif level >= logging.INFO:
        console.PrintMessage(line)
    else:
        console.PrintLog(line)


def info(message: str) -> None:
    log(logging.INFO, message)


def warning(message: str) -> None:
    log(logging.WARNING, message)


def error(message: str) -> None:
    log(logging.ERROR, message)
