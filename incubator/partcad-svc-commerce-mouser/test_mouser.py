#
# partcad-svc-commerce-mouser, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests of the Mouser plugin, with Mouser answered from a table.

The answers have the shape Mouser's Search API (its Swagger, V1) gives them -
a keyword search, a part number search, 'Errors' in a 200 - with values made
up. Nothing here touches the network.
"""

import hashlib
import json
import os
import runpy

import distributor as d
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
plugin = runpy.run_path(os.path.join(_HERE, "mouser.py"), run_name="mouser_under_test")
Mouser = plugin["Mouser"]

API = "https://api.mouser.com/api/v1"


def _part(sku, packaging, minimum, multiple, breaks, stock, **more):
    part = {
        "MouserPartNumber": sku,
        "ManufacturerPartNumber": "LM358DR",
        "Manufacturer": "Texas Instruments",
        "Description": "Operational Amplifiers - Op Amps Dual Gen Purpose",
        "Category": "Operational Amplifiers - Op Amps",
        "ProductDetailUrl": "https://www.mouser.com/ProductDetail/%s" % sku,
        "DataSheetUrl": "https://www.ti.com/lit/ds/symlink/lm358.pdf",
        "Availability": "%d In Stock" % stock,
        "AvailabilityInStock": str(stock),
        "LeadTime": "42 Days",
        "LifecycleStatus": None,
        "IsDiscontinued": "false",
        "Min": str(minimum),
        "Mult": str(multiple),
        "PriceBreaks": [
            {"Quantity": q, "Price": "%s €" % str(p).replace(".", ","), "Currency": "EUR"} for q, p in breaks
        ],
        "ProductAttributes": [{"AttributeName": "Packaging", "AttributeValue": packaging}],
    }
    part.update(more)
    return part


CUT = _part("595-LM358DR", "Cut Tape", 1, 1, [(1, 0.45), (10, 0.32), (100, 0.21)], 12345)
REEL = _part("595-LM358DRR", "Reel", 2500, 2500, [(2500, 0.12)], 50000)
GONE = _part("595-LM358D", "Tube", 1, 1, [(1, 0.5)], 0, LifecycleStatus="Obsolete")


def answer(body):
    if "SearchByKeywordRequest" in body:
        return 200, {"Errors": [], "SearchResults": {"NumberOfResult": 3, "Parts": [CUT, REEL, GONE]}}
    number = body["SearchByPartRequest"]["mouserPartNumber"]
    parts = {"595-LM358DR": [CUT], "LM358DR": [CUT, REEL], "595-LM358D": [GONE]}.get(number, [])
    return 200, {"Errors": [], "SearchResults": {"NumberOfResult": len(parts), "Parts": parts}}


class Wire:
    def __init__(self, table):
        self.table = dict(table)
        self.asked = []

    def __call__(self, url, headers=None, data=None, method=None, timeout=60):
        self.asked.append((url, dict(headers or {}), data))
        base = url.split("?")[0]
        if base not in self.table:
            return d.pm.Response(404, {}, b"{}", url)
        entry = self.table[base]
        status, body = entry(data) if callable(entry) else entry
        return d.pm.Response(status, {}, json.dumps(body).encode(), url)


TABLE = {API + "/search/keyword": answer, API + "/search/partnumber": answer}


@pytest.fixture
def mouser(tmp_path, monkeypatch):
    monkeypatch.setenv("PARTCAD_MOUSER_CACHE", str(tmp_path))
    monkeypatch.delenv("MOUSER_API_KEY", raising=False)

    def make(api_key="key-1"):
        made = Mouser({"parameters": {"api_key": api_key}, "userInfo": {"country": "NL", "currency": "EUR"}})
        made.http.request = Wire(TABLE)
        return made

    return make


def test_the_key_goes_where_mouser_wants_it(mouser):
    made = mouser()
    made.get("search/part?q=lm358")
    url, _, body = made.http.request.asked[0]
    assert url == API + "/search/keyword?apiKey=key-1"
    assert body["SearchByKeywordRequest"]["keyword"] == "lm358"


def test_the_catalogue_is_one_package_that_is_searched_not_built(mouser):
    made = mouser()
    meta = made.get("meta")
    assert meta["searchKinds"] == ["part"] and meta["instanceKinds"] == []
    assert made.get("deps") == []


def test_a_search_finds_what_to_quote_and_serves_nothing_to_build(mouser):
    hits = mouser().get("search/part?q=lm358")
    assert list(hits) == ["595-LM358DR", "595-LM358DRR", "595-LM358D"]
    assert all("type" not in hit for hit in hits.values())
    assert "quote it as 'vendor: mouser', 'sku: 595-LM358DR'" in hits["595-LM358DR"]["desc"]


def test_a_price_written_for_a_person_is_read(mouser):
    product = mouser().fetch_product("595-LM358DR")
    assert product.breaks == [(1, d.Decimal("0.45")), (10, d.Decimal("0.32")), (100, d.Decimal("0.21"))]
    assert product.currency == "EUR" and product.stock == 12345 and product.packaging == "Cut Tape"


def test_mousers_number_is_quoted(mouser):
    cart = {"parts": {"a": {"vendor": "mouser", "sku": "595-LM358DR", "count": 20}}}
    answer = mouser().quote({"cart": cart})
    assert answer["currency"] == "EUR" and answer["price"] == pytest.approx(6.4)


def test_a_manufacturers_number_is_quoted_in_the_cheapest_packaging(mouser):
    made = mouser()
    assert made.avail({"vendor": "Texas Instruments", "sku": "LM358DR", "count": 50})["sku"] == "595-LM358DR"
    assert made.avail({"vendor": "TI", "sku": "LM358DR", "count": 5000})["available"] is False
    assert made.avail({"vendor": "Texas Instruments", "sku": "LM358DR", "count": 5000})["sku"] == "595-LM358DRR"


def test_an_obsolete_part_is_not_available(mouser):
    answer = mouser().avail({"vendor": "mouser", "sku": "595-LM358D", "count": 1})
    assert answer == {"available": False, "reason": "595-LM358D is obsolete at Mouser"}


def test_a_key_mouser_refuses_says_to_log_in(mouser):
    made = mouser("bad")
    made.http.request.table[API + "/search/partnumber"] = (
        200,
        {"Errors": [{"Id": 0, "Code": "Invalid", "Message": "Invalid unique identifier."}], "SearchResults": None},
    )
    answer = made.avail({"vendor": "mouser", "sku": "595-LM358DR", "count": 1})
    assert answer["available"] is False and "pc login //pub/svc/commerce/mouser:mouser" in answer["reason"]
    assert made.whoami({"api_key": "bad"}) is None


@pytest.mark.parametrize(
    "message, about_the_key",
    [
        ("Invalid unique identifier.", True),
        ("The API key is invalid.", True),
        ("apiKey is required.", True),
        ("Keyword is required.", False),
        ("The keyword must be at least 3 characters.", False),
    ],
)
def test_only_an_error_about_the_key_says_to_log_in(mouser, message, about_the_key):
    made = mouser()
    code = "Invalid" if message.startswith("Invalid") else "Required"
    made.http.request.table[API + "/search/keyword"] = (
        200,
        {"Errors": [{"Id": 0, "Code": code, "Message": message}], "SearchResults": None},
    )
    with pytest.raises(d.SiteError) as raised:
        made.ask("/search/keyword", {"SearchByKeywordRequest": {"keyword": "lm"}}, "a search", ttl=0)
    assert isinstance(raised.value, d.NeedsCredentials) is about_the_key
    assert message in str(raised.value)


def test_without_a_key_nothing_is_asked(mouser, capsys):
    made = mouser("")
    assert d.pm.serve(made, "search/part?q=lm358") is None
    assert "MOUSER_API_KEY" in capsys.readouterr().err
    assert made.http.request.asked == []


def test_partcad_runs_it_and_reads_the_answer_from_output():
    result = runpy.run_path(
        os.path.join(_HERE, "mouser.py"), init_globals={"request": {"key": "meta", "parameters": {}}}, run_name="get"
    )
    assert result["output"]["result"]["searchKinds"] == ["part"]


def test_the_shared_module_is_the_one_every_distributor_plugin_has():
    with open(os.path.join(_HERE, "distributor.py"), "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    with open(os.path.join(_HERE, "distributor.sha256")) as f:
        expected = f.read().split()[0]
    assert digest == expected, "distributor.py differs from the shared copy: run incubator/_shared/copy.sh"
