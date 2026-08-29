#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from ..service import run


# TODO-94: @alexanderilyin: Replace -i, -a, -s, -S with --type; https://stackoverflow.com/a/37491504/25671117
@click.command(help="Show detailed information about a part, assembly, scene, or software")
@click.option(
    "-P",
    "--package",
    "package",
    type=str,
    help="Package to retrieve the object from",
    default=None,
    show_envvar=True,
)
@click.option(
    "-i",
    "--interface",
    "interface",
    is_flag=True,
    help="The object is an interface",
    show_envvar=True,
)
@click.option(
    "-a",
    "--assembly",
    "assembly",
    is_flag=True,
    help="The object is an assembly",
    show_envvar=True,
)
@click.option(
    "-s",
    "--sketch",
    "sketch",
    is_flag=True,
    help="The object is a sketch",
    show_envvar=True,
)
@click.option(
    "-S",
    "--scene",
    "scene",
    is_flag=True,
    help="The object is a scene",
    show_envvar=True,
)
@click.option(
    "-w",
    "--software",
    "software",
    is_flag=True,
    help="The object is software",
    show_envvar=True,
)
@click.option(
    "-p",
    "--param",
    "params",
    type=str,
    multiple=True,
    metavar="<name>=<value>",
    help="Assign a value to the parameter",
    show_envvar=True,
)
@click.argument("object", type=str, required=False)  # help="Part (default), assembly or scene to show"
@click.pass_obj
def cli(cli_ctx, package, interface, assembly, sketch, scene, software, object, params):
    run(
        cli_ctx,
        "info.object",
        {
            "package": package,
            "interface": interface,
            "assembly": assembly,
            "sketch": sketch,
            "scene": scene,
            "software": software,
            "object": object,
            "params": list(params),
        },
        needs_context=True,
    )
