#
# partcad-svc-commerce-mouser, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Mouser as a PartCAD store and a searchable catalogue, through Mouser's Search API.

One script serves both of the package's plugins: the store provider 'mouser'
(PartCAD asks it 'avail' and 'quote') and the repository 'mouser_repo' behind
//pub/svc/commerce/mouser/products (PartCAD asks it 'get'). What the two answer
is distributor.py's; what this says is how Mouser is asked.

The API is Mouser's own (https://api.mouser.com/api/docs/ui/index), with a
Search API key the user requests from their My Mouser account - free, and
given at once. The key goes in the query string of every request, which is
Mouser's choice: it is the plugin's 'api_key' parameter, set by 'pc login', or
MOUSER_API_KEY.

    POST /api/v1/search/keyword       a search: {"SearchByKeywordRequest": {...}}
    POST /api/v1/search/partnumber    up to ten numbers, Mouser's or a manufacturer's,
                                      separated by '|': {"SearchByPartRequest": {...}}

Mouser's API is a store's: prices (up to four breaks), stock, the minimum and
the multiple, by Mouser's part number or a manufacturer's. It has no category
tree and no CAD: the catalogue is one package, searched with Mouser's search,
and every product it finds is found and not served - listed with its Mouser
number to quote it by, since Mouser hands out no 3D model to build it from.
Prices are in the currency of the account the key belongs to, which every
price break says. Mouser allows a key 30 requests a minute and 1,000 a day.
"""

import importlib.util
import os
import sys
import urllib.parse

# When this plugin's answers stopped meaning what they meant before. PartCAD
# keys everything it caches of the catalogue on it, so raise it with any change
# to what is answered - here or in distributor.py.
#
# v1: Mouser's search, and its store.
CACHE_VERSION = 1


def _shared():
    """distributor.py, beside this script, under a name of this plugin's own."""
    name = "_partcad_mouser_distributor"
    if name not in sys.modules:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "distributor.py")
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


d = _shared()

API = "https://api.mouser.com/api/v1"
WEB = "https://www.mouser.com"

# What Mouser says of a product that can no longer be ordered.
GONE = ("obsolete", "endoflife", "discontinued", "factorydiscontinued")


class Mouser(d.Distributor):
    NAME = "mouser"
    TITLE = "Mouser"
    URL = WEB
    DESC = (
        "Mouser's range, searched with Mouser's search. Mouser's API has no categories and no 3D models: a product "
        "is found, with the Mouser part number to quote it by, and is not a part to build. Nothing is listed."
    )
    VERSION = CACHE_VERSION
    VENDOR = "mouser"
    VENDOR_ALIASES = ("mouser electronics",)
    PACKAGE = "//pub/svc/commerce/mouser"
    STORE = "mouser"
    CATALOGUE = "mouser_repo"
    CREDENTIALS = {"api_key": "MOUSER_API_KEY"}
    LOGIN_INSTRUCTIONS = (
        "Mouser's Search API takes a key of your own, which is free: sign in to My Mouser at https://www.mouser.com, "
        "fill in the Search API request form at https://www.mouser.com/api-search/ and copy the key it gives (it is "
        "also under My Mouser > APIs). The Cart and Order keys are not this one."
    )

    def __init__(self, request=None):
        super().__init__(request)
        self.api_key = self.credentials()["api_key"]

    def cache_scope(self):
        # Prices follow the key's account, and the key is in every URL.
        return ""

    def meta_of(self, category):
        meta = super().meta_of(category)
        # Nothing it answers is a part to build: what a search finds is said, not instantiated.
        meta["instanceKinds"] = []
        return meta

    # -- the wire --

    def ask(self, path, body, what, ttl):
        if not self.api_key:
            raise self.needs_credentials(what)
        url = "%s%s?%s" % (API, path, urllib.parse.urlencode({"apiKey": self.api_key}))
        answer = self.http.json(
            url,
            what,
            data=body,
            ttl=ttl,
            # Mouser answers a failure with a 200 and 'Errors': not one to keep.
            valid=lambda value: isinstance(value, dict) and not value.get("Errors"),
        )
        errors = [e for e in (answer or {}).get("Errors") or [] if isinstance(e, dict)]
        if errors:
            message = "; ".join(str(e.get("Message") or e.get("Code")) for e in errors)
            if any(d.fold(e.get("Code")) in ("invalid", "unauthorized") for e in errors) or "key" in message.lower():
                raise d.NeedsCredentials("mouser: %s: %s: %s again" % (what, message, self.login_command()))
            raise d.SiteError("mouser: %s: %s" % (what, message))
        return [self.product_of(p) for p in ((answer or {}).get("SearchResults") or {}).get("Parts") or []]

    # -- the catalogue --

    def find_products(self, text, category, limit):
        body = {
            "SearchByKeywordRequest": {
                "keyword": text,
                "records": min(limit, 50),
                "startingRecord": 0,
                "searchOptions": "None",
                "searchWithYourSignUpLanguage": "false",
            }
        }
        return [p for p in self.ask("/search/keyword", body, "a search for '%s'" % text, d.SEARCH_TTL) if p]

    def by_number(self, number, what):
        body = {"SearchByPartRequest": {"mouserPartNumber": number, "partSearchOptions": "Exact"}}
        return [p for p in self.ask("/search/partnumber", body, what, d.OFFER_TTL) if p]

    def fetch_product(self, sku):
        found = self.by_number(sku, "part %s" % sku)
        for product in found:
            if d.fold(product.sku) == d.fold(sku):
                return product
        raise d.NotFound("mouser: Mouser has no part %s" % sku)

    def find_mpn(self, manufacturer, mpn):
        return self.by_number(mpn, "the listings of %s" % mpn)

    def product_of(self, part):
        if not isinstance(part, dict):
            return None
        sku = str(part.get("MouserPartNumber") or "").strip()
        if not sku or sku.upper() == "N/A":
            return None  # listed, and not sold by Mouser
        status = part.get("LifecycleStatus") or ""
        discontinued = str(part.get("IsDiscontinued") or "").strip().lower() == "true"
        breaks, currency = [], None
        for price in part.get("PriceBreaks") or []:
            if not isinstance(price, dict):
                continue
            # 'RawPrice' where Mouser says it; 'Price' is written for a person ('6,85 €').
            value = price.get("RawPrice") if price.get("RawPrice") is not None else price.get("Price")
            breaks.append((price.get("Quantity"), value))
            currency = currency or price.get("Currency")
        attributes = {
            a.get("AttributeName"): a.get("AttributeValue")
            for a in part.get("ProductAttributes") or []
            if isinstance(a, dict)
        }
        return d.Product(
            sku,
            mpn=part.get("ManufacturerPartNumber"),
            manufacturer=part.get("Manufacturer"),
            title=part.get("Description"),
            url=part.get("ProductDetailUrl"),
            datasheet=part.get("DataSheetUrl"),
            status=status or ("Discontinued" if discontinued else None),
            orderable=not discontinued and d.fold(status) not in GONE and not part.get("RestrictionMessage"),
            stock=d.whole(part.get("AvailabilityInStock"), 0),
            moq=part.get("Min"),
            multiple=part.get("Mult"),
            packaging=attributes.get("Packaging"),
            lead_time=part.get("LeadTime"),
            breaks=breaks,
            currency=currency,
            specs=[("Category", part.get("Category"))] + [(k, v) for k, v in attributes.items() if k != "Packaging"],
            files=[],
        )

    def download(self, model, file):
        raise d.NotFound("mouser: Mouser's API hands out no 3D models")

    # -- logging in --

    def whoami(self, credentials):
        key = credentials.get("api_key")
        if not key:
            return None
        self.api_key = key
        try:
            # One request of the day's thousand: the cheapest question there is.
            self.by_number("LM358", "a check of the key")
        except d.NeedsCredentials:
            return None
        return "a Mouser Search API key %s..." % key[:8]

    def login_spec(self):
        return {
            "url": "https://www.mouser.com/api-search/",
            "title": "Mouser Search API",
            "capture": [
                {
                    "name": "api_key",
                    "ask": {"label": "Your Mouser Search API key", "secret": True},
                }
            ],
        }


# Last, so that everything above is defined when PartCAD runs this.
if __name__ in ("get", "login", "avail", "quote", "caps", "order"):
    output = d.run(Mouser, __name__, globals().get("request") or {}, globals().get("partcad_login"))
