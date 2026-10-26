#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Pulling an assembly apart: which way each item goes, and how far.

Two things draw an assembly with its items apart, and they have to agree on
where each item goes:

  * an assembly instruction book, whose every step shows one item backed out of
    what it is joined to (see assembly_guide.py);
  * an ASSY assembly with ``exploded: true`` - an object-type parameter of the
    ``assy`` type, so ``logo;exploded=true`` is an object of its own, with a
    cache key of its own (see 'Assembly.exploded') - which is the whole
    assembly drawn that way.

Both ask this module the same question of each item: what it is joined to
('counterpart'), and which way and how far it backs out of that
('separation_async'). The direction is the joint's when there is one - the two
were mated face to face, so the item backs out along the normal of the port it
was connected by - and the line between the two centers otherwise. The distance
is what the connection says in ``exploded:``, in millimetres, or a fraction of
the larger of the two.

What the whole assembly adds is that the moves add up ('offsets_async'): an item
joined to an item that has itself been moved goes with it, the way pulling a
bolt out of a bracket already pulled off a frame leaves the bolt with the
bracket. An item joined to everything placed before it rather than to one item
backs out of where that group was assembled.

Only the assembly's own items move. One that is an assembly itself - a
sub-assembly, or a nested 'links:' list - moves as one piece, with everything
inside it where it was: a sub-assembly is something put together before it is
put in, and drawing it in pieces is asking for it to be exploded on its own.

Whatever is drawn against an item moves with it. Its ports do, wherever they are
read from - the ones '--with-internals' draws, and the ones a 'map:' makes the
assembly's own - because every reader takes the item's placement from one
answer ('Assembly.exploded_offsets_async', composed by 'moved').
"""

import asyncio
import math
from dataclasses import dataclass
from typing import Optional

from .geom import Location

# How far apart an exploded view pulls an item and what it is joined to, as a
# fraction of the largest dimension of the two, unless the connection says
# otherwise.
EXPLODED_FRACTION = 0.5

# What to space two items by when neither of them can be measured (an empty
# shape, or a runtime that failed to hand a bounding box back). Small enough to
# be harmless, large enough to be visible.
FALLBACK_EXPLODED_DISTANCE = 10.0

# The way an item backs out when nothing says otherwise: neither a joint nor two
# centers apart from each other.
DEFAULT_DIRECTION = (0.0, 0.0, 1.0)


@dataclass
class Separation:
    """Which way one item backs out of what it is joined to, and how far."""

    direction: tuple = DEFAULT_DIRECTION
    distance: float = FALLBACK_EXPLODED_DISTANCE
    # The line that shows the gap: from where the two meet to where the item
    # has moved to.
    gap: Optional[tuple] = None

    def offset(self) -> tuple:
        return tuple(self.direction[i] * self.distance for i in range(3))


def offset_location(offset) -> Location:
    """A move by 'offset', as the location an item's own is composed with."""
    return Location([list(offset), [0, 0, 1], 0])


def moved(location, offset):
    """Where an item placed at 'location' is drawn once it is moved by 'offset'.

    The move is composed in front of the item's own placement, so that what the
    item holds - its own items, its ports - moves with it, by the same amount.
    'location' is what an assembly records, a Location or its packed form, and
    None for an item nothing moved; it is handed back as it is when there is
    no move, so a caller that tells "not moved" from "moved to the origin"
    still can.
    """
    if offset is None or not any(offset):
        return location
    move = offset_location(offset)
    if location is None:
        return move
    return move * (location if isinstance(location, Location) else Location(location))


def counterpart_child(placed, child):
    """The one placed item 'child' is joined to, or None for the whole group placed so far.

    A child that names what it connects to is joined to that item alone, and the
    second item of an assembly to the first. Anything else is joined to
    everything placed before it, which is what whoever is putting the thing
    together has in their hands at that point.
    """
    target = (child.connection or {}).get("target")
    if target is not None:
        for candidate in placed:
            if candidate.name == target:
                return candidate
    if len(placed) == 1:
        return placed[0]
    return None


def counterpart(assembly, placed, child):
    """What 'child' is joined to, as (item, its name, where it is).

    The item, when it is one (see 'counterpart_child'). Otherwise the items
    placed so far, as an assembly in their own right - the same thing a filtered
    render is (see 'partcad.assembly_filter'): a view of an assembly made of some
    of its children, where the assembly put them. A declaration of its own,
    rather than this assembly's: a step is not the object, so it must not
    inherit the object's name, its placement or the file types configured for
    it.
    """
    one = counterpart_child(placed, child)
    if one is not None:
        return one.item, one.name or one.item.name, one.location or Location()

    from . import assembly_filter

    partial = assembly_filter.derive(
        assembly,
        placed,
        config={
            "name": "%s-step-%d" % (assembly.name or "assembly", len(placed)),
            "child": True,
        },
    )
    return partial, "the sub-assembly so far", Location()


async def separation_async(ctx, item, location, other, other_location, connection=None) -> Separation:
    """Which way 'item' at 'location' backs out of 'other' at 'other_location', and how far."""
    connection = connection or {}
    location = location or Location()

    # Both centers at once: each is a bounding box measured in a sandbox, and
    # neither is an input to the other.
    item_center, other_center = await asyncio.gather(
        placed_center(ctx, item, location),
        placed_center(ctx, other, other_location),
    )
    away = [item_center[i] - other_center[i] for i in range(3)]

    direction = normalized(connection.get("direction")) or normalized(away)
    if direction is None:
        direction = DEFAULT_DIRECTION
    # A port's normal is an axis, not a side: which end of it points out of the
    # material depends on how the port was declared. Take the end that moves the
    # item away from what it is being joined to, so that an exploded view always
    # pulls the two apart rather than pushing one through the other.
    if sum(direction[i] * away[i] for i in range(3)) < 0:
        direction = tuple(-value for value in direction)

    distance = connection.get("exploded")
    if distance is None:
        # Both bounding boxes were measured above and a shape remembers its own,
        # so this is two dictionary lookups in the common case; it is gathered
        # for the case where one of them could not be measured at all.
        dimensions = await asyncio.gather(
            item.get_max_dimension_async(ctx),
            other.get_max_dimension_async(ctx),
        )
        dimensions = [dimension for dimension in dimensions if dimension]
        distance = EXPLODED_FRACTION * max(dimensions) if dimensions else FALLBACK_EXPLODED_DISTANCE
    distance = float(distance)

    # The line that shows the gap runs from where the two meet to where the item
    # has been moved to. Without a joint to point at, it runs from the item's own
    # center, which is where it came from.
    start = connection.get("point") or item_center
    end = [start[i] + direction[i] * distance for i in range(3)]
    return Separation(direction=direction, distance=distance, gap=(list(start), end))


async def offsets_async(ctx, assembly, children=None) -> list:
    """How far each child of 'assembly' moves in its exploded view, as (x, y, z), in order.

    The first child stays where it is: there is nothing to back it out of. Every
    other one backs out of what it is joined to by its 'separation_async', on
    top of however far that has moved itself - so the moves add up along the
    connections and nothing is pushed into something that has already moved
    away. One joined to the group placed so far backs out of where the group was
    assembled, which is where the group's first item still is.
    """
    children = list(assembly.children if children is None else children)
    if len(children) < 2:
        return [(0.0, 0.0, 0.0)] * len(children)

    async def separation(index):
        child = children[index]
        other, _, other_location = counterpart(assembly, children[:index], child)
        return await separation_async(ctx, child.item, child.location, other, other_location, child.connection)

    # Each child's separation is measured where the assembly put it, so none of
    # them waits for another's.
    separations = await asyncio.gather(*[separation(index) for index in range(1, len(children))])

    offsets = [(0.0, 0.0, 0.0)]
    for index, found in enumerate(separations, start=1):
        child = children[index]
        one = counterpart_child(children[:index], child)
        # By identity: four legs of one table are four children equal in every
        # field but the one that says where each is.
        base = next((offsets[at] for at in range(index) if children[at] is one), (0.0, 0.0, 0.0))
        own = found.offset()
        offsets.append(tuple(base[i] + own[i] for i in range(3)))
    return offsets


async def placed_center(ctx, shape, location):
    """The center of a shape's bounding box, where the assembly puts it."""
    box = await shape.get_bounding_box_async(ctx)
    if box is None:
        center = (0.0, 0.0, 0.0)
    else:
        center = ((box[0] + box[3]) / 2.0, (box[1] + box[4]) / 2.0, (box[2] + box[5]) / 2.0)
    return location.transform_point(center) if location is not None else center


def normalized(vector):
    if not vector:
        return None
    length = math.sqrt(sum(float(value) ** 2 for value in vector))
    if length < 1e-9:
        return None
    return tuple(float(value) / length for value in vector)
