#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc ops rev stage [OBJECT]`: stage every change of the subject that is not staged.

The Revisions tab's **Stage all** (`ops.rev.stage`, see
`partcad.working_copy.stage`). A package's own files, untracked ones included,
and none of its sub-packages'; an object's files and its own declaration in
`partcad.yaml`, only the lines of it -- so another object's edit in the same
file stays out.
"""

import rich_click as click

from ....operations_args import echo_json, print_status, run_subject, target_options


@click.command(
    help=(
        "Stage every change of OBJECT -- its files and its own declaration -- or, with no OBJECT, of the package "
        "-P selects -- its own files, not its sub-packages' -- that is not staged yet"
    )
)
@target_options
@click.option("--json", "as_json", is_flag=True, help="Print JSON")
@click.argument("object", type=str, required=False)
@click.pass_obj
def cli(cli_ctx, package, interface, assembly, scene, sketch, as_json, object):
    result = run_subject(cli_ctx, "ops.rev.stage", (package, interface, assembly, scene, sketch, object))
    if as_json:
        echo_json(result)
        return
    for note in result.get("notes") or []:
        click.echo(note)
    staged = result.get("staged") or []
    click.echo("Staged: %s" % ", ".join(staged) if staged else "Nothing was left to stage")
    if result.get("status"):
        click.echo("")
        print_status(result["status"])
