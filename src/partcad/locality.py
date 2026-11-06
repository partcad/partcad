#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Which of a plugin's places is nearest the user: PartCAD's answer to 'partcad_user.choose_place'.

A plugin is told the user's country, state and city and nothing finer (see
'UserConfig.user_info'). A store that has several shops in that city or state
has to pick one - for its stock, its opening hours, its address on a quote -
and the one to pick is the nearest, which only the user's address or location
says. So the plugin does not ask where the user is: it hands PartCAD the shops
it is choosing between, and PartCAD, which has the user's configuration, says
which one (see 'wrappers/plugin_callbacks.py' for the plugin's side). What the
plugin learns is a shop it named itself.

The choice, best evidence first:

1. 'location': the place nearest it, as the crow flies, of those that say
   where they are ('latitude'/'longitude', or 'lat'/'lng');
2. the address's ZIP code (its spaces aside), then its city, then its state:
   the first place that matches, in the order the plugin gave them;
3. otherwise none, and the plugin decides - and should say what it decided.

Nothing here asks anything of the network: an address is matched as it is
written, not looked up.
"""

import math

from . import logging as pc_logging

# How many places a plugin may hand over to choose between: a country's shops,
# not a gazetteer.
MAX_PLACES = 1000

EARTH_RADIUS_KM = 6371.0088


def _coordinates(place):
    latitude = place.get("latitude", place.get("lat"))
    longitude = place.get("longitude", place.get("lng"))
    try:
        latitude, longitude = float(latitude), float(longitude)
    except (TypeError, ValueError):
        return None
    if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
        return None
    return latitude, longitude


def distance_km(a, b):
    """The great-circle distance between two (latitude, longitude) pairs in degrees, in kilometres."""
    (lat1, lng1), (lat2, lng2) = [(math.radians(x), math.radians(y)) for x, y in (a, b)]
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, h)))


def _same(a, b, key=None):
    """Whether two names of a place are the same, as written: case aside, and for a ZIP code its spaces too."""
    if not a or not b:
        return False
    a, b = str(a).strip().casefold(), str(b).strip().casefold()
    if key == "zip":
        # '3825 HB' and '3825HB' are one Dutch postcode; '1012' is '1012'.
        a, b = "".join(a.split()), "".join(b.split())
    return a == b


def choose(user_config, spec) -> dict:
    """'{"id": <the chosen place's id or None>, "by": "location"|"zip"|"city"|"state"|None}' for a plugin's question.

    'spec' is what the plugin asked: '{"what": "store", "places": [{"id", ...}]}',
    each place with an 'id' and any of 'latitude'/'longitude', 'zip', 'city'
    and 'state'. The answer says how it was chosen and never says where the
    user is: not the distance, not the address it matched.
    """
    places = [p for p in (spec or {}).get("places") or [] if isinstance(p, dict) and p.get("id") is not None]
    what = str((spec or {}).get("what") or "place")
    if not places:
        return {"id": None, "by": None}
    if len(places) > MAX_PLACES:
        pc_logging.warning(
            "A plugin asked which of %d %ss is nearest; only the first %d are considered"
            % (len(places), what, MAX_PLACES)
        )
        places = places[:MAX_PLACES]

    here = getattr(user_config, "location", None)
    if here:
        origin = (here["latitude"], here["longitude"])
        located = []
        for index, place in enumerate(places):
            at = _coordinates(place)
            if at is not None:
                located.append((distance_km(origin, at), index, place))
        if located:
            return {"id": min(located)[2]["id"], "by": "location"}

    address = user_config.address() if hasattr(user_config, "address") else {}
    for field, key in (("zipCode", "zip"), ("city", "city"), ("stateCode", "state")):
        for place in places:
            if _same(place.get(key), address.get(field), key):
                return {"id": place["id"], "by": key}
    return {"id": None, "by": None}
