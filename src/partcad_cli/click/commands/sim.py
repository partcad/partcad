#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc sim` -- run the simulations a part or an assembly declares.

`pc test` asks whether a part can be made. This asks whether it works: it takes
the `simulate:` section of a part or an assembly, places that object in the
scene the section names, runs it through the simulation plugin the section
names, and evaluates the `validation:` expression the section states over what
came back. See `docs/source/simulation.rst` and `partcad.simulation`.

All of that is daemon work -- it loads the package graph, exports the scene
through a CAD wrapper and runs the plugin in a sandbox -- so this command is a
thin front end for `simulate.run`, like `pc test` and `pc render` are for
theirs. What is decided here is only what the exit code and the output look
like: a failed validation exits non-zero, because a simulation nobody notices
failing is not a check.
"""

import json
import sys

import rich_click as click

from ..service import run


@click.command(help="Run the simulations declared by a part or an assembly")
@click.option(
    "--package",
    "-P",
    type=str,
    default="",
    show_envvar=True,
    help="Package to retrieve the object from",
)
@click.option(
    "--recursive",
    "-r",
    is_flag=True,
    show_envvar=True,
    help="Recursively simulate the objects of all imported packages",
)
@click.option(
    "--assembly",
    "-a",
    is_flag=True,
    show_envvar=True,
    help="The object is an assembly",
)
@click.option(
    "--filter",
    "-f",
    "filter_name",
    type=str,
    default=None,
    show_envvar=True,
    metavar="NAME",
    help="Only run the simulation declared under this name",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Print the full result of every run as JSON, including what the plugin reported",
)
@click.argument("object", type=str, required=False)  # help="Part (default) or assembly to simulate"
@click.pass_obj
def cli(cli_ctx, package, recursive, assembly, filter_name, as_json, object) -> None:
    result = run(
        cli_ctx,
        "simulate.run",
        {
            "package": package,
            "recursive": recursive,
            "assembly": assembly,
            "filter": filter_name,
            "object": object,
        },
        needs_context=True,
    )

    if result is None:
        # The package did not load; the daemon has already said so.
        raise click.ClickException("Nothing was simulated")

    if as_json:
        # To stdout, so it can be piped into `jq` no matter where the logs go.
        # The verdict per run is rendered by the daemon through the same logging
        # path as `pc test`, which is why it is not repeated here.
        sys.stdout.write(json.dumps(result, indent=4) + "\n")
        sys.stdout.flush()

    if not result.get("ok", True):
        raise click.ClickException(
            "%d of %d simulation(s) did not pass" % (result.get("failed", 0), result.get("total", 0))
        )
