#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc ops uses REVISION`: the dependencies a package declared at a revision, each at its commit.

The Revisions tab's "Uses (Dependencies)" view: the name each dependency is
declared under, the first eight characters of the commit it is at, and the
name that loads it at that commit (`<package>@<sha>`), which any other command
takes. Loading a dependency may download it.
"""

import rich_click as click

from ...operations_args import echo_json, print_dependencies
from ...parameters import param_option, param_params
from ...service import run


@click.command(
    help=(
        "List the dependencies the package declared at REVISION, each with the commit it is at and the name "
        "that loads it there ('<package>@<sha>'). Of the package -P selects, or of the package OBJECT is in."
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
        "revisions.uses",
        {"package": package or ".", "object": object or None, "revision": revision, **param_params(params)},
        needs_context=True,
    )
    if result is None:
        raise click.ClickException("Nothing was listed")
    if as_json:
        echo_json(result)
    else:
        print_dependencies(result)
