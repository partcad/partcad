#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc ops rev new [OBJECT] -m MESSAGE`: commit what is staged as a new revision of the subject.

The Revisions tab's **New revision** (`ops.rev.new`, see
`partcad.working_copy.new_revision`). Only what is staged is committed. Before
it is, the daemon checks that something of the subject is staged, says what
else is staged (asked here, or agreed to with `--include-others`) and what of
the subject is not, or changed again since it was staged (asked here, or agreed
to with `--yes`), and runs lint and the qualification tests of what is staged
(`--skip-checks` commits without them). The author is who git on this machine
says the user is, never whoever the daemon runs as.
"""

import os
import sys

import rich_click as click

from partcad_utils import git_identity

from ....operations_args import echo_json, print_status, target_options, target_params
from ....service import Refusal, run

# What the daemon asks to be agreed to, by its code, and the flag that agrees.
_ASKS = {"others-staged": "include_others", "warnings": "yes"}


def _interactive() -> bool:
    """Whether there is somebody to ask: a terminal, rather than a script or an agent."""
    return sys.stdin.isatty()


@click.command(
    help=(
        "Commit what is staged as a new revision of OBJECT -- or, with no OBJECT, of the package -P selects -- "
        "once lint and the qualification tests of it pass. Asks before committing anything else that is staged "
        "(--include-others agrees) and while changes of it are not staged (--yes agrees)."
    )
)
@target_options
@click.option("--message", "-m", type=str, required=True, help="What the revision is: its first line is its summary")
@click.option("--include-others", is_flag=True, help="Commit what else is staged as well, without asking")
@click.option(
    "--yes", "-y", "accept", is_flag=True, help="Commit although changes of it are not staged, without asking"
)
@click.option("--skip-checks", is_flag=True, help="Commit without running lint and the qualification tests")
@click.option("--json", "as_json", is_flag=True, help="Print JSON")
@click.argument("object", type=str, required=False)
@click.pass_obj
def cli(
    cli_ctx, package, interface, assembly, scene, sketch, message, include_others, accept, skip_checks, as_json, object
):
    request = target_params(package, interface, assembly, scene, sketch, object)
    request.update(
        {
            "message": message,
            "author": git_identity.identity(getattr(cli_ctx, "path", None) or os.getcwd()),
            "include_others": include_others,
            "yes": accept,
            "skip_checks": skip_checks,
        }
    )
    while True:
        try:
            result = run(cli_ctx, "ops.rev.new", request, needs_context=True)
            break
        except Refusal as refusal:
            data = refusal.data or {}
            flag = _ASKS.get(data.get("code"))
            if flag is None or request.get(flag) or not _interactive():
                if data.get("status") and not as_json:
                    print_status(data["status"])
                for entry in (data.get("status") or {}).get("checks") or []:
                    click.echo("%s  %s" % ("passed" if entry.get("passed") else "FAILED", entry.get("summary")))
                raise
            click.echo(str(refusal.message))
            if not click.confirm("Make the revision all the same?", default=False):
                raise click.Abort()
            request[flag] = True
    if result is None:
        raise click.ClickException("No revision was made")
    if as_json:
        echo_json(result)
        return
    for entry in result.get("checks") or []:
        click.echo("%s  %s" % ("passed" if entry.get("passed") else "FAILED", entry.get("summary")))
    click.echo("%s  %s" % (result.get("short"), result.get("summary")))
