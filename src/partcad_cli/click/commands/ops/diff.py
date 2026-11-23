#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc ops diff REVISION [OBJECT]`: what changed since a revision, as a unified diff.

The comparison the IDE's Revisions tab draws side by side, printed the way
'git diff' prints one: the object at REVISION against the object as it is now,
each written out as `pc copy` writes one -- so what differs is what the object
means -- or, with no OBJECT, the package's `partcad.yaml` as Jinja2 rendered
it at each. The daemon writes the diff (`revisions.compare`'s `unified`).
"""

import rich_click as click

from ...operations_args import echo_json, print_unified, target_options, target_params
from ...parameters import param_option, param_params
from ...service import run


@click.command(
    help=(
        "Show what changed in OBJECT since REVISION (a commit id, a tag or a branch), as a unified diff: the "
        "object at REVISION against the object now, each written as 'pc copy' writes one. With no OBJECT, the "
        "package's partcad.yaml, as Jinja2 rendered it at each. Prints nothing when nothing changed."
    )
)
@target_options
@click.option(
    "--context",
    "-U",
    "context",
    type=click.IntRange(min=0),
    default=3,
    show_default=True,
    help="Lines of what did not change to show around each change",
)
@click.option("--exit-code", is_flag=True, help="Exit with 1 when something changed, as 'git diff --exit-code' does")
@click.option("--json", "as_json", is_flag=True, help="Print JSON: the side-by-side rows and the unified diff")
@param_option
@click.argument("revision", type=str)
@click.argument("object", type=str, required=False)
@click.pass_obj
def cli(cli_ctx, package, interface, assembly, scene, sketch, context, exit_code, as_json, params, revision, object):
    # '-p': the instance with these values, compared at each side.
    request = {**target_params(package, interface, assembly, scene, sketch, object), **param_params(params)}
    request.update({"revision": revision, "lines": context})
    result = run(cli_ctx, "revisions.compare", request, needs_context=True)
    if result is None:
        raise click.ClickException("Nothing was compared")
    if as_json:
        echo_json(result)
    else:
        print_unified(result.get("unified") or "")
    if exit_code and not result.get("same"):
        raise SystemExit(1)
