#
# partcad-svc-commerce-digikey, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""DigiKey as a PartCAD store and catalogue, through DigiKey's Product Information API v4.

One script serves both of the package's plugins: the store provider 'digikey'
(PartCAD asks it 'avail' and 'quote') and the repository 'digikey_repo' behind
//pub/svc/commerce/digikey/products (PartCAD asks it 'get'). What the two
answer is distributor.py's; what this says is how DigiKey is asked.

The API is DigiKey's own, documented at https://developer.digikey.com, and
free: an application registered there ("Production", with the Product
Information API) has a Client ID and a Client Secret, which are this plugin's
'client_id' and 'client_secret' parameters - set by 'pc login', or given as
DIGIKEY_CLIENT_ID and DIGIKEY_CLIENT_SECRET. They are exchanged for an access
token (OAuth 2.0 client credentials, a 2-legged flow: no DigiKey account is
signed in to), which lasts ten minutes and is kept that long.

    POST /v1/oauth2/token                                   the token
    GET  /products/v4/search/categories                     the category tree
    POST /products/v4/search/keyword                        a search, in a category or all of them
    GET  /products/v4/search/{product number}/productdetails one product, its prices and stock
    GET  /products/v4/search/{product number}/media         its pictures, datasheets and models

Every request says where the user is - the site, the language and the currency
(X-DIGIKEY-Locale-*) - from what PartCAD says of the user (their country,
language and currency), so a price is the one DigiKey shows them.

A product of DigiKey is sold in several packagings - cut tape, tape and reel,
Digi-Reel, a tube - each a DigiKey part number of its own, with its own
minimum and its own price breaks. A part of the catalogue is one of those
numbers, and it is what is quoted; a part given by its manufacturer and MPN is
quoted in the packaging that makes the quantity asked for cheapest. A
Digi-Reel's reeling fee is not in a quote.

A 3D model is among a product's media when DigiKey has one (a 'MediaType'
naming a 3D or CAD model). Most of DigiKey's models are its own, a STEP file on
its media server; an EDA/CAD model link to a partner's site (SnapEDA, Ultra
Librarian) is a page to sign in to, not a file, and is not followed.
"""

import concurrent.futures
import importlib.util
import io
import os
import sys
import threading
import urllib.parse
import zipfile

# When this plugin's answers stopped meaning what they meant before. PartCAD
# keys everything it caches of the catalogue on it, so raise it with any change
# to what is answered - here or in distributor.py.
#
# v1: DigiKey's categories, search, products with their 3D models; the store.
CACHE_VERSION = 1


def _shared():
    """distributor.py, beside this script, under a name of this plugin's own."""
    name = "_partcad_digikey_distributor"
    if name not in sys.modules:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "distributor.py")
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


d = _shared()

API = "https://api.digikey.com"
SANDBOX = "https://sandbox-api.digikey.com"
WEB = "https://www.digikey.com"

# DigiKey's sites, by the country PartCAD says the user is in, and the
# currencies each prices in. A country with no site of its own is served by
# the US site, in US dollars, which is what DigiKey does.
SITES = {
    "US": ("USD",),
    "CA": ("CAD", "USD"),
    "MX": ("USD",),
    "GB": ("GBP", "EUR", "USD"),
    "UK": ("GBP", "EUR", "USD"),
    "DE": ("EUR", "USD"),
    "FR": ("EUR", "USD"),
    "IT": ("EUR", "USD"),
    "ES": ("EUR", "USD"),
    "NL": ("EUR", "USD"),
    "BE": ("EUR", "USD"),
    "AT": ("EUR", "USD"),
    "IE": ("EUR", "USD"),
    "FI": ("EUR", "USD"),
    "PT": ("EUR", "USD"),
    "CH": ("CHF", "EUR", "USD"),
    "SE": ("SEK", "EUR", "USD"),
    "DK": ("DKK", "EUR", "USD"),
    "NO": ("NOK", "EUR", "USD"),
    "PL": ("PLN", "EUR", "USD"),
    "CZ": ("CZK", "EUR", "USD"),
    "HU": ("HUF", "EUR", "USD"),
    "IL": ("ILS", "USD"),
    "JP": ("JPY", "USD"),
    "CN": ("CNY", "USD"),
    "HK": ("HKD", "USD"),
    "TW": ("TWD", "USD"),
    "KR": ("KRW", "USD"),
    "SG": ("SGD", "USD"),
    "IN": ("INR", "USD"),
    "AU": ("AUD", "USD"),
    "NZ": ("NZD", "USD"),
}
LANGUAGES = ("en", "ja", "de", "fr", "ko", "zhs", "zht", "it", "es", "he", "nl", "sv", "pl", "fi", "da", "no")

# What a medium is called when it may be a model of the product ('3D Models',
# 'EDA / CAD Models', 'EDA Models'). Most such links are a CAD partner's page
# (SnapEDA, Ultra Librarian) to sign in to, not a file: only a link to a file
# PartCAD reads, or a zip of one, is taken.
MODEL_MEDIA = ("3d", "cad", "eda", "model")


class DigiKey(d.Distributor):
    NAME = "digikey"
    TITLE = "DigiKey"
    URL = WEB
    DESC = (
        "DigiKey's range, by DigiKey's own categories: search it, and every product DigiKey has a 3D model of "
        "is a part, bought from DigiKey by its DigiKey part number. Nothing is listed."
    )
    VERSION = CACHE_VERSION
    VENDOR = "digikey"
    VENDOR_ALIASES = ("digi-key", "digikey electronics", "digi-key electronics")
    PACKAGE = "//pub/svc/commerce/digikey"
    STORE = "digikey"
    CATALOGUE = "digikey_repo"
    CREDENTIALS = {"client_id": "DIGIKEY_CLIENT_ID", "client_secret": "DIGIKEY_CLIENT_SECRET"}
    LOGIN_INSTRUCTIONS = (
        "DigiKey's API takes the Client ID and Client Secret of an application of your own, and is free. Sign in "
        "at https://developer.digikey.com, create an organization if you have none, then a production app "
        "(any name; the OAuth callback may be https://localhost) with the Product Information API v4, and copy "
        "its Client ID and Client Secret from the app's page."
    )

    def __init__(self, request=None):
        super().__init__(request)
        credentials = self.credentials()
        self.client_id = credentials["client_id"]
        self.client_secret = credentials["client_secret"]
        parameters = self.request.get("parameters") or {}
        self.api = SANDBOX if str(parameters.get("sandbox") or "").lower() in ("1", "true", "yes") else API
        # Your DigiKey account number, for your own prices; unset is DigiKey's standard ones.
        self.account = str(parameters.get("account") or "").strip()
        # The media asked for, by DigiKey number: every packaging of a product shares them.
        self._media = {}
        self._media_lock = threading.Lock()

    # -- the wire --

    def cache_scope(self):
        account = str((self.request.get("parameters") or {}).get("account") or "").strip()
        return "%s|%s" % ("|".join(self.locale()), account)

    def locale(self):
        """(site, language, currency): what DigiKey prices in for the user, as close to what they asked as it has."""
        site = self.country if self.country in SITES else "US"
        if site == "UK":
            site = "GB"
        currencies = SITES[site]
        currency = self.currency if self.currency in currencies else currencies[0]
        language = self.language if self.language in LANGUAGES else "en"
        return site, language, currency

    def headers(self, what):
        token = self.bearer(self.api + "/v1/oauth2/token", self.client_id, self.client_secret, what)
        site, language, currency = self.locale()
        headers = {
            "Authorization": "Bearer " + token,
            "X-DIGIKEY-Client-Id": self.client_id,
            "X-DIGIKEY-Locale-Site": site,
            "X-DIGIKEY-Locale-Language": language,
            "X-DIGIKEY-Locale-Currency": currency,
        }
        if self.account:
            # What replaced X-DIGIKEY-Customer-Id (2025-11-24): it is what 'MyPricing' is for.
            headers["X-DIGIKEY-Account-Id"] = self.account
        return headers

    def ask(self, path, what, data=None, ttl=d.PRODUCT_TTL):
        return self.http.json(self.api + path, what, headers=self.headers(what), data=data, ttl=ttl)

    # -- the catalogue --

    def fetch_categories(self):
        answer = self.ask("/products/v4/search/categories", "DigiKey's categories", ttl=d.CATEGORIES_TTL)
        return [category_of(c) for c in (answer or {}).get("Categories") or []]

    def find_products(self, text, category, limit):
        body = {"Keywords": text, "Limit": min(limit, 50), "Offset": 0}
        if category is not None:
            body["FilterOptionsRequest"] = {"CategoryFilter": [{"Id": category.id}]}
        answer = self.ask("/products/v4/search/keyword", "a search for '%s'" % text, data=body, ttl=d.SEARCH_TTL)
        # The same search, of what DigiKey has a 3D model of: a product's media
        # cost a request each, and DigiKey's daily quota is a thousand, so only
        # these are asked what their model is.
        modelled = dict(body)
        modelled["FilterOptionsRequest"] = dict(body.get("FilterOptionsRequest") or {}, SearchOptions=["Has3DModel"])
        with_model = self.ask(
            "/products/v4/search/keyword", "a search for '%s' with models" % text, data=modelled, ttl=d.SEARCH_TTL
        )
        has_model = {
            item.get("ManufacturerProductNumber")
            for item in list(with_model.get("ExactMatches") or []) + list(with_model.get("Products") or [])
            if isinstance(item, dict)
        }
        found, seen = [], set()
        for item in list(answer.get("ExactMatches") or []) + list(answer.get("Products") or []):
            for product in self.products_of(item):
                if product.sku not in seen:
                    seen.add(product.sku)
                    product.extra["has_model"] = product.mpn in has_model
                    found.append(product)
        return found

    def find_mpn(self, manufacturer, mpn):
        # The live prices of every DigiKey listing of a manufacturer's part number.
        quoted = urllib.parse.quote(mpn, safe="")
        answer = self.ask(
            "/products/v4/search/%s/pricing?limit=10&excludeMarketplace=true" % quoted,
            "the listings of %s" % mpn,
            ttl=d.OFFER_TTL,
        )
        found = []
        for item in (answer or {}).get("ProductPricings") or []:
            if isinstance(item, dict):
                found.extend(self.products_of(item))
        return found

    def fetch_product(self, sku):
        quoted = urllib.parse.quote(sku, safe="")
        answer = self.ask("/products/v4/search/%s/productdetails" % quoted, "product %s" % sku, ttl=d.OFFER_TTL)
        item = (answer or {}).get("Product")
        if not isinstance(item, dict):
            raise d.NotFound("digikey: product %s: not found" % sku)
        products = self.products_of(item)
        # The packaging asked for, else (a manufacturer's number) the first.
        for product in products:
            if d.fold(product.sku) == d.fold(sku):
                return product
        if products:
            return products[0]
        raise d.NotFound("digikey: product %s: not found" % sku)

    def products_of(self, item):
        """A DigiKey product as one Product per packaging: each is a DigiKey part number of its own."""
        common = {
            "mpn": item.get("ManufacturerProductNumber"),
            "manufacturer": ((item.get("Manufacturer") or {}).get("Name")),
            "title": ((item.get("Description") or {}).get("ProductDescription")),
            "desc": ((item.get("Description") or {}).get("DetailedDescription")),
            "url": item.get("ProductUrl"),
            "datasheet": item.get("DatasheetUrl"),
            "status": ((item.get("ProductStatus") or {}).get("Status")),
            # 'productdetails' says a product's category nested, 'pricing' as a flat list.
            "categories": category_ids(item.get("Category"))
            or [str(c.get("CategoryId")) for c in item.get("Categories") or [] if isinstance(c, dict)],
            "specs": [
                (p.get("ParameterText"), p.get("ValueText"))
                for p in item.get("Parameters") or []
                if isinstance(p, dict) and p.get("ValueText") not in (None, "", "-")
            ],
            "currency": self.locale()[2],
            "lead_time": item.get("ManufacturerLeadWeeks") and "%s weeks" % item["ManufacturerLeadWeeks"],
        }
        gone = any(item.get(k) for k in ("Discontinued", "EndOfLife", "IsDiscontinued", "IsObsolete", "IsEndOfLife"))
        orderable = not gone and d.fold(common["status"]) not in (
            "obsolete",
            "discontinuedatdigikey",
            "notfornewdesigns",
        )
        files = self.models_in(item.get("MediaLinks"))
        # Every packaging of a product has the same media: asked for once, by the first.
        first = next((v.get("DigiKeyProductNumber") for v in item.get("ProductVariations") or []), None)
        products = []
        for variation in item.get("ProductVariations") or []:
            sku = variation.get("DigiKeyProductNumber")
            if not sku:
                continue
            pricing = variation.get("MyPricing") or variation.get("StandardPricing") or []
            products.append(
                d.Product(
                    sku,
                    packaging=((variation.get("PackageType") or {}).get("Name")),
                    moq=variation.get("MinimumOrderQuantity"),
                    stock=d.whole(variation.get("QuantityAvailableforPackageType"), item.get("QuantityAvailable")),
                    breaks=[(p.get("BreakQuantity"), p.get("UnitPrice")) for p in pricing if isinstance(p, dict)],
                    orderable=orderable and variation.get("MarketPlace") is not True,
                    files=files,
                    extra={"media_of": first},
                    **common,
                )
            )
        return products

    def models_in(self, media):
        """The 3D models among a product's media, as Files; None when what was read did not list its media."""
        if media is None:
            return None
        files = []
        for link in media:
            if not isinstance(link, dict) or not link.get("Url"):
                continue
            kind = d.fold(link.get("MediaType"))
            if not any(word in kind for word in MODEL_MEDIA):
                continue
            url = urllib.parse.urljoin(WEB, link["Url"])
            name = urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1]) or "model"
            if d.pm.format_of(name) is None and not name.lower().endswith(".zip"):
                continue  # a page about a model, not a file of one
            files.append(d.File(url, name, url=url))
        return files

    def cad_files(self, product):
        if product.extra.get("has_model") is False:
            return []  # a search said DigiKey has no model of it: not worth a request
        sku = product.extra.get("media_of") or product.sku
        with self._media_lock:
            pending = self._media.get(sku)
            if pending is None:
                pending = self._media[sku] = concurrent.futures.Future()
                mine = True
            else:
                mine = False
        if mine:
            try:
                quoted = urllib.parse.quote(sku, safe="")
                answer = self.ask("/products/v4/search/%s/media" % quoted, "the media of %s" % sku)
                pending.set_result(self.models_in((answer or {}).get("MediaLinks") or []) or [])
            except BaseException as e:
                pending.set_exception(e)
        return list(pending.result())

    def download(self, model, file):
        data = self.http.download(file.extra["url"], "the 3D model %s of %s" % (file.name, model.id))
        if d.pm.is_zip(data):
            # A model handed out zipped: the first file in it PartCAD reads.
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for member in archive.namelist():
                    if d.pm.format_of(member) is not None:
                        return archive.read(member)
            raise d.NotFound("digikey: the 3D model %s of %s holds no file PartCAD reads" % (file.name, model.id))
        return data

    # -- logging in --

    def whoami(self, credentials):
        if not credentials.get("client_id") or not credentials.get("client_secret"):
            return None
        try:
            self.bearer(
                self.api + "/v1/oauth2/token", credentials["client_id"], credentials["client_secret"], "logging in"
            )
        except d.NeedsCredentials:
            return None
        return "the DigiKey app %s..." % credentials["client_id"][:8]

    def login_spec(self):
        return {
            "url": "https://developer.digikey.com/teams",
            "title": "DigiKey API",
            "capture": [
                {"name": "client_id", "ask": {"label": "The Client ID of your DigiKey app", "secret": False}},
                {"name": "client_secret", "ask": {"label": "The Client Secret of your DigiKey app", "secret": True}},
            ],
        }


def category_of(item):
    category = d.Category(
        item.get("CategoryId"),
        item.get("Name"),
        count=item.get("ProductCount"),
        url="%s/en/products/filter/%s/%s" % (WEB, d.slug(item.get("Name")), item.get("CategoryId")),
    )
    # 'Children' in the category tree, 'ChildCategories' in a product's category.
    children = item.get("Children") or item.get("ChildCategories") or []
    category.children = [category_of(c) for c in children if isinstance(c, dict)]
    return category


def category_ids(category):
    """A product's category and the ones under it it is filed in, as DigiKey nests them: [id, ...]."""
    ids = []
    while isinstance(category, dict):
        if category.get("CategoryId") is not None:
            ids.append(str(category["CategoryId"]))
        children = category.get("ChildCategories") or category.get("Children") or []
        category = children[0] if children else None
    return ids


# Last, so that everything above is defined when PartCAD runs this.
if __name__ in ("get", "login", "avail", "quote", "caps", "order"):
    output = d.run(DigiKey, __name__, globals().get("request") or {}, globals().get("partcad_login"))
