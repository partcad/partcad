#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc ops impact [OBJECT]`: what a change reaches, and what each object it reaches now risks.

The IDE's Operations > Impact tab (`ops.impact`, see `partcad.impact`): the
objects that changed between two states of the repository -- everything not
committed by default; `--staged`, `--unstaged`, `--since REV` or `--from` and
`--to` for another change -- then everything that uses them, each with its
findings (breaking, changed, verify, info). For an object, also what it uses
that changed. Looks where `pc ops used-by` looks: what is loaded, the workspace
with `--load`. `--measure` and `--test` build shapes, and take their time.
"""

import rich_click as click

from ...operations_args import echo_json, print_impact, run_subject, state_options, state_params, target_options


@click.command(
    help=(
        "Show what a change reaches: the objects of OBJECT's package -- or, with no OBJECT, of the package -P "
        "selects -- that changed, everything that uses them, and what each now risks. Everything not committed "
        "by default; --staged, --unstaged, --since REV, or --from and --to (a revision, STAGED or WORKTREE)."
    )
)
@target_options
@state_options
@click.option("--measure", is_flag=True, help="Measure how much each changed part or assembly moved (builds both)")
@click.option("--test", is_flag=True, help="Run the qualification tests of every object reached")
@click.option("--load", is_flag=True, help="Load every package below the root first, so that all of them are asked")
@click.option("--exit-code", is_flag=True, help="Exit with 1 when anything reached is breaking")
@click.option("--json", "as_json", is_flag=True, help="Print JSON")
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
    measure,
    test,
    load,
    exit_code,
    as_json,
    object,
):
    extra = {
        **state_params(from_state, to_state, staged, unstaged, since),
        "measure": measure,
        "test": test,
        "load": load,
    }
    result = run_subject(cli_ctx, "ops.impact", (package, interface, assembly, scene, sketch, object), extra)
    if as_json:
        echo_json(result)
    else:
        print_impact(result)
        if not load:
            click.echo("Only what PartCAD has loaded was looked at: --load looks at the whole workspace")
    if exit_code and (result.get("summary") or {}).get("breaking"):
        raise SystemExit(1)
