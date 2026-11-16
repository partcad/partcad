#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc req add port OBJECT NAME` -- a port the object has to have, and as much of where it is as matters.

    pc req add port bracket top                                   # only that it is there
    pc req add port bracket top --direction 0 0 -1                # and that it faces down
    pc req add port bracket top --position null null '>=5' --angle 90 --boundary m3-hole

Written as `requirements: ports: <NAME>:`, a mapping of what was said and
nothing else: every part of a location left out is no requirement on it.
`--boundary` is the port's `sketch:`, named apart from `--sketch`, which says
that OBJECT is a sketch.
"""

import rich_click as click

from .... import object_kind
from ....requirement_args import (
    add,
    location,
    location_options,
    object_options,
    object_params,
    read_stdin,
    refuse_both,
    replace_option,
    stdin_options,
    value,
)


@click.command(help="Require a port of OBJECT: NAME, and as much of where it is as matters. " + object_kind.LOOKED_UP)
@object_options
@replace_option
@stdin_options
@location_options
@click.option(
    "--boundary", type=str, default=None, metavar="SKETCH", help="The sketch its boundary is drawn with ('sketch:')"
)
@click.argument("object", type=str)
@click.argument("name", type=str)
@click.pass_obj
def cli(
    cli_ctx,
    package,
    assembly,
    scene,
    sketch,
    replace,
    from_stdin,
    as_json,
    position,
    direction,
    angle,
    boundary,
    object,
    name,
):
    drawn = boundary
    refuse_both(from_stdin, {"--position": position, "--direction": direction, "--angle": angle, "--boundary": drawn})
    if from_stdin:
        required = read_stdin(as_json)
    else:
        required = location(position, direction, angle)
        if drawn is not None:
            required = {**(required or {}), "sketch": value(drawn)}
    add(cli_ctx, object_params(package, assembly, scene, sketch, object), "port", name, required, replace)
