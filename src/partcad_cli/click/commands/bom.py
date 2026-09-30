#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import json
import sys

import rich_click as click

from ..service import run


@click.command(help="Print the bill of materials of an assembly or a scene")
@click.option(
    "-P",
    "--package",
    "package",
    type=str,
    help="Package to retrieve the object from",
    default=None,
    show_envvar=True,
)
@click.option(
    "-j",
    "--json",
    "api",
    is_flag=True,
    help="Produce JSON output",
    show_envvar=True,
)
@click.option(
    "-s",
    "--stop-at-purchasable",
    "stop_at_purchasable",
    is_flag=True,
    help="Do not expand a sub-assembly that can be purchased as a whole "
    "(it declares a vendor and an SKU, and a supplier has it available); "
    "list it as a single line item instead",
    show_envvar=True,
)
@click.option(
    "-p",
    "--param",
    "params",
    type=str,
    multiple=True,
    metavar="<name>=<value>",
    help="Assign a value to the parameter",
    show_envvar=True,
)
@click.argument("object", type=str, required=True)  # help="Assembly to print the bill of materials of"
@click.pass_obj
def cli(cli_ctx, package: str, api: bool, stop_at_purchasable: bool, params: tuple[str, ...], object: str) -> None:
    result = run(
        cli_ctx,
        "bom",
        {
            "package": package,
            "object": object,
            "params": list(params),
            "stop_at_purchasable": stop_at_purchasable,
            "json": api,
        },
        needs_context=True,
    )

    # The human-readable table is rendered by the daemon, through the same
    # logging path as `pc list`. JSON goes to stdout instead, so it can be piped
    # into `jq` no matter where the logs are sent.
    if api and result is not None:
        sys.stdout.write(json.dumps(result, indent=4) + "\n")
        sys.stdout.flush()
