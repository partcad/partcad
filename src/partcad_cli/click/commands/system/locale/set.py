#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import json

import rich_click as click

from partcad_utils import logging as pc_logging
from partcad_utils import telemetry as pc_telemetry
from partcad_utils import user_locale
from partcad_utils.user_config import save_options

from ....locale_state import state

# The address options, by the field of the 'user' section each one sets.
ADDRESS_OPTIONS = {
    "line1": "line1",
    "line2": "line2",
    "city": "city",
    "state_code": "stateCode",
    "zip_code": "zipCode",
    "address_country": "countryCode",
}


def _code(value, parse, what):
    """'' to remove, or the code 'parse' makes of it - and a usage error for something that is not one."""
    if value is None or value.strip() == "":
        return None
    code = parse(value)
    if code is None:
        raise click.BadParameter("'%s' is not %s" % (value, what))
    return code


@click.command(help="Set where you are. Each option given is written; an empty value removes it")
@click.option("--country", help="Your country, as an ISO 3166-1 code (NL)")
@click.option("--language", help="The language you read, as an ISO 639-1 code (en)")
@click.option("--currency", help="What you pay in, as an ISO 4217 code (EUR)")
@click.option("--location", help="Where you are, as 'latitude,longitude' in degrees (52.37,4.89)")
@click.option(
    "--location-access/--no-location-access",
    default=None,
    help="Whether PartCAD may ask this computer's location service where it is",
)
@click.option(
    "--manufacturing-orders",
    help="What you use PartCAD for: 'place' (order manufacturing), 'handle' (handle orders), both, or 'none'",
)
@click.option("--line1", help="The first line of your address")
@click.option("--line2", help="The second line of your address")
@click.option("--city", help="Your city")
@click.option("--state-code", help="Your state, province or region, as its code (NH)")
@click.option("--zip-code", help="Your ZIP or postal code")
@click.option("--address-country", help="Your address' country, as an ISO 3166-1 code (NL)")
@click.option("--json", "as_json", is_flag=True, help="Print JSON: what is configured afterwards, as 'show' does")
@click.pass_obj
def cli(cli_ctx, as_json, location_access, manufacturing_orders, **values) -> None:
    """Write what was given into the user configuration, and nothing else.

    "Blank" is an empty value, and it removes the option: a country left blank
    is worked out from this computer's language and region again, a location
    left blank is none. That is what the IDE's form sends for a field the user
    emptied, and what it sends for everything when they said they only design.
    """
    options = {}
    if values["country"] is not None:
        options["country"] = _code(values["country"], user_locale.country_code, "a country code")
    if values["language"] is not None:
        options["language"] = _code(values["language"], user_locale.language_code, "a language code")
    if values["currency"] is not None:
        options["currency"] = _code(values["currency"], user_locale.currency_code, "a currency code")
    user = {}
    if values["location"] is not None:
        options["location"] = _code(values["location"], user_locale.location, "'latitude,longitude' in degrees")
        # The other place a location is read from: left there, it would still
        # be the location after this one was removed.
        user["location"] = None
    if location_access is not None:
        options["locationAccess"] = location_access
    if manufacturing_orders is not None:
        words = manufacturing_orders.strip().lower()
        orders = user_locale.manufacturing_orders(words)
        if words and words != user_locale.NO_MANUFACTURING_ORDERS and not orders:
            raise click.BadParameter("'%s' is none of 'place', 'handle' and 'none'" % manufacturing_orders)
        # Blank is "not asked", which is how somebody asks to be asked again.
        options["manufacturingOrders"] = orders if words else None
    for option, field in ADDRESS_OPTIONS.items():
        if values[option] is None:
            continue
        if option == "address_country":
            user[field] = _code(values[option], user_locale.country_code, "a country code")
        else:
            user[field] = values[option].strip() or None

    if not options and not user:
        raise click.UsageError("Nothing to set: give at least one option. 'pc system locale set --help' lists them.")

    with pc_telemetry.set_context(cli_ctx.otel_context):
        with pc_logging.Process("SysSetLocale", "global"):
            path = save_options(options, user)
            pc_logging.info("Saved to %s" % path)
    if as_json:
        click.echo(json.dumps(state(), indent=2))
