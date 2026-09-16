#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-13
#
# Licensed under Apache License, Version 2.0.
#

from . import logging as pc_logging

METHOD_NONE: None = None
# Note: The assigned numbers are used in APIs and must never change unless the old method is deprecated.
METHOD_ADDITIVE: int = 100
METHOD_SUBTRACTIVE: int = 200
METHOD_FORMING: int = 300
METHOD_SHEET_METAL: int = 400

# These are ways of making a part, and a part only: an assembly is put together
# rather than made, and has its own single method (see AssemblyConfigManufacturing).
_METHOD_MAP: dict[str, int] = {
    "additive": METHOD_ADDITIVE,
    "subtractive": METHOD_SUBTRACTIVE,
    "forming": METHOD_FORMING,
    "sheet_metal": METHOD_SHEET_METAL,
}

_METHOD_NAMES: dict[int, str] = {value: name for name, value in _METHOD_MAP.items()}

# What a sheet metal part has to say beyond naming the method, and what each of
# them is.
#
# Bending is not something done to a block of stock: it is done to a flat piece
# that already has its outline and its holes, and the result is that piece in
# another shape. So the declaration names two things rather than describing one:
#
# * 'source' - the part that goes into the brake. It is a part rather than a
#   drawing because it is a part: somebody makes it, it has a thickness, a
#   material and a tolerance, and it is manufactured by a process of its own
#   (see the documentation - it is expected to be subtractive: laser cut,
#   waterjet, routed).
# * 'instructions' - the sketch that says where the bends are and what each of
#   them is. A sketch rather than a file, so that what states it is PartCAD's
#   own object and not one format (see 'Sketch.get_annotations'); the sketch's
#   own layer parameters pick the bend layers out of a drawing that also holds
#   the outline: 'instructions: bends;include=BEND_UP,BEND_DOWN'.
#
# Both are references, resolved against the package the part is declared in like
# every other reference a part makes.
SHEET_METAL_REQUIRED = ("source", "instructions")


class PartConfigManufacturing:
    method: int | None

    # The part that is worked on, and the sketch that says how, for the methods
    # that are defined in terms of another object. None for every other method,
    # which describes a part made from stock and has nothing to point at.
    source: str | None
    instructions: str | None

    def __init__(self, final_config: dict) -> None:
        manufacturing_config = final_config.get("manufacturing", {}) or {}
        method_string = manufacturing_config.get("method", None)
        self.method = _METHOD_MAP.get(method_string, METHOD_NONE)
        if self.method == METHOD_NONE and method_string is not None:
            pc_logging.error(
                f"Unknown manufacturing method '{method_string}'. Supported methods: {list(_METHOD_MAP.keys())}."
            )
        self.source = manufacturing_config.get("source", None)
        self.instructions = manufacturing_config.get("instructions", None)

    def missing_fields(self) -> list[str]:
        """What this method needs that the declaration does not state.

        Read rather than raised on, because a declaration is judged where the
        judging is done: 'pc test' reports it against the one part, while
        loading a package must not fail over it - a part whose 'manufacturing:'
        section is incomplete is still a part, and everything that is not about
        making it goes on working.

        Empty for every method that needs nothing beyond its own name.
        """
        if self.method != METHOD_SHEET_METAL:
            return []
        return [field for field in SHEET_METAL_REQUIRED if not getattr(self, field, None)]

    def _method_string(self) -> str:
        if self.method in _METHOD_NAMES:
            return _METHOD_NAMES[self.method]
        if self.method == METHOD_NONE:
            return "none"
        return "unknown"

    def __str__(self) -> str:
        return f"PartConfigManufacturing(method={self._method_string()})"
