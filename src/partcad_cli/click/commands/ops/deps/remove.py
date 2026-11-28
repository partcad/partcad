#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc ops deps remove NAME`: take a dependency out of a package's declaration.

`ops.deps.remove`: the objects of the package that still use it are named, since
they will not load until they use something else.
"""

import rich_click as click

from ....service import run


@click.command(
    help="Take the dependency NAME out of the declaration of the package -P selects, naming what still uses it"
)
@click.option("--package", "-P", type=str, default="", show_envvar=True, help="The package, when not this one")
@click.argument("name", type=str)
@click.pass_obj
def cli(cli_ctx, package, name):
    result = run(cli_ctx, "ops.deps.remove", {"package": package or ".", "name": name}, needs_context=True)
    if result is None:
        raise click.ClickException("%s was not removed" % name)
    click.echo("Removed %s from %s" % (name, result.get("package")))
    if result.get("users"):
        click.echo("Still used by: %s" % ", ".join(result["users"]))
