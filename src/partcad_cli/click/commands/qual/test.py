#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc qual test` -- run the qualification tests of a part, an assembly, a scene or a whole package.

Every built-in check of the subtypes asked for, each of the objects it has
something to ask of, and every check an object declares under `qual:` itself.
`--basic`, `--topology`, `--simulation` and `--other` select subtypes and may be
combined; none of them is all four. Daemon work, like `pc test`, whose method
(`qual.run`) it calls with the subtypes chosen.
"""

import rich_click as click

from ... import fast_only, object_kind
from ...exclude import exclude_option, exclude_params
from ...parameters import param_option, param_params
from ...service import run


@click.command(
    help=(
        "Run the qualification tests of a part, an assembly, a scene or a sketch -- all four subtypes unless "
        "'--basic', '--topology', '--simulation' or '--other' say which. "
        "OBJECT may be written '...:<name>' to mean every object of that name in this "
        "package and in every package below it. " + object_kind.LOOKED_UP
    ),
)
@click.option(
    "--package",
    "-P",
    type=str,
    default="",
    show_envvar=True,
    help="Package to retrieve the object from ('<package>...' for that package and every package below it)",
)
@click.option(
    "--recursive",
    "-r",
    is_flag=True,
    show_envvar=True,
    help="Recursively qualify all imported packages (older spelling of '<package>...')",
)
@fast_only.option(short=False)
@click.option("--basic", is_flag=True, help="Run the basic tests: findings in words")
@click.option("--topology", is_flag=True, help="Run the topology tests: findings that are places on the object")
@click.option(
    "--simulation",
    "--sim",
    "simulation",
    is_flag=True,
    help="Run the simulations the object declares under 'qual: sim:'",
)
@click.option("--other", is_flag=True, help="Run the tests other tools supply through plugins")
@click.option(
    "--filter",
    "-f",
    help="Only run tests whose names start with the given prefix",
    type=str,
    show_envvar=True,
    default=None,
)
@click.option("--sketch", "-s", is_flag=True, show_envvar=True, help=object_kind.flag_help("a sketch"))
@click.option("--interface", "-i", is_flag=True, show_envvar=True, help=object_kind.flag_help("an interface"))
@click.option("--assembly", "-a", is_flag=True, show_envvar=True, help=object_kind.flag_help("an assembly"))
@click.option("--scene", "-S", is_flag=True, show_envvar=True, help=object_kind.flag_help("a scene"))
@exclude_option
@param_option
@click.argument("object", type=str, required=False)
@click.pass_obj
def cli(
    cli_ctx,
    package,
    recursive,
    fast_only,
    basic,
    topology,
    simulation,
    other,
    filter,
    sketch,
    interface,
    assembly,
    scene,
    exclude,
    params,
    object,
):
    subtypes = [
        subtype
        for subtype, chosen in (("basic", basic), ("topology", topology), ("sim", simulation), ("other", other))
        if chosen
    ]
    run(
        cli_ctx,
        "qual.run",
        {
            "package": package,
            "recursive": recursive,
            "fast_only": fast_only,
            "filter": filter,
            "subtypes": subtypes,
            "sketch": sketch,
            "interface": interface,
            "assembly": assembly,
            "scene": scene,
            "object": object,
            **param_params(params),
            **exclude_params(exclude),
        },
        needs_context=True,
    )
