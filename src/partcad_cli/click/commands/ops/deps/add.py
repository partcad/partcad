#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc ops deps add NAME LOCATION`: declare a dependency of a package.

What `pc add dep` was (`ops.deps.add`, see `Project.add_import`): LOCATION is a
path, a git URL or a tarball URL; a git dependency is added tracking a branch,
with `revision:` pinned to the commit that branch is at now.
"""

import rich_click as click

from ....service import run


def add(cli_ctx, package: str, name: str, location: str, track) -> dict:
    request = {"package": package or ".", "name": name, "location": location}
    if track:
        request["track"] = track
    result = run(cli_ctx, "ops.deps.add", request, needs_context=True)
    if result is None:
        raise click.ClickException("%s was not added" % name)
    click.echo("Added %s to %s" % (name, result.get("package")))
    return result


@click.command(
    help=(
        "Declare the dependency NAME of the package -P selects, at LOCATION: a path, a git URL or a tarball URL. A "
        "git dependency is added tracking a branch, with 'revision:' pinned to the commit that branch is at now; "
        "'pc ops deps update' moves the pin from then on."
    )
)
@click.option("--package", "-P", type=str, default="", show_envvar=True, help="The package, when not this one")
@click.option(
    "--track", type=str, default=None, help="The branch of a git dependency to track: its default one if not given"
)
@click.argument("name", type=str)
@click.argument("location", type=str)
@click.pass_obj
def cli(cli_ctx, package, track, name, location):
    add(cli_ctx, package, name, location, track)
