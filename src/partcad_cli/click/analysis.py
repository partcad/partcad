#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The options every `pc cae` analysis takes, and the request it turns into.

`pc cae fea`, `pc cae dynamic`, `pc cae thermal` and `pc cae cfd` differ in one
word: which section of the part holds the boundary conditions, and what the model
file is named after. Everything else -- where the object comes from, which of the
section's scenarios to run, who runs the analysis, where the model goes, how the
findings are printed -- is the same for all of them, and has to be: a user who
has learned one of them has learned the others.

A section is a map of named scenarios, as `simulate:` is a map of simulations,
and the command treats them the way `pc sim` treats those: every one is run,
unless `-f` names the one to run, and the command fails when any of them did not
run or found anything.

So the command modules are a name and a docstring each, and this is the
command. The same reason `viewport.py` holds the three options `pc render` and
`pc adhoc render` share.
"""

import os

import rich_click as click

from .parameters import param_option, param_params
from .service import run

_OPTIONS = (
    click.option(
        "-P",
        "--package",
        help="Package to retrieve the object from",
        type=str,
        show_envvar=True,
    ),
    click.option(
        "-f",
        "--filter",
        "filter_name",
        help="Only run the scenario declared under this name (as 'pc sim -f' runs one simulation)",
        type=str,
        default=None,
        metavar="NAME",
        show_envvar=True,
    ),
    click.option(
        "-i",
        "--implementation",
        help=(
            "Who runs the analysis, as '<package>:<file type>'. Overrides the default "
            "for this run only; the default itself is the user configuration option named "
            "after the analysis: 'caeFeaImplementation', 'caeDynamicImplementation', "
            "'caeThermalImplementation' or 'caeCfdImplementation'"
        ),
        type=str,
        show_envvar=True,
    ),
    click.option(
        "-O",
        "--output-dir",
        help="Write the model into the given directory instead of where the configuration puts it",
        type=click.Path(exists=True, file_okay=False, dir_okay=True),
        show_envvar=True,
    ),
    click.option(
        "--json",
        "as_json",
        help=(
            "Print the findings as the JSON array they are, instead of as a table: every scenario's, "
            "each carrying the 'scenario' it is of"
        ),
        is_flag=True,
        show_envvar=True,
    ),
)


def analysis_options(command):
    """Add the shared `pc cae` options to a command.

    Applied in reverse because click reverses the parameters it collected, which
    is what makes them read in this order in '--help'.
    """
    command = param_option(command)
    for option in reversed(_OPTIONS):
        command = option(command)
    return command


def analysis_command(cli_ctx, analysis, package, filter_name, implementation, output_dir, as_json, params, object):
    """Run the scenarios of one analysis on the daemon and let it report.

    The findings are printed by the daemon through PartCAD logging, exactly as
    `pc bom` prints its table, so that what a user sees does not depend on which
    client asked -- and so is why a scenario did not run. `--json` is the
    exception: a machine-readable array has to reach stdout of *this* process to
    be piped anywhere.
    """
    result = run(
        cli_ctx,
        "cae.analyze",
        {
            "analysis": analysis,
            "package": package,
            "object": object,
            "scenario": filter_name,
            **param_params(params),
            "implementation": implementation,
            # Resolved to absolute so the model lands in the user's working
            # directory rather than the daemon's, which is somewhere else.
            "output_dir": os.path.abspath(output_dir) if output_dir else None,
            "json": as_json,
        },
        needs_context=True,
    )
    if as_json:
        import json

        click.echo(json.dumps((result or {}).get("findings") or [], indent=2))

    if result and result.get("failed"):
        # Each one's reason is in the log already, said by the daemon.
        raise click.ClickException(
            "%d of %d %s scenario(s) did not run" % (result["failed"], result.get("total", 0), analysis.upper())
        )
    # A finding is what the user asked about, so a run that produced one is a
    # run whose answer is "no": `pc cae fea && ...` has to stop there, the same
    # way `pc test` exits non-zero on a failed test.
    if result and result.get("findings"):
        raise SystemExit(1)
