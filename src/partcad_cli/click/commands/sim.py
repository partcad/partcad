#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc sim` -- run the simulations a part or an assembly declares.

A part says what it is; `simulate:` is where it says what it is supposed to do.
This takes that section of a part or an assembly, places the object in the
scene the section names, runs it through the simulation plugin the section
names, and evaluates the `validation:` expression the section states over what
came back. See `docs/source/simulation.rst` and `partcad.simulation`.

`pc test` holds an object to the same claims, as its `sim` check
(`partcad.test.sim`), so a `simulate:` is checked whenever the package is
tested and not only when somebody asks. Both run a simulation through
`simulation.run_async`, so they cannot disagree about how one runs, and share
its cache. What this command is for is asking on purpose: one simulation by name
(`-f`), and everything the plugin reported (`--json`) rather than a verdict --
which is also why a declaration with no `validation:` is run here and reported
as having run, where `pc test` skips or fails it: here it is how somebody looks
at what a plugin reports before writing the condition.

All of that is daemon work -- it loads the package graph, exports the scene
through a CAD wrapper and runs the plugin in a sandbox -- so this command is a
thin front end for `simulate.run`, like `pc test` and `pc render` are for
theirs. What is decided here is only what the exit code and the output look
like: a failed validation exits non-zero, because a simulation nobody notices
failing is not a check.

`--before` and `--after` are the one thing done here rather than by the daemon:
they write the state a simulation started from and ended in to files the user
named, and the daemon may be on another machine, where a path would name a file
nobody here could open. The daemon sends the two objects back with the result,
and this process writes them -- YAML, which reads, unless `--json` was asked
for or the path ends in `.json`.
"""

import json
import os
import sys

import rich_click as click

from .. import fast_only
from ..exclude import exclude_option, exclude_params
from ..service import run


@click.command(
    help=(
        "Run the simulations declared by a part or an assembly. "
        "OBJECT may be written '...:<name>' to mean every object of that name in this "
        "package and in every package below it"
    ),
)
@click.option(
    "--package",
    "-P",
    type=str,
    default="",
    show_envvar=True,
    help="Package to retrieve the object from ('<package>...' for that package and every package below it)",
)
@click.option(
    "--recursive",
    "-r",
    is_flag=True,
    show_envvar=True,
    help="Recursively simulate the objects of all imported packages (older spelling of '<package>...')",
)
@fast_only.option(short=False)
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
    help=(
        "Print the full result of every run as JSON, including what the plugin reported; "
        "and write '--before'/'--after' as JSON rather than YAML"
    ),
)
@click.option(
    "--plugin",
    type=str,
    default=None,
    show_envvar=True,
    metavar="PACKAGE:NAME",
    help=(
        "Run with this simulation plugin instead of the one each simulation names in its "
        "'simulation:', e.g. '//pub/feature/simulate/gazebo:gazebo'"
    ),
)
@click.option(
    "--before",
    "before_path",
    type=click.Path(dir_okay=False, writable=True),
    default=None,
    help="Save the state the simulation started from to this file (YAML, or JSON for a '.json' path)",
)
@click.option(
    "--after",
    "after_path",
    type=click.Path(dir_okay=False, writable=True),
    default=None,
    help="Save the state the simulation ended in to this file (YAML, or JSON for a '.json' path)",
)
@exclude_option
@click.argument("object", type=str, required=False)  # help="Part (default) or assembly to simulate"
@click.pass_obj
def cli(
    cli_ctx,
    package,
    recursive,
    fast_only,
    assembly,
    filter_name,
    as_json,
    plugin,
    before_path,
    after_path,
    exclude,
    object,
) -> None:
    result = run(
        cli_ctx,
        "simulate.run",
        {
            "package": package,
            "recursive": recursive,
            "fast_only": fast_only,
            "assembly": assembly,
            "filter": filter_name,
            "object": object,
            "plugin": plugin,
            **exclude_params(exclude),
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

    # Before the verdict decides the exit status: a run whose validation did
    # not hold is exactly the run whose state somebody wants to look at.
    for moment, path in (("before", before_path), ("after", after_path)):
        if path:
            save_state(result, moment, path, as_json)

    if not result.get("ok", True):
        raise click.ClickException(
            "%d of %d simulation(s) did not pass" % (result.get("failed", 0), result.get("total", 0))
        )


def save_state(result: dict, moment: str, path: str, as_json: bool) -> None:
    """Write one simulation's 'before' or 'after' to 'path', or say why not.

    One simulation's: the file is that run's state, and a file holding several
    keyed by name would be a different shape depending on how many ran, which
    is not something a script reading it can rely on. So more than one is
    refused, and '-f' is how to name the one wanted.
    """
    simulations = result.get("simulations") or []
    if len(simulations) != 1:
        raise click.ClickException(
            "--%s saves the state of one simulation, and %d ran: name the object, and the "
            "simulation with -f" % (moment, len(simulations))
        )
    (simulation,) = simulations
    state = (simulation.get("result") or {}).get(moment)
    if state is None:
        raise click.ClickException(
            "%s: the simulation '%s' has no '%s' to save: %s"
            % (
                simulation.get("object"),
                simulation.get("simulation"),
                moment,
                simulation.get("error") or "its plugin reported none",
            )
        )

    if as_json or path.lower().endswith(".json"):
        text = json.dumps(state, indent=2) + "\n"
    else:
        import yaml

        # Flow style for the innermost lists, so that a position or a quaternion
        # is a line rather than a column.
        text = yaml.safe_dump(state, sort_keys=False, default_flow_style=None, allow_unicode=True)

    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    # To stderr: with '--json', stdout is the result and nothing else.
    click.echo(
        "Saved the state %s the simulation '%s' to %s" % (moment, simulation.get("simulation"), path),
        err=True,
    )
