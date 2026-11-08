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
the process's locale ('nl_NL.UTF-8'), the currency from the country. A process
whose environment names no locale - one started from the Dock or the Start menu,
which is how an editor usually is - asks the operating system for the one the
user chose in its settings instead (see '_os_locale_name'). A daemon serving
that client is handed the client's values with the rest of its configuration
and works nothing out of its own. The location is never worked out from any of
that: it is the user's to give, as it is what a plugin must never be told (see
'UserConfig.user_info') - typed in, or asked of this machine's location service
when the user has said PartCAD may ('locationAccess', 'partcad_client.location').

Two more options say whether any of this is wanted at all, and they are what
the IDE's first-run question writes:

- ``locationAccess``: whether PartCAD may ask this machine's operating system
  where it is. Off unless the user turns it on;
- ``manufacturingOrders``: what the user said they use PartCAD for -
  ``place`` (ordering the manufacturing of parts and assemblies) and/or
  ``handle`` (handling such orders themselves). An empty list is an answer -
  "neither, I design" - and the option missing altogether is "never asked".

Plain Python: a client must stay cheap to import, and this is read by both.
"""

import locale
import math
import os
import re
import sys

from .booleans import to_bool

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
    """The locale names the process was started with, most specific first, and then the operating system's."""
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        yield os.environ.get(name, "")
    # 'LANGUAGE' is a list of languages a user reads, best first.
    yield os.environ.get("LANGUAGE", "").split(":")[0]
    try:
        yield locale.getlocale()[0] or ""
    except (ValueError, TypeError):  # pragma: no cover - a locale Python cannot parse
        pass
    # Last, and only reached when everything above left the country or the
    # language unsaid: what the user chose in the operating system's settings.
    yield _os_locale_name()


# A script subtag ('Hans' in 'zh-Hans-CN'), which says how a language is
# written rather than which one it is or where.
_SCRIPT = re.compile(r"[-_][A-Z][a-z]{3}(?=[-_@.]|$)")


def _os_locale_name():
    """The locale the user chose in the operating system's own settings, as 'en_NL', or '' where there is none.

    POSIX has no such thing beside the environment above, which is where its
    desktops put it. Windows and macOS do: a process started from the Start
    menu or the Dock has no 'LANG' at all, and on Windows 'locale.getlocale()'
    answers 'English_United States', which names no code. Both are asked
    through the system's own library, in process - no command is run - so it
    costs nothing to ask on every start of a client.

    The country is the system's *region* where the system keeps one apart from
    the language, which is where the user is rather than how they want numbers
    written: English with the region set to the Netherlands is 'en_NL'.
    """
    try:
        if sys.platform == "win32":
            name = _windows_locale_name()
        elif sys.platform == "darwin":
            name = _macos_locale_name()
        else:
            return ""
    except Exception:  # pylint: disable=broad-except  # a system that will not say says nothing
        return ""
    return _SCRIPT.sub("", name or "")


def _windows_locale_name():  # pragma: no cover - Windows only
    import ctypes

    kernel32 = ctypes.windll.kernel32
    buffer = ctypes.create_unicode_buffer(85)  # LOCALE_NAME_MAX_LENGTH
    if not kernel32.GetUserDefaultLocaleName(buffer, len(buffer)):
        return ""
    language = buffer.value.split("-")[0]
    # Settings > Time & language > Region > "Country or region".
    GEOCLASS_NATION, GEO_ISO2, GEOID_NOT_AVAILABLE = 16, 4, -1
    geo = kernel32.GetUserGeoID(GEOCLASS_NATION)
    region = ctypes.create_unicode_buffer(8)
    if geo != GEOID_NOT_AVAILABLE and kernel32.GetGeoInfoW(geo, GEO_ISO2, region, len(region), 0):
        return "%s_%s" % (language, region.value)
    return buffer.value.replace("-", "_")


def _macos_locale_name():  # pragma: no cover - macOS only
    import ctypes

    foundation = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    foundation.CFLocaleCopyCurrent.restype = ctypes.c_void_p
    foundation.CFLocaleGetIdentifier.restype = ctypes.c_void_p
    foundation.CFLocaleGetIdentifier.argtypes = [ctypes.c_void_p]
    foundation.CFStringGetCString.restype = ctypes.c_bool
    foundation.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
    foundation.CFRelease.argtypes = [ctypes.c_void_p]
    K_CF_STRING_ENCODING_UTF8 = 0x08000100

    current = foundation.CFLocaleCopyCurrent()
    if not current:
        return ""
    try:
        # 'en_NL', or 'en_US@rg=nlzzzz' where the region was set apart from
        # the language - and the region is what '_LOCALE' reads either way.
        identifier = foundation.CFLocaleGetIdentifier(current)
        buffer = ctypes.create_string_buffer(128)
        if identifier and foundation.CFStringGetCString(identifier, buffer, len(buffer), K_CF_STRING_ENCODING_UTF8):
            name = buffer.value.decode("utf-8")
            region = re.search(r"@(?:.*;)?rg=([a-z]{2})zzzz", name)
            if region:
                return "%s_%s" % (name.split("_")[0].split("@")[0], region.group(1).upper())
            return name
    finally:
        foundation.CFRelease(current)
    return ""


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


# What someone uses PartCAD for, of the two things that need to know where they
# are: ordering the manufacturing of parts and assemblies, and handling such
# orders themselves. See 'manufacturing_orders'.
MANUFACTURING_ORDERS = ("place", "handle")

# What says "neither": an empty list in the file, or this word where a list
# cannot be written (PC_MANUFACTURING_ORDERS, a command line).
NO_MANUFACTURING_ORDERS = "none"


def manufacturing_orders(value):
    """What the user said they use PartCAD for, as a list in MANUFACTURING_ORDERS' order - or None, never asked.

    A list (``[place, handle]``), or text of them separated by commas or
    whitespace ("place,handle"), which is what an environment variable has to
    carry. An empty list and 'none' are both "neither": the question was
    answered, and the answer is that nothing here is wanted. An empty string -
    which is how a configuration that has never been told is handed on to the
    daemon - is None. A word that is not one of the two is dropped rather than
    failing every command over a typo in a file.
    """
    if value is None:
        return None
    if isinstance(value, str):
        if not value.strip():
            return None
        words = re.split(r"[\s,]+", value.strip().lower())
    elif isinstance(value, (list, tuple, set)):
        words = [str(word).strip().lower() for word in value]
    else:
        return None
    return [order for order in MANUFACTURING_ORDERS if order in words]


def location_access(value):
    """Whether PartCAD may ask the operating system where this machine is: only when somebody said yes."""
    return to_bool(value) if value not in (None, "") else False


def rounded_location(value, places=2):
    """A location rounded to 'places' decimals - two is about a kilometre - or None for one that is not a place.

    What is kept of a location asked of the operating system: enough to tell
    which shop is nearest, which is all PartCAD uses it for, and not enough to
    find a front door.
    """
    found = location(value)
    if found is None:
        return None
    return {key: round(found[key], places) for key in ("latitude", "longitude")}


EARTH_RADIUS_KM = 6371.0088


def distance_km(a, b):
    """The great-circle distance between two (latitude, longitude) pairs in degrees, in kilometres.

    Here rather than in 'partcad.locality', which chooses a plugin's nearest
    shop with it, because the client that asks the location service needs it
    too (see 'moved') and must stay cheap to import.
    """
    (lat1, lng1), (lat2, lng2) = [(math.radians(x), math.radians(y)) for x, y in (a, b)]
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, h)))


# How far apart two answers for one place may be with nobody having moved, in
# kilometres, before the service's own accuracy is counted: each was rounded to
# two decimals, which is up to about 0.8 km apiece.
MOVED_KM = 2.0


def moved(saved, found, accuracy_m=None):
    """Whether 'found' - a location the system just gave - is somewhere else than 'saved'.

    Not "is it a different number": a location service does not give the same
    answer twice. GeoClue blurs a neighbourhood-level answer by up to the
    accuracy it states, on purpose, and a Wi-Fi fix wanders by tens of metres -
    either of which crosses a two-decimal rounding often enough to rewrite the
    configuration on every ask, and writing it restarts the daemon that read
    it. Two answers for one place can each be off by the accuracy the service
    states, in opposite directions, so it has moved only when it is further from
    where it was than twice that, and than MOVED_KM.
    """
    saved, found = location(saved), location(found)
    if saved is None or found is None:
        return found is not None
    try:
        accuracy_km = max(float(accuracy_m or 0), 0.0) / 1000.0
    except (TypeError, ValueError):
        accuracy_km = 0.0
    tolerance = MOVED_KM + 2 * accuracy_km
    return distance_km((saved["latitude"], saved["longitude"]), (found["latitude"], found["longitude"])) > tolerance
