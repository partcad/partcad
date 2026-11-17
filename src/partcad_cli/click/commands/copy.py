#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""``pc copy`` -- declare a second object as what the first one is.

A daemon command, like every other command that writes into ``partcad.yaml``:
the new object has to exist in the package the daemon is serving, or the warm
context goes on answering for the package as it was before the command ran.

The declaration written is the first object's *as PartCAD read it* -- rendered,
normalized, with what is only a default left out, in the order it was declared
in (see ``partcad.serialize``) -- not the text of the file it came from.
"""

import rich_click as click

from ..service import run


@click.command(
    help=(
        "Declare OBJECT_TO as a copy of OBJECT_FROM. The declaration written is OBJECT_FROM as PartCAD read it -- "
        "rendered, normalized and with every default left out, in the order it was declared in -- not the text "
        "of the file it came from. OBJECT_FROM may be in any package, a revision of one included "
        "('//pkg@v1.2:bracket'); OBJECT_TO is declared in the package --package selects, or the one it names. "
        "An OBJECT_TO the package already declares is refused."
    ),
)
@click.option(
    "-P",
    "--package",
    help="Package OBJECT_FROM is read from and OBJECT_TO is written to, when they do not name one",
    type=str,
    show_envvar=True,
)
@click.option(
    "--dry-run",
    help="Print the declaration that would be written, and write nothing",
    is_flag=True,
    show_envvar=True,
)
@click.argument("object_from", metavar="OBJECT_FROM", type=str, required=True)
@click.argument("object_to", metavar="OBJECT_TO", type=str, required=True)
@click.pass_obj
def cli(cli_ctx, package, dry_run, object_from, object_to):
    result = run(
        cli_ctx,
        "copy.object",
        {
            "package": package,
            "object": object_from,
            "target": object_to,
            "dry_run": dry_run,
        },
        needs_context=True,
    )
    if dry_run and isinstance(result, dict) and result.get("declaration"):
        click.echo(result["declaration"], nl=False)
