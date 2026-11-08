#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import json

import rich_click as click

from partcad_client import location as pc_location


@click.command(help="Open this computer's location privacy settings")
@click.option("--json", "as_json", is_flag=True, help="Print JSON")
@click.pass_context
def cli(click_ctx, as_json: bool) -> None:
    """Where the system decides which applications may know where it is.

    Windows: Settings > Privacy & security > Location. macOS: System Settings >
    Privacy & Security > Location Services. GNOME: Settings > Privacy >
    Location. Another desktop has no such page PartCAD knows of, and is told so.
    """
    opened, detail = pc_location.open_settings()
    if as_json:
        click.echo(json.dumps({"opened": opened, "detail": detail}))
    else:
        click.echo(detail if not opened else "Opened %s" % detail, err=not opened)
    if not opened:
        click_ctx.exit(1)
