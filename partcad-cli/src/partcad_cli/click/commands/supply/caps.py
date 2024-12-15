import rich_click as click
from partcad import logging
import asyncio
import json
import partcad as pc

from partcad.provider_request_caps import ProviderRequestCaps


@click.command(help="Get capabilities of the provider")
@click.option(
    "--providers", "-p", metavar="provider[;key=value]", help="Providers to query for capabilities", multiple=True
)
@click.pass_obj
def cli(ctx, providers):
    # TODO: Create tests for: Multiple provider scenarios
    # TODO: Create tests for: Error handling cases
    # TODO: Create tests for: Async behavior testing
    # TODO: Create tests for: Input validation
    with logging.Process("SupplyCaps", "this"):
        for provider_spec in providers:
            provider = ctx.get_provider(provider_spec)
            req = ProviderRequestCaps()
            caps = asyncio.run(provider.query_caps(req))
            pc.logging.info(f"{provider_spec}: {json.dumps(caps, indent=4)}")
