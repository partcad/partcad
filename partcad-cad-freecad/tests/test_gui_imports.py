#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The Qt/FreeCAD half at least loads, and wires itself up as expected.

Neither Qt nor FreeCAD is available where this suite runs, so the modules are
imported against stand-ins. That is a narrow check, but it is the one that
catches what nothing else here can: a name that only exists at import time (an
enum on the wrong class, a renamed helper, a base class that moved) and would
otherwise fail on a user's machine when the workbench is first activated.
"""

import sys
import types

import pytest


class _AutoMeta(type):
    """A class whose attributes are further classes, created on demand."""

    def __getattr__(cls, name):
        created = _auto(name)
        setattr(cls, name, created)
        return created


def _auto(name):
    return _AutoMeta(name, (object,), {"__init__": lambda self, *args, **kwargs: None})


class _Module(types.ModuleType):
    def __getattr__(self, name):
        created = _auto(name)
        setattr(self, name, created)
        return created


_GUI = "partcad_freecad.gui"


@pytest.fixture
def stub_qt(monkeypatch):
    """Import the addon's GUI modules against a ``PySide`` (and FreeCAD) stand-in.

    The GUI modules imported here hold references to the stand-ins, so they are
    removed again afterwards -- otherwise a later test that has a real Qt
    available would get these instead.
    """
    saved = {name: module for name, module in sys.modules.items() if name.startswith(_GUI)}
    for name in saved:
        del sys.modules[name]

    pyside = _Module("PySide")
    for name in ("QtCore", "QtGui", "QtWidgets"):
        setattr(pyside, name, _auto(name))
    monkeypatch.setitem(sys.modules, "PySide", pyside)
    for name in ("FreeCAD", "FreeCADGui"):
        monkeypatch.setitem(sys.modules, name, _Module(name))

    yield

    for name in [name for name in sys.modules if name.startswith(_GUI)]:
        del sys.modules[name]
    sys.modules.update(saved)


def test_the_qt_shim_imports(stub_qt):
    from partcad_freecad.gui import qt

    assert qt.QtCore is not None and qt.QtWidgets is not None


def test_every_gui_module_imports(stub_qt):
    from partcad_freecad.gui import controller, dialog, explorer, worker  # noqa: F401

    assert explorer.ExplorerDock.OBJECT_NAME == "PartCADExplorer"


def test_the_controller_is_a_singleton(stub_qt):
    from partcad_freecad.gui import controller

    assert controller.instance() is controller.instance()
    assert controller.instance().service is None


def test_every_command_is_registered_under_its_own_name(stub_qt):
    from partcad_freecad.gui import commands

    registered = {}
    commands.FreeCADGui.addCommand = lambda name, command: registered.__setitem__(name, command)

    commands.register()

    assert sorted(registered) == sorted(commands.COMMANDS)
    assert len(commands.COMMANDS) == len(set(commands.COMMANDS))


def test_every_command_advertises_an_icon_that_exists(stub_qt):
    import os

    from partcad_freecad.gui import commands

    for command in (commands.ShowExplorer(), commands.OpenPackage(), commands.Refresh(), commands.ImportSelected()):
        resources = command.GetResources()
        assert resources["MenuText"] and resources["ToolTip"]
        assert os.path.isfile(resources["Pixmap"]), resources["Pixmap"]


def test_a_failing_command_is_reported_before_it_propagates(stub_qt):
    from partcad_freecad.gui import commands

    class Failing(commands._Command):
        def run(self):
            raise RuntimeError("no package")

    reported = []
    commands.log.error = reported.append

    with pytest.raises(RuntimeError):
        Failing().Activated()

    assert reported and "no package" in reported[0]
