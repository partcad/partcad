#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc ops deps update [NAME...]`: move tracked dependencies to the tip of their branches.

What `pc update` was (`ops.deps.update`, see `partcad.actions.package.update`):
each git dependency that says `track: <branch>` has its `revision:` rewritten to
the commit that branch is at now, and every import is fetched again. Of the
package `-P` selects -- only the NAMEs given, when any are -- or with `--all` of
every package of the workspace.
"""

import rich_click as click

from ....service import run


def update(cli_ctx, package, names, everything: bool) -> dict:
    request = {"all": True} if everything else {"package": package or "."}
    if names:
        request["names"] = list(names)
    result = run(cli_ctx, "ops.deps.update", request, span_name="update", needs_context=True)
    if result is None:
        raise click.ClickException("Nothing was updated")
    return result


@click.command(
    help=(
        "Move each tracked dependency of the package -P selects -- only NAME..., when given -- to the newest "
        "commit of its branch: its 'revision:' in partcad.yaml is rewritten, and every import is fetched again. "
        "--all moves every tracked dependency of the workspace."
    )
)
@click.option("--package", "-P", type=str, default="", show_envvar=True, help="The package, when not this one")
@click.option("--all", "everything", is_flag=True, help="Every tracked dependency of every package of the workspace")
@click.argument("names", type=str, nargs=-1)
@click.pass_obj
def cli(cli_ctx, package, everything, names):
    if everything and (package or names):
        raise click.UsageError("--all is every dependency of every package: give it alone")
    update(cli_ctx, package, names, everything)
