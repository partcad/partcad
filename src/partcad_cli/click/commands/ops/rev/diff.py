#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc ops rev diff [OBJECT]`: the subject at one state against another, as a unified diff.

The comparison the IDE's Revisions tab draws side by side (`ops.rev.diff`),
printed the way 'git diff' prints one: OBJECT -- written out as `pc copy` writes
it, so what differs is what it means -- or, with no OBJECT, the package's
`partcad.yaml` as rendered, after a list of what changed in it object by
object. From HEAD to WORKTREE by default, so that with no option it is what is
not committed yet.
"""

import rich_click as click

from ....operations_args import (
    echo_json,
    print_changes,
    print_unified,
    run_subject,
    state_options,
    state_params,
    target_options,
)
from ....parameters import param_option, param_params


@click.command(
    help=(
        "Show what changed in OBJECT -- or, with no OBJECT, in the package -P selects -- between two states, as a "
        "unified diff of what it means: everything not committed by default; --staged, --unstaged, --since REV, "
        "or --from and --to (a revision, STAGED or WORKTREE). Prints nothing when nothing changed."
    )
)
@target_options
@state_options
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
@click.argument("object", type=str, required=False)
@click.pass_obj
def cli(
    cli_ctx,
    package,
    interface,
    assembly,
    scene,
    sketch,
    from_state,
    to_state,
    staged,
    unstaged,
    since,
    context,
    exit_code,
    as_json,
    params,
    object,
):
    # '-p': the instance with these values, compared at each side.
    extra = {**state_params(from_state, to_state, staged, unstaged, since), "lines": context, **param_params(params)}
    result = run_subject(cli_ctx, "ops.rev.diff", (package, interface, assembly, scene, sketch, object), extra)
    if as_json:
        echo_json(result)
    else:
        print_changes(result.get("changes"))
        print_unified(result.get("unified") or "")
    if exit_code and not result.get("same"):
        raise SystemExit(1)
