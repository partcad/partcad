#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc req add interface OBJECT INTERFACE` -- an interface the object has to implement, and where.

    pc req add interface bracket //pub/std/metric/m3:m3-hole                         # any instance, anywhere
    pc req add interface bracket m3-hole --instance left --instance right            # these instances
    pc req add interface bracket m3-hole --instance left --direction 0 0 1           # this one, facing up
    pc req add interface bracket m3-hole --direction 0 0 1                           # some instance faces up

Written as `requirements: interfaces: <INTERFACE>:`. An instance is added to
those the interface is already required with; INTERFACE is looked up first,
from OBJECT's package, and one that is not found is refused.
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
)


@click.command(
    help=(
        "Require OBJECT to implement INTERFACE: any instance of it, the instances '--instance' names, or an "
        "instance where the location options say. " + object_kind.LOOKED_UP
    )
)
@object_options
@replace_option
@stdin_options
@location_options
@click.option(
    "--instance",
    "instances",
    multiple=True,
    help="An instance that has to be there ('' is the unnamed one); with a location, where it has to be",
)
@click.argument("object", type=str)
@click.argument("interface", type=str)
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
    instances,
    object,
    interface,
):
    refuse_both(from_stdin, {"--position": position, "--direction": direction, "--angle": angle})
    required = read_stdin(as_json) if from_stdin else location(position, direction, angle)
    request = object_params(package, assembly, scene, sketch, object)
    add(cli_ctx, request, "interface", interface, required, replace, instances)
