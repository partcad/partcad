#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""PartCAD's side of what any plugin may ask about the user, inside the sandbox: the 'partcad_user' callback.

Every plugin is run with 'request["userInfo"]', what PartCAD tells it about the
user - their country, state and city, the language they read and the currency
they pay in - and nothing finer: no name, no street, no ZIP code, no location
(see 'UserConfig.user_info'). That is enough to answer in the right country's
range and prices, and not enough to choose between a store's shops in one city.

So a plugin that has places to choose between - a store's shops - asks PartCAD
to choose, with 'partcad_user.choose_place(places)', in its globals:

    shop = partcad_user.choose_place(
        [{"id": "088", "latitude": 52.3, "longitude": 4.9, "city": "Amsterdam", "state": "NLNH"}, ...],
        what="store",
    )

and is answered with the 'id' of the one nearest the user - by their location,
else their address - or None when PartCAD cannot tell (see
'partcad.locality'). It learns which of its own places was chosen, never where
the user is.

PartCAD has the user's configuration and the sandbox does not, so the call
cannot simply return. It is a replay, the way 'partcad_login.open_browser' is:
the first time 'choose_place' is called it raises 'PlaceNeeded', carrying the
places; PartCAD chooses, and runs the plugin again from the top with the
answer to hand, which the same call then returns. The n-th call returns the
n-th answer. So a plugin has to be the same up to each call - which reading a
list of shops is.

'PlaceNeeded' is a 'BaseException', for the same reason 'KeyboardInterrupt' is
one: it is not a failure, and a plugin's 'except Exception' around its whole
body must not turn it into one.
"""

# The most places one call may hand over (see 'partcad.locality.MAX_PLACES').
MAX_PLACES = 1000
# What a place may say about itself, besides its 'id'. Anything else is left
# out of what PartCAD is handed: it has no use for it.
PLACE_FIELDS = ("name", "latitude", "longitude", "lat", "lng", "zip", "city", "state")


class PlaceNeeded(BaseException):
    """The plugin asked which of its places is nearest: PartCAD is to choose, and run the plugin again."""

    def __init__(self, spec):
        super().__init__("which %s is nearest the user is PartCAD's to say" % spec.get("what"))
        self.spec = spec


def place_spec(places, what):
    """What PartCAD is handed for 'choose_place': the places, checked, with what each says about where it is."""
    if not isinstance(places, (list, tuple)):
        raise ValueError("choose_place: 'places' must be a list of places, not %r" % type(places).__name__)
    if len(places) > MAX_PLACES:
        raise ValueError("choose_place: at most %d places, not %d" % (MAX_PLACES, len(places)))
    checked = []
    for index, place in enumerate(places):
        if not isinstance(place, dict) or place.get("id") in (None, ""):
            raise ValueError("choose_place: place %d has no 'id'" % index)
        entry = {"id": str(place["id"])}
        for field in PLACE_FIELDS:
            if place.get(field) not in (None, ""):
                entry[field] = place[field]
        checked.append(entry)
    return {"what": str(what or "place"), "places": checked}


class UserCallback:
    """'partcad_user' in a plugin's globals: PartCAD's answers about the user, replayed."""

    PlaceNeeded = PlaceNeeded

    def __init__(self, state=None):
        state = state or {}
        self._answers = [dict(answer or {}) for answer in state.get("places") or []]
        self._asked = 0

    def choose_place(self, places, what="place"):
        """The 'id' of the one of 'places' nearest the user, or None when PartCAD cannot tell which that is."""
        spec = place_spec(places, what)
        if not spec["places"]:
            return None
        index = self._asked
        self._asked += 1
        if index < len(self._answers):
            return self._answers[index].get("id")
        raise PlaceNeeded(spec)
