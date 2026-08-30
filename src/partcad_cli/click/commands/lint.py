#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc lint` -- run PartCAD's checks, over a package or over named files.

The two modes sit on opposite sides of the command boundary, and that is the
whole reason both exist.

Checking a **package** means walking the package graph -- which packages,
resolved how, with which files -- so it is daemon work like any other, and
`--recursive` reaches imported packages the client has never seen.

Checking a **file** is not. An ASSY file is a Jinja2 template rendered to YAML
and matched against a schema: pure text work, no package graph, no CAD runtime.
The file is the client's own, sometimes not even saved yet (`--stdin`), and the
moment it most needs checking is when the package will not load *because* of it.
So `--file` never leaves this process: it runs `partcad_client.lint` here, which
is the same checker the daemon runs over a package, and is what the VS Code
extension reaches by running this command.

One thing the daemon does know and this side has to work out: whether the file
is an assembly or a scene, because a scene is checked against the same schema
with `how` forbidden. `--schema` says which; `auto`, the default, reads the
`partcad.yaml` files around the file to find out (see
`partcad_client.lint.detect_flavor`).
"""

import json
import sys

import rich_click as click

from ..service import run


@click.command(help="Run linting checks on files within packages")
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
    help="Recursively performs lint checks on all imported packages",
)
@click.option(
    "--filter",
    "-f",
    help="Only run lint checks that start with the given prefix",
    type=str,
    show_envvar=True,
    default=None,
)
@click.option(
    "--file",
    "file_paths",
    multiple=True,
    type=str,
    metavar="PATH",
    help="Check these files here, without a daemon, instead of a package. May be repeated.",
)
@click.option(
    "--stdin",
    is_flag=True,
    help="Read the content of the single --file from standard input (an editor's unsaved buffer).",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Print the findings of --file as JSON, with zero-based line/column numbers.",
)
@click.option(
    "--schema",
    "flavor",
    type=click.Choice(["auto", "assembly", "scene"]),
    default="auto",
    show_default=True,
    help=(
        "Which schema to check an ASSY --file against: the full one ('assembly'), "
        "the same one without 'how' ('scene'), or whichever the packages around the file "
        "say it is ('auto')."
    ),
)
@click.pass_context
def cli(
    click_ctx, package: str, recursive: bool, filter: str, file_paths, stdin: bool, as_json: bool, flavor: str
) -> None:
    if file_paths:
        if package or recursive:
            raise click.UsageError("--file checks the files named on the command line; --package/-r check a package")
        _lint_files(click_ctx, list(file_paths), stdin, as_json, flavor)
        return

    if stdin or as_json:
        raise click.UsageError("--stdin and --json only apply to --file")

    run(
        click_ctx.obj,
        "lint.run",
        {"package": package, "recursive": recursive, "filter": filter},
        needs_context=True,
    )


def _lint_files(click_ctx, paths: list, stdin: bool, as_json: bool, flavor: str = "auto") -> None:
    """Check the named files in this process and report what came back."""
    text = None
    if stdin:
        if len(paths) != 1:
            raise click.UsageError("--stdin supplies the content of one file; name exactly one --file")
        text = sys.stdin.read()

    # Deferred: `pc --help` imports every command module to print its short help,
    # and this one pulls in jsonschema and jinja2.
    from partcad_client import lint as client_lint

    try:
        reports = client_lint.check_files(paths, text, None if flavor == "auto" else flavor)
    except (OSError, IOError, UnicodeDecodeError) as e:
        raise click.UsageError(str(e))

    if as_json:
        # Machine-readable and self-contained, so a caller needs neither the log
        # stream nor the exit code to know what was found. Printed even when
        # nothing was: an empty list is the answer "this file is clean".
        click.echo(json.dumps({"files": [report.to_dict() for report in reports]}))
        if any(report.failed for report in reports):
            click_ctx.exit(1)
        return

    _report(reports)


def _report(reports: list) -> None:
    """Print the findings the way the package-wide checks print theirs.

    Through the logging subsystem rather than `click.echo`, so a failure sets the
    same `had_errors` flag every other command uses and `pc lint --file` exits
    non-zero for exactly the same reason `pc lint` does.
    """
    from partcad_utils import assy_lint
    from partcad_utils import logging as pc_logging

    for report in reports:
        if not report.checked:
            pc_logging.info("%s: no PartCAD checks apply to this file type" % report.path)
            continue
        for diagnostic in report.diagnostics:
            message = diagnostic.format(report.path)
            if diagnostic.severity == assy_lint.SEVERITY_WARNING:
                pc_logging.warning(message)
            else:
                pc_logging.error(message)
