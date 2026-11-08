#
# partcad-svc-commerce-octopart, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Octopart as a PartCAD store and catalogue, through the Nexar API (the "Octopart API").

One script serves both of the package's plugins: the store provider 'octopart'
(PartCAD asks it 'avail' and 'quote') and the repository 'octopart_repo' behind
//pub/svc/commerce/octopart/products (PartCAD asks it 'get'). What the two
answer is distributor.py's; what this says is how Nexar is asked.

Octopart sells nothing: it is a search engine over what authorized
distributors offer. So a part of this catalogue is a manufacturer's part -
'vendor' is the manufacturer and 'sku' its part number, which is what any
store quotes by - and is named by both, '<MPN>~<manufacturer>'
('BAV99~nexperia'), since two manufacturers can have one part number. The
store quotes the cheapest authorized offer for the quantity, among every
distributor's, in the user's currency (Nexar converts), and says which
distributor it is and its part number there. Nothing is ordered: Octopart has
no ordering, only links to each distributor's cart.

The API is Nexar's GraphQL endpoint (https://api.nexar.com/graphql), with an
app of the user's own at https://portal.nexar.com (OAuth 2.0 client
credentials, scope 'supply.domain'; a token lasts a day and is kept that long).
Nexar meters it in parts returned, monthly, and its free plan is small: a
search answers as many parts as it is asked for, so ask for few.

    supCategories                 the category tree (not metered)
    supSearch(q, filters)         a search, in a category ('category_id') or all
    supMultiMatch(queries)        a manufacturer's part by its MPN, with every offer
    part.cad                      whether there is a 3D model, and the KiCad
                                  library it comes in

Nexar has no STEP of its own to hand out: a part's 3D model comes inside the
ECAD library Octopart's CAD partner made of it, a zip for KiCad, from which the
STEP file is taken. Whether a plan includes CAD, and whether its downloads
need an Octopart sign-in, are Nexar's to decide; when they do, the part says
so rather than building.

Nexar's terms keep what it answers for a day at most, and a key is the user's
own, never a package's.
"""

import importlib.util
import io
import os
import re
import sys
import zipfile

# When this plugin's answers stopped meaning what they meant before. PartCAD
# keys everything it caches of the catalogue on it, so raise it with any change
# to what is answered - here or in distributor.py.
#
# v1: Octopart's categories and search; a manufacturer's part with its 3D model; the store.
CACHE_VERSION = 1


def _shared():
    """distributor.py, beside this script, under a name of this plugin's own."""
    name = "_partcad_octopart_distributor"
    if name not in sys.modules:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "distributor.py")
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


d = _shared()

API = "https://api.nexar.com/graphql"
TOKEN = "https://identity.nexar.com/connect/token"
WEB = "https://octopart.com"

# What every query asks of a part. 'sellers' only where offers are needed: a
# search lists parts, it does not price them.
PART = """
  id mpn shortDescription octopartUrl totalAvail
  manufacturer { id name }
  category { id name path }
  bestDatasheet { url }
  specs { attribute { shortname name } displayValue }
  cad { has3dModel hasKicad downloadUrlKicad }
"""
SELLERS = """
  sellers(authorizedOnly: true, includeBrokers: false) {
    company { id name }
    offers {
      sku inventoryLevel moq orderMultiple packaging factoryLeadDays clickUrl
      prices { quantity price currency convertedPrice convertedCurrency }
    }
  }
"""
SEARCH = (
    "query Search($q: String!, $limit: Int, $filters: Map, $country: String!, $currency: String!) {"
    " supSearch(q: $q, start: 0, limit: $limit, filters: $filters, country: $country, currency: $currency)"
    " { hits results { part { %s } } } }" % PART
)
MATCH = (
    "query Match($queries: [SupPartMatchQuery!]!, $country: String!, $currency: String!) {"
    " supMultiMatch(queries: $queries, country: $country, currency: $currency,"
    " options: {requireAuthorizedSellers: true}) { reference hits parts { %s %s } } }" % (PART, SELLERS)
)
CATEGORIES = "query Categories { supCategories { id name parentId path numParts } }"

# The name of a part: its MPN, '~', and its manufacturer's slug.
SEPARATOR = "~"


def key_of(mpn, manufacturer):
    return "%s%s%s" % (mpn, SEPARATOR, d.slug(manufacturer))


class Octopart(d.Distributor):
    NAME = "octopart"
    TITLE = "Octopart"
    URL = WEB
    DESC = (
        "Octopart's index of what authorized distributors sell, by Octopart's categories: search it, and every "
        "part Octopart has a 3D model of is a part, named '<MPN>~<manufacturer>' and bought by its manufacturer "
        "and MPN - from whichever distributor offers it cheapest. Nothing is listed."
    )
    VERSION = CACHE_VERSION
    VENDOR = "octopart"
    VENDOR_ALIASES = ("nexar",)
    PACKAGE = "//pub/svc/commerce/octopart"
    STORE = "octopart"
    CATALOGUE = "octopart_repo"
    CAD_SOURCE = "Octopart's CAD partner, in its KiCad library"
    CREDENTIALS = {"client_id": "NEXAR_CLIENT_ID", "client_secret": "NEXAR_CLIENT_SECRET"}
    LOGIN_INSTRUCTIONS = (
        "Octopart's API is Nexar's, and takes the Client ID and Client Secret of an app of your own. Sign up at "
        "https://portal.nexar.com, create an app with the Supply scope, and copy its Client ID and Client Secret "
        "from the app's Authorization tab. The free plan answers a limited number of parts a month."
    )

    def __init__(self, request=None):
        super().__init__(request)
        credentials = self.credentials()
        self.client_id = credentials["client_id"]
        self.client_secret = credentials["client_secret"]

    # -- the wire --

    def graphql(self, query, variables, what, ttl=d.PRODUCT_TTL):
        token = self.bearer(TOKEN, self.client_id, self.client_secret, what, extra={"scope": "supply.domain"})
        answer = self.http.json(
            API,
            what,
            headers={"Authorization": "Bearer " + token},
            data={"query": query, "variables": variables},
            ttl=ttl,
            # A GraphQL failure is a 200 with 'errors': not one to keep.
            valid=lambda value: isinstance(value, dict) and not value.get("errors"),
        )
        errors = (answer or {}).get("errors") if isinstance(answer, dict) else None
        if errors:
            message = "; ".join(str(e.get("message")) for e in errors if isinstance(e, dict))
            raise d.SiteError("octopart: %s: %s" % (what, message[:300]))
        return (answer or {}).get("data") or {}

    def where(self):
        return {"country": self.country or "US", "currency": self.currency or "USD"}

    # -- the catalogue --

    def fetch_categories(self):
        data = self.graphql(CATEGORIES, {}, "Octopart's categories", ttl=d.DAY)
        found = {}
        for item in data.get("supCategories") or []:
            if isinstance(item, dict) and item.get("id"):
                path = item.get("path") or ""
                found[str(item["id"])] = (
                    item,
                    d.Category(
                        item["id"], item.get("name"), count=item.get("numParts"), url=WEB + path if path else None
                    ),
                )
        roots = []
        for item, category in found.values():
            parent = found.get(str(item.get("parentId") or ""))
            (parent[1].children if parent else roots).append(category)
        # Everything is under one root, 'Electronic Parts': its children are the top.
        if len(roots) == 1 and roots[0].children:
            roots = roots[0].children
        return roots

    def find_products(self, text, category, limit):
        variables = dict(self.where(), q=text, limit=min(limit, 50))
        if category is not None:
            variables["filters"] = {"category_id": [category.id]}
        data = self.graphql(SEARCH, variables, "a search for '%s'" % text, ttl=d.SEARCH_TTL)
        results = (data.get("supSearch") or {}).get("results") or []
        return [self.product_of(r["part"]) for r in results if isinstance(r, dict) and isinstance(r.get("part"), dict)]

    def match(self, mpn, what):
        variables = dict(self.where(), queries=[{"mpn": mpn, "limit": 10, "reference": "1"}])
        data = self.graphql(MATCH, variables, what, ttl=d.OFFER_TTL)
        parts = []
        for result in data.get("supMultiMatch") or []:
            parts.extend(p for p in (result or {}).get("parts") or [] if isinstance(p, dict))
        return [self.product_of(p) for p in parts]

    def find_mpn(self, manufacturer, mpn):
        return self.match(mpn, "the offers of %s" % mpn)

    def fetch_product(self, sku):
        mpn, separator, maker = sku.rpartition(SEPARATOR) if SEPARATOR in sku else (sku, "", "")
        found = [p for p in self.match(mpn, "part %s" % sku) if d.fold(p.mpn) == d.fold(mpn)]
        if separator:
            found = [p for p in found if d.slug(p.manufacturer) == maker]
        if len(found) == 1 or (found and separator):
            return found[0]
        if found:
            raise d.NotFound(
                "octopart: %s is made by %s: name one, '%s'"
                % (mpn, " and by ".join(str(p.manufacturer) for p in found), d.name_of(found[0].sku))
            )
        raise d.NotFound("octopart: Octopart has no part %s" % sku)

    def product_of(self, part):
        manufacturer = (part.get("manufacturer") or {}).get("name")
        category = part.get("category") or {}
        cad = part.get("cad") or {}
        files = []
        if cad.get("has3dModel") and cad.get("downloadUrlKicad"):
            # The STEP inside the KiCad library: named as what it is, fetched as what it comes in.
            name = "%s.step" % re.sub(r"[^A-Za-z0-9._-]+", "_", part.get("mpn") or "model")
            files.append(d.File("kicad", name, url=cad["downloadUrlKicad"]))
        return d.Product(
            key_of(part.get("mpn"), manufacturer),
            mpn=part.get("mpn"),
            manufacturer=manufacturer,
            title=part.get("shortDescription"),
            url=part.get("octopartUrl"),
            datasheet=(part.get("bestDatasheet") or {}).get("url"),
            stock=d.whole(part.get("totalAvail")),
            categories=[category.get("id")] if category.get("id") else [],
            specs=[
                ((s.get("attribute") or {}).get("name"), s.get("displayValue"))
                for s in part.get("specs") or []
                if isinstance(s, dict)
            ],
            files=files,
            extra={"sellers": part.get("sellers"), "id": part.get("id")},
        )

    def vendor_sku(self, product):
        return product.manufacturer, product.mpn

    def sold(self, product):
        sellers = [s for s in product.extra.get("sellers") or [] if (s or {}).get("offers")]
        names = [str((s.get("company") or {}).get("name")) for s in sellers]
        if names:
            text = "Offered by %d authorized distributor%s: %s" % (
                len(names),
                "" if len(names) == 1 else "s",
                ", ".join(names[:6]) + (", ..." if len(names) > 6 else ""),
            )
        else:
            text = "Indexed by Octopart"
        if product.stock:
            text += "; %s in stock among them" % format(product.stock, ",")
        return text

    def download(self, model, file):
        what = "the 3D model of %s" % model.id
        data = self.http.download(file.extra["url"], what)
        if not d.pm.is_zip(data):
            raise d.NeedsCredentials(
                "octopart: %s did not come as a library: Octopart's CAD downloads may take an Octopart "
                "sign-in or a plan with CAD, which this plugin cannot give" % what
            )
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            steps = [m for m in archive.namelist() if m.lower().endswith((".step", ".stp"))]
            if not steps:
                raise d.NotFound("octopart: the KiCad library of %s has no STEP model in it" % model.id)
            return archive.read(sorted(steps, key=lambda m: ("3d" not in m.lower(), len(m)))[0])

    # -- the store --

    def offers_of(self, product):
        """Every authorized distributor's offer of a part, priced in the user's currency."""
        wanted = self.where()["currency"]
        offers = []
        for seller in product.extra.get("sellers") or []:
            name = ((seller or {}).get("company") or {}).get("name")
            for offer in (seller or {}).get("offers") or []:
                if not isinstance(offer, dict) or not offer.get("sku"):
                    continue
                breaks, currencies = {}, set()
                for point in offer.get("prices") or []:
                    quantity = d.whole(point.get("quantity"))
                    if point.get("currency") == wanted:
                        price, currency = point.get("price"), wanted
                    else:
                        price, currency = point.get("convertedPrice"), point.get("convertedCurrency")
                    if quantity and price is not None and currency:
                        currencies.add(currency)
                        # A quantity listed in two currencies: the one in the user's, else the cheaper.
                        native = point.get("currency") == wanted
                        if quantity not in breaks or native or d.decimal(price) < breaks[quantity][0]:
                            breaks[quantity] = (d.decimal(price), native)
                if len(currencies) != 1:
                    continue  # unpriced, or priced in what Nexar did not convert
                offers.append(
                    d.Product(
                        offer["sku"],
                        mpn=product.mpn,
                        manufacturer=product.manufacturer,
                        url=offer.get("clickUrl"),
                        stock=d.whole(offer.get("inventoryLevel")),
                        moq=offer.get("moq"),
                        multiple=offer.get("orderMultiple"),
                        packaging=offer.get("packaging"),
                        lead_time=offer.get("factoryLeadDays") and "%s days" % offer["factoryLeadDays"],
                        breaks=[(q, price) for q, (price, _) in breaks.items()],
                        currency=currencies.pop(),
                        extra={"seller": name},
                    )
                )
        return offers

    # -- logging in --

    def whoami(self, credentials):
        if not credentials.get("client_id") or not credentials.get("client_secret"):
            return None
        try:
            self.bearer(
                TOKEN,
                credentials["client_id"],
                credentials["client_secret"],
                "logging in",
                extra={"scope": "supply.domain"},
            )
        except d.NeedsCredentials:
            return None
        return "the Nexar app %s..." % credentials["client_id"][:8]

    def login_spec(self):
        return {
            "url": "https://portal.nexar.com",
            "title": "Nexar (Octopart) API",
            "capture": [
                {"name": "client_id", "ask": {"label": "The Client ID of your Nexar app", "secret": False}},
                {"name": "client_secret", "ask": {"label": "The Client Secret of your Nexar app", "secret": True}},
            ],
        }


# Last, so that everything above is defined when PartCAD runs this.
if __name__ in ("get", "login", "avail", "quote", "caps", "order"):
    output = d.run(Octopart, __name__, globals().get("request") or {}, globals().get("partcad_login"))
