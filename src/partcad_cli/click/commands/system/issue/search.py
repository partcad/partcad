#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from . import emit, read, workspace


@click.command(help="Find PartCAD's issues for a defect, as JSON; only maintainers' comments are shown")
@click.option("--signature", help="The defect's 'pc-sig:...'; worked out from --error and --traceback otherwise")
@click.option("--error", "error", help="The error message")
@click.option("--traceback", "traceback_path", type=click.Path(allow_dash=True), help="A file holding the traceback")
@click.pass_obj
def cli(cli_ctx, signature, error, traceback_path) -> None:
    from partcad_client import issues

    traceback = read(traceback_path)
    if not signature and not error and not traceback:
        raise click.UsageError("Give --signature, --error or --traceback")
    if not signature:
        signature = issues.signature(error, traceback)
    try:
        emit(issues.search(signature, error, workspace(cli_ctx)))
    except issues.Unavailable as e:
        raise click.ClickException(str(e)) from e
