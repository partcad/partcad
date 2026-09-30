#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The PartCAD workbench.

FreeCAD executes this file at start-up for every directory under ``Mod``, with
that directory on ``sys.path`` -- which is what makes ``import partcad_freecad``
below work. Keep it to registration: everything the workbench does lives in
:mod:`partcad_freecad`, so a syntax or import error here would cost the user the
whole workbench rather than one command.
"""

import os

import FreeCAD
import FreeCADGui

ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
ICON = os.path.join(ADDON_DIR, "resources", "icons", "partcad.svg")


class PartCADWorkbench(FreeCADGui.Workbench):
    """Browse PartCAD packages and import their parts and assemblies."""

    MenuText = "PartCAD"
    ToolTip = "Browse PartCAD packages and import parts and assemblies"
    Icon = ICON

    def Initialize(self):  # noqa: N802 - FreeCAD's API
        """Called the first time the user switches to this workbench."""
        from partcad_freecad.gui import commands

        commands.register()
        self.appendToolbar("PartCAD", commands.COMMANDS)
        self.appendMenu("PartCAD", commands.COMMANDS)

    def Activated(self):  # noqa: N802 - FreeCAD's API
        from partcad_freecad.gui import controller, explorer

        explorer.show(controller.instance())

    def Deactivated(self):  # noqa: N802 - FreeCAD's API
        # The explorer stays where it is: the panel is useful while another
        # workbench does the modelling, and the daemon connection is shared.
        pass

    def GetClassName(self):  # noqa: N802 - FreeCAD's API
        return "Gui::PythonWorkbench"


FreeCADGui.addWorkbench(PartCADWorkbench())
FreeCAD.Console.PrintLog("PartCAD: workbench registered from %s\n" % ADDON_DIR)
