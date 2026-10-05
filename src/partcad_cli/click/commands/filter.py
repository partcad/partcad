#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""``pc filter`` -- declare a second assembly made of some of the first one's links.

A daemon command, like every other command that writes into ``partcad.yaml``:
the new object has to exist in the package the daemon is serving, or the warm
context goes on answering for the package as it was before the command ran.

What stays in the client is the first argument, and only because of where the
file is: a filter is a filename first, and the file is on the machine the user
typed the command on. See ``partcad_cli.click.link_filter``.
"""

import rich_click as click

from ..link_filter import HELP, filter_params, resolve
from ..service import run


@click.command(
    help=(
        "Declare DST as a copy of SRC holding only the links FILTER keeps. "
        "SRC is an assembly or a scene, and DST is the same kind of object; "
        "an existing DST is overwritten.\n\nFILTER: " + HELP
    ),
)
@click.option(
    "-P",
    "--package",
    help="Package to retrieve the object from",
    type=str,
    show_envvar=True,
)
@click.option(
    "-a",
    "--assembly",
    help="The object is an assembly (the default is whichever SRC is)",
    is_flag=True,
    show_envvar=True,
)
@click.option(
    "-S",
    "--scene",
    help="The object is a scene (the default is whichever SRC is)",
    is_flag=True,
    show_envvar=True,
)
@click.option(
    "--dry-run",
    help="Say what would be written, and write nothing",
    is_flag=True,
    show_envvar=True,
)
@click.argument("filter", metavar="FILTER", type=str, callback=resolve, required=True)
@click.argument("src", metavar="SRC", type=str, required=True)
@click.argument("dst", metavar="DST", type=str, required=True)
@click.pass_obj
def cli(cli_ctx, package, assembly, scene, dry_run, filter, src, dst):
    if assembly and scene:
        raise click.UsageError("SRC is an assembly or a scene, not both")
    run(
        cli_ctx,
        "filter.object",
        {
            "package": package,
            "assembly": assembly,
            "scene": scene,
            "object": src,
            "target": dst,
            "dry_run": dry_run,
            **filter_params(filter),
        },
        needs_context=True,
    )
