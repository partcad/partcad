#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The 'tools' a package declares: what a product is made *with*.

A part is what the product is made of; a tool is what somebody (or something)
holds while making it. A finger, a screwdriver, a 3D printer's extruder and an
end mill are all tools, and what they have in common is that none of them ends
up in the bill of materials: a tool acts on the product and then goes back in
the drawer.

Two things separate 'tools:' from every other section of 'partcad.yaml'.

  * It does not enumerate its objects directly. It holds one sub-section per
    **category** ('mechanical', 'additive', 'subtractive'), and the objects go
    inside those, so a tool never has to repeat what kind of tool it is and a
    package's tools read as the groups they belong to. The sub-section name
    becomes the 'category' property of every tool declared in it (see
    'Project._tool_configs').

  * The category decides the *class*: what a mechanical tool has to say about
    itself (what it grips, how hard, how much torque) is nothing like what an
    additive one has to (which process, which material, how fine a layer). They
    are subclasses of the one 'Tool' below rather than one class with every
    field of all three, so that a property means the same thing wherever it is
    read, and so that a fourth category is a class rather than another handful
    of fields nobody else uses.

Every tool carries a 'visual': a reference to a part that *stands for* the tool
in a picture. It is only ever a likeness - the assembly instruction book puts it
where the tool would be so that a step shows the hands and the driver, not two
bare shapes floating apart - so it is never manufactured, never ordered and
never counted, and the part it points at does not have to be manufacturable.
"""

import typing

from . import logging as pc_logging
from . import telemetry
from .utils import normalize_resource_path, resolve_resource_path

# The categories a tool may be declared under. Each is a sub-section of
# 'tools:', and each has a class of its own below.
CATEGORY_MECHANICAL = "mechanical"
CATEGORY_ADDITIVE = "additive"
CATEGORY_SUBTRACTIVE = "subtractive"
CATEGORIES = (CATEGORY_MECHANICAL, CATEGORY_ADDITIVE, CATEGORY_SUBTRACTIVE)


def _as_list(value) -> list:
    """A scalar-or-list configuration value as a list."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [item for item in value if item is not None]
    return [value]


@telemetry.instrument()
class Tool:
    """One tool of a package.

    Deliberately not a 'Shape': a tool has no geometry of its own. What can be
    drawn is the part its 'visual' points at, and that is a part like any other
    - fetched, built and cached by the machinery that already exists for parts.
    """

    name: str
    project_name: str
    desc: str
    kind: str = "tool"
    category: str = None
    config: dict[str, typing.Any]
    visual: typing.Optional[str] = None
    url: typing.Optional[str] = None
    errors: list[str]

    def __init__(self, project_name: str, config: dict[str, typing.Any] = {}) -> None:
        self.project_name = project_name
        self.config = config
        self.name = config["name"]
        # Stripped the way 'Shape' and 'Software' strip theirs: a folded YAML
        # scalar ends with a newline, and that newline reaches a generated
        # README as a trailing line break inside a table cell.
        desc = config.get("desc", "")
        self.desc = desc.strip() if isinstance(desc, str) else desc
        self.category = config.get("category", None)
        self.url = config.get("url", None)
        self.errors = []

        # Resolved here, against the package that *declared* the tool, because
        # this is the only place that knows which package that is: a bare
        # 'finger' means the finger of this package wherever the tool is later
        # read from.
        visual = config.get("visual", None)
        if visual is None:
            self.visual = None
            self.error("no 'visual': there is nothing to draw where this tool acts")
        elif not isinstance(visual, str) or not visual.strip():
            self.visual = None
            self.error("'visual' must be the name of a part, ignoring: %s" % (visual,))
        else:
            self.visual = normalize_resource_path(project_name, visual.strip())

    def error(self, msg: str) -> None:
        self.errors.append(msg)
        pc_logging.error("%s: %s: %s" % (self.project_name, self.name, msg))

    def _number(self, field, minimum=0.0):
        """A numeric property of this tool, or None if it is absent or unusable."""
        value = self.config.get(field, None)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            self.error("'%s' must be a number, ignoring: %s" % (field, value))
            return None
        if minimum is not None and value < minimum:
            self.error("'%s' must not be below %s, ignoring: %s" % (field, minimum, value))
            return None
        return float(value)

    def _string(self, field):
        value = self.config.get(field, None)
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            self.error("'%s' must be a non-empty string, ignoring: %s" % (field, value))
            return None
        return value.strip()

    def get_visual(self, ctx):
        """The part that stands for this tool in a picture, or None.

        Never manufactured, never ordered and never counted: whoever draws it
        places it where the tool acts and throws the result away. A visual that
        does not resolve is reported once, here, and costs the picture its tool
        rather than failing whatever asked for it.
        """
        if self.visual is None or ctx is None:
            return None
        part = ctx.get_part(self.visual)
        if part is None:
            self.error("the 'visual' part is not found: %s" % self.visual)
        return part

    def tool_info(self) -> dict:
        """What this tool is, as the '<label>: <value>' pairs 'pc info' prints."""
        info = {
            "Path": self.project_name,
            "Category": self.category,
        }
        if self.desc:
            info["Desc"] = self.desc
        if self.visual is not None:
            info["Visual"] = self.visual
        if self.url is not None:
            info["Url"] = self.url
        info.update(self.properties_info())
        if self.errors:
            info["Errors"] = list(self.errors)
        return info

    def properties_info(self) -> dict:
        """What this *kind* of tool adds to 'pc info'. Empty for the base class."""
        return {}

    def info(self) -> dict:
        """The default, replaced by the factory that created this object."""
        return self.tool_info()

    def matches(self, keyword: str) -> bool:
        if not keyword:
            return False
        keyword = keyword.lower()
        return keyword in self.name.lower() or keyword in str(self.config).lower()


@telemetry.instrument()
class MechanicalTool(Tool):
    """A tool that holds, turns or presses something: a finger, a driver, a clamp.

    This is the category an assembly step can name. 'mates' is what makes that
    work without spelling every port out: it lists the interfaces the tool meets
    an object through, so an ASSY file that asks to be held with a finger and
    says nothing else gets every place on the object a finger fits.

    'forceMin'/'forceMax' bound what the tool can press with, in newtons, and
    'torqueMax' what it can turn with, in newton-metres. A tool that cannot turn
    anything leaves 'torqueMax' at zero, and that is exactly what disqualifies
    it from being a connection's 'driver' - a finger is not a screwdriver.
    """

    mates: list[str]
    force_min: typing.Optional[float]
    force_max: typing.Optional[float]
    torque_max: float

    def __init__(self, project_name: str, config: dict[str, typing.Any] = {}) -> None:
        super().__init__(project_name, config)

        # Interface references, resolved against the declaring package for the
        # same reason 'visual' is.
        self.mates = []
        for mate in _as_list(config.get("mates", None)):
            if not isinstance(mate, str) or not mate.strip():
                self.error("'mates' must list interface names, ignoring: %s" % (mate,))
                continue
            resolved = normalize_resource_path(project_name, mate.strip())
            if resolved not in self.mates:
                self.mates.append(resolved)

        self.force_min = self._number("forceMin")
        self.force_max = self._number("forceMax")
        if self.force_min is not None and self.force_max is not None and self.force_min > self.force_max:
            self.error("'forceMin' is above 'forceMax' (%s > %s), ignoring both" % (self.force_min, self.force_max))
            self.force_min = None
            self.force_max = None

        torque_max = self._number("torqueMax")
        self.torque_max = 0.0 if torque_max is None else torque_max

    def can_drive(self) -> bool:
        """Whether this tool can turn what it holds, and so be a 'driver'."""
        return self.torque_max > 0.0

    def properties_info(self) -> dict:
        info = {}
        if self.mates:
            info["Mates"] = list(self.mates)
        if self.force_min is not None:
            info["ForceMin"] = self.force_min
        if self.force_max is not None:
            info["ForceMax"] = self.force_max
        if self.torque_max:
            info["TorqueMax"] = self.torque_max
        return info


@telemetry.instrument()
class AdditiveTool(Tool):
    """A tool that puts material down: an extruder, a laser sintering a bed.

    'process' names how ('fdm', 'sla', 'sls', 'dmls', ...), 'material' what,
    'layerHeight' and 'spotSize' how finely - the layer in millimetres and the
    width of what the tool lays down in one pass - and 'buildVolume' how much of
    it fits, as [x, y, z] in millimetres.
    """

    process: typing.Optional[str]
    material: typing.Optional[str]
    layer_height: typing.Optional[float]
    spot_size: typing.Optional[float]
    build_volume: typing.Optional[list]

    def __init__(self, project_name: str, config: dict[str, typing.Any] = {}) -> None:
        super().__init__(project_name, config)
        self.process = self._string("process")
        self.material = self._string("material")
        self.layer_height = self._number("layerHeight")
        self.spot_size = self._number("spotSize")
        self.build_volume = self._extent("buildVolume")

    def _extent(self, field):
        value = self.config.get(field, None)
        if value is None:
            return None
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            self.error("'%s' must be [x, y, z] in millimetres, ignoring: %s" % (field, value))
            return None
        extent = []
        for item in value:
            if isinstance(item, bool) or not isinstance(item, (int, float)) or item < 0.0:
                self.error("'%s' must be three non-negative numbers, ignoring: %s" % (field, value))
                return None
            extent.append(float(item))
        return extent

    def properties_info(self) -> dict:
        info = {}
        if self.process is not None:
            info["Process"] = self.process
        if self.material is not None:
            info["Material"] = self.material
        if self.layer_height is not None:
            info["LayerHeight"] = self.layer_height
        if self.spot_size is not None:
            info["SpotSize"] = self.spot_size
        if self.build_volume is not None:
            info["BuildVolume"] = list(self.build_volume)
        return info


@telemetry.instrument()
class SubtractiveTool(Tool):
    """A tool that takes material away: an end mill, a drill, a laser cutting.

    'process' names how ('milling', 'turning', 'drilling', 'laser', 'waterjet',
    'edm', ...), 'diameter' and 'length' the cutting geometry in millimetres,
    'flutes' how many cutting edges it has, and 'spindleSpeedMax' /
    'feedRateMax' what it may be run at (rpm and mm/min).
    """

    process: typing.Optional[str]
    diameter: typing.Optional[float]
    length: typing.Optional[float]
    flutes: typing.Optional[int]
    spindle_speed_max: typing.Optional[float]
    feed_rate_max: typing.Optional[float]

    def __init__(self, project_name: str, config: dict[str, typing.Any] = {}) -> None:
        super().__init__(project_name, config)
        self.process = self._string("process")
        self.diameter = self._number("diameter")
        self.length = self._number("length")
        self.flutes = self._count("flutes")
        self.spindle_speed_max = self._number("spindleSpeedMax")
        self.feed_rate_max = self._number("feedRateMax")

    def _count(self, field):
        value = self.config.get(field, None)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            self.error("'%s' must be a positive whole number, ignoring: %s" % (field, value))
            return None
        return value

    def properties_info(self) -> dict:
        info = {}
        if self.process is not None:
            info["Process"] = self.process
        if self.diameter is not None:
            info["Diameter"] = self.diameter
        if self.length is not None:
            info["Length"] = self.length
        if self.flutes is not None:
            info["Flutes"] = self.flutes
        if self.spindle_speed_max is not None:
            info["SpindleSpeedMax"] = self.spindle_speed_max
        if self.feed_rate_max is not None:
            info["FeedRateMax"] = self.feed_rate_max
        return info


# The class each category is served by. The one place that says so: the factory
# dispatch is keyed on the category, and so is everything that has to know what
# a tool of a given category can be asked.
TOOL_CLASSES = {
    CATEGORY_MECHANICAL: MechanicalTool,
    CATEGORY_ADDITIVE: AdditiveTool,
    CATEGORY_SUBTRACTIVE: SubtractiveTool,
}


def lookup(ctx, ref: str, quiet: bool = False):
    """The (package, tool) a fully qualified reference points at.

    Both are None when the reference resolves to nothing. Reported here, once,
    rather than by each caller, exactly as 'software.lookup' does it: an
    assembly step and a generated document ask the same question and a
    reference that does not resolve is the same mistake either way.
    """
    package_name, name = resolve_resource_path("", ref)
    project = ctx.get_project(package_name) if ctx is not None else None
    if project is None:
        if not quiet:
            pc_logging.error("The tool '%s' is not found: no such package" % ref)
        return None, None
    tool = project.get_tool(name, quiet=quiet)
    if tool is None:
        # 'get_tool' has already said why, unless it was asked not to.
        return project, None
    return project, tool
