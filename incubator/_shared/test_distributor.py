#
# PartCAD distributor plugins, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests of distributor.py, the part every distributor plugin shares.

The distributor here is a stand-in with a range of four products; nothing
touches the network. What each plugin asks its own API is tested beside it.
"""

import base64
import os

import distributor as d
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))

STEP = b"ISO-10303-21;\nHEADER;\nENDSEC;\nEND-ISO-10303-21;\n"


def _resistor(sku, packaging, moq, breaks, stock, pack=1):
    return d.Product(
        sku,
        mpn="RC0603FR-0710KL",
        manufacturer="YAGEO",
        title="RES 10K OHM 1% 1/10W 0603",
        url="https://example.com/%s" % sku,
        packaging=packaging,
        moq=moq,
        breaks=breaks,
        stock=stock,
        currency="USD",
        pack=pack,
        categories=["52"],
        specs=[("Resistance", "10 kOhms"), ("Package / Case", "0603 (1608 Metric)")],
        files=[d.File("m1", "RC0603.step", url="https://example.com/m1")],
    )


class Fake(d.Distributor):
    NAME = "fake"
    TITLE = "Fake"
    URL = "https://example.com"
    DESC = "A distributor for the tests."
    VENDOR = "fake"
    VENDOR_ALIASES = ("fake-electronics",)
    PACKAGE = "//pub/svc/commerce/fake"
    STORE = "fake"
    CATALOGUE = "fake_repo"
    CREDENTIALS = {"api_key": "FAKE_API_KEY"}

    RANGE = {
        "R-CT": _resistor("R-CT", "Cut Tape", 1, [(1, "0.10"), (10, "0.05"), (100, "0.02")], 5000),
        "R-REEL": _resistor("R-REEL", "Tape & Reel", 5000, [(5000, "0.004")], 100000, pack=5000),
        "SCREW-100": d.Product(
            "SCREW-100",
            mpn="91290A115",
            manufacturer="Fake Fasteners",
            title="Socket head screw M3 x 10 mm",
            pack=100,
            per="pack",
            breaks=[(1, "9.85"), (5, "8.50")],
            stock=None,
            currency="USD",
            files=[
                d.File("s-stl", "91290A115.stl", url="https://example.com/s.stl"),
                d.File("s-step", "91290A115.STEP", url="https://example.com/s.step"),
            ],
        ),
        "LT1013CN8#PBF": d.Product(
            "LT1013CN8#PBF",
            mpn="LT1013CN8#PBF",
            manufacturer="Analog Devices Inc.",
            title="IC OPAMP GP 2 CIRCUIT 8DIP",
            status="Obsolete",
            orderable=False,
            files=[],
        ),
    }

    def __init__(self, request=None):
        super().__init__(request)
        self.searched = []

    def fetch_categories(self):
        resistors = d.Category("2", "Resistors", count=12345)
        resistors.children = [d.Category("52", "Chip Resistor - Surface Mount"), d.Category("53", "Through Hole")]
        return [resistors, d.Category("32", "Integrated Circuits (ICs)"), d.Category("33", "Integrated Circuits")]

    def find_products(self, text, category, limit):
        self.searched.append((text, category.id if category else None, limit))
        words = d.fold(text)
        return [p for p in self.RANGE.values() if words in d.fold(p.title) or words in d.fold(p.mpn)]

    def fetch_product(self, sku):
        if sku not in self.RANGE:
            raise d.NotFound("fake: no %s" % sku)
        return self.RANGE[sku]

    def find_mpn(self, manufacturer, mpn):
        return [p for p in self.RANGE.values() if d.fold(p.mpn) == d.fold(mpn)]

    def download(self, model, file):
        return STEP if file.format == "step" else b"solid x\nendsolid x\n"


@pytest.fixture
def fake(tmp_path, monkeypatch):
    monkeypatch.setenv("PARTCAD_FAKE_CACHE", str(tmp_path))
    return lambda request=None: Fake(request or {"parameters": {}})


# --- names ---------------------------------------------------------------------


@pytest.mark.parametrize("sku", ["296-1395-5-ND", "LT1013CN8#PBF-ND", "A/B C,D", "91290A115"])
def test_a_part_number_is_a_name_and_back(sku):
    name = d.name_of(sku)
    assert all(c.isalnum() or c in "-._~%" for c in name)
    assert d.sku_of(name) == sku


def test_a_name_partcad_has_decoded_is_read_as_it_is():
    """PartCAD decodes the escapes of its reserved characters before a plugin sees the name."""
    assert d.sku_of("LT1013CN8#PBF-ND") == "LT1013CN8#PBF-ND"


@pytest.mark.parametrize(
    "text, value",
    [("0.32", "0.32"), ("$1,234.50", "1234.50"), ("1.234,50 €", "1234.50"), ("0,325", "0.325"), (0.5, "0.5")],
)
def test_a_price_is_read_however_it_is_written(text, value):
    assert d.decimal(text) == d.Decimal(value)


def test_a_category_name_is_a_package_name():
    assert d.slug("Logic - Gates & Inverters") == "logic-gates-and-inverters"
    assert d.slug("Integrated Circuits (ICs)") == "integrated-circuits-ics"


# --- the catalogue ---------------------------------------------------------------


def test_the_catalogue_says_it_is_searched_and_supplied_by_its_store(fake):
    meta = fake().get("meta")
    assert meta["searchKinds"] == ["part"] and meta["instanceKinds"] == ["part"]
    assert meta["suppliers"] == {"//pub/svc/commerce/fake:fake": {}}
    assert meta["manufacturable"] is False


def test_categories_are_packages_with_names_of_their_own(fake):
    made = fake()
    assert made.get("deps") == ["resistors", "integrated-circuits-ics", "integrated-circuits"]
    assert made.get("resistors/deps") == ["chip-resistor-surface-mount", "through-hole"]
    assert "Chip Resistor" in made.get("resistors/chip-resistor-surface-mount/meta")["desc"]
    assert "12,345 products" in made.get("resistors/meta")["desc"]


def test_two_categories_that_would_share_a_name_do_not():
    class Twins(Fake):
        def fetch_categories(self):
            return [d.Category("1", "Cables"), d.Category("2", "Cables")]

    assert Twins({}).get("deps") == ["cables", "cables-2"]


def test_a_child_package_is_told_its_subfolder_in_the_query(fake):
    made = fake(
        {
            "key": "resistors/search/part?q=10k&limit=5",
            "query": {"what": "search", "kind": "part", "text": "10k", "limit": 5, "subfolder": "resistors"},
            "parameters": {},
        }
    )
    made.get("resistors/search/part?q=10k&limit=5")
    assert made.searched == [("10k", "2", 5)]


def test_nothing_is_listed(fake):
    assert fake().get("objects/part") == {}
    assert fake().get("resistors/objects/part") == {}


def test_a_product_is_a_part_named_by_its_part_number_and_bought_by_it(fake):
    config = fake().get("objects/part/R-CT")
    assert config["type"] == "step"
    assert config["vendor"] == "fake" and config["sku"] == "R-CT"
    assert config["desc"].startswith("YAGEO RC0603FR-0710KL: RES 10K OHM 1% 1/10W 0603")
    assert "Resistance: 10 kOhms" in config["desc"]
    assert "Sold by Fake as R-CT" in config["desc"]
    assert config["url"] == "https://example.com/R-CT"
    assert "count_per_sku" not in config


def test_a_pack_is_bought_by_the_pack(fake):
    config = fake().get("objects/part/SCREW-100")
    assert config["count_per_sku"] == 100
    assert "in packs of 100" in config["desc"]
    # STEP before a mesh, whatever order the distributor lists them in.
    assert config["type"] == "step"
    assert fake().get("objects/part/SCREW-100;format=stl")["type"] == "stl"


def test_its_model_is_served_through_the_plugin(fake):
    made = fake()
    config = made.get("objects/part/SCREW-100")
    assert base64.b64decode(made.get("files/" + config["path"])) == STEP


def test_a_product_with_no_model_is_not_a_part_and_says_how_to_buy_it(fake, capsys):
    made = fake()
    assert d.pm.serve(made, "objects/part/" + d.name_of("LT1013CN8#PBF")) is None
    said = capsys.readouterr().err
    assert "has no 3D model at Fake" in said and "'vendor: fake' and 'sku: LT1013CN8#PBF'" in said


def test_a_search_names_parts_by_part_number_and_lists_what_has_no_model(fake):
    hits = fake().get("search/part?q=RC0603&limit=5")
    assert list(hits) == ["R-CT", "R-REEL"]
    hits = fake().get("search/part?q=opamp")
    assert list(hits) == ["LT1013CN8%23PBF"]
    assert "type" not in hits["LT1013CN8%23PBF"]
    assert "no 3D model at Fake" in hits["LT1013CN8%23PBF"]["desc"]


def test_an_empty_search_asks_nothing(fake):
    made = fake()
    assert made.get("search/part?q=") == {}
    assert made.searched == []


def test_an_unknown_parameter_is_refused(fake, capsys):
    assert d.pm.serve(fake(), "objects/part/R-CT;colour=red") is None
    assert "unknown parameter colour" in capsys.readouterr().err


def test_an_older_partcad_that_sends_the_key_alone_is_answered(fake):
    made = fake()
    assert made.get("resistors/chip-resistor-surface-mount/deps") == []
    assert made.get("resistors/objects/part/R-CT")["sku"] == "R-CT"


# --- the store -------------------------------------------------------------------


def test_its_own_part_number_is_available(fake):
    answer = fake().avail({"vendor": "fake", "sku": "R-CT", "count": 10, "count_per_sku": 1})
    assert answer["available"] is True
    assert answer["stock"] == 5000 and answer["matched"] == "Fake part number"


def test_an_alias_of_its_name_is_its_own(fake):
    assert fake().avail({"vendor": "Fake Electronics", "sku": "R-CT", "count": 1})["available"] is True


def test_a_manufacturers_part_is_found_by_its_mpn(fake):
    answer = fake().avail({"vendor": "Yageo", "sku": "RC0603FR-0710KL", "count": 10})
    assert answer["available"] is True
    # Ten are cheapest on cut tape; a reel is 5000.
    assert answer["sku"] == "R-CT"
    assert fake().avail({"vendor": "Yageo", "sku": "RC0603FR-0710KL", "count": 20000})["sku"] == "R-REEL"


def test_another_makers_part_of_the_same_number_is_not_sold_as_it(fake):
    answer = fake().avail({"vendor": "Vishay", "sku": "RC0603FR-0710KL", "count": 1})
    assert answer["available"] is False
    assert "by YAGEO, not by 'Vishay'" in answer["reason"]


def test_what_cannot_be_ordered_is_not_available(fake):
    answer = fake().avail({"vendor": "fake", "sku": "LT1013CN8#PBF", "count": 1})
    assert answer == {"available": False, "reason": "LT1013CN8#PBF is obsolete at Fake"}


def test_what_it_does_not_have_is_not_available(fake):
    assert fake().avail({"vendor": "fake", "sku": "NOPE", "count": 1}) == {
        "available": False,
        "reason": "Fake has no part NOPE",
    }


def test_a_quote_is_at_the_break_the_order_reaches(fake):
    cart = {
        "qos": "normal",
        "parts": {"r": {"vendor": "fake", "sku": "R-CT", "count": 12}},
        "skus": [{"vendor": "fake", "sku": "R-CT", "count": 12, "parts": ["r"]}],
    }
    answer = fake().quote({"cart": cart})
    assert answer["currency"] == "USD"
    assert answer["price"] == pytest.approx(0.60)
    (line,) = answer["lines"]
    assert line["quantity"] == 12 and line["unitPrice"] == pytest.approx(0.05) and line["inStock"] is True


def test_a_quote_orders_the_minimum_and_says_so(fake):
    cart = {"parts": {"r": {"vendor": "fake", "sku": "R-REEL", "count": 10}}}
    (line,) = fake().quote({"cart": cart})["lines"]
    assert line["count"] == 10 and line["quantity"] == 5000
    assert line["price"] == pytest.approx(20.0)


def test_a_quote_without_skus_works_them_out_from_the_parts(fake):
    cart = {"parts": {"a": {"vendor": "fake", "sku": "SCREW-100", "count": 150, "count_per_sku": 100}}}
    (line,) = fake().quote({"cart": cart})["lines"]
    assert line["count"] == 2 and line["price"] == pytest.approx(19.70)
    assert line["inStock"] is None


def test_a_quote_for_what_cannot_be_had_fails_with_why(fake):
    cart = {"parts": {"a": {"vendor": "fake", "sku": "NOPE", "count": 1}}}
    with pytest.raises(d.SiteError, match="Fake has no part NOPE"):
        fake().quote({"cart": cart})


def test_order_quantity_is_a_whole_multiple():
    product = d.Product("X", moq=10, multiple=4, breaks=[(1, "1")])
    assert product.order_quantity(1) == 12
    assert product.order_quantity(13) == 16


# --- the apis --------------------------------------------------------------------


def test_a_failed_quote_is_raised_and_a_failed_key_is_said(fake, capsys):
    assert d.run(Fake, "get", {"key": "objects/part/NOPE", "parameters": {}}) == {"result": None}
    assert "fake: no NOPE" in capsys.readouterr().err
    with pytest.raises(RuntimeError, match="Fake has no part NOPE"):
        d.run(Fake, "quote", {"cart": {"parts": {"a": {"vendor": "fake", "sku": "NOPE", "count": 1}}}})


def test_ordering_says_where_to_order(fake):
    with pytest.raises(RuntimeError, match="put the quote's lines in a cart at https://example.com"):
        d.run(Fake, "order", {"cartId": None})


def test_logging_in_says_to_log_in_to_both():
    message = Fake({}).login_message("Logged in")
    assert "'pc login //pub/svc/commerce/fake:fake' and 'pc login //pub/svc/commerce/fake:fake_repo'" in message


def test_missing_credentials_say_how_to_give_them():
    error = Fake({}).needs_credentials("a search")
    assert isinstance(error, d.NeedsCredentials)
    assert "pc login //pub/svc/commerce/fake:fake_repo" in str(error) and "FAKE_API_KEY" in str(error)


def test_an_access_token_is_kept_until_it_expires(fake):
    made = fake()
    asked = []

    def wire(url, headers=None, data=None, method=None, timeout=60):
        asked.append((url, data))
        return d.pm.Response(200, {}, b'{"access_token": "t1", "expires_in": 600}', url)

    made.http.request = wire
    assert made.bearer("https://example.com/token", "id", "secret", "a search") == "t1"
    assert fake().bearer("https://example.com/token", "id", "secret", "a search") == "t1"
    assert len(asked) == 1
    assert b"grant_type=client_credentials" in asked[0][1]


def test_credentials_that_are_refused_say_to_log_in_again(fake):
    made = fake()
    made.http.request = lambda url, **kw: d.pm.Response(401, {}, b"{}", url)
    with pytest.raises(d.NeedsCredentials, match="did not take your API credentials"):
        made.bearer("https://example.com/token", "id", "bad", "a search")


def test_answers_in_another_currency_are_cached_apart(tmp_path, monkeypatch):
    """plugin_models keys its cache on the URL and the credentials; a price also depends on where it is asked."""
    monkeypatch.setenv("PARTCAD_FAKE_CACHE", str(tmp_path))
    euros = Fake({"parameters": {}, "userInfo": {"country": "NL", "currency": "EUR"}})
    dollars = Fake({"parameters": {}, "userInfo": {"country": "US", "currency": "USD"}})
    assert euros.http.root != dollars.http.root
    assert Fake({"parameters": {"currency": "USD"}, "userInfo": {"country": "US"}}).http.root == dollars.http.root


class Aliased(Fake):
    def alias_of(self, model):
        product = model.product
        return "//pub/cad/partner:%s~%s" % (product.mpn, d.slug(product.manufacturer)) if product.mpn else None


def test_a_product_without_a_model_can_be_drawn_with_a_partners(tmp_path, monkeypatch):
    monkeypatch.setenv("PARTCAD_FAKE_CACHE", str(tmp_path))
    made = Aliased({"parameters": {}})
    config = made.get("objects/part/" + d.name_of("LT1013CN8#PBF"))
    assert config["type"] == "alias"
    assert config["source"] == "//pub/cad/partner:LT1013CN8#PBF~analog-devices-inc"
    # Still bought from the distributor, by its own number.
    assert (config["vendor"], config["sku"]) == ("fake", "LT1013CN8#PBF")
    hits = made.get("search/part?q=opamp")
    assert hits["LT1013CN8%23PBF"]["type"] == "alias"


def test_client_credentials_can_go_as_http_basic(fake):
    made = fake()
    asked = []

    def wire(url, headers=None, data=None, method=None, timeout=60):
        asked.append((headers, data))
        return d.pm.Response(200, {}, b'{"access_token": "t2", "expires_in": 600}', url)

    made.http.request = wire
    assert made.bearer("https://example.com/token", "id 1", "s:2", "a search", basic=True) == "t2"
    headers, form = asked[0]
    assert headers["Authorization"] == "Basic " + d.base64.b64encode(b"id%201:s%3A2").decode()
    assert b"client_secret" not in form and b"grant_type=client_credentials" in form


def test_a_package_says_the_categories_below_it(fake):
    """'pc list packages' leaves out a package that lists nothing, so its description names what is below."""
    made = fake()
    assert made.get("meta")["desc"].endswith("Categories: resistors, integrated-circuits-ics, integrated-circuits.")
    assert made.get("resistors/meta")["desc"].endswith("Categories: chip-resistor-surface-mount, through-hole.")
    assert "Categories" not in made.get("resistors/through-hole/meta")["desc"]


def test_a_reel_is_ordered_whole_and_priced_by_the_item():
    reel = d.Product("R-TR", pack=5000, moq=5000, breaks=[(5000, "0.004"), (25000, "0.003")])
    assert reel.order(1) == (1, 5000, d.Decimal("20.000"))
    assert reel.order(5001) == (2, 10000, d.Decimal("40.000"))
    assert reel.order(30000) == (6, 30000, d.Decimal("90.000"))


def test_a_pack_is_ordered_whole_and_priced_by_the_pack():
    bag = d.Product("SCREW-100", pack=100, per="pack", breaks=[(1, "9.85"), (5, "8.50")])
    assert bag.order(150) == (2, 200, d.Decimal("19.70"))
    assert bag.order(450) == (5, 500, d.Decimal("42.50"))


def test_a_quote_counts_items_by_what_the_part_declares_a_sku_is(fake):
    """A part declaring the reel as one SKU of 5000 asks for reels; one declaring nothing, for items."""
    reels = {
        "parts": {"r": {"vendor": "fake", "sku": "R-REEL", "count": 6000, "count_per_sku": 5000}},
        "skus": [{"vendor": "fake", "sku": "R-REEL", "count": 2, "parts": ["r"]}],
    }
    (line,) = fake().quote({"cart": reels})["lines"]
    assert (line["count"], line["items"], line["quantity"]) == (2, 10000, 10000)
    items = {"parts": {"r": {"vendor": "fake", "sku": "R-REEL", "count": 6000}}}
    (line,) = fake().quote({"cart": items})["lines"]
    # 6000 items are two whole reels.
    assert (line["count"], line["items"], line["packs"], line["quantity"]) == (6000, 6000, 2, 10000)


# --- a product's part, and its SKUs ----------------------------------------------


class Based(Fake):
    BASE_PARTS = True


@pytest.fixture
def based(tmp_path, monkeypatch):
    monkeypatch.setenv("PARTCAD_FAKE_CACHE", str(tmp_path))
    return lambda: Based({"parameters": {}})


def test_a_product_is_a_part_bought_by_its_manufacturers_number(based):
    config = based().get("objects/part/RC0603FR-0710KL~yageo")
    assert config["type"] == "step"
    assert (config["vendor"], config["sku"]) == ("YAGEO", "RC0603FR-0710KL")
    assert "count_per_sku" not in config
    assert "Sold by Fake as R-CT (Cut Tape), R-REEL (Tape & Reel, 5000 per SKU)" in config["desc"]


def test_each_sku_is_an_alias_of_the_products_part_with_its_pack(based):
    made = based()
    cut = made.get("objects/part/R-CT")
    assert (cut["type"], cut["source"]) == ("alias", ":RC0603FR-0710KL~yageo")
    assert (cut["vendor"], cut["sku"]) == ("fake", "R-CT") and "count_per_sku" not in cut
    reel = made.get("objects/part/R-REEL")
    assert (reel["source"], reel["sku"], reel["count_per_sku"]) == (":RC0603FR-0710KL~yageo", "R-REEL", 5000)


def test_a_search_answers_the_product_then_its_skus(based):
    hits = based().get("search/part?q=RC0603")
    assert list(hits) == ["RC0603FR-0710KL~yageo", "R-CT", "R-REEL"]
    assert hits["RC0603FR-0710KL~yageo"]["type"] == "step"
    assert hits["R-REEL"]["count_per_sku"] == 5000


def test_a_product_with_no_model_is_found_and_neither_it_nor_its_skus_served(based):
    hits = based().get("search/part?q=opamp")
    assert list(hits) == ["LT1013CN8%23PBF~analog-devices-inc", "LT1013CN8%23PBF"]
    assert all("type" not in hit for hit in hits.values())


def test_the_products_part_is_quoted_in_its_cheapest_sku(based):
    made = based()
    assert made.avail({"vendor": "YAGEO", "sku": "RC0603FR-0710KL", "count": 12})["sku"] == "R-CT"
    assert made.avail({"vendor": "YAGEO", "sku": "RC0603FR-0710KL", "count": 9000})["sku"] == "R-REEL"


def test_the_products_model_is_served_under_its_name(based):
    made = based()
    config = made.get("objects/part/RC0603FR-0710KL~yageo")
    assert d.base64.b64decode(made.get("files/" + config["path"])) == STEP


def test_a_tilde_in_a_part_number_is_not_the_separator(based):
    assert d.name_of("A~B") == "A%7EB"
    assert based().base_name(d.Product("X", mpn="A~B", manufacturer="M")) == "A%7EB~m"


@pytest.mark.parametrize(
    "vendor, manufacturer, same",
    [
        ("Texas Instruments", "texas-instruments", True),
        ("Analog Devices", "Analog Devices Inc.", True),
        ("Microchip", "Microchip Technology", True),
        ("onsemi", "ON Semiconductor", True),
        ("TE Connectivity", "TE", True),
        # An initialism is not the name it abbreviates, nor another one that
        # happens to begin with its letters.
        ("ti", "Texas Instruments", False),
        ("TE", "Texas Instruments", False),
        ("Intel", "Intelligent Memory", False),
        ("", "Texas Instruments", False),
    ],
)
def test_same_maker_compares_whole_words(vendor, manufacturer, same):
    assert d.Distributor.same_maker(vendor, manufacturer) is same
