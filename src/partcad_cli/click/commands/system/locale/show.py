#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import json

import rich_click as click

from ....locale_state import describe, state


@click.command(help="Show where you are, as this computer's configuration says it")
@click.option("--json", "as_json", is_flag=True, help="Print JSON: what is configured, resolved and detected")
def cli(as_json: bool) -> None:
    """What the user configuration says about where the user is.

    It is the user's own address and location, printed in the user's own
    terminal: unlike `pc config`, which is what gets pasted into bug reports,
    nothing here is scrubbed.
    """
    answer = state()
    if as_json:
        click.echo(json.dumps(answer, indent=2))
        return
    for line in describe(answer):
        click.echo(line)
