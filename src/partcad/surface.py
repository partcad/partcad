#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Which parts are surfaces on purpose, and what that excuses them from.

PartCAD's rule is that a part is a body and not a skin (see "A part is a body,
not a skin" in AGENTS.md): a shell is a set of faces with nothing said about
which side of them is material, nothing downstream of a boolean can compute
with one, and so a closed shell is turned into the solid it bounds and an open
one is reported. No object can switch any of that off for itself.

A *kind* of object can be exempt, on what it is - a sketch is not measured for
having size in every direction, because a drawing is flat - and this is the one
other kind: a part whose type builds a surface because a surface is what it is
for. A wall drawn to lay out a room is a sheet of faces seen from one side,
with no thickness, nothing inside it and nothing anybody will make out of it;
reporting it for being a skin would be reporting it for being a wall.

What such a part is, it is by its *type*, decided here and in no declaration:

  * it is never manufacturable, and says so - its declaration, or its package,
    states 'manufacturable: false', and a type in 'SURFACE_PART_TYPES' refuses a
    part that does not (see 'PartFactoryWall');
  * it leaves its factory as it was built: no closed shell of it is turned into
    a solid, and it is not judged for not being one ('Shape.finish_request');
  * it is drawn one-sided, from the side its faces look to: it reports
    'oneSided: true' among its properties ('Shape._shape_properties'), an alias
    of it included, which is what everything that draws it reads;
  * the checks that ask whether a part is a body - 'shell', 'degenerate',
    'solidity' - and 'manufacturability' pass over it as inapplicable, naming
    why; and an assembly that is to be made fails on it, because a surface
    cannot be made whatever the assembly around it says.

The test is on the declaration a part *resolves to* ('shape_config
.final_config'), so an alias of a wall, or an enrich of one, is a wall too.
"""

from .shape_config import final_config

# What a surface part reports among its properties, whatever reference it is
# reached through: drawn from the front of its faces only, and see-through from
# behind (see 'wrappers/appearance.py' and the IDE's 'appearance.ts').
ONE_SIDED_KEY = "oneSided"

# The part types that build a surface on purpose. Adding one is a decision
# about what that type is, not about any one part: see the module docstring.
SURFACE_PART_TYPES = frozenset({"wall"})

# Why a check that asks whether a part is a body does not ask it of one of these.
NOT_A_BODY = "it is a surface by its type ('%s'): one-sided faces with no body to them, and never manufactured"


def surface_type(shape):
    """The surface part type 'shape' resolves to, or None if it is not a surface part.

    Asked of anything: a sketch, an assembly or a scene is never one, and a part
    is one when the declaration it resolves to - its own, or what an alias or an
    enrich points at - names a type in 'SURFACE_PART_TYPES'.
    """
    if getattr(shape, "kind", None) != "part":
        return None
    config = final_config(shape)
    if not isinstance(config, dict):
        return None
    kind = config.get("type")
    return kind if kind in SURFACE_PART_TYPES else None


def is_surface(shape) -> bool:
    """Whether 'shape' is a part that is a surface by its type (see 'surface_type')."""
    return surface_type(shape) is not None


def not_a_body(shape):
    """Why 'shape' is passed over by a check that asks whether a part is a body, or None if it is not."""
    kind = surface_type(shape)
    if kind is None:
        return None
    return NOT_A_BODY % kind
