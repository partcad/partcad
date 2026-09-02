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

import copy
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


class ToolRange:
    """What a machine can do along one axis of one property.

    A tool describes a machine, and a machine has a range rather than a value: a
    printer prints layers from 0.05 to 0.30mm, not "a 0.2mm layer". What a
    *part* asks for is one number inside that range, and 'contains()' is what
    says whether the two agree.

    'default' is the value the machine uses when nothing asks for one. It is
    optional and is not invented: a range with no default leaves the property
    unset, and what to do about that is the machine's own business rather than
    something PartCAD guesses.

    Four spellings, all of them the same thing:

        layerHeight: 0.2                       a fixed value
        layerHeight: [0.05, 0.30]              a range with no default
        layerHeight: [0.05, 0.30, 0.20]        a range with one
        layerHeight: {min: 0.05, max: 0.30, default: 0.20}
    """

    minimum: float
    maximum: float
    default: typing.Optional[float]

    def __init__(self, minimum: float, maximum: float, default=None):
        self.minimum = float(minimum)
        self.maximum = float(maximum)
        self.default = None if default is None else float(default)

    @staticmethod
    def parse(config, where: str, field: str, report=None):
        """A 'ToolRange' from any of the four spellings, or None if unusable."""

        def fail(message):
            if report is not None:
                report("'%s' %s, ignoring: %s" % (field, message, config))
            else:
                pc_logging.error("%s: '%s' %s, ignoring: %s" % (where, field, message, config))
            return None

        def number(value):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return None
            return float(value)

        if config is None:
            return None
        if isinstance(config, dict):
            values = [config.get(key) for key in ("min", "max", "default")]
            if config.get("min") is None or config.get("max") is None:
                return fail("needs both 'min' and 'max'")
            for key in config:
                if key not in ("min", "max", "default"):
                    return fail("takes only 'min', 'max' and 'default'")
        elif isinstance(config, (list, tuple)):
            if len(config) not in (2, 3):
                return fail("as a list is [min, max] or [min, max, default]")
            values = list(config) + [None] * (3 - len(config))
        else:
            single = number(config)
            if single is None:
                return fail("must be a number, a range or a [min, max] pair")
            values = [single, single, single]

        minimum, maximum, default = (None if value is None else number(value) for value in values)
        if minimum is None or maximum is None:
            return fail("must be numbers")
        if minimum > maximum:
            return fail("has a minimum above its maximum")
        if default is not None and not (minimum <= default <= maximum):
            return fail("has a default outside its own range")
        return ToolRange(minimum, maximum, default)

    def contains(self, value) -> bool:
        return self.minimum <= float(value) <= self.maximum

    def info(self):
        info = {"min": self.minimum, "max": self.maximum}
        if self.default is not None:
            info["default"] = self.default
        return info

    def __repr__(self):
        if self.minimum == self.maximum:
            return str(self.minimum)
        return "%s..%s" % (self.minimum, self.maximum)


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

    def properties_data(self) -> dict:
        """The same, under the names the configuration uses. Empty here.

        'properties_info' is for a person reading 'pc info'; this is for a
        program - a CAM plugin, which is handed the machine it is writing
        instructions for and has to find the fields where its own documentation
        says they are.
        """
        return {}

    def request_data(self) -> dict:
        """Everything a plugin is told about this tool.

        Plain data, under the configuration's own names, so that a plugin reads
        what the package author wrote rather than a translation of it.
        """
        data = {"name": self.name, "package": self.project_name, "category": self.category}
        if self.desc:
            data["desc"] = self.desc
        data.update(self.properties_data())
        return data

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

    def properties_data(self) -> dict:
        data = {}
        if self.mates:
            data["mates"] = list(self.mates)
        if self.force_min is not None:
            data["forceMin"] = self.force_min
        if self.force_max is not None:
            data["forceMax"] = self.force_max
        if self.torque_max:
            data["torqueMax"] = self.torque_max
        return data

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


# The additive properties a machine has a range for and a part asks for one
# value of. The name is the field on both sides, so the two are matched without
# a translation table; the unit is what the value is in, everywhere in PartCAD.
ADDITIVE_RANGES = {
    "layerHeight": "mm",
    "spotSize": "mm",
    "speed": "mm/s",
    "temperature": "C",
    "bedTemperature": "C",
}

# What a machine has to be told before it can put anything down: the sequence
# that gets the tool from wherever it was to a known point over the bed. Every
# one of these is what a G-code preamble is made of, and they are named for what
# they are rather than for the codes that carry them - a machine that homes with
# something other than G28 still homes.
POSITIONING_FIELDS = (
    "units",
    "absolute",
    "home",
    "homeFeedRate",
    "travelFeedRate",
    "safeZ",
    "origin",
    "bedLeveling",
    "prime",
)
POSITIONING_UNITS = ("mm", "inch")
BED_LEVELING = ("none", "auto", "mesh")
# The axes a machine may be told to home, in the order the sequence names them.
AXES = ("x", "y", "z")

# What the machine does with the material when it stops putting it down.
#
# A machine that can pull the filament back does not string between the places
# it prints; one that cannot leaves a thread behind on every travel move. That
# is a property of the extruder - a Bowden tube needs several millimetres where
# a direct drive needs a fraction of one - so it belongs to the machine and not
# to the part, exactly like 'positioning'.
#
# Declaring the section at all is the *capability*: a machine that says nothing
# here is one nothing may pull filament back on, which is the safe reading for a
# pellet extruder, a resin printer, or simply a machine nobody has measured yet.
# 'distance' is what makes it meaningful, so a section without one retracts
# nothing.
RETRACTION_FIELDS = (
    "distance",
    "feedRate",
    "zHop",
    "minTravel",
)


@telemetry.instrument()
class AdditiveTool(Tool):
    """A tool that puts material down: an extruder, a laser sintering a bed.

    Unlike a mechanical tool, this describes a *machine*, so what it states about
    itself are **ranges**: a printer prints layers from 0.05 to 0.30mm, and which
    of them a given part is printed at is that part's business (see the
    'manufacturing:' section of a part). 'ADDITIVE_RANGES' is the closed set of
    those properties, and a part's setting for one is checked against the range
    the machine gave.

    Three more are not ranges. 'process' names how the material is put down,
    'materials' what the machine can put down, and 'buildVolume' how much of it
    fits, as [x, y, z] in millimetres. 'stepSize' is the smallest move the
    machine can make on each axis - the resolution of its motion system, which is
    what says whether a feature is reachable at all.

    'positioning' is the initial sequence: what the machine has to be told before
    it can start, which is what a CAM plugin turns into the preamble of the file
    it writes. It is a closed set of named properties in PartCAD's own units
    (millimetres, mm/min for a feed rate, degrees Celsius), never the G-codes
    themselves - which machine dialect they become is the plugin's business.

    'retraction' is the same kind of thing for the other end of a move: what the
    machine pulls the material back by when it stops putting it down, so that it
    does not string across the gap. Declaring the section is the capability - a
    machine that says nothing there is one nothing retracts on.
    """

    process: typing.Optional[str]
    materials: list[str]
    build_volume: typing.Optional[list]
    step_size: typing.Optional[list]
    ranges: dict
    positioning: dict
    retraction: dict

    def __init__(self, project_name: str, config: dict[str, typing.Any] = {}) -> None:
        super().__init__(project_name, config)
        self.process = self._string("process")
        self.materials = self._materials()
        self.build_volume = self._extent("buildVolume")
        self.step_size = self._extent("stepSize")

        self.ranges = {}
        for field in ADDITIVE_RANGES:
            if field not in self.config:
                continue
            parsed = ToolRange.parse(self.config[field], self.project_name, field, report=self.error)
            if parsed is not None:
                self.ranges[field] = parsed

        self.positioning = self._positioning()
        self.retraction = self._retraction()

    def _materials(self) -> list:
        """What this machine can put down, as a list of material names.

        'material' in the singular is accepted as the one-entry form, because a
        machine that only takes one is the common case and naming it twice over
        is noise.
        """
        declared = _as_list(self.config.get("materials", None)) or _as_list(self.config.get("material", None))
        materials = []
        for material in declared:
            if not isinstance(material, str) or not material.strip():
                self.error("'materials' must name materials, ignoring: %s" % (material,))
                continue
            if material.strip() not in materials:
                materials.append(material.strip())
        return materials

    def _extent(self, field):
        """A three-number [x, y, z] in millimetres, or None."""
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

    def _positioning(self) -> dict:
        """The initial sequence, validated field by field.

        A field PartCAD cannot read is dropped rather than carried: what this
        section is for is being handed to a CAM plugin, and a plugin that is
        handed something it cannot act on writes a preamble that does not do what
        the package said.
        """
        section = self.config.get("positioning", None)
        if section is None:
            return {}
        if not isinstance(section, dict):
            self.error("'positioning' must be a section, ignoring: %s" % (section,))
            return {}

        positioning = {}
        for field, value in section.items():
            if field not in POSITIONING_FIELDS:
                self.error("unknown 'positioning' field, ignoring: %s" % field)
                continue
            resolved = self._positioning_field(field, value)
            if resolved is not None:
                positioning[field] = resolved
        return positioning

    def _positioning_field(self, field, value):
        if field == "units":
            if value in POSITIONING_UNITS:
                return value
            self.error("'positioning.units' must be one of %s, ignoring: %s" % (list(POSITIONING_UNITS), value))
            return None
        if field == "absolute":
            if isinstance(value, bool):
                return value
            self.error("'positioning.absolute' must be true or false, ignoring: %s" % (value,))
            return None
        if field == "bedLeveling":
            if value in BED_LEVELING:
                return value
            self.error("'positioning.bedLeveling' must be one of %s, ignoring: %s" % (list(BED_LEVELING), value))
            return None
        if field == "home":
            axes = []
            for axis in _as_list(value):
                if not isinstance(axis, str) or axis.lower() not in AXES:
                    self.error("'positioning.home' names axes (%s), ignoring: %s" % (", ".join(AXES), axis))
                    return None
                axes.append(axis.lower())
            return axes
        if field == "origin":
            return self._origin(value)
        if field == "prime":
            return self._prime(value)
        # The three feed rates and the safe height: plain non-negative numbers.
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0.0:
            self.error("'positioning.%s' must be a non-negative number, ignoring: %s" % (field, value))
            return None
        return float(value)

    def _origin(self, value):
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            self.error("'positioning.origin' must be [x, y, z] in millimetres, ignoring: %s" % (value,))
            return None
        origin = []
        for item in value:
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                self.error("'positioning.origin' must be three numbers, ignoring: %s" % (value,))
                return None
            origin.append(float(item))
        return origin

    def _prime(self, value):
        """The purge line a machine draws before the first layer, or None."""
        if not isinstance(value, dict):
            self.error("'positioning.prime' must be a section, ignoring: %s" % (value,))
            return None
        prime = {}
        for field, item in value.items():
            if field not in ("length", "extrude", "feedRate"):
                self.error("unknown 'positioning.prime' field, ignoring: %s" % field)
                continue
            if isinstance(item, bool) or not isinstance(item, (int, float)) or item < 0.0:
                self.error("'positioning.prime.%s' must be a non-negative number, ignoring: %s" % (field, item))
                continue
            prime[field] = float(item)
        return prime or None

    def _retraction(self) -> dict:
        """What this machine pulls back, and how, or nothing.

        Empty where the section is absent, and empty where it is present but
        says no distance: both mean the same thing to whoever writes the
        instructions - do not retract - and collapsing them here saves every
        plugin from deciding it again.
        """
        section = self.config.get("retraction", None)
        if section is None:
            return {}
        if not isinstance(section, dict):
            self.error("'retraction' must be a section, ignoring: %s" % (section,))
            return {}

        retraction = {}
        for field, value in section.items():
            if field not in RETRACTION_FIELDS:
                self.error("unknown 'retraction' field, ignoring: %s" % field)
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0.0:
                self.error("'retraction.%s' must be a non-negative number, ignoring: %s" % (field, value))
                continue
            retraction[field] = float(value)

        if not retraction.get("distance"):
            if retraction:
                self.error("'retraction' says no 'distance', so nothing is pulled back: %s" % (section,))
            return {}
        return retraction

    @property
    def retracts(self) -> bool:
        """Whether this machine pulls the material back when it stops."""
        return bool(self.retraction)

    def range_of(self, field: str) -> typing.Optional[ToolRange]:
        """What this machine can do for one of 'ADDITIVE_RANGES', or None."""
        return self.ranges.get(field)

    def fits(self, extent) -> typing.Optional[str]:
        """Why an [x, y, z] does not fit the build volume, or None if it does.

        The part is not turned to make it fit: which way up something is printed
        decides how it is supported and how strong it comes out, so it is the
        package's choice and not something to work around here.
        """
        if self.build_volume is None or extent is None:
            return None
        over = [
            "%s: %.1fmm > %.1fmm" % (axis, size, limit)
            for axis, size, limit in zip("XYZ", extent, self.build_volume)
            if size > limit
        ]
        return None if not over else ", ".join(over)

    def properties_data(self) -> dict:
        data = {}
        if self.process is not None:
            data["process"] = self.process
        if self.materials:
            data["materials"] = list(self.materials)
        if self.build_volume is not None:
            data["buildVolume"] = list(self.build_volume)
        if self.step_size is not None:
            data["stepSize"] = list(self.step_size)
        for field, allowed in self.ranges.items():
            # With the unit spelled out. A plugin writes a file for a machine
            # that has its own idea of what a number means - a feed rate in
            # mm/min where PartCAD said mm/s - and converting it is the plugin's
            # job, which it cannot do without being told which is which.
            data[field] = dict(allowed.info(), unit=ADDITIVE_RANGES[field])
        if self.positioning:
            data["positioning"] = copy.deepcopy(self.positioning)
        if self.retraction:
            data["retraction"] = dict(self.retraction)
        return data

    def properties_info(self) -> dict:
        info = {}
        if self.process is not None:
            info["Process"] = self.process
        if self.materials:
            info["Materials"] = list(self.materials)
        if self.build_volume is not None:
            info["BuildVolume"] = list(self.build_volume)
        if self.step_size is not None:
            info["StepSize"] = list(self.step_size)
        for field, unit in ADDITIVE_RANGES.items():
            if field in self.ranges:
                info[field[0].upper() + field[1:]] = dict(self.ranges[field].info(), unit=unit)
        if self.positioning:
            info["Positioning"] = dict(self.positioning)
        if self.retraction:
            info["Retraction"] = dict(self.retraction)
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

    def properties_data(self) -> dict:
        data = {}
        for field, value in (
            ("process", self.process),
            ("diameter", self.diameter),
            ("length", self.length),
            ("flutes", self.flutes),
            ("spindleSpeedMax", self.spindle_speed_max),
            ("feedRateMax", self.feed_rate_max),
        ):
            if value is not None:
                data[field] = value
        return data

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
