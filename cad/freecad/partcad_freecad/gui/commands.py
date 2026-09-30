#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The FreeCAD commands the PartCAD workbench puts on its toolbar and menu.

Importing this module registers them; :data:`COMMANDS` is the order they appear
in. Each one is a thin shell over :mod:`partcad_freecad.gui.controller` -- the
command classes exist to satisfy FreeCAD's command API, not to hold logic.
"""

import os

import FreeCADGui

from .. import log
from . import controller, explorer

# .../partcad_freecad/gui/commands.py -> the addon directory FreeCAD loaded.
_ADDON_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ICON_DIR = os.path.join(_ADDON_ROOT, "resources", "icons")

CMD_EXPLORER = "PartCAD_Explorer"
CMD_OPEN = "PartCAD_OpenPackage"
CMD_REFRESH = "PartCAD_Refresh"
CMD_IMPORT = "PartCAD_Import"

COMMANDS = [CMD_EXPLORER, CMD_OPEN, CMD_REFRESH, CMD_IMPORT]


def icon(name: str) -> str:
    return os.path.join(ICON_DIR, name)


class _Command:
    """Shared plumbing: FreeCAD instantiates these and calls the hooks below."""

    menu = ""
    tooltip = ""
    icon_file = "partcad.svg"

    def GetResources(self):  # noqa: N802 - FreeCAD's API
        return {
            "Pixmap": icon(self.icon_file),
            "MenuText": self.menu,
            "ToolTip": self.tooltip,
        }

    def IsActive(self):  # noqa: N802 - FreeCAD's API
        return True

    def Activated(self):  # noqa: N802 - FreeCAD's API
        try:
            self.run()
        except Exception as e:  # pylint: disable=broad-except
            # A command that raises leaves only a traceback in the console;
            # report it where a FreeCAD user will see it.
            log.error("%s failed: %s" % (type(self).__name__, e))
            raise

    def run(self):
        raise NotImplementedError


class ShowExplorer(_Command):
    """Open (or raise) the PartCAD explorer panel."""

    menu = "PartCAD Explorer"
    tooltip = "Show the PartCAD explorer with the packages, parts and assemblies"

    def run(self):
        explorer.show(controller.instance())


class OpenPackage(_Command):
    """Pick a PartCAD package directory and load it into the explorer."""

    menu = "Open Package..."
    tooltip = "Open a PartCAD package directory (a folder with partcad.yaml)"
    icon_file = "partcad-open.svg"

    def run(self):
        dock = explorer.show(controller.instance())
        dock.widget.open_package()


class Refresh(_Command):
    """Re-fetch the imported packages and reload the tree."""

    menu = "Refresh"
    tooltip = "Update the imported packages and reload the contents"
    icon_file = "partcad-refresh.svg"

    def IsActive(self):  # noqa: N802 - FreeCAD's API
        return controller.instance().service is not None

    def run(self):
        dock = explorer.show(controller.instance())
        dock.widget.refresh()


class ImportSelected(_Command):
    """Import the selected part or assembly into the active document."""

    menu = "Import Selected..."
    tooltip = "Set the parameters of the selected part or assembly and import it as a STEP"
    icon_file = "partcad-import.svg"

    def IsActive(self):  # noqa: N802 - FreeCAD's API
        return controller.instance().service is not None

    def run(self):
        dock = explorer.show(controller.instance())
        dock.widget.import_selected()


def register() -> None:
    """Register every command with FreeCAD. Safe to call more than once."""
    FreeCADGui.addCommand(CMD_EXPLORER, ShowExplorer())
    FreeCADGui.addCommand(CMD_OPEN, OpenPackage())
    FreeCADGui.addCommand(CMD_REFRESH, Refresh())
    FreeCADGui.addCommand(CMD_IMPORT, ImportSelected())
