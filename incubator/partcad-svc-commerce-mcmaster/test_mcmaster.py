#
# partcad-svc-commerce-mcmaster, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests of the McMaster-Carr plugin, with McMaster-Carr answered from a table.

The answers have the shape the Product Information API answers with - a login,
a product subscribed to, its price, a CAD file - as McMaster-Carr's own
examples show them, with values made up. Nothing here touches the network, and
no certificate is needed: the client that would present one is replaced.
"""

import base64
import hashlib
import json
import os
import runpy

import distributor as d
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
plugin = runpy.run_path(os.path.join(_HERE, "mcmaster.py"), run_name="mcmaster_under_test")
McMaster = plugin["McMaster"]

API = "https://api.mcmaster.com"
STEP = "/v1/cad/library/20180924/91290A115_BLACK-OXIDE%20ALLOY%20STEEL%20SOCKET%20HEAD%20SCREW.STEP"

SCREW = {
    "PartNumber": "91290A115",
    "ProductStatus": "Active",
    "FamilyDescription": "Black-Oxide Alloy Steel Socket Head Screw",
    "DetailDescription": "M3 x 0.5 mm Thread, 10 mm Long",
    "Specifications": [
        {"Attribute": "Thread Size", "Values": ["M3"]},
        {"Attribute": "Length", "Values": ["10 mm"]},
        {"Attribute": "Material", "Values": ["Black-Oxide Alloy Steel"]},
    ],
    "Links": [
        {"Key": "Price", "Value": "/v1/products/91290A115/price"},
        {"Key": "Image", "Value": "/v1/images/contents/gfx/imagecache/912/91290A115p1.png"},
        {"Key": "2-D DWG", "Value": "/v1/cad/library/20180924/91290A115.DWG"},
        {"Key": "3-D STEP", "Value": STEP},
    ],
}
FITTING = {
    "PartNumber": "4936K451",
    "ProductStatus": "Discontinued",
    "FamilyDescription": "Compact Extreme-Pressure Steel Pipe Fitting",
    "DetailDescription": "Adapter, 1/2 NPT Female, M20 x 1.5mm Male Thread",
    "Specifications": [],
    "Links": [{"Key": "SuggestedProduct", "Value": "https://www.mcmaster.com/15185A41"}],
}

TABLE = {
    API + "/v1/login": (200, {"AuthToken": "token-1", "ExpirationTS": "2026-11-09T22:08:50.6227667Z"}),
    API
    + "/v1/products": lambda body: (
        (200, SCREW)
        if body == {"URL": "https://mcmaster.com/91290A115"}
        else (
            (200, FITTING)
            if body == {"URL": "https://mcmaster.com/4936K451"}
            else (400, {"ErrorCode": 400, "ErrorMessage": "BAD_REQUEST", "ErrorDescription": "Invalid part number"})
        )
    ),
    API
    + "/v1/products/91290A115/price": (
        200,
        [
            {"Amount": 9.85, "MinimumQuantity": 1, "UnitOfMeasure": "Pack of 100"},
            {"Amount": 8.5, "MinimumQuantity": 5, "UnitOfMeasure": "Pack of 100"},
        ],
    ),
    API + "/v1/products/4936K451/price": (200, [{"Amount": 3.46, "MinimumQuantity": 1, "UnitOfMeasure": "Each"}]),
    API + STEP: (200, b"ISO-10303-21;\nEND-ISO-10303-21;\n"),
}


class Wire:
    def __init__(self, table):
        self.table = dict(table)
        self.asked = []

    def __call__(self, url, headers=None, data=None, method=None, timeout=60):
        self.asked.append((url, dict(headers or {}), data, method))
        if url not in self.table:
            return d.pm.Response(404, {}, b"{}", url)
        answer = self.table[url]
        status, body = answer(data) if callable(answer) else answer
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        return d.pm.Response(status, {}, body, url)


@pytest.fixture
def mcmaster(tmp_path, monkeypatch):
    monkeypatch.setenv("PARTCAD_MCMASTER_CACHE", str(tmp_path))
    for variable in McMaster.CREDENTIALS.values():
        monkeypatch.delenv(variable, raising=False)

    def make(**parameters):
        for name in ("username", "password", "certificate", "certificate_password"):
            parameters.setdefault(name, "x-" + name)
        made = McMaster({"parameters": parameters, "userInfo": {"country": "NL", "currency": "EUR"}})
        # The client that would present the certificate, replaced by a table.
        made._api = d.pm.Http("mcmaster", "test")
        made._api.request = Wire(TABLE)
        return made

    return make


def test_a_part_is_its_mcmaster_number_with_its_step(mcmaster):
    made = mcmaster()
    config = made.get("objects/part/91290A115")
    assert config["type"] == "step" and config["vendor"] == "mcmaster" and config["sku"] == "91290A115"
    assert config["desc"].startswith(
        "McMaster-Carr 91290A115: Black-Oxide Alloy Steel Socket Head Screw M3 x 0.5 mm Thread, 10 mm Long."
    )
    assert "Thread Size: M3" in config["desc"]
    assert config["url"] == "https://www.mcmaster.com/91290A115"
    # Sold by the pack, which the price says.
    assert config["count_per_sku"] == 100
    data = made.get("files/" + config["path"])
    assert base64.b64decode(data).startswith(b"ISO-10303-21")


def test_every_request_is_made_with_the_token_of_the_login(mcmaster):
    made = mcmaster()
    made.get("objects/part/91290A115")
    asked = made._api.request.asked
    assert asked[0][0] == API + "/v1/login"
    assert asked[0][2] == {"UserName": "x-username", "Password": "x-password"}
    assert all(headers.get("Authorization") == "Bearer token-1" for _, headers, _, _ in asked[1:])
    # Reading a part subscribes to it: the API reads nothing else.
    assert (API + "/v1/products", {"URL": "https://mcmaster.com/91290A115"}, "PUT") in [
        (url, data, method) for url, _, data, method in asked
    ]


def test_a_search_answers_the_part_numbers_in_it(mcmaster):
    made = mcmaster()
    hits = made.get("search/part?q=91290A115+socket+head")
    assert list(hits) == ["91290A115"]
    # Words that are no part number cost nothing: the API has no search.
    assert made.get("search/part?q=socket+head+screw") == {}
    assert [url for url, *_ in made._api.request.asked if url.endswith("/products")] == [API + "/v1/products"]


def test_a_two_dimensional_drawing_is_not_a_model(mcmaster):
    model = mcmaster().model("91290A115")
    assert [f.name for f in model.files] == ["91290A115_BLACK-OXIDE ALLOY STEEL SOCKET HEAD SCREW.STEP"]


def test_a_quote_is_by_the_pack_in_dollars(mcmaster):
    cart = {"parts": {"screw": {"vendor": "McMaster-Carr", "sku": "91290A115", "count": 450, "count_per_sku": 100}}}
    answer = mcmaster().quote({"cart": cart})
    assert answer["currency"] == "USD"
    (line,) = answer["lines"]
    assert line["count"] == 5 and line["unitPrice"] == pytest.approx(8.5) and line["price"] == pytest.approx(42.5)
    assert line["stock"] is None


def test_a_discontinued_part_is_not_available_and_says_what_replaces_it(mcmaster):
    made = mcmaster()
    answer = made.avail({"vendor": "mcmaster", "sku": "4936K451", "count": 1})
    assert answer == {"available": False, "reason": "4936K451 is discontinued at McMaster-Carr"}
    assert "suggests https://www.mcmaster.com/15185A41" in made.describe(made.fetch_product("4936K451"))


def test_what_mcmaster_does_not_have_is_said(mcmaster):
    made = mcmaster()
    assert made.avail({"vendor": "mcmaster", "sku": "99999Z999", "count": 1})["available"] is False
    assert made.avail({"vendor": "mcmaster", "sku": "not a number", "count": 1}) == {
        "available": False,
        "reason": "McMaster-Carr has no part not a number",
    }


def test_another_makers_part_is_not_mcmasters_to_sell(mcmaster):
    answer = mcmaster().avail({"vendor": "Bossard", "sku": "BN610", "count": 1})
    assert answer["available"] is False


def test_a_login_mcmaster_refuses_says_so(mcmaster):
    made = mcmaster()
    made._api.request.table[API + "/v1/login"] = (
        401,
        {"ErrorCode": 401, "ErrorMessage": "LOGIN_FAILED", "ErrorDescription": "Incorrect username or password."},
    )
    with pytest.raises(d.NeedsCredentials, match="LOGIN_FAILED: Incorrect username or password"):
        made.fetch_product("91290A115")
    assert made.whoami(dict(made.keys)) is None


def test_without_credentials_the_root_loads_and_a_part_says_what_it_needs(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PARTCAD_MCMASTER_CACHE", str(tmp_path))
    for variable in McMaster.CREDENTIALS.values():
        monkeypatch.delenv(variable, raising=False)
    made = McMaster({"parameters": {}})
    assert made.get("meta")["searchKinds"] == ["part"]
    assert made.get("deps") == []
    assert d.pm.serve(made, "objects/part/91290A115") is None
    assert "pc login //pub/svc/commerce/mcmaster:mcmaster" in capsys.readouterr().err


def test_a_certificate_that_is_no_certificate_is_said(tmp_path):
    with pytest.raises(d.SiteError, match="neither a file there is nor a base64 certificate"):
        plugin["certificate_context"]("not base64 at all!", "")


def test_partcad_runs_it_and_reads_the_answer_from_output():
    result = runpy.run_path(
        os.path.join(_HERE, "mcmaster.py"), init_globals={"request": {"key": "meta", "parameters": {}}}, run_name="get"
    )
    assert result["output"]["result"]["manufacturable"] is False


def test_the_shared_module_is_the_one_every_distributor_plugin_has():
    with open(os.path.join(_HERE, "distributor.py"), "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    with open(os.path.join(_HERE, "distributor.sha256")) as f:
        expected = f.read().split()[0]
    assert digest == expected, "distributor.py differs from the shared copy: run incubator/_shared/copy.sh"
