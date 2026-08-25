#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""One import site for Qt.

FreeCAD ships a ``PySide`` shim that points at whichever binding the build uses
(PySide6 since FreeCAD 1.0, PySide2 before it). Importing through the shim keeps
the addon working on both; the explicit fallbacks cover a FreeCAD build without
the shim and a plain-Qt environment.
"""

try:
    from PySide import QtCore, QtGui, QtWidgets  # type: ignore
except ImportError:  # pragma: no cover - depends on the host FreeCAD build
    try:
        from PySide6 import QtCore, QtGui, QtWidgets  # type: ignore
    except ImportError:
        from PySide2 import QtCore, QtGui, QtWidgets  # type: ignore

__all__ = ["QtCore", "QtGui", "QtWidgets", "exec_dialog", "exec_loop", "exec_menu"]


def _exec(obj, *args):
    """Enter a modal loop. The method is ``exec_`` on PySide2, ``exec`` on PySide6."""
    runner = getattr(obj, "exec", None) or obj.exec_
    return runner(*args)


def exec_dialog(dialog):
    """Run a modal dialog and return its result code."""
    return _exec(dialog)


def exec_loop(loop):
    """Run a ``QEventLoop`` until something quits it."""
    return _exec(loop)


def exec_menu(menu, position):
    """Pop a context menu up at a global position."""
    return _exec(menu, position)
