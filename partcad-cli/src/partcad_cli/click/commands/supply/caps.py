import rich_click as click
from partcad import logging
import asyncio
import json
import partcad as pc

from partcad.provider_request_caps import ProviderRequestCaps
from partcad.sentry import tracer as pc_tracer


@click.command(help="Get capabilities of the provider")
@click.option(
    "--providers",
    "-p",
    metavar="provider[;key=value]",
    help="Providers to query for capabilities",
    multiple=True,
    show_envvar=True,
)
@click.pass_obj
@pc_tracer.start_as_current_span("Command [pc supply caps]")
def cli(ctx, providers):
    # TODO-109: Create tests for: Multiple provider scenarios
    # TODO-110: Create tests for: Error handling cases
    # TODO-111: Create tests for: Async behavior testing
    # TODO-112: Create tests for: Input validation
    with logging.Process("SupplyCaps", "this"):
        for provider_spec in providers:
            provider = ctx.get_provider(provider_spec)
            if not provider:
                pc.logging.error(f"Provider {provider} not found.")
                return
            req = ProviderRequestCaps()
            caps = asyncio.run(provider.query_caps(req))
            pc.logging.info(f"{provider_spec}: {json.dumps(caps, indent=4)}")
