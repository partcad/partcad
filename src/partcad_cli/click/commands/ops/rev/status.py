#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc ops rev status [OBJECT]`: what of the subject is staged and what is not, by object.

What the Revisions tab shows above the commits (`ops.rev.status`, see
`partcad.working_copy.status`): the objects whose changes are staged -- in a new
revision -- and the ones whose are not, the files of the package no object is
built from, and what else in the repository is staged or changed. When anything
of the subject is not staged, it ends with one sentence to hand an agent.
"""

import rich_click as click

from ....operations_args import echo_json, print_status, run_subject, target_options


@click.command(
    help=(
        "Say what of OBJECT -- or, with no OBJECT, of the package -P selects -- is staged and what is not, by "
        "object, and what else in the repository is staged or changed"
    )
)
@target_options
@click.option("--json", "as_json", is_flag=True, help="Print JSON")
@click.argument("object", type=str, required=False)
@click.pass_obj
def cli(cli_ctx, package, interface, assembly, scene, sketch, as_json, object):
    result = run_subject(cli_ctx, "ops.rev.status", (package, interface, assembly, scene, sketch, object))
    if as_json:
        echo_json(result)
    else:
        print_status(result)
