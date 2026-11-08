#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a quote may go without, which of a plugin's shops is nearest, and what a price is in.

- An optional item (what a scene holds, or anything under '--ignore-missing')
  that nobody supplies is left out of the quote and named, rather than quoted
  under "no provider".
- A plugin choosing between its shops is answered from the user's location,
  else their address, and is never told either ('partcad.locality').
- A quote always says its currency: the one it said, else the provider's
  declared one, else US dollars with a warning ('plugin_provider.with_currency').
"""

import logging
import types

import pytest

from partcad import locality
from partcad.context import Context
from partcad.plugin_provider import declared_currency, with_currency
from partcad.plugin_provider_data_cart import ProviderCart, ProviderCartItem

# ---- left out ----------------------------------------------------------------


def _item(name, count, optional):
    item = ProviderCartItem()
    item.name, item.count, item.optional = name, count, optional
    return item


def test_what_may_go_unsupplied_is_left_out_and_named():
    cart = ProviderCart()
    for item in (_item("//p:chair", 2, True), _item("//p:wall", 1, True), _item("//p:bolt", 4, False)):
        cart.add_item(item)
    preferred = {"//p:chair#2": "//shop:store", "//p:wall#1": "", "//p:bolt#4": ""}

    kept, left_out = Context.drop_unsupplied_optional(None, cart, preferred)

    # The wall is nobody's to sell and goes; the bolt is not optional, and is
    # still quoted under "no provider" - the failure it always was.
    assert kept == {"//p:chair#2": "//shop:store", "//p:bolt#4": ""}
    assert left_out == ["//p:wall"]


def test_nothing_is_left_out_of_a_cart_where_everything_is_supplied():
    cart = ProviderCart()
    cart.add_item(_item("//p:chair", 1, True))
    preferred = {"//p:chair#1": "//shop:store"}
    assert Context.drop_unsupplied_optional(None, cart, preferred) == (preferred, [])


# ---- which shop --------------------------------------------------------------

SHOPS = {
    "what": "store",
    "places": [
        {"id": "north", "latitude": 53.2, "longitude": 6.6, "city": "Groningen", "state": "GR", "zip": "9723"},
        {"id": "centre", "lat": 52.37, "lng": 4.89, "city": "Amsterdam", "state": "NH", "zip": "1012"},
        {"id": "south", "city": "Eindhoven", "state": "NB"},
    ],
}


def _user(location=None, **address):
    return types.SimpleNamespace(location=location, address=lambda: dict(address))


def test_the_nearest_of_the_places_that_say_where_they_are():
    assert locality.choose(_user({"latitude": 52.1, "longitude": 5.1}), SHOPS) == {"id": "centre", "by": "location"}
    assert locality.choose(_user({"latitude": 53.0, "longitude": 6.5}), SHOPS) == {"id": "north", "by": "location"}


@pytest.mark.parametrize(
    "address, expected",
    [
        ({"zipCode": "9723", "city": "Amsterdam"}, {"id": "north", "by": "zip"}),
        ({"zipCode": " 97 23 "}, {"id": "north", "by": "zip"}),
        ({"city": "amsterdam "}, {"id": "centre", "by": "city"}),
        ({"stateCode": "NB"}, {"id": "south", "by": "state"}),
        ({"city": "Paris"}, {"id": None, "by": None}),
        ({}, {"id": None, "by": None}),
    ],
)
def test_without_a_location_the_address_matches(address, expected):
    assert locality.choose(_user(**address), SHOPS) == expected


def test_no_places_no_choice():
    assert locality.choose(_user({"latitude": 0, "longitude": 0}), {"places": []}) == {"id": None, "by": None}
    assert locality.choose(_user(), None) == {"id": None, "by": None}


def test_the_answer_says_nothing_about_where_the_user_is():
    answer = locality.choose(_user({"latitude": 52.1, "longitude": 5.1}, city="Amsterdam"), SHOPS)
    assert set(answer) == {"id", "by"}


def test_distances_are_great_circle_kilometres():
    # Amsterdam to Groningen is about 146 km as the crow flies.
    assert locality.distance_km((52.37, 4.89), (53.22, 6.57)) == pytest.approx(146, abs=3)


def test_the_plugin_s_side_checks_what_it_hands_over():
    from partcad.wrappers import plugin_callbacks

    spec = plugin_callbacks.place_spec([{"id": 88, "city": "Delft", "phone": "+31"}], "store")
    assert spec == {"what": "store", "places": [{"id": "88", "city": "Delft"}]}
    with pytest.raises(ValueError):
        plugin_callbacks.place_spec([{"city": "Delft"}], "store")
    with pytest.raises(ValueError):
        plugin_callbacks.place_spec("Delft", "store")


def test_the_plugin_s_side_replays_answers_in_order_and_asks_for_the_next():
    from partcad.wrappers import plugin_callbacks

    user = plugin_callbacks.UserCallback({"places": [{"id": "a", "by": "city"}]})
    assert user.choose_place([{"id": "a"}, {"id": "b"}]) == "a"
    with pytest.raises(plugin_callbacks.PlaceNeeded) as asked:
        user.choose_place([{"id": "c"}], what="warehouse")
    assert asked.value.spec == {"what": "warehouse", "places": [{"id": "c"}]}
    # Not an 'Exception': a plugin's catch-all must not swallow the question.
    assert not isinstance(asked.value, Exception)
    assert plugin_callbacks.UserCallback().choose_place([]) is None


# ---- what a price is in ------------------------------------------------------


@pytest.mark.parametrize(
    "config, expected",
    [
        ({"parameters": {"currency": {"type": "string", "default": "eur"}}}, "EUR"),
        ({"parameters": {"currency": "CAD"}}, "CAD"),
        ({"with": {"currency": "gbp"}}, "GBP"),
        ({"parameters": {"currency": {"type": "string"}}}, None),
        ({}, None),
        (None, None),
    ],
)
def test_what_a_provider_declares_its_quotes_are_in(config, expected):
    assert declared_currency(config) == expected


def test_a_quote_says_its_own_currency(caplog):
    with caplog.at_level(logging.WARNING):
        quote = with_currency("//s:shop", {"parameters": {"currency": "USD"}}, {"price": 1.0, "currency": " sek"})
    assert quote["currency"] == "SEK"
    assert "US dollars" not in caplog.text


def test_else_the_provider_s_declared_currency(caplog):
    with caplog.at_level(logging.WARNING):
        quote = with_currency("//s:shop", {"parameters": {"currency": "EUR"}}, {"price": 1.0})
    assert quote["currency"] == "EUR"
    assert "US dollars" not in caplog.text


@pytest.mark.parametrize("said", [None, "", "dollars"])
def test_else_dollars_and_a_warning(caplog, said):
    result = {"price": 1.0}
    if said is not None:
        result["currency"] = said
    with caplog.at_level(logging.WARNING):
        quote = with_currency("//s:shop", {}, result)
    assert quote["currency"] == "USD"
    assert "//s:shop" in caplog.text and "taken to be US dollars" in caplog.text


@pytest.mark.parametrize("result", [None, {}, {"price": None}, "not a quote"])
def test_no_price_no_currency_to_say(result):
    assert with_currency("//s:shop", {}, result) == result
