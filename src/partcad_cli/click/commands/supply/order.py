#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click

import partcad as pc
from ...cli_context import CliContext


@click.command(help="Order from suppliers")
@click.pass_obj
def cli(cli_ctx: CliContext) -> None:
    with pc.telemetry.set_context(cli_ctx.otel_context):
        # ctx: pc.Context = cli_ctx.get_partcad_context()

        with pc.logging.Process("SupplyOrder", "this"):
            # TODO-113: Implement Supplier validation
            # TODO-114: Implement Order processing
            # TODO-115: Implement Error handling
            # TODO-116: Implement Success confirmation
            pass
