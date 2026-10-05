#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import base64
import os

import rich_click as click

from partcad_utils import garage

from ..service import run


@click.command(
    help=(
        "Write the assembly instructions of an assembly, as PDF or HTML. "
        "The steps follow the assembly's links in order; -r adds the steps of every sub-assembly that is built "
        "and -b the making of every part that is built, each where it is first needed, as the IDE's Build tab "
        "lists them. What is built and what is bought is what was chosen in the IDE's Build vs Buy tab, saved "
        "on this machine"
    ),
)
@click.option(
    "-t",
    "--format",
    "fmt",
    type=click.Choice(["pdf", "html"]),
    default="pdf",
    show_default=True,
    help="The format to write the instructions in",
    show_envvar=True,
)
@click.option(
    "-r",
    "--recursive",
    is_flag=True,
    help="Include the steps of every sub-assembly that is built, each before the step that adds it",
    show_envvar=True,
)
@click.option(
    "-b",
    "--build-parts",
    is_flag=True,
    help="Include how to make every part that is built, each before the step that first needs it",
    show_envvar=True,
)
@click.option(
    "-O",
    "--output-dir",
    type=click.Path(file_okay=False, dir_okay=True),
    default=None,
    help="Where to write the file (the current directory if not given)",
    show_envvar=True,
)
@click.option(
    "-P",
    "--package",
    type=str,
    default=None,
    help="Package to retrieve the assembly from",
    show_envvar=True,
)
@click.option(
    "--ignore-manufacturability",
    is_flag=True,
    help="Write the instructions even if the assembly is not manufacturable",
    show_envvar=True,
)
@click.argument("object", type=str, required=True)
@click.pass_obj
def cli(cli_ctx, fmt, recursive, build_parts, output_dir, package, ignore_manufacturability, object):
    result = run(
        cli_ctx,
        "assembly.guide",
        {
            "package": package,
            "object": object,
            "format": fmt,
            # Not 'recursive': on a request that names an object, that is a
            # walk over the packages below it.
            "subassemblies": recursive,
            "build_parts": build_parts,
            "ignore_manufacturability": ignore_manufacturability,
            # The Build vs Buy choices are saved by the client that made them,
            # on this machine (see 'partcad_utils.garage'), and keyed by the
            # fully qualified name only the daemon resolves 'object' to - so
            # all of them go, and the daemon picks.
            "bvb": garage.load_all_bvb(),
        },
        needs_context=True,
    )
    if not result or not result.get("file"):
        raise click.ClickException("No instructions were written for %s" % object)

    # Written here rather than by the daemon: it may be on another machine,
    # and the file is the user's, wherever they ran this.
    file = result["file"]
    directory = os.path.abspath(output_dir or os.getcwd())
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, os.path.basename(file["filename"]))
    with open(path, "wb") as f:
        f.write(base64.b64decode(file["content"]))
    click.echo(path)
