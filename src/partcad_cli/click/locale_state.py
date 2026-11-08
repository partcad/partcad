#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What `pc system locale` reports: what the file says, what PartCAD resolved, and what this machine says itself.

Three answers, because the editor's form needs all three: what the user wrote
(to fill the fields in with), what PartCAD will use (which is that, or what it
worked out), and what it would work out on its own (to say what leaving a field
blank means). Not imported by name from outside this directory - the leading
underscore keeps it out of the command list.
"""

import os

import click

from partcad_client import location as pc_location
from partcad_utils import user_locale
from partcad_utils.user_config import ADDRESS_FIELDS, UserConfig


def _file(path):
    """The configuration file, as a mapping, or an empty one where there is none or it is not one."""
    if not os.path.exists(path):
        return {}
    from ruamel.yaml import YAML

    try:
        with open(path, "r", encoding="utf-8") as f:
            document = YAML(typ="safe").load(f)
    except Exception as e:  # pylint: disable=broad-except
        raise click.ClickException("%s cannot be read: %s" % (path, e))
    return document if isinstance(document, dict) else {}


def state(config: UserConfig = None) -> dict:
    """Everything `show` reports, as plain data."""
    config = config or UserConfig()
    path = UserConfig.get_config_path()
    document = _file(path)
    user = document.get("user") if isinstance(document.get("user"), dict) else {}

    orders = user_locale.manufacturing_orders(document.get("manufacturingOrders"))
    configured_location = user_locale.location(document.get("location")) or user_locale.location(user.get("location"))
    detected_country, detected_language = user_locale.detect()
    return {
        "configFile": path,
        # The question the IDE asks the first time is asked while this is
        # missing from the file; an empty list is an answer.
        "asked": orders is not None,
        "manufacturingOrders": orders,
        "locationAccess": user_locale.location_access(document.get("locationAccess")),
        "configured": {
            "country": user_locale.country_code(document.get("country")),
            "language": user_locale.language_code(document.get("language")),
            "currency": user_locale.currency_code(document.get("currency")),
            "location": configured_location,
            "address": {field: str(user[field]) for field in ADDRESS_FIELDS if user.get(field) not in (None, "")},
        },
        "resolved": {
            "country": config.country,
            "language": config.language,
            "currency": config.currency,
            "location": config.location,
            "locationAccess": config.location_access,
        },
        "detected": {
            "country": detected_country,
            "language": detected_language,
            "currency": user_locale.currency_of(detected_country),
        },
        "locationService": pc_location.service(),
        "settings": pc_location.settings_command() is not None,
    }


def _where(configured, resolved, detected):
    if configured:
        return configured
    if resolved and resolved == detected:
        return "%s (worked out from this computer's language and region)" % resolved
    if resolved:
        return "%s (from the environment or the address)" % resolved
    return "not set"


def describe(answer: dict) -> list:
    """`show` for a person: one line each."""
    configured, resolved, detected = answer["configured"], answer["resolved"], answer["detected"]
    orders = answer["manufacturingOrders"]
    if orders is None:
        uses = "not asked yet"
    elif not orders:
        uses = "neither (designing only)"
    else:
        uses = " and ".join(
            {"place": "ordering manufacturing", "handle": "handling manufacturing orders"}[order] for order in orders
        )
    address = configured["address"]
    location = configured["location"] or resolved["location"]
    service = answer["locationService"]
    return [
        "Configuration file: %s" % answer["configFile"],
        "Used for: %s" % uses,
        "Country: %s" % _where(configured["country"], resolved["country"], detected["country"]),
        "Language: %s" % _where(configured["language"], resolved["language"], detected["language"]),
        "Currency: %s" % _where(configured["currency"], resolved["currency"], detected["currency"]),
        "Address: %s" % (", ".join(address[field] for field in ADDRESS_FIELDS if field in address) or "not set"),
        "Location: %s" % ("%s, %s" % (location["latitude"], location["longitude"]) if location else "not set"),
        "Location access: %s"
        % (
            ("on" if answer["locationAccess"] else "off")
            + (" (through %s)" % service if service else " (no location service on this computer)")
        ),
    ]
