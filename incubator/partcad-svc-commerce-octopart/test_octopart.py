#
# partcad-svc-commerce-octopart, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests of the Octopart plugin, with Nexar answered from a table.

The answers have the shape Nexar's GraphQL schema gives them - supCategories,
supSearch, supMultiMatch, a part's sellers, offers and CAD - with values made
up; the queries themselves were validated against that schema. Nothing here
touches the network.
"""

import base64
import hashlib
import io
import json
import os
import runpy
import zipfile

import distributor as d
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
plugin = runpy.run_path(os.path.join(_HERE, "octopart.py"), run_name="octopart_under_test")
Octopart = plugin["Octopart"]

API = "https://api.nexar.com/graphql"
TOKEN = "https://identity.nexar.com/connect/token"
KICAD = "https://octopart.com/cad/kicad/BAV99.zip"


def _offer(sku, stock, moq, prices, multiple=1, packaging="Cut Tape"):
    return {
        "sku": sku,
        "inventoryLevel": stock,
        "moq": moq,
        "orderMultiple": multiple,
        "packaging": packaging,
        "factoryLeadDays": 70,
        "clickUrl": "https://octopart.com/click/%s" % sku,
        "prices": [
            {"quantity": q, "price": p, "currency": c, "convertedPrice": cp, "convertedCurrency": "EUR"}
            for q, p, c, cp in prices
        ],
    }


BAV99 = {
    "id": "39432",
    "mpn": "BAV99",
    "shortDescription": "Diode Switching 100V 0.215A 3-Pin SOT-23",
    "octopartUrl": "https://octopart.com/bav99-nexperia-39432",
    "totalAvail": 2500000,
    "manufacturer": {"id": "1", "name": "Nexperia"},
    "category": {"id": "4219", "name": "Diodes", "path": "/electronic-parts/discrete-semiconductors/diodes"},
    "bestDatasheet": {"url": "https://assets.nexperia.com/BAV99.pdf"},
    "specs": [{"attribute": {"shortname": "case_package", "name": "Case/Package"}, "displayValue": "SOT-23"}],
    "cad": {"has3dModel": True, "hasKicad": True, "downloadUrlKicad": KICAD},
    "sellers": [
        {
            "company": {"id": "459", "name": "Digi-Key"},
            "offers": [
                _offer("1727-BAV99,215CT-ND", 400000, 1, [(1, 0.10, "USD", 0.092), (100, 0.03, "USD", 0.028)]),
                _offer("1727-BAV99,215TR-ND", 1500000, 3000, [(3000, 0.012, "USD", 0.011)], 3000, "Tape & Reel"),
            ],
        },
        {
            "company": {"id": "2401", "name": "Mouser"},
            "offers": [_offer("771-BAV99-T/R", 600000, 1, [(1, 0.09, "EUR", 0.09), (100, 0.025, "EUR", 0.025)])],
        },
    ],
}
# Another manufacturer's part of the same number.
BAV99_ONSEMI = dict(BAV99, id="1007", manufacturer={"id": "2", "name": "onsemi"}, cad=None, sellers=[])


def answer(body):
    query = body["query"]
    if "supCategories" in query:
        return 200, {
            "data": {
                "supCategories": [
                    {"id": "4161", "name": "Electronic Parts", "parentId": None, "path": "/electronic-parts"},
                    {"id": "4215", "name": "Discrete Semiconductors", "parentId": "4161", "numParts": 900000},
                    {"id": "4219", "name": "Diodes", "parentId": "4215", "numParts": 250000},
                    {"id": "4165", "name": "Passive Components", "parentId": "4161", "numParts": 4000000},
                ]
            }
        }
    if "supSearch" in query:
        light = {k: v for k, v in BAV99.items() if k != "sellers"}
        return 200, {"data": {"supSearch": {"hits": 1, "results": [{"part": light}]}}}
    if "supMultiMatch" in query:
        mpn = body["variables"]["queries"][0]["mpn"]
        parts = [BAV99, BAV99_ONSEMI] if mpn == "BAV99" else []
        return 200, {"data": {"supMultiMatch": [{"reference": "1", "hits": len(parts), "parts": parts}]}}
    return 200, {"errors": [{"message": "unexpected query"}]}


def _kicad():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("BAV99/BAV99.kicad_sym", "(kicad_symbol_lib)")
        z.writestr("BAV99/3D/SOT-23.step", "ISO-10303-21;\nEND-ISO-10303-21;\n")
    return out.getvalue()


TABLE = {
    TOKEN: (200, {"access_token": "token-1", "expires_in": 86400}),
    API: answer,
    KICAD: (200, _kicad()),
}


class Wire:
    def __init__(self, table):
        self.table = dict(table)
        self.asked = []

    def __call__(self, url, headers=None, data=None, method=None, timeout=60):
        self.asked.append((url, dict(headers or {}), data))
        if url not in self.table:
            return d.pm.Response(404, {}, b"{}", url)
        entry = self.table[url]
        status, body = entry(data) if callable(entry) else entry
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        return d.pm.Response(status, {}, body, url)


@pytest.fixture
def octopart(tmp_path, monkeypatch):
    monkeypatch.setenv("PARTCAD_OCTOPART_CACHE", str(tmp_path))
    monkeypatch.delenv("NEXAR_CLIENT_ID", raising=False)
    monkeypatch.delenv("NEXAR_CLIENT_SECRET", raising=False)

    def make(**parameters):
        parameters.setdefault("client_id", "client-1")
        parameters.setdefault("client_secret", "secret-1")
        made = Octopart({"parameters": parameters, "userInfo": {"country": "NL", "currency": "EUR"}})
        made.http.request = Wire(TABLE)
        return made

    return make


def _queries(made):
    return [body for url, _, body in made.http.request.asked if url == API]


def test_the_token_asks_for_the_supply_scope(octopart):
    made = octopart()
    made.get("deps")
    url, _, form = made.http.request.asked[0]
    assert url == TOKEN and b"scope=supply.domain" in form and b"grant_type=client_credentials" in form
    assert made.http.request.asked[1][1]["Authorization"] == "Bearer token-1"


def test_the_categories_are_under_electronic_parts(octopart):
    made = octopart()
    assert made.get("deps") == ["discrete-semiconductors", "passive-components"]
    assert made.get("discrete-semiconductors/deps") == ["diodes"]


def test_a_search_in_a_category_is_filtered_by_it_and_priced_nowhere(octopart):
    made = octopart()
    hits = made.get("discrete-semiconductors/diodes/search/part?q=bav99&limit=3")
    (body,) = [b for b in _queries(made) if "supSearch" in b["query"]]
    assert body["variables"]["filters"] == {"category_id": ["4219"]}
    assert (body["variables"]["country"], body["variables"]["currency"]) == ("NL", "EUR")
    # A search lists parts: it does not cost their sellers.
    assert "sellers" not in body["query"]
    assert list(hits) == ["BAV99~nexperia"]


def test_a_part_is_the_manufacturers_bought_by_its_mpn(octopart):
    config = octopart().get("objects/part/BAV99~nexperia")
    assert config["vendor"] == "Nexperia" and config["sku"] == "BAV99"
    assert config["type"] == "step"
    assert "Offered by 2 authorized distributors: Digi-Key, Mouser" in config["desc"]
    assert "2,500,000 in stock" in config["desc"]


def test_its_model_is_the_step_in_its_kicad_library(octopart):
    made = octopart()
    config = made.get("objects/part/BAV99~nexperia")
    assert base64.b64decode(made.get("files/" + config["path"])).startswith(b"ISO-10303-21")


def test_a_number_two_makers_have_needs_the_maker(octopart, capsys):
    assert d.pm.serve(octopart(), "objects/part/BAV99") is None
    assert "BAV99 is made by Nexperia and by onsemi" in capsys.readouterr().err


def test_a_part_with_no_model_says_how_to_buy_it(octopart, capsys):
    assert d.pm.serve(octopart(), "objects/part/BAV99~onsemi") is None
    assert "'vendor: onsemi' and 'sku: BAV99'" in capsys.readouterr().err


def test_the_cheapest_authorized_offer_is_quoted_in_the_users_currency(octopart):
    cart = {"parts": {"d": {"vendor": "Nexperia", "sku": "BAV99", "count": 200}}}
    answer = octopart().quote({"cart": cart})
    assert answer["currency"] == "EUR"
    (line,) = answer["lines"]
    # Mouser's 0.025 EUR beats DigiKey's 0.028 EUR at 200.
    assert line["seller"] == "Mouser" and line["sku"] == "771-BAV99-T/R"
    assert line["price"] == pytest.approx(5.0)


def test_a_reel_wins_where_the_quantity_fills_one(octopart):
    answer = octopart().avail({"vendor": "Nexperia", "sku": "BAV99", "count": 6000})
    assert answer["available"] is True and answer["sku"] == "1727-BAV99,215TR-ND" and answer["seller"] == "Digi-Key"


def test_a_part_by_its_octopart_name_is_available(octopart):
    assert octopart().avail({"vendor": "octopart", "sku": "BAV99~nexperia", "count": 1})["available"] is True


def test_another_maker_is_not_sold_as_the_one_named(octopart):
    answer = octopart().avail({"vendor": "Vishay", "sku": "BAV99", "count": 1})
    assert answer["available"] is False and "not by 'Vishay'" in answer["reason"]


def test_a_graphql_error_is_said_and_not_kept(octopart, capsys):
    made = octopart()
    made.http.request.table[API] = (200, {"errors": [{"message": "Quota exceeded"}]})
    assert d.pm.serve(made, "search/part?q=bav99") is None
    assert "Quota exceeded" in capsys.readouterr().err
    made.http.request.table[API] = answer
    assert list(made.get("search/part?q=bav99")) == ["BAV99~nexperia"]


def test_partcad_runs_it_and_reads_the_answer_from_output():
    result = runpy.run_path(
        os.path.join(_HERE, "octopart.py"), init_globals={"request": {"key": "meta", "parameters": {}}}, run_name="get"
    )
    assert result["output"]["result"]["searchKinds"] == ["part"]


def test_the_shared_module_is_the_one_every_distributor_plugin_has():
    with open(os.path.join(_HERE, "distributor.py"), "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    with open(os.path.join(_HERE, "distributor.sha256")) as f:
        expected = f.read().split()[0]
    assert digest == expected, "distributor.py differs from the shared copy: run incubator/_shared/copy.sh"
