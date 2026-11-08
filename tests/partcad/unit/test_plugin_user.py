#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a plugin is told about the user, what it may ask, and what a quote it answers must say.

Through the sandbox plugins really run in: a store whose 'quote' reports what it
was handed, asks which of its shops is nearest the user
('partcad_user.choose_place', see 'wrappers/plugin_callbacks.py'), and answers
with or without a currency.
"""

import asyncio
import logging
import textwrap

import pytest

import partcad as pc
from partcad.plugin_provider_data_cart import ProviderCart, ProviderCartItem
from partcad.plugin_request_provider_quote import ProviderRequestQuote
from partcad_utils.user_config import UserConfig

SCRIPT = textwrap.dedent("""
    SHOPS = [
        {"id": "north", "latitude": 53.2, "longitude": 6.6, "city": "Groningen", "state": "GR", "zip": "9723"},
        {"id": "centre", "latitude": 52.37, "longitude": 4.89, "city": "Amsterdam", "state": "NH", "zip": "1012"},
        {"id": "south", "latitude": 51.44, "longitude": 5.47, "city": "Eindhoven", "state": "NB"},
    ]

    if __name__ == "quote":
        output = {
            "price": 10.0,
            "cartId": None,
            "shop": partcad_user.choose_place(SHOPS, what="store"),
            "userInfo": request.get("userInfo"),
            "toldUser": "user" in request,
        }
        if request["parameters"].get("say_currency"):
            output["currency"] = "eur"
    elif __name__ == "avail":
        output = {"available": True}
    else:
        output = {}
    """)

PACKAGE = textwrap.dedent("""
    name: //user_test
    providers:
      shop:
        type: store
        path: shop.py
        parameters:
          say_currency:
            type: bool
            default: false
      shop_in_euros:
        type: store
        path: shop.py
        parameters:
          say_currency:
            type: bool
            default: false
          currency:
            type: string
            default: EUR
      shop_saying:
        type: store
        path: shop.py
        parameters:
          say_currency:
            type: bool
            default: true
    """)

USER = {
    "firstName": "Ann",
    "line1": "Damrak 1",
    "city": "Amsterdam",
    "stateCode": "NH",
    "zipCode": "1012",
    "countryCode": "NL",
}


def _quote(tmp_path, provider="shop", **settings):
    (tmp_path / "partcad.yaml").write_text(PACKAGE)
    (tmp_path / "shop.py").write_text(SCRIPT)
    ctx = pc.Context(str(tmp_path), user_config=UserConfig.from_dict(settings))
    store = ctx.get_project("//").get_provider(provider)
    cart = ProviderCart()
    item = ProviderCartItem()
    item.name, item.count, item.vendor, item.sku = "//user_test:thing", 1, "acme", "1"
    cart.add_item(item)
    return asyncio.run(store.query_quote(ProviderRequestQuote(cart)))


def test_a_plugin_is_told_where_the_user_is_coarsely_and_not_who_or_exactly_where(tmp_path):
    quote = _quote(
        tmp_path,
        country="NL",
        language="nl",
        currency="EUR",
        user=dict(USER, location={"latitude": 52.0, "longitude": 4.3}),
    )
    assert quote["userInfo"] == {
        "country": "NL",
        "state": "NH",
        "city": "Amsterdam",
        "language": "nl",
        "currency": "EUR",
    }
    # A store is no manufacturer shipping to the user: it is not handed the 'user' section at all.
    assert quote["toldUser"] is False


def test_the_nearest_place_is_chosen_by_the_user_s_location(tmp_path):
    # Nearest Eindhoven, whatever the address says.
    quote = _quote(tmp_path, user=dict(USER, location={"latitude": 51.5, "longitude": 5.4}))
    assert quote["shop"] == "south"


def test_without_a_location_the_address_chooses(tmp_path):
    assert _quote(tmp_path, user=USER)["shop"] == "centre"
    assert _quote(tmp_path, user={"city": "Groningen"})["shop"] == "north"


def test_without_either_nothing_is_chosen_and_the_plugin_decides(tmp_path):
    assert _quote(tmp_path)["shop"] is None


def test_a_quote_without_a_currency_is_taken_to_be_in_dollars_and_warned_about(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        quote = _quote(tmp_path)
    assert quote["currency"] == "USD"
    assert "without saying in what currency: taken to be US dollars" in caplog.text


@pytest.mark.parametrize("provider", ["shop_in_euros", "shop_saying"])
def test_a_quote_is_in_the_currency_it_or_its_provider_says(tmp_path, caplog, provider):
    with caplog.at_level(logging.WARNING):
        quote = _quote(tmp_path, provider)
    assert quote["currency"] == "EUR"
    assert "taken to be US dollars" not in caplog.text
