#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click
import asyncio
import json

import partcad as pc
from ...cli_context import CliContext


@click.command(help="Get capabilities of the provider")
@click.option(
    "--provider",
    "-p",
    metavar="provider[;param=value[,param=value]]",
    help="One or more providers to query for capabilities",
    multiple=True,
    show_envvar=True,
)
@click.pass_obj
def cli(cli_ctx: CliContext, provider):
    with pc.telemetry.set_context(cli_ctx.otel_context):
        ctx: pc.Context = cli_ctx.get_partcad_context()

        # TODO-109: Create tests for: Multiple provider scenarios
        # TODO-110: Create tests for: Error handling cases
        # TODO-111: Create tests for: Async behavior testing
        # TODO-112: Create tests for: Input validation
        with pc.logging.Process("SupplyCaps", "this"):
            for provider_spec in provider:
                p = ctx.get_provider(provider_spec)
                if not p:
                    pc.logging.error(f"Provider {provider_spec} not found.")
                    return
                req = pc.provider_request_caps.ProviderRequestCaps()
                caps = asyncio.run(p.query_caps(req))
                pc.logging.info(f"{provider_spec}: {json.dumps(caps, indent=4)}")
            else:
                pc.logging.info("No providers specified.")
