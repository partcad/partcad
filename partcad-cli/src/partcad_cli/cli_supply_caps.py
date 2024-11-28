#
# OpenVMP, 2024
#
# Author: PartCAD Inc. <support@partcad.org>
# Created: 2024-09-07
#
# Licensed under Apache License, Version 2.0.
#

import asyncio
import json
import partcad as pc

from partcad.provider_request_caps import ProviderRequestCaps


def cli_help_supply_caps(subparsers):
    parser = subparsers.add_parser(
        "caps",
        help="Get capabilities of the provider",
    )
    parser.add_argument(
        "providers",
        metavar="provider[;key=value]",
        help="Providers to query for capabilities",
        nargs="+",
    )


def cli_supply_caps(args, ctx):
    for provider_spec in args.providers:
        provider = ctx.get_provider(provider_spec)
        req = ProviderRequestCaps()
        caps = asyncio.run(provider.query_caps(req))
        pc.logging.info(f"{provider_spec}: {json.dumps(caps, indent=4)}")
