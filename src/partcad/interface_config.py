#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What an interface's 'parameters:' section holds, and how the two kinds are told apart.

An interface has declared **freedom of movement** in 'parameters:' since
interfaces existed: 'moveX', 'turnZ', a custom name with the 'dir' it moves
along. What it could not declare was what a part and a sketch declare in the
section of the same name - the **construction parameters** the object is built
from, which 'm-thru;size=4,depth=3' sets.

Both live in 'parameters:' now, because "the same way as for a part" is the
point of the feature and a second section would be a second thing to learn. They
are told apart by their own contents rather than by where they are written, and
the two vocabularies barely overlap: a freedom-of-movement parameter states a
range and an axis ('min', 'max', 'dir'), and a construction parameter states a
value type and a default ('type: float', 'enum', 'desc'). 'default' is the only
key both use, and 'type' is shared but with disjoint values.

So the rule is, in order:

1. One of the six predefined movement names ('moveX'/'moveY'/'moveZ',
   'turnX'/'turnY'/'turnZ', and the hyphenated spellings a 'mates:' section
   uses) is freedom of movement, whatever it looks like.
2. The short list form '[min, max, default]' is freedom of movement. A
   construction parameter has no list form on an interface: 'array' is not one
   of the types a parameter may declare.
3. A declaration stating 'min', 'max' or 'dir', or 'type: move'/'type: turn',
   is freedom of movement. None of those four keys means anything to a part's
   parameter.
4. Anything else is a construction parameter, read exactly as a part's.

Every freedom-of-movement parameter that PartCAD's schema has ever accepted is
caught by 1 or 3: a custom name is *required* to state its 'dir'. So a
declaration written before this existed keeps the meaning it had, and there is
no shape that could be read as either.
"""

from . import logging as pc_logging
from .config import apply_user_parameter_overrides, normalize_parameters

# The movement parameters that need no 'dir' because their axis is in their
# name. Both spellings: an interface's own 'parameters:' uses 'moveX' and a
# 'mates:' section uses 'move-x', and both have always been accepted.
MOVEMENT_PARAMETER_NAMES = frozenset(
    ["move%s" % axis for axis in "XYZ"]
    + ["turn%s" % axis for axis in "XYZ"]
    + ["move-%s" % axis for axis in "xyz"]
    + ["turn-%s" % axis for axis in "xyz"]
)

# The keys that only a freedom-of-movement parameter has, and the two values of
# 'type' that only it uses.
MOVEMENT_PARAMETER_KEYS = ("min", "max", "dir")
MOVEMENT_PARAMETER_TYPES = ("move", "turn")

# The name of the section both kinds are declared in - the same one a part and a
# sketch use, which is the whole point.
PARAMETERS = "parameters"

# An interface that is another interface under a different name.
ALIAS = "alias"


def is_movement_parameter(name: str, declaration) -> bool:
    """Whether this 'parameters:' entry is freedom of movement rather than a value.

    The rules in this module's docstring, in order.
    """
    if name in MOVEMENT_PARAMETER_NAMES:
        return True
    if isinstance(declaration, (list, tuple)):
        return True
    if isinstance(declaration, dict):
        if any(key in declaration for key in MOVEMENT_PARAMETER_KEYS):
            return True
        if declaration.get("type") in MOVEMENT_PARAMETER_TYPES:
            return True
    return False


def split_parameters(parameters: dict) -> tuple[dict, dict]:
    """One 'parameters:' section, as (freedom of movement, construction values)."""
    movement = {}
    construction = {}
    for name, declaration in (parameters or {}).items():
        if is_movement_parameter(name, declaration):
            movement[name] = declaration
        else:
            construction[name] = declaration
    return movement, construction


def movement_parameters(parameters: dict) -> dict:
    return split_parameters(parameters)[0]


def construction_parameters(parameters: dict) -> dict:
    return split_parameters(parameters)[1]


class InterfaceConfiguration:
    """Normalization of one interface declaration.

    Interfaces are not shapes - nothing constructs them, they have no factory
    and no cache - so they have no 'ShapeConfiguration'. What they do share with
    parts and sketches is the construction half of 'parameters:': the short
    forms ('size: 3') expand to the long one, and the user's own configuration
    gets to override a default. The freedom-of-movement half is left exactly as
    written; 'InterfaceParameter.config_normalize' is what expands that.
    """

    @staticmethod
    def normalize(name, config, object_name):
        if config is None:
            config = {}
        elif isinstance(config, str):
            # The short form of an alias, the same one a sketch and a part have:
            # "m3-thru-3: m-thru;size=3,depth=3" is the whole declaration.
            config = {ALIAS: config}

        config["name"] = name
        if "orig_name" not in config:
            config["orig_name"] = name

        declared = config.get(PARAMETERS)
        if isinstance(declared, list):
            # The short list form, '[moveX, moveY, turnZ]': names with no bounds,
            # which is how an interface says a connection may move along an axis
            # freely. Expanded here rather than where it is read, because there
            # is more than one reader now - 'split_parameters' sees this config
            # before 'Interface.__init__' does, and a list has no '.items()'.
            declared = {param_name: {} for param_name in declared}
            config[PARAMETERS] = declared
        if declared:
            movement, construction = split_parameters(declared)
            if construction:
                normalize_parameters(construction)
                declared.update(construction)
                # Overridden against the construction half only: the user's
                # 'parameters' configuration sets the values an object is built
                # with, and a freedom-of-movement range is not one of those.
                apply_user_parameter_overrides({PARAMETERS: construction}, object_name, PARAMETERS)
                declared.update(construction)
            for param_name in movement:
                pc_logging.debug("%s: '%s' is a freedom-of-movement parameter" % (object_name, param_name))

        return config
