#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The factories that create a package's tools, one per category.

All four classes live in one module, unlike the part and sketch factories which
get one file each. There is nothing per-category to implement: a category
decides which 'Tool' subclass reads the declaration and nothing else, because a
tool is not built, fetched, cached or rendered - the part its 'visual' points at
is, and that part goes through the part machinery like any other. Three files of
four lines apiece would say less than the table below does.
"""

import typing

from . import factory
from . import logging as pc_logging
from . import telemetry
from .tool import CATEGORIES, TOOL_CLASSES, Tool


@telemetry.instrument()
class ToolFactory(factory.Factory):
    """The base of every 'tool' factory.

    Deliberately not a 'ShapeFactory' - and not even a file factory, which is
    what 'SoftwareFactory' still shares with the shapes. A tool has no geometry
    and no file of its own: everything it stands for is either a property of the
    declaration or the part named by 'visual'.
    """

    name: str
    orig_name: str
    tool: Tool
    # The 'Tool' subclass this factory creates. Set by each category below.
    TOOL_CLASS: typing.Type[Tool] = Tool

    def __init__(self, ctx, source_project, target_project, config) -> None:
        super().__init__()

        self.ctx = ctx
        self.project = source_project
        self.target_project = target_project
        self.config = config
        self.name = config["name"]
        self.orig_name = config["orig_name"]

        with pc_logging.Action("InitTool", target_project.name, self.name):
            self._create(config)

    def _create(self, config) -> None:
        self.tool = self.TOOL_CLASS(self.target_project.name, config)
        self.tool.info = lambda: self.info(self.tool)
        self.target_project.register_object("tool", self.name, self.tool)

    def info(self, tool) -> dict:
        info = tool.tool_info()
        config_obj = self.project.config_obj or {}
        if config_obj.get("url") is not None:
            info["Url"] = config_obj["url"]
        if config_obj.get("importUrl") is not None:
            info["ImportUrl"] = config_obj["importUrl"]
        return info


def _factory_for(category: str):
    """The factory class serving one category of tools."""
    return type(
        "ToolFactory" + category.capitalize(),
        (ToolFactory,),
        {
            "TOOL_CLASS": TOOL_CLASSES[category],
            "__doc__": "Creates the '%s' tools of a package (see 'partcad.tool')." % category,
        },
    )


# One factory per category, registered under the category name: a tool's 'type'
# *is* its category (see 'ToolConfiguration.normalize'), so a declaration under
# a sub-section PartCAD does not know fails as an unknown type, naming the three
# that exist.
FACTORIES = {category: _factory_for(category) for category in CATEGORIES}
