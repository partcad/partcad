#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Where the user is, what they read and what they pay in: the country, language, currency and location options.

A store, a catalog or anything else a plugin is a client of is a different
thing in different places - another range, other prices in other money, a page
in another language, the shop round the corner. So 'UserConfig' carries four
options that say where the user is, and this module is what makes sense of
them:

- ``country``: an ISO 3166-1 alpha-2 code, upper case ('NL', 'US');
- ``language``: an ISO 639-1 code, lower case ('en', 'nl');
- ``currency``: an ISO 4217 code, upper case ('EUR', 'USD');
- ``location``: where the user is on Earth, ``{"latitude": .., "longitude": ..}``
  in degrees.

The first three are worked out on the machine of whoever runs the command - the
client - when the configuration does not say: the country and the language from
the process's locale ('nl_NL.UTF-8'), the currency from the country. A daemon
serving that client is handed the client's values with the rest of its
configuration and works nothing out of its own. The location is never worked
out: it is the user's to give, as it is what a plugin must never be told (see
'UserConfig.user_info').

Plain Python: a client must stay cheap to import, and this is read by both.
"""

import locale
import os
import re

# A country's currency, for the countries a user is most likely to be in. A
# country missing here has no currency worked out for it, and says so by
# leaving the option unset: a wrong currency is worse than none.
CURRENCY_OF_COUNTRY = {
    # The euro area.
    **{
        country: "EUR"
        for country in ("AT BE HR CY EE FI FR DE GR IE IT LV LT LU MT NL PT SK SI ES AD MC SM VA ME XK".split())
    },
    "US": "USD",
    "CA": "CAD",
    "MX": "MXN",
    "GB": "GBP",
    "CH": "CHF",
    "LI": "CHF",
    "NO": "NOK",
    "SE": "SEK",
    "DK": "DKK",
    "IS": "ISK",
    "PL": "PLN",
    "CZ": "CZK",
    "HU": "HUF",
    "RO": "RON",
    "BG": "BGN",
    "RS": "RSD",
    "UA": "UAH",
    "TR": "TRY",
    "IL": "ILS",
    "AE": "AED",
    "SA": "SAR",
    "QA": "QAR",
    "KW": "KWD",
    "BH": "BHD",
    "OM": "OMR",
    "JO": "JOD",
    "EG": "EGP",
    "MA": "MAD",
    "ZA": "ZAR",
    "IN": "INR",
    "CN": "CNY",
    "HK": "HKD",
    "TW": "TWD",
    "JP": "JPY",
    "KR": "KRW",
    "SG": "SGD",
    "MY": "MYR",
    "TH": "THB",
    "ID": "IDR",
    "PH": "PHP",
    "VN": "VND",
    "AU": "AUD",
    "NZ": "NZD",
    "BR": "BRL",
    "AR": "ARS",
    "CL": "CLP",
    "CO": "COP",
    "PE": "PEN",
    "DO": "DOP",
    "PR": "USD",
}

# What a locale's language is when the locale says nothing worth reading.
_NOT_A_LOCALE = {"", "c", "posix"}

_LOCALE = re.compile(r"^([A-Za-z]{2,3})(?:[_-]([A-Za-z]{2}))?(?:[.@].*)?$")


def country_code(value):
    """An ISO 3166-1 alpha-2 code from what was configured ('nl' -> 'NL'), or None for one that is not one."""
    value = str(value or "").strip().upper()
    return value if re.fullmatch(r"[A-Z]{2}", value) else None


def language_code(value):
    """An ISO 639-1 code from what was configured ('EN', 'en-GB', 'en_GB.UTF-8' -> 'en'), or None."""
    found = _LOCALE.match(str(value or "").strip())
    if not found or len(found.group(1)) != 2:
        return None
    return found.group(1).lower()


def currency_code(value):
    """An ISO 4217 code from what was configured ('eur' -> 'EUR'), or None for one that is not one."""
    value = str(value or "").strip().upper()
    return value if re.fullmatch(r"[A-Z]{3}", value) else None


def currency_of(country):
    """The currency of a country, when it is one of CURRENCY_OF_COUNTRY's; else None."""
    return CURRENCY_OF_COUNTRY.get(country_code(country) or "")


def location(value):
    """'{latitude, longitude}' from what was configured - a mapping, a pair, or '52.37,4.89' - or None.

    Anything that is not a place on Earth is None rather than an error: it is
    asked for by a plugin choosing a shop, and the plugin can do without it.
    """
    if isinstance(value, dict):
        latitude, longitude = value.get("latitude", value.get("lat")), value.get("longitude", value.get("lng"))
    elif isinstance(value, (list, tuple)) and len(value) == 2:
        latitude, longitude = value
    elif isinstance(value, str) and value.count(",") == 1:
        latitude, longitude = value.split(",")
    else:
        return None
    try:
        latitude, longitude = float(latitude), float(longitude)
    except (TypeError, ValueError):
        return None
    if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
        return None
    return {"latitude": latitude, "longitude": longitude}


def _locale_names():
    """The locale names the process was started with, most specific first."""
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        yield os.environ.get(name, "")
    # 'LANGUAGE' is a list of languages a user reads, best first.
    yield os.environ.get("LANGUAGE", "").split(":")[0]
    try:
        yield locale.getlocale()[0] or ""
    except (ValueError, TypeError):  # pragma: no cover - a locale Python cannot parse
        pass


def detect():
    """(country, language) from the process's locale, each None when the locale does not say.

    'nl_NL.UTF-8' is ('NL', 'nl'); 'C' and 'POSIX' say nothing; a locale that
    names a language and no country ('en') gives the language alone.
    """
    country = language = None
    for name in _locale_names():
        name = (name or "").strip()
        if name.lower() in _NOT_A_LOCALE:
            continue
        found = _LOCALE.match(name)
        if not found:
            continue
        language = language or language_code(found.group(1))
        country = country or country_code(found.group(2))
        if country and language:
            break
    return country, language
