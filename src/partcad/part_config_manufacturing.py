#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-13
#
# Licensed under Apache License, Version 2.0.
#
"""How a part is made, as the part's own configuration states it.

'manufacturing.method' is the kind of process, and the rest of the section is
what that process needs to be told. Only 'additive' has settings so far: which
machine makes the part ('tool', a reference to an additive tool - see
'partcad.tool') and the values it is made at, each of which the machine has a
range for.

Nothing here reaches out: this is built from a configuration and has no context
to resolve a tool in. 'resolve_tool()' is what does that, for the callers that
have one - 'pc cam', which hands the settings to a CAM plugin, and 'pc test',
which is where a setting the machine cannot honour is a failure.
"""

import typing

from . import logging as pc_logging
from .utils import normalize_resource_path

METHOD_NONE: None = None
# Note: The assigned numbers are used in APIs and must never change unless the old method is deprecated.
METHOD_ADDITIVE: int = 100
METHOD_SUBTRACTIVE: int = 200
METHOD_FORMING: int = 300

# These are ways of making a part, and a part only: an assembly is put together
# rather than made, and has its own single method (see AssemblyConfigManufacturing).
_METHOD_MAP: dict[str, int] = {
    "additive": METHOD_ADDITIVE,
    "subtractive": METHOD_SUBTRACTIVE,
    "forming": METHOD_FORMING,
}

# What an additive part states about how it is made, beside the method and the
# machine. The numeric ones are the properties the machine gives a range for
# ('tool.ADDITIVE_RANGES'), named the same on both sides so that the two are
# matched without a translation table.
#
# 'material' and 'color' are here as well as in 'properties:', and they mean
# different things in the two places. In 'properties:' they are what the
# finished part *is* - what an assembly's bill of materials and an exported
# model report. Here they are what the machine is loaded with to make it. They
# are usually the same thing, which is why this one defaults to that one; they
# come apart when a part is printed in whatever is on the spool and painted
# afterwards.
ADDITIVE_SETTINGS = {
    "material": str,
    "color": str,
    "layerHeight": float,
    "spotSize": float,
    "speed": float,
    "temperature": float,
    "bedTemperature": float,
    "infill": float,
    "perimeters": int,
    "supports": bool,
}

# The settings above that are fractions of one rather than a measurement, and
# so are bounded by what they are rather than by what any machine can do. A
# machine states no range for them: an infill of 1.4 is not a machine it does
# not fit, it is not a number of that kind at all.
FRACTION_SETTINGS = ("infill",)


class PartConfigManufacturing:
    method: int | None
    tool: str | None
    settings: dict

    def __init__(self, final_config: dict, project_name: str = "", where: typing.Optional[str] = None) -> None:
        manufacturing_config = final_config.get("manufacturing", {}) or {}
        self.where = where or manufacturing_config.get("name") or "manufacturing"
        self.config = manufacturing_config

        method_string = manufacturing_config.get("method", None)
        self.method = _METHOD_MAP.get(method_string, METHOD_NONE)
        if self.method == METHOD_NONE and method_string is not None:
            pc_logging.error(
                f"Unknown manufacturing method '{method_string}'. Supported methods: {list(_METHOD_MAP.keys())}."
            )

        # The machine that makes this part, as a fully qualified reference.
        # Resolved against the package that declared it, like every other object
        # reference: a bare name is a tool of this package.
        tool = manufacturing_config.get("tool", None)
        if tool is None:
            self.tool = None
        elif not isinstance(tool, str) or not tool.strip():
            self._error("'tool' must be the name of a tool, ignoring: %s" % (tool,))
            self.tool = None
        else:
            self.tool = normalize_resource_path(project_name, tool.strip())

        self.settings = self._settings(final_config)

    def _error(self, message: str) -> None:
        pc_logging.error("%s: %s" % (self.where, message))

    def _settings(self, final_config: dict) -> dict:
        """What this part is made at, typed and defaulted.

        Only for 'additive': the other methods state a method and nothing else
        yet, and a setting under one of them would be a field nothing reads.
        """
        if self.method != METHOD_ADDITIVE:
            for field in ADDITIVE_SETTINGS:
                if field in self.config:
                    self._error("'%s' is an additive setting, and this part is not made that way" % field)
            return {}

        properties = final_config.get("properties", {}) or {}
        settings = {}
        for field, kind in ADDITIVE_SETTINGS.items():
            value = self.config.get(field, None)
            if value is None and field in ("material", "color"):
                # What the part is made of is normally what it is: 'properties:'
                # says so once, for everything that reads a finished part, and
                # this is the machine being loaded with the same thing.
                value = properties.get(field, None)
            if value is None:
                continue
            typed = self._typed(field, kind, value)
            if typed is not None:
                settings[field] = typed

        for field in FRACTION_SETTINGS:
            if field in settings and not 0.0 <= settings[field] <= 1.0:
                self._error("'%s' is a fraction between 0 and 1, ignoring: %s" % (field, settings[field]))
                del settings[field]
        return settings

    def _typed(self, field, kind, value):
        if kind is bool:
            if isinstance(value, bool):
                return value
            self._error("'%s' must be true or false, ignoring: %s" % (field, value))
            return None
        if kind is str:
            if isinstance(value, str) and value.strip():
                return value.strip()
            self._error("'%s' must be a non-empty string, ignoring: %s" % (field, value))
            return None
        if kind is int:
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                return value
            self._error("'%s' must be a non-negative whole number, ignoring: %s" % (field, value))
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0.0:
            self._error("'%s' must be a non-negative number, ignoring: %s" % (field, value))
            return None
        return float(value)

    def resolve_tool(self, ctx):
        """The machine that makes this part, or None once the miss is reported.

        Reported rather than raised: a part whose tool does not resolve is still
        a part, and what breaks is only the command that needed the machine.
        """
        if self.tool is None or ctx is None:
            return None
        from .tool import AdditiveTool

        tool = ctx.get_tool(self.tool, quiet=True)
        if tool is None:
            self._error("the manufacturing tool is not found: %s" % self.tool)
            return None
        if self.method == METHOD_ADDITIVE and not isinstance(tool, AdditiveTool):
            self._error("'%s' is a '%s' tool, and this part is made additively" % (self.tool, tool.category))
            return None
        return tool

    def problems(self, ctx, extent=None) -> list:
        """Everything about this part's manufacturing that does not add up.

        A list of sentences, empty when it does, so that a caller can report all
        of them at once - which is what 'pc test' does with it. 'extent' is the
        part's own [x, y, z] in millimetres, when the caller has measured it;
        without it the build volume is not checked, because nothing else here
        needs the geometry.
        """
        found = []
        if self.method is None:
            return found
        tool = self.resolve_tool(ctx)
        if self.tool is not None and tool is None:
            return ["the manufacturing tool is not found: %s" % self.tool]
        if tool is None:
            return found

        from .tool import ADDITIVE_RANGES

        for field, unit in ADDITIVE_RANGES.items():
            value = self.settings.get(field)
            allowed = tool.range_of(field)
            if value is None or allowed is None:
                continue
            if not allowed.contains(value):
                found.append(
                    "%s is %s %s, and %s does %s..%s %s"
                    % (field, value, unit, self.tool, allowed.minimum, allowed.maximum, unit)
                )

        material = self.settings.get("material")
        if material is not None and tool.materials and material not in tool.materials:
            found.append("%s does not take %s (it takes %s)" % (self.tool, material, ", ".join(tool.materials)))

        over = tool.fits(extent)
        if over is not None:
            found.append("the part does not fit the build volume of %s (%s)" % (self.tool, over))
        return found

    def _method_string(self) -> str:
        if self.method == METHOD_ADDITIVE:
            return "additive"
        if self.method == METHOD_SUBTRACTIVE:
            return "subtractive"
        if self.method == METHOD_FORMING:
            return "forming"
        if self.method == METHOD_NONE:
            return "none"
        return "unknown"

    def info(self) -> dict:
        info = {"method": self._method_string()}
        if self.tool is not None:
            info["tool"] = self.tool
        if self.settings:
            info["settings"] = dict(self.settings)
        return info

    def __str__(self) -> str:
        return f"PartConfigManufacturing(method={self._method_string()})"
