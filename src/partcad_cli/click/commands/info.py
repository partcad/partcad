#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from .. import object_kind
from ..exclude import exclude_option, exclude_params
from ..parameters import param_option, param_params
from ..service import run


@click.command(
    help=(
        "Show detailed information about a part, assembly, scene, or software, or about a material, colour or "
        "finish. OBJECT may be written '...:<name>' to mean every object of that name in this "
        "package and in every package below it. " + object_kind.LOOKED_UP + ". " + object_kind.CMF_LOOKED_UP + "."
    ),
)
@click.option(
    "-P",
    "--package",
    "package",
    type=str,
    help="Package to retrieve the object from ('<package>...' for that package and every package below it)",
    default=None,
    show_envvar=True,
)
@click.option(
    "-i",
    "--interface",
    "interface",
    is_flag=True,
    help=object_kind.flag_help("an interface"),
    show_envvar=True,
)
@click.option(
    "-a",
    "--assembly",
    "assembly",
    is_flag=True,
    help=object_kind.flag_help("an assembly"),
    show_envvar=True,
)
@click.option(
    "-s",
    "--sketch",
    "sketch",
    is_flag=True,
    help=object_kind.flag_help("a sketch"),
    show_envvar=True,
)
@click.option(
    "-S",
    "--scene",
    "scene",
    is_flag=True,
    help=object_kind.flag_help("a scene"),
    show_envvar=True,
)
@click.option(
    "-w",
    "--software",
    "software",
    is_flag=True,
    help=object_kind.flag_help("software"),
    show_envvar=True,
)
@click.option(
    "-m",
    "--material",
    "material",
    is_flag=True,
    help=object_kind.cmf_flag_help("a material"),
    show_envvar=True,
)
@click.option(
    "--color",
    "color",
    is_flag=True,
    help=object_kind.cmf_flag_help("a colour"),
    show_envvar=True,
)
@click.option(
    "--finish",
    "finish",
    is_flag=True,
    help=object_kind.cmf_flag_help("a finish"),
    show_envvar=True,
)
@param_option
@exclude_option
@click.argument("object", type=str, required=False)  # help="Part (default), assembly or scene to show"
@click.pass_obj
def cli(
    cli_ctx, package, interface, assembly, sketch, scene, software, material, color, finish, exclude, object, params
):
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
            "material": material,
            "color": color,
            "finish": finish,
            "object": object,
            **param_params(params),
            **exclude_params(exclude),
        },
        needs_context=True,
    )
