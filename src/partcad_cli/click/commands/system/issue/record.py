#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

from . import emit


@click.command(help="Remember that a defect's issue was filed or upvoted from this machine")
@click.argument("signature")
@click.argument("issue", type=int)
@click.option("--upvoted", is_flag=True, help="It was upvoted rather than filed")
def cli(signature, issue, upvoted) -> None:
    from partcad_client import issues

    try:
        entry = issues.record(signature, issue, "upvoted" if upvoted else "filed")
    except ValueError as e:
        raise click.BadParameter(str(e), param_hint="SIGNATURE") from e
    emit({"signature": signature, **entry})
