#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from . import emit, read, workspace


@click.command(help="Draft a new issue for a defect in PartCAD, as JSON, without the user's paths or credentials")
@click.option("--error", "error", required=True, help="The error message")
@click.option("--traceback", "traceback_path", type=click.Path(allow_dash=True), help="A file holding the traceback")
@click.option("--summary", help="What was being done, and what happened")
@click.option("--reproduction", help="The smallest steps or files that show it, with none of the user's own")
@click.option("--method", help="The command or daemon method that failed")
@click.option("--title", help="The issue's title; the error's first line otherwise")
@click.option("--agent", help="The agent filing it")
@click.pass_obj
def cli(cli_ctx, error, traceback_path, summary, reproduction, method, title, agent) -> None:
    from partcad_client import issues

    try:
        emit(
            issues.draft(
                error,
                read(traceback_path),
                summary,
                reproduction,
                method,
                agent=agent,
                workspace=workspace(cli_ctx),
                title=title,
            )
        )
    except issues.Unavailable as e:
        raise click.ClickException(str(e)) from e
