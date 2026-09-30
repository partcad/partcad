#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-12-22
#
# Licensed under Apache License, Version 2.0.
#


# Merge render configs (to override project's config with the part's config)
def render_cfg_merge(a: dict, b: dict, path=[]):
    for key in b:
        if key in a:
            if isinstance(a[key], dict) and isinstance(b[key], dict):
                a[key] = render_cfg_merge(a[key], b[key], path + [str(key)])
            if isinstance(a[key], list) and isinstance(b[key], list):
                a[key].extend(b[key])
            elif a[key] != b[key]:
                a[key] = b[key]
        else:
            a[key] = b[key]
    return a


# The named viewing directions of a 2D projection, and what each one is in the
# terms 'partcad.yaml' already uses: 'viewport_origin' is the point the shape is
# looked at from, 'viewport_up' is which way is up in the resulting picture.
#
# A name is nothing but shorthand for that pair, so that
#
#     pc render -t png --view front
#
# and
#
#     render:
#       png:
#         viewport_origin: [0, -100, 0]
#         viewport_up: [0, 0, 1]
#
# ask for the same picture. Keeping the CLI a naming of the configuration, and
# not a second way to say the same thing, is what lets a package pin the view it
# publishes and a caller override it for one run.
#
# PartCAD is Z-up, with +Y pointing away from whoever is looking at the front of
# a shape - which is what puts the front camera on -Y and leaves +X to the right
# of the front view. The distance is arbitrary (a viewport origin says which
# direction to look from, and the projection is scaled to fit whatever it is
# written into); it is spelled as 100 to match the wrapper's own defaults.
VIEWS = {
    "front": ((0, -100, 0), (0, 0, 1)),
    "back": ((0, 100, 0), (0, 0, 1)),
    "left": ((-100, 0, 0), (0, 0, 1)),
    "right": ((100, 0, 0), (0, 0, 1)),
    "top": ((0, 0, 100), (0, 1, 0)),
    # Up is -Y so that +X stays on the right, the way a bottom view is drawn:
    # the top view flipped about the horizontal axis rather than mirrored.
    "bottom": ((0, 0, -100), (0, -1, 0)),
    # Where a part is looked at from when nothing says otherwise - the
    # front-right-top corner. See 'builtin/render/render_svg.py', which is where
    # that default lives; naming it here is what makes it selectable again after
    # a package has configured something else.
    "iso": ((100, -100, 100), (0, 0, 1)),
}

VIEW_NAMES = tuple(VIEWS)


def _viewport_vector(name: str, value):
    """One viewport vector, as three floats, or a ValueError explaining why not."""
    # A string is iterable and three characters long often enough to matter:
    # '123' would otherwise come through as [1.0, 2.0, 3.0] and aim the camera
    # somewhere nobody asked for. The CLI parses 'X,Y,Z' into a list before it
    # gets here; anything still a string at this point is a client that did not.
    if isinstance(value, (str, bytes)):
        raise ValueError("%s must be three numbers (X, Y, Z), not a string: %r" % (name, value))
    try:
        vector = [float(component) for component in value]
    except (TypeError, ValueError):
        raise ValueError("%s must be three numbers, got: %r" % (name, value)) from None
    if len(vector) != 3:
        raise ValueError("%s must be three numbers (X, Y, Z), got %d: %r" % (name, len(vector), value))
    if not any(vector):
        raise ValueError("%s must not be the zero vector: it names a direction" % name)
    return vector


def resolve_viewport(view=None, viewport_origin=None, viewport_up=None) -> dict:
    """The viewport overrides one render request asks for, as export parameters.

    'view' names a direction from 'VIEWS'; the two vectors say it outright, and
    each of them replaces the one the name resolved to - so '--view top' can be
    tilted by giving an up vector alone, without spelling the pair out again. What comes back is merged into the
    request the implementation is handed, on top of the configuration - so an
    empty dict, which is what no arguments produce, changes nothing.

    Raises:
        ValueError: an unknown view name, or a vector that is not three numbers.
    """
    overrides = {}
    if view is not None:
        # Checked before the lookup: an unhashable value would raise TypeError
        # there, and only ValueError is turned into a usage error by the
        # callers. The CLI constrains this to a choice, but it is not the only
        # client - the editor extensions speak the protocol directly.
        if not isinstance(view, str) or view not in VIEWS:
            raise ValueError("Unknown view %r. Known views: %s" % (view, ", ".join(VIEW_NAMES)))
        origin, up = VIEWS[view]
        overrides["viewport_origin"] = list(origin)
        overrides["viewport_up"] = list(up)
    if viewport_origin is not None:
        overrides["viewport_origin"] = _viewport_vector("viewport_origin", viewport_origin)
    if viewport_up is not None:
        overrides["viewport_up"] = _viewport_vector("viewport_up", viewport_up)

    # An up vector along the line of sight names no orientation: there is no
    # rotation of the camera that puts it at the top of the picture. Both
    # vectors pass their own checks, so this is only visible once they are read
    # together - which is here, and only when this request settles both of them.
    # When one comes from the configuration instead, the pair is the
    # implementation's to reconcile and there is nothing to compare yet.
    if "viewport_origin" in overrides and "viewport_up" in overrides:
        origin = overrides["viewport_origin"]
        up = overrides["viewport_up"]
        cross = (
            origin[1] * up[2] - origin[2] * up[1],
            origin[2] * up[0] - origin[0] * up[2],
            origin[0] * up[1] - origin[1] * up[0],
        )
        if not any(cross):
            raise ValueError(
                "viewport_up %r is parallel to the direction the camera looks from (%r): "
                "it does not say which way is up in the picture" % (up, origin)
            )
    return overrides
