#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The options every `pc cae` analysis takes, and the request it turns into.

`pc cae fea` and `pc cae cfd` differ in one word: which section of the part holds
the boundary conditions, and what the model file is named after. Everything else
-- where the object comes from, who runs the analysis, where the model goes, how
the findings are printed -- is the same for both, and has to be: a user who has
learned one of them has learned the other.

So the two command modules are a name and a docstring each, and this is the
command. The same reason `viewport.py` holds the three options `pc render` and
`pc adhoc render` share.
"""

import os

import rich_click as click

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
        "-i",
        "--implementation",
        help=(
            "Who runs the analysis, as '<package>:<file type>'. Overrides the default "
            "for this run only; the default itself is the 'caeFeaImplementation'/"
            "'caeCfdImplementation' user configuration option"
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
        "-p",
        "--create-dirs",
        help="Create the necessary directory structure if it is missing",
        is_flag=True,
        show_envvar=True,
    ),
    click.option(
        "--json",
        "as_json",
        help="Print the findings as the JSON array they are, instead of as a table",
        is_flag=True,
        show_envvar=True,
    ),
)


def analysis_options(command):
    """Add the shared `pc cae` options to a command.

    Applied in reverse because click reverses the parameters it collected, which
    is what makes them read in this order in '--help'.
    """
    for option in reversed(_OPTIONS):
        command = option(command)
    return command


def analysis_command(cli_ctx, analysis, package, implementation, output_dir, create_dirs, as_json, object):
    """Run one analysis on the daemon and let it report.

    The findings are printed by the daemon through PartCAD logging, exactly as
    `pc bom` prints its table, so that what a user sees does not depend on which
    client asked. `--json` is the exception: a machine-readable array has to
    reach stdout of *this* process to be piped anywhere.
    """
    result = run(
        cli_ctx,
        "cae.analyze",
        {
            "analysis": analysis,
            "package": package,
            "object": object,
            "implementation": implementation,
            # Resolved to absolute so the model lands in the user's working
            # directory rather than the daemon's, which is somewhere else.
            "output_dir": os.path.abspath(output_dir) if output_dir else None,
            "create_dirs": create_dirs,
            "json": as_json,
        },
        needs_context=True,
    )
    if as_json:
        import json

        click.echo(json.dumps((result or {}).get("findings") or [], indent=2))

    # A finding is what the user asked about, so a run that produced one is a
    # run whose answer is "no": `pc cae fea && ...` has to stop there, the same
    # way `pc test` exits non-zero on a failed test.
    if result and result.get("findings"):
        raise SystemExit(1)
