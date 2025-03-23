#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click
import asyncio
import json
from typing import Any, List

import partcad as pc
from ...cli_context import CliContext


@click.command(help="Find suppliers")
@click.option(
    "--json",
    "-j",
    "api",
    help="Produce JSON output",
    is_flag=True,
    show_envvar=True,
)
@click.option(
    "--qos",
    help="Requested quality of service",
    show_envvar=True,
)
@click.option(
    "--provider",
    help="Provider to use",
    show_envvar=True,
)
@click.argument(
    "specs",
    metavar="object[[,material],count]",
    nargs=-1,
)  # help="Part (default) or assembly to quote, with options"
@click.pass_obj
def cli(cli_ctx: CliContext, api: bool, qos: str, provider: str, specs: List[str]) -> None:
    with pc.telemetry.set_context(cli_ctx.otel_context):
        ctx: pc.Context = cli_ctx.get_partcad_context()

        with pc.logging.Process("SupplyFind", "this"):
            cart = pc.ProviderCart()
            asyncio.run(cart.add_objects(ctx, specs))

            suppliers = {}
            if provider:
                provider = ctx.get_provider(provider)
                if not provider:
                    pc.logging.error(f"Provider {provider} not found.")
                    return
                if not provider.is_qos_available(qos):
                    pc.logging.error(f"Provider {provider.name} cannot provide qos: {qos}.")
                asyncio.run(provider.load(cart))
                for part_spec in cart.parts.values():
                    suppliers[str(part_spec)] = []
                    if not asyncio.run(provider.is_part_available(part_spec)):
                        pc.logging.error(f"Provider {provider.name} cannot provide {part_spec.name}.")
                        return
                    suppliers[str(part_spec)].append(provider.name)
            else:
                suppliers = asyncio.run(ctx.find_suppliers(cart, qos))
                pc.logging.debug(f"Suppliers: {suppliers}")

            if api:
                print(json.dumps(suppliers))
            else:
                pc.logging.info("The requested parts are available through the following suppliers:")
                for spec_str, supplier_list in suppliers.items():
                    suppliers_str = ""
                    for supplier in supplier_list:
                        suppliers_str += "\n\t\t" + str(supplier)
                    pc.logging.info(f"{spec_str}:{suppliers_str}")
