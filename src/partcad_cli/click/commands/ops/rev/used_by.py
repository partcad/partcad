#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc ops rev used-by REVISION`: what among the loaded packages uses a package at a revision.

The Revisions tab's "Used By" view: every object the daemon has loaded that
refers to the package at REVISION -- by its commit, a tag, a branch, or as the
dependency checked out there -- with how many times. Only what is loaded is
looked at; `pc ops used-by` is the same question about what is checked out.
"""

import rich_click as click

from ....operations_args import echo_json, print_used_by
from ....parameters import param_option, param_params
from ....service import run


@click.command(
    help=(
        "List the objects PartCAD has loaded that use the package at REVISION, each with how many times. Of the "
        "package -P selects, or of the package OBJECT is in. Only what is loaded is looked at."
    )
)
@click.option("--package", "-P", type=str, default="", show_envvar=True, help="The package, when not this one")
@click.option("--json", "as_json", is_flag=True, help="Print JSON")
@param_option
@click.argument("revision", type=str)
@click.argument("object", type=str, required=False)
@click.pass_obj
def cli(cli_ctx, package, as_json, params, revision, object):
    result = run(
        cli_ctx,
        "revisions.used_by",
        {"package": package or ".", "object": object or None, "revision": revision, **param_params(params)},
        needs_context=True,
    )
    if result is None:
        raise click.ClickException("Nothing was listed")
    if as_json:
        echo_json(result)
    else:
        print_used_by(result, "%s at %s" % (result.get("package"), (result.get("revision") or revision)[:8]))
