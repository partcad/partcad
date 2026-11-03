#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The viewing angle options, shared by every command that writes a projection.

`pc render` and `pc adhoc render` offer the same four, and have to: a viewport
is a property of the projection, not of where the shape came from, and a user
who has learned `--view top` in one should not find it spelled differently in
the other. The fourth, `--turn`, is how the object stands in front of the
camera the other three place: turned about its own axes, the way the 3D view's
Animate turns it and a video's frames do.

Only the *names* of the views live here, for `--help` and for rejecting a typo
without a round trip to the daemon - the same reason `adhoc/convert/part.py`
inlines its type lists. What each name means is `partcad.render.VIEWS`, which is
what resolves them, on the daemon side where the heavy package already is.
"""

import rich_click as click

VIEW_NAMES = ["front", "back", "left", "right", "top", "bottom", "iso"]


def viewport_vector(ctx, param, value):
    """Parse 'X,Y,Z' into three floats, the way a viewport vector is written.

    Rejected here rather than on the daemon so that a typo costs a message and
    not a round trip. The daemon checks the same things anyway: it also serves
    the editor extensions, which do not come through this parser.
    """
    if value is None:
        return None

    def refuse(reason):
        return click.BadParameter("%s: %s" % (reason, value), ctx=ctx, param=param)

    try:
        vector = [float(component) for component in value.replace(",", " ").split()]
    except ValueError:
        raise refuse("expected three numbers as 'X,Y,Z'") from None
    if len(vector) != 3:
        raise refuse("expected three numbers as 'X,Y,Z', got %d" % len(vector)) from None
    if not any(vector):
        raise refuse("must not be the zero vector, it names a direction") from None
    return vector


def turn_vector(ctx, param, value):
    """Parse 'X,Y,Z' degrees into three floats; one number is a turn about Z alone.

    Also what '--speed' of a video is read with: degrees a second about the same
    three axes.
    """
    if value is None:
        return None
    try:
        vector = [float(component) for component in value.replace(",", " ").split()]
    except ValueError:
        raise click.BadParameter("expected 'X,Y,Z' or one number, got: %s" % value, ctx=ctx, param=param) from None
    if len(vector) == 1:
        return [0.0, 0.0, vector[0]]
    if len(vector) != 3:
        raise click.BadParameter("expected 'X,Y,Z' or one number, got: %s" % value, ctx=ctx, param=param)
    return vector


_OPTIONS = (
    click.option(
        "--view",
        help=(
            "Look at the object from a named direction for this run: "
            "front, back, left, right, top, bottom or iso. "
            "Shorthand for the '--viewport-origin'/'--viewport-up' pair below, and so for the "
            "'viewport_origin'/'viewport_up' of a render file type in 'partcad.yaml'"
        ),
        type=click.Choice(VIEW_NAMES),
        show_envvar=True,
    ),
    click.option(
        "--viewport-origin",
        help="Where the object is looked at from, as 'X,Y,Z'. Overrides '--view' and the configuration",
        type=str,
        callback=viewport_vector,
        show_envvar=True,
    ),
    click.option(
        "--viewport-up",
        help="Which way is up in the projection, as 'X,Y,Z'. Overrides '--view' and the configuration",
        type=str,
        callback=viewport_vector,
        show_envvar=True,
    ),
    click.option(
        "--turn",
        help=(
            "Turn the object in front of the camera by 'X,Y,Z' degrees about its own axes, through its "
            "middle - or by one number, about Z, as the 3D view's Animate turns it. Goes with any view: "
            "'--view front --turn 0,0,45'. A video's frame at a given moment is the picture of that turn"
        ),
        type=str,
        callback=turn_vector,
        show_envvar=True,
    ),
)


def viewport_options(command):
    """Add '--view', '--viewport-origin', '--viewport-up' and '--turn' to a command.

    Applied in reverse because click reverses the parameters it collected, which
    is what makes them read in this order in '--help'.
    """
    for option in reversed(_OPTIONS):
        command = option(command)
    return command


def viewport_params(view, viewport_origin, viewport_up, turn=None):
    """The four as JSON-RPC params, so every caller sends the same names."""
    return {
        "view": view,
        "viewport_origin": viewport_origin,
        "viewport_up": viewport_up,
        "turn": turn,
    }
