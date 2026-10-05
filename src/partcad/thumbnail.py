#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A small picture of a shape, for a list of them.

The IDE's Build vs Buy table has a picture in front of every line item, and
there are as many line items as an assembly has distinct parts. A projection is
a sandbox process of its own, so drawing them anew every time the table is
opened is what would make it slow, and the pictures change only when the shapes
do. So each one is drawn once and kept in PartCAD's cache ('ctx.cache_renders'),
under the shape's own cache key - which changes whenever anything the geometry
is built from does - and the size it was drawn at.

The size is part of the key because it is part of the picture, not only of how
it is shown. An SVG scales, but its lines scale with it: a projection drawn with
the line weight a full-size render uses is a picture of hairlines at 64 pixels.
So the line weight is chosen for the size asked for, and a picture drawn for one
size is not the picture for another.

The SVG is otherwise the one 'pc render -t svg' writes, given the pixel size on
its root element so that whoever shows it gets the size it was drawn for.
"""

import os
import re
import tempfile

from . import logging as pc_logging

# Bumped whenever what is stored under a thumbnail key changes: a stale entry is
# then never looked up again rather than read back as if it were current.
THUMBNAIL_VERSION = 1

# The width of a line, in pixels of the picture, whatever its size.
LINE_PIXELS = 1.25

# The width the SVG projection is drawn at, before it is scaled to the size
# asked for (see 'render_svg.process', which scales the largest dimension of the
# projection to this many millimetres).
PROJECTION_SIZE = 512.0

_ROOT = re.compile(r"<svg\b[^>]*>", re.DOTALL)


def cache_key(width: int, height: int) -> str:
    return "thumbnail-svg-%dx%d-v%d" % (width, height, THUMBNAIL_VERSION)


def sized(svg: str, width: int, height: int) -> str:
    """The SVG with its root element saying how many pixels it is drawn at.

    The projection's own 'width'/'height' are in millimetres; the 'viewBox'
    stays, and 'preserveAspectRatio' keeps a long part long inside a square.
    """
    match = _ROOT.search(svg)
    if match is None:
        return svg
    root = match.group(0)
    root = re.sub(r'\s(width|height|preserveAspectRatio)="[^"]*"', "", root)
    root = root.replace(
        "<svg",
        '<svg width="%d" height="%d" preserveAspectRatio="xMidYMid meet"' % (width, height),
        1,
    )
    return svg[: match.start()] + root + svg[match.end() :]


async def svg_thumbnail_async(ctx, shape, width: int, height: int):
    """The shape's thumbnail, as SVG bytes, or None when it cannot be drawn."""
    width, height = max(1, int(width)), max(1, int(height))
    # Built first: the cache key of a shape means nothing until the files it is
    # built from have been read, and a shape that does not build has no picture.
    if await shape.get_wrapped(ctx) is None:
        return None

    cache = getattr(ctx, "cache_renders", None)
    key = cache_key(width, height)
    cacheable = cache is not None and shape.get_cacheable() and shape.hash is not None
    if cacheable:
        found = await cache.read_data_async(shape.hash, [key])
        if found.get(key):
            return found[key]

    with tempfile.TemporaryDirectory(prefix="partcad-thumbnail-") as directory:
        path = os.path.join(directory, "thumbnail.svg")
        await shape.render_async(
            ctx,
            "svg",
            filepath=path,
            # The projection is drawn PROJECTION_SIZE across and shown 'width'
            # across, so a line has to be that much wider to be LINE_PIXELS wide.
            line_weight=LINE_PIXELS * PROJECTION_SIZE / min(width, height),
        )
        if not os.path.exists(path):
            pc_logging.debug("No thumbnail was drawn for %s:%s" % (shape.project_name, shape.name))
            return None
        with open(path, encoding="utf-8") as f:
            data = sized(f.read(), width, height).encode("utf-8")

    if cacheable:
        await cache.write_data_async(shape.hash, {key: data})
    return data
