#
# PartCAD distributor plugins, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What the PartCAD plugins for parts distributors have in common.

This file is in every distributor package (the partcad-svc-commerce-<store>
packages: digikey, mouser, octopart, mcmaster), byte for byte; change it in all
of them, and raise each plugin's CACHE_VERSION when what it answers changes.
Each plugin's own script (``<store>.py``) says how its distributor's API is
asked; this says what PartCAD is answered.

A distributor is two things to PartCAD, and one script serves both:

* **a catalogue** - a ``basic`` repository plugin behind the package's
  external dependency ``products``. Its child packages are the distributor's
  own categories; nothing is listed (a range of millions of products is not
  something to enumerate), and every package searches the distributor itself
  (``searchKinds``). A product is a part named by the distributor's part
  number - ``products/<category>/...:<part number>`` - whose geometry is the
  3D model the distributor offers for it, fetched through the plugin as
  ``files/<path>`` (the plugin holds the credentials), and which says
  ``vendor`` and ``sku``, so that it can be bought. A product with no 3D model
  is found by a search, said to have none, and not served: it is still sold,
  and a part of one's own with its ``vendor`` and ``sku`` is quoted like any
  other.

* **a store** - a ``store`` provider, asked ``avail`` and ``quote`` for a
  vendor and a SKU. The SKU is the distributor's own part number when the
  vendor is the distributor's (which is what every product of the catalogue
  says); with any other vendor it is taken to be that manufacturer's part
  number, and the distributor's listing of it is looked up, so a part declared
  with its manufacturer and MPN anywhere - not only in this catalogue - can be
  quoted here. A quote is priced at the quantity actually ordered: raised to
  the minimum order quantity and to the order multiple, at the price break it
  then falls in. Stock is said, never refused - a quote is for what is asked,
  and says per line how many the distributor has.

The repository protocol and the name grammar are PartCAD's, and so are the
HTTP client, its cache and the errors: they come from ``plugin_models``, the
toolkit PartCAD gives every repository plugin (PartCAD 0.9.17 or newer), which
this builds on rather than copies.

Credentials are the user's, never a package's: each API's keys are the
plugin's parameters, set by ``pc login`` (which keeps them in
~/.partcad/config.yaml) or by the environment variables each plugin names. A
store and its catalogue are two plugins, and each keeps its own: log in to
both.
"""

import base64
import concurrent.futures
import hashlib
import json
import os
import re
import time
import unicodedata
import urllib.parse
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import plugin_models as pm  # PartCAD's toolkit, on the path of every plugin it runs

SiteError = pm.SiteError
NotFound = pm.NotFound
Refused = pm.Refused
NeedsCredentials = pm.NeedsCredentials
LoginFailed = pm.LoginFailed
File = pm.File
Model = pm.Model
warn = pm.warn

HOUR = 3600
DAY = 24 * HOUR
WEEK = 7 * DAY

# How long what a distributor said is kept: a price and a stock level move
# during a day, a product's description and its model do not, and a category
# tree moves less still.
OFFER_TTL = HOUR
PRODUCT_TTL = DAY
SEARCH_TTL = DAY
CATEGORIES_TTL = WEEK
QUOTE_TTL = timedelta(hours=1)

# How many products a search answers with when it is not told, and the most.
DEFAULT_LIMIT = 20
MAX_LIMIT = 50

# What separates a product's part number from its manufacturer in the name of
# its base part: 'RC0603FR-0710KL~yageo'.
SEPARATOR = "~"

# What a part name may hold as it is; anything else in a part number is written
# percent-encoded ('LT1013CN8#PBF-ND' is 'LT1013CN8%23PBF-ND').
_NAME_SAFE = "-._"


def name_of(sku):
    """The part name of a part number: itself, with what a name cannot hold percent-encoded."""
    # 'quote' never escapes '~', which separates a base part's MPN from its maker.
    return urllib.parse.quote(str(sku), safe=_NAME_SAFE).replace("~", "%7E")


def sku_of(name):
    """The part number a part name is: the name decoded."""
    return urllib.parse.unquote(str(name))


def slug(text, limit=60):
    """A package name of a category's name: 'Logic - Gates and Inverters' is 'logic-gates-and-inverters'."""
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text.replace("&", " and ")).strip("-")
    return text[:limit].rstrip("-") or "category"


# How long a manufacturer's name written run together has to be to match the
# start of another ('onsemi', 'ON Semiconductor'): longer than an initialism.
RUN_TOGETHER = 6


def fold(text):
    """Lower case letters and digits only: what part numbers and manufacturer names are compared as."""
    text = unicodedata.normalize("NFKD", str(text or ""))
    return re.sub(r"[^0-9a-z]+", "", "".join(c for c in text if not unicodedata.combining(c)).lower())


def decimal(value):
    """A price as a Decimal: '1,234.50', '$0.32', 0.32 and '0.32 €' are all read; None when it is none."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    text = re.sub(r"[^0-9.,-]", "", str(value))
    if not text:
        return None
    if "," in text and "." in text:
        # '1.234,50' or '1,234.50': whichever comes last is the decimal point.
        text = text.replace(".", "").replace(",", ".") if text.rfind(",") > text.rfind(".") else text.replace(",", "")
    elif "," in text:
        # '1,234' is a thousand and more, '0,325' and '1,5' are a decimal comma.
        integer, _, fraction = text.rpartition(",")
        thousands = len(fraction) == 3 and integer.lstrip("-") not in ("", "0")
        text = text.replace(",", "") if thousands else integer.replace(",", "") + "." + fraction
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def whole(value, default=None):
    """A count as an int: '1,000', 1000.0 and '1000' are 1000; 'default' when it is none."""
    if value is None or isinstance(value, bool):
        return default
    try:
        return int(Decimal(re.sub(r"[^0-9.]", "", str(value)) or "x"))
    except InvalidOperation:
        return default


# --- what a distributor sells ---------------------------------------------------


class Category:
    """One of the distributor's categories: a package of the catalogue."""

    def __init__(self, id, name, count=None, url=None, children=None):
        self.id = str(id)
        self.name = str(name or id)
        self.count = count
        self.url = url
        self.children = list(children or [])
        self.slug = slug(self.name)

    def __repr__(self):
        return "Category(%r, %r)" % (self.id, self.name)


class Product:
    """One product as the distributor sells it.

    'sku' is the distributor's part number - what is ordered, and what the
    product's part is named by; 'mpn' and 'manufacturer' are whose part it is.
    'pack' is how many items one SKU is: a bag of 100 screws, a full reel of
    5000 resistors, one cut-tape resistor. 'per' says what the price breaks,
    [(quantity, price)] in 'currency', count and price: an item ('item', which
    DigiKey and Mouser quote by, a reel being 5000 of them) or a whole SKU
    ('pack', which McMaster-Carr quotes by). 'moq' is the least that is sold and
    'multiple' what an order is a multiple of, in the same units.
    'stock' is how many the distributor has, None when it did not say.
    'files' are the 3D models of it, as plugin_models.File, or None when what
    was read did not say (they are then asked for when the part is built).
    """

    def __init__(self, sku, **fields):
        self.sku = str(sku)
        self.mpn = fields.get("mpn")
        self.manufacturer = fields.get("manufacturer")
        self.title = fields.get("title")
        self.desc = fields.get("desc")
        self.url = fields.get("url")
        self.datasheet = fields.get("datasheet")
        self.status = fields.get("status")
        self.orderable = fields.get("orderable", True)
        self.stock = fields.get("stock")
        self.moq = max(whole(fields.get("moq"), 1) or 1, 1)
        self.multiple = max(whole(fields.get("multiple"), 1) or 1, 1)
        self.pack = max(whole(fields.get("pack"), 1) or 1, 1)
        self.per = "pack" if fields.get("per") == "pack" else "item"
        self.packaging = fields.get("packaging")
        self.lead_time = fields.get("lead_time")
        self.currency = (fields.get("currency") or "").upper() or None
        breaks = []
        for quantity, price in fields.get("breaks") or []:
            quantity, price = whole(quantity), decimal(price)
            if quantity and price is not None:
                breaks.append((quantity, price))
        self.breaks = sorted(breaks)
        self.categories = [str(c) for c in fields.get("categories") or []]
        self.specs = list(fields.get("specs") or [])
        self.files = fields.get("files")
        self.cad_source = fields.get("cad_source")
        self.extra = fields.get("extra") or {}

    def __repr__(self):
        return "Product(%r)" % self.sku

    @property
    def priced(self):
        return bool(self.breaks)

    def order_quantity(self, needed):
        """How many to order to have 'needed': at least the minimum, the least price break, a whole multiple."""
        quantity = max(int(needed), self.moq, self.breaks[0][0] if self.breaks else 1, 1)
        if self.multiple > 1 and quantity % self.multiple:
            quantity += self.multiple - quantity % self.multiple
        return quantity

    def unit_price(self, quantity):
        """The unit price at 'quantity': that of the largest break it reaches; None when unpriced."""
        price = None
        for at, unit in self.breaks:
            if at <= quantity:
                price = unit
        if price is None and self.breaks:
            price = self.breaks[0][1]
        return price

    def in_stock_for(self, quantity):
        return None if self.stock is None else self.stock >= quantity

    def order(self, items):
        """(SKUs, items, price) of the least order that has at least 'items': whole SKUs, the minimum, the multiple.

        The price is at the break the order reaches; None when unpriced.
        """
        packs = -(-max(int(items), 1) // self.pack)
        if self.per == "pack":
            packs = self.order_quantity(packs)
            unit = self.unit_price(packs)
            return packs, packs * self.pack, (unit * packs if unit is not None else None)
        count = self.order_quantity(packs * self.pack)
        packs = -(-count // self.pack)
        count = packs * self.pack
        unit = self.unit_price(count)
        return packs, count, (unit * count if unit is not None else None)


# --- the distributor, as a plugin serves it --------------------------------------


class Distributor(pm.Site):
    """A distributor. Each plugin's script makes one, and the script's apis are answered by it."""

    VENDOR = None  # what the catalogue's parts say as 'vendor': 'digikey'
    VENDOR_ALIASES = ()  # other spellings of it a part may use: ('digi-key',)
    PACKAGE = None  # '//pub/svc/commerce/digikey'
    STORE = None  # the provider's name in the package: 'digikey'
    CATALOGUE = None  # the repository's name in the package: 'digikey_repo'
    # Where the plugin is, for its User-Agent; defaults to the package's repository.
    HOMEPAGE = None
    # What the distributor's 3D models are called on a part's page, when they
    # are somebody else's: "SnapEDA", "the manufacturer".
    CAD_SOURCE = None

    def __init__(self, request=None):
        if not self.HOMEPAGE:
            self.HOMEPAGE = "https://github.com/partcad/partcad-svc-commerce-" + self.NAME
        super().__init__(request)
        self.user = self._user_info()
        # What the distributor answers depends on more than the URL and the
        # credentials plugin_models keys its cache on: the country and currency
        # it is asked in, an account's own prices. Each is cached apart.
        scope = self.cache_scope()
        if scope:
            digest = hashlib.sha256(scope.encode("utf-8")).hexdigest()[:16]
            self.http.root = os.path.join(self.http.root, "scope-" + digest)

    def cache_scope(self):
        """What, besides the URL and the credentials, the distributor's answers depend on: '' for nothing."""
        return "%s|%s" % (self.country or "", self.currency or "")

    # -- what a distributor implements --

    def fetch_categories(self):
        """The category tree: the top-level Categories, each with its 'children'. [] for none."""
        return []

    def find_products(self, text, category, limit):
        """The Products the distributor finds for 'text' in 'category' (a Category, or None for all), best first."""
        raise NotImplementedError

    def fetch_product(self, sku):
        """The Product with this distributor part number. Raises NotFound."""
        raise NotImplementedError

    def find_mpn(self, manufacturer, mpn):
        """The Products that are the manufacturer's part 'mpn', as the distributor lists it (any packaging)."""
        return self.find_products(mpn, None, 10)

    def cad_files(self, product):
        """The 3D models of a product, as Files. By default what 'fetch_product' said."""
        return list(product.files or [])

    def download(self, model, file):
        """The bytes of one of a product's 3D models. 'model.product' is the Product."""
        raise NotImplementedError

    # -- where the user is, as PartCAD says it --

    def _user_info(self):
        info = self.request.get("userInfo")
        return dict(info) if isinstance(info, dict) else {}

    @property
    def country(self):
        return str(self.user.get("country") or "").strip().upper() or None

    @property
    def currency(self):
        """What to price in: the plugin's 'currency' parameter, else the user's, else None (the API's own)."""
        said = ((self.request.get("parameters") or {}).get("currency") or self.user.get("currency") or "").strip()
        return said.upper() or None

    @property
    def language(self):
        return str(self.user.get("language") or "en").strip().lower()

    # -- the catalogue's categories --

    _tree = None

    def tree(self):
        """The category tree, with sibling names made unique: [Category]."""
        if self._tree is None:
            roots = self.fetch_categories() or []
            self._unique(roots)
            self._tree = roots
        return self._tree

    def _unique(self, siblings):
        seen = {}
        for category in siblings:
            if category.slug in seen:
                category.slug = "%s-%s" % (category.slug, slug(category.id))
            seen[category.slug] = category
            self._unique(category.children)

    def category_at(self, subfolder):
        """The Category a package's subfolder is; None for the root. Raises NotFound for one there is not."""
        if not subfolder:
            return None
        found, siblings = None, self.tree()
        for part in subfolder.strip("/").split("/"):
            found = next((c for c in siblings if c.slug == part), None)
            if found is None:
                raise NotFound("%s: there is no category '%s'" % (self.NAME, subfolder))
            siblings = found.children
        return found

    def category_by_id(self, category_id):
        stack = list(self.tree())
        while stack:
            category = stack.pop()
            if category.id == str(category_id):
                return category
            stack.extend(category.children)
        return None

    # -- what PartCAD is answered: the catalogue --

    @property
    def provider_name(self):
        return "%s:%s" % (self.PACKAGE, self.STORE)

    def meta_of(self, category):
        meta = {
            "manufacturable": False,
            "objectKinds": ["part"],
            "searchKinds": ["part"],
            # A search here answers for every category below: PartCAD asks the
            # top of the tree it searches, not each of its categories.
            "searchScope": "tree",
            "instanceKinds": ["part"],
            # Every product is bought from the package's own store.
            "suppliers": {self.provider_name: {}},
        }
        if category is None:
            meta["desc"] = self.DESC
            meta["url"] = self.URL
        else:
            desc = "%s's '%s'" % (self.TITLE, category.name)
            if category.count:
                desc += " (%s products)" % format(int(category.count), ",")
            meta["desc"] = desc + ". Search it: nothing is listed."
            if category.url:
                meta["url"] = category.url
        # What is below, by name: a package that lists nothing is one PartCAD's
        # 'pc list packages' leaves out, so this is where its children are said.
        try:
            below = [c.slug for c in (self.tree() if category is None else category.children)]
        except SiteError:
            below = []  # the root's description needs no credentials, the categories do
        if below:
            shown = ", ".join(below[:60]) + (", ..." if len(below) > 60 else "")
            meta["desc"] = "%s\nCategories: %s." % (meta["desc"].rstrip(), shown)
        return meta

    def children_of(self, category):
        try:
            return [c.slug for c in (self.tree() if category is None else category.children)]
        except NeedsCredentials as e:
            # The catalogue's root loads without credentials; its categories
            # are the API's, and are said to need them.
            warn(str(e))
            return []

    def get(self, key):
        """One key of the repository protocol; None for a key there is no answer to."""
        query, subfolder = self._query(key)
        what = query["what"]
        if what in ("meta", "deps", "search"):
            category = self.category_at(subfolder) if subfolder else None
            if what == "meta":
                return self.meta_of(category)
            if what == "deps":
                return self.children_of(category)
            return self.find(query.get("text"), query.get("limit"), category) if query.get("kind") == "part" else {}
        if what == "objects":
            # Nothing is listed: the range is searched, not enumerated.
            return {}
        if what == "object":
            if query.get("kind") != "part":
                return None
            return self.resolve(str(query.get("name") or ""), dict(query.get("parameters") or {}))
        if what == "file":
            return self.file(query.get("path") or "")
        return None

    def _query(self, key):
        """(the key taken apart, the subfolder of the package it is for)."""
        query = self.request.get("query") if self.request.get("key") == key else None
        if isinstance(query, dict) and "what" in query:
            return query, str(query.get("subfolder") or "")
        # A PartCAD that sends the key alone: a child package's keys come
        # prefixed with its subfolder, which is the path of its category.
        parts = key.split("/")
        keywords = ("meta", "deps", "objects", "search", "files")
        index = 0
        while index < len(parts) and parts[index].partition("?")[0] not in keywords:
            index += 1
        return pm.query_of("/".join(parts[index:])), "/".join(parts[:index])

    def valid_id(self, model_id):
        return bool(model_id) and len(model_id) <= 120 and not any(c in model_id for c in "\r\n\t")

    # -- a product's base part, and its SKUs --
    #
    # A distributor that sells one product as several SKUs - cut tape and a
    # full reel, a bag of 10 and a bag of 100 - serves it as one part with the
    # geometry, its base part, named '<MPN>~<manufacturer>' and bought by its
    # manufacturer and part number (any store quotes that, in whichever of its
    # SKUs is cheapest), and as an alias of that part per SKU, bought by the
    # SKU and saying how many items one is ('count_per_sku'). A distributor
    # without SKUs of one product (McMaster-Carr, Octopart) serves one part.
    BASE_PARTS = False

    def base_name(self, product):
        """The name of a product's base part, '<MPN>~<manufacturer>'; None where there is none."""
        if not self.BASE_PARTS or not product.mpn or not product.manufacturer:
            return None
        return "%s%s%s" % (name_of(product.mpn), SEPARATOR, slug(product.manufacturer))

    def family(self, key):
        """The products a base part is, every SKU of it, best first: [] for none."""
        mpn, _, maker = key.rpartition(SEPARATOR)
        mpn = sku_of(mpn)
        return [
            p
            for p in self.find_mpn(None, mpn)
            if fold(p.mpn) == fold(mpn) and slug(p.manufacturer) == maker and self.why_not(p) is None
        ] or [p for p in self.find_mpn(None, mpn) if fold(p.mpn) == fold(mpn) and slug(p.manufacturer) == maker]

    def model(self, model_id):
        """A product as plugin_models sees a model: its 3D models are its files. A base part is its first SKU's."""
        if self.BASE_PARTS and SEPARATOR in model_id:
            products = self.family(model_id)
            if not products:
                raise NotFound("%s: %s has no product %s" % (self.NAME, self.TITLE, model_id))
            model = self.model_of(self.fetch_product(products[0].sku), model_id)
            model.family = products
            return model
        return self.model_of(self.fetch_product(model_id))

    def model_of(self, product, model_id=None):
        files = product.files
        if files is None:
            files = self.cad_files(product)
            product.files = files
        model = Model(model_id or product.sku, title=self.title_of(product), url=product.url, files=files)
        model.product = product
        model.family = [product]
        return model

    def resolve(self, base, parameters):
        # A base part's name is read as it is: its '~' is the separator, and
        # any other one was written percent-encoded.
        is_base = self.BASE_PARTS and SEPARATOR in base
        sku = base if is_base else sku_of(base)
        unknown = sorted(set(parameters) - {"file", "format"})
        if unknown:
            raise SiteError(
                "%s: unknown parameter%s %s; a part takes 'format' and 'file'"
                % (self.NAME, "s" if len(unknown) > 1 else "", ", ".join(unknown))
            )
        if not self.valid_id(sku):
            raise NotFound("%s: '%s' is not a %s part number" % (self.NAME, sku, self.TITLE))
        wanted_format = None
        if parameters.get("format"):
            wanted_format = pm.normalize_format(parameters["format"])
            if wanted_format is None:
                raise SiteError(
                    "%s: unknown format '%s'; PartCAD reads %s"
                    % (self.NAME, parameters["format"], ", ".join(pm.FORMAT_NAMES))
                )
        model = self.model(sku)
        if not any(f.format for f in model.files or []):
            source = self.alias_of(model)
            if source and (is_base or not self.base_name(model.product)):
                return self.alias_config(model, source, base=is_base)
            if not source:
                vendor, number = self.vendor_sku(model.product)
                raise NotFound(
                    "%s: %s has no 3D model at %s. It is still sold: a part of your own declared with "
                    "'vendor: %s' and 'sku: %s' is quoted by %s"
                    % (self.NAME, model.id, self.TITLE, vendor, number, self.provider_name)
                )
        if not is_base and self.base_name(model.product):
            # A SKU of a product: an alias of the product's part.
            return self.sku_config(model.product)
        file = self.choose(model, parameters.get("file") or None, wanted_format, None)
        return self.part_config(model, file, base=is_base)

    def parameters(self, file):
        return {
            "format": {
                "type": "string",
                "default": file.format,
                "enum": list(pm.FORMAT_NAMES),
                "desc": "The format to take the product's 3D model in, where %s has it in several." % self.TITLE,
            },
        }

    def title_of(self, product):
        who = " ".join(str(w) for w in (product.manufacturer, product.mpn) if w)
        what = product.title or product.desc or ""
        if who and what and fold(who) not in fold(what):
            return "%s: %s" % (who, what)
        return what or who or "%s %s" % (self.TITLE, product.sku)

    def describe(self, product, file=None, family=None):
        """What 'pc list' and 'pc info' say of a product: what it is, its specifications, how it is sold."""
        sentences = [self.title_of(product)]
        if product.desc and product.title and fold(product.desc) not in fold(sentences[0]):
            sentences.append(product.desc)
        specs = ["%s: %s" % (name, value) for name, value in product.specs[:8] if name and value not in (None, "")]
        if specs:
            sentences.append("; ".join(specs))
        if family:
            sentences.append("Sold by %s as %s" % (self.TITLE, ", ".join(self.sku_said(p) for p in family)))
        else:
            sentences.append(self.sold(product))
        if file is not None:
            source = product.cad_source or self.CAD_SOURCE
            sentences.append("3D model: %s%s" % (file.name, " (from %s)" % source if source else ""))
        return " ".join(s.strip().rstrip(".") + "." for s in sentences if s and s.strip())

    @staticmethod
    def sku_said(product):
        """A SKU, as a description lists it: '311-10.0KHRTR-ND (Tape & Reel, 5000 per SKU)'."""
        said = [w for w in (product.packaging, "%d per SKU" % product.pack if product.pack > 1 else None) if w]
        return "%s (%s)" % (product.sku, ", ".join(said)) if said else product.sku

    def sold(self, product):
        """How a product is sold, in a sentence of its description."""
        sold = "Sold by %s as %s" % (self.TITLE, product.sku)
        if product.pack > 1:
            sold += ", in packs of %d" % product.pack
        if product.moq > 1:
            sold += ", at least %d" % product.moq
        if product.status and fold(product.status) not in ("active", ""):
            sold += " (%s)" % product.status
        return sold

    def vendor_sku(self, product):
        """What a product's part says it is bought as: the distributor and its part number.

        An aggregator, which sells nothing itself, says the manufacturer and its part number instead.
        """
        return self.VENDOR, product.sku

    def bought_as(self, product, base):
        """(vendor, SKU, items per SKU) a part says: a base part's are its manufacturer's and MPN, one item each."""
        if base:
            return product.manufacturer, product.mpn, 1
        vendor, sku = self.vendor_sku(product)
        return vendor, sku, product.pack

    def part_config(self, model, file, base=False):
        product = model.product
        vendor, sku, per_sku = self.bought_as(product, base)
        config = {
            "type": pm.part_type_of(file.format),
            "path": pm.file_path(model, file),
            "desc": self.describe(product, file, family=model.family if base else None),
            "vendor": vendor,
            "sku": sku,
            "parameters": self.parameters(file),
        }
        if product.url:
            config["url"] = product.url
        if per_sku > 1:
            config["count_per_sku"] = per_sku
        return config

    def alias_of(self, model):
        """Another package's part to draw a product with, when the distributor has no model of it; else None.

        A distributor that links to a CAD partner's page for a model - DigiKey
        to SnapMagic - can serve the product as an alias of that partner's part.
        """
        return None

    def alias_config(self, model, source, base=False):
        """A product drawn with another package's part: an alias of it, still bought from this distributor."""
        product = model.product
        vendor, sku, per_sku = self.bought_as(product, base)
        config = {
            "type": "alias",
            "source": source,
            "desc": "%s 3D model: %s." % (self.describe(product, family=model.family if base else None), source),
            "vendor": vendor,
            "sku": sku,
        }
        if product.url:
            config["url"] = product.url
        if per_sku > 1:
            config["count_per_sku"] = per_sku
        return config

    def sku_config(self, product):
        """One SKU of a product: an alias of the product's base part, bought by the SKU, so many items to one."""
        base = self.base_name(product)
        said = ", ".join(w for w in (product.packaging, "%d per SKU" % product.pack if product.pack > 1 else "") if w)
        config = {
            "type": "alias",
            "source": ":" + base,
            "desc": "%s, sold by %s as %s%s. The product is :%s."
            % (self.title_of(product), self.TITLE, product.sku, " (%s)" % said if said else "", base),
            "vendor": self.VENDOR,
            "sku": product.sku,
        }
        if product.url:
            config["url"] = product.url
        if product.pack > 1:
            config["count_per_sku"] = product.pack
        return config

    def unserved(self, model):
        vendor, sku = self.vendor_sku(model.product)
        return "no 3D model at %s; quote it as 'vendor: %s', 'sku: %s'" % (self.TITLE, vendor, sku)

    def find(self, text, limit=None, category=None):
        """A search answered: {part name: config}, best first; a product with no 3D model listed with no 'type'.

        Where a distributor sells a product as several SKUs, the product's part
        comes first, then an alias of it per SKU.
        """
        text = (text or "").strip()
        if not text:
            return {}
        limit = min(limit or DEFAULT_LIMIT, MAX_LIMIT)

        def complete(product):
            try:
                return self.model_of(product), None
            except SiteError as e:
                return None, e

        # A search's products may not say what 3D models they have, and asking
        # costs a request each: a few at a time, in the distributor's order.
        products = self.find_products(text, category, limit)[:limit]
        with concurrent.futures.ThreadPoolExecutor(max_workers=pm.WORKERS) as pool:
            completed = list(pool.map(complete, products))
        families = {}
        for product, (model, error) in zip(products, completed):
            base = self.base_name(product)
            if base and model is not None:
                families.setdefault(base, []).append(product)
        hits, said = {}, set()
        for product, (model, error) in zip(products, completed):
            if error is not None:
                warn(str(error))
                continue
            base = self.base_name(product)
            served = self.served(model)
            if base and base not in said:
                said.add(base)
                model.family = families.get(base) or [product]
                hits[base] = served(model, base=True)
            if base:
                hits[name_of(product.sku)] = (
                    self.sku_config(product) if "type" in hits[base] else self.unserved_hit(model, self.unserved(model))
                )
            else:
                hits[self.name_for(product)] = served(model, base=False)
        return hits

    def name_for(self, product):
        """The name of a product's part, where it has no base part: its part number, written as a name."""
        return name_of(product.sku)

    def served(self, model):
        """How a model is answered: a part of its file, an alias of a partner's, or found and not served."""
        readable = [f for f in model.files or [] if f.format]
        if not readable:
            source = self.alias_of(model)
            if source:
                return lambda m, base: self.alias_config(m, source, base=base)
            return lambda m, base: self.unserved_hit(m, self.unserved(m))
        try:
            file = self.choose(model)
        except SiteError:
            return lambda m, base: self.unserved_hit(m, self.unserved(m))
        return lambda m, base: self.part_config(m, file, base=base)

    # -- what PartCAD is answered: the store --

    def is_own(self, vendor):
        return fold(vendor) in {fold(v) for v in (self.VENDOR,) + tuple(self.VENDOR_ALIASES)}

    def offer(self, vendor, sku, needed=1):
        """(the Product to sell for vendor and SKU, how it was matched); (None, why not) when there is none."""
        sku = str(sku or "").strip()
        if not sku:
            return None, "no SKU"
        if self.is_own(vendor):
            try:
                products, matched = [self.fetch_product(sku)], "%s part number" % self.TITLE
            except NotFound:
                # A manufacturer's part number given with the distributor's name.
                products = [p for p in self.find_mpn(None, sku) if fold(p.mpn) == fold(sku)]
                matched = "manufacturer part number"
                if not products:
                    return None, "%s has no part %s" % (self.TITLE, sku)
        else:
            matches = [p for p in self.find_mpn(vendor, sku) if fold(p.mpn) == fold(sku)]
            products = [p for p in matches if self.same_maker(vendor, p.manufacturer)]
            matched = "%s's part number" % vendor
            if not products and matches:
                makers = " and ".join(sorted({str(p.manufacturer) for p in matches}))
                return None, "%s lists %s by %s, not by '%s'" % (self.TITLE, sku, makers, vendor)
            if not products:
                return None, "%s does not list %s's %s" % (self.TITLE, vendor, sku)
        offers = [offer for product in products for offer in self.offers_of(product)]
        if not offers:
            return None, "nobody offers %s at %s" % (sku, self.TITLE)
        return self.best(offers, needed), matched

    def offers_of(self, product):
        """What a product can be bought as: itself, at a distributor; each seller's offer, at an aggregator."""
        return [product]

    @staticmethod
    def same_maker(vendor, manufacturer):
        """Whether a part's 'vendor' names the manufacturer a distributor lists: 'ti' is not, 'Texas Instruments' is.

        Compared word by word, not as one string: 'TE' is in 'texasinstruments'
        as letters, and is TE Connectivity, not Texas Instruments - the very
        case this is here to tell apart, since two makers of one part number
        are what it decides between. So a name matches the same name spelled
        another way, a name its words begin ('Analog Devices' and 'Analog
        Devices Inc.'), one sharing its first word ('Microchip' and 'Microchip
        Technology'), and a name run together that begins the other ('onsemi'
        and 'ON Semiconductor'), when it is too long to be an initialism.
        """
        a, b = fold(vendor), fold(manufacturer)
        if not a or not b:
            return False
        if a == b:
            return True
        words_a = [w for w in (fold(w) for w in re.split(r"[\s,./-]+", str(vendor))) if w]
        words_b = [w for w in (fold(w) for w in re.split(r"[\s,./-]+", str(manufacturer))) if w]
        if words_a and words_b:
            shorter, longer = sorted((words_a, words_b), key=len)
            if longer[: len(shorter)] == shorter or words_a[0] == words_b[0]:
                return True
        short, long_ = sorted((a, b), key=len)
        return len(short) >= RUN_TOGETHER and long_.startswith(short)

    def best(self, products, needed):
        """Of the listings of one part, the one to buy 'needed' of: sellable, then in stock, then cheapest."""

        def cost(product):
            _, items, total = product.order(needed)
            stocked = product.in_stock_for(items if product.per == "item" else -(-items // product.pack))
            return (
                not (product.orderable and product.priced),
                stocked is False,
                total if total is not None else Decimal("Infinity"),
                product.moq,
            )

        return min(products, key=cost)

    def why_not(self, product):
        """Why a product cannot be sold, or None when it can - whatever the stock."""
        if not product.orderable:
            return "%s is %s at %s" % (product.sku, (product.status or "not orderable").lower(), self.TITLE)
        if not product.priced:
            return "%s has no price at %s" % (product.sku, self.TITLE)
        return None

    def describe_offer(self, product, matched=None):
        offer = {
            "sku": product.sku,
            "mpn": product.mpn,
            "manufacturer": product.manufacturer,
            "url": product.url,
            "seller": product.extra.get("seller") or self.TITLE,
            "stock": product.stock,
            "moq": product.moq,
        }
        if product.multiple > 1:
            offer["multiple"] = product.multiple
        if product.pack > 1:
            offer["pack"] = product.pack
        if product.packaging:
            offer["packaging"] = product.packaging
        if product.lead_time:
            offer["leadTime"] = product.lead_time
        if matched:
            offer["matched"] = matched
        return offer

    def avail(self, request):
        vendor, sku = request.get("vendor"), request.get("sku")
        # How many items are wanted: what a SKU is, the distributor says.
        needed = max(whole(request.get("count"), 1) or 1, 1)
        try:
            product, matched = self.offer(vendor, sku, needed)
        except NeedsCredentials as e:
            return {"available": False, "reason": str(e)}
        if product is None:
            return {"available": False, "reason": matched}
        reason = self.why_not(product)
        if reason:
            return {"available": False, "reason": reason}
        return {"available": True, **self.describe_offer(product, matched)}

    def quote(self, request):
        cart = request.get("cart") or {}
        lines, total, currencies = [], Decimal(0), set()
        for vendor, sku, count, items in order_lines(cart):
            product, matched = self.offer(vendor, sku, items)
            if product is None:
                raise SiteError("%s: %s" % (self.NAME, matched))
            reason = self.why_not(product)
            if reason:
                raise SiteError("%s: %s" % (self.NAME, reason))
            packs, quantity, price = product.order(items)
            total += price
            currencies.add(product.currency or self.currency)
            line = dict(self.describe_offer(product, matched), vendor=vendor, count=count, items=items)
            stocked = product.in_stock_for(quantity if product.per == "item" else packs)
            line.update(packs=packs, quantity=quantity, price=float(price), inStock=stocked)
            # The price of what the distributor prices: an item, or a pack.
            line["unitPrice"] = float(price / (packs if product.per == "pack" else quantity))
            line["per"] = product.per
            lines.append(line)
        currencies.discard(None)
        if len(currencies) > 1:
            raise SiteError("%s priced this cart in %s at once" % (self.TITLE, " and ".join(sorted(currencies))))
        answer = {
            "qos": cart.get("qos"),
            "price": float(total),
            "expire": (datetime.now(timezone.utc) + QUOTE_TTL).timestamp(),
            # Nothing was put in a cart at the distributor.
            "cartId": None,
            "lines": lines,
        }
        if currencies:
            answer["currency"] = currencies.pop()
        return answer

    # -- logging in --

    def login_command(self):
        """How the user logs in to both plugins: the store's and the catalogue's keys are kept apart."""
        return " and ".join("'pc login %s:%s'" % (self.PACKAGE, name) for name in (self.STORE, self.CATALOGUE) if name)

    def login_message(self, message):
        return "%s. The store and the catalogue keep their keys apart: log in to both (%s)" % (
            message,
            self.login_command(),
        )

    def needs_credentials(self, what):
        return NeedsCredentials(
            "%s: %s needs your %s API credentials: %s, or set %s"
            % (self.NAME, what, self.TITLE, self.login_command(), " and ".join(self.CREDENTIALS.values()))
        )

    # -- OAuth 2.0 client credentials, kept on disk until they expire --

    def bearer(self, token_url, client_id, client_secret, what, extra=None, basic=False):
        """An access token for the client credentials, from the cache while it lasts.

        'basic' sends the client's ID and secret as HTTP Basic authentication,
        which OAuth 2.0 prefers (RFC 6749, 2.3.1), rather than in the form,
        which is all some servers take (DigiKey's).
        """
        if not client_id or not client_secret:
            raise self.needs_credentials(what)
        digest = hashlib.sha256(("%s\n%s\n%s" % (token_url, client_id, client_secret)).encode("utf-8")).hexdigest()
        path = os.path.join(self.http.root, "tokens", digest)
        try:
            with open(path, encoding="utf-8") as f:
                kept = json.load(f)
            if kept.get("expires", 0) > time.time() + 60:
                return kept["token"]
        except (OSError, ValueError, KeyError):
            pass
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        form = {"grant_type": "client_credentials"}
        if basic:
            pair = "%s:%s" % (urllib.parse.quote(client_id, safe=""), urllib.parse.quote(client_secret, safe=""))
            headers["Authorization"] = "Basic " + base64.b64encode(pair.encode("utf-8")).decode("ascii")
        else:
            form.update(client_id=client_id, client_secret=client_secret)
        form.update(extra or {})
        response = self.http.request(
            token_url, headers=headers, data=urllib.parse.urlencode(form).encode("ascii"), method="POST"
        )
        if response.status in (400, 401, 403):
            raise NeedsCredentials(
                "%s: %s did not take your API credentials (HTTP %d): %s again"
                % (self.NAME, self.TITLE, response.status, self.login_command())
            )
        self.http.checked(response, "an access token")
        try:
            answer = response.json()
            token = answer["access_token"]
        except (ValueError, KeyError, TypeError):
            raise SiteError("%s: %s answered no access token" % (self.NAME, self.TITLE)) from None
        expires = time.time() + float(answer.get("expires_in") or 600)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            descriptor = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as f:
                json.dump({"token": token, "expires": expires}, f)
            os.replace(path + ".tmp", path)
        except OSError:
            pass  # asked again next time
        return token


# --- the cart, as PartCAD hands it over ---------------------------------------------


def order_lines(cart):
    """(vendor, SKU, how many of it, how many items that is), one per SKU, as PartCAD worked it out.

    PartCAD counts SKUs by the 'count_per_sku' a part declares; a SKU's items
    are that many times it. What a SKU of the distributor holds is the
    distributor's to say, and an order is made of whole ones of those.
    """
    parts = cart.get("parts") or {}
    for name, part in parts.items():
        if not part.get("vendor") or not part.get("sku"):
            raise SiteError("'%s' is not something a store sells: it has no vendor and SKU" % name)

    def per_sku(names):
        declared = [max(int(parts[n].get("count_per_sku") or 1), 1) for n in names if n in parts]
        return max(declared) if declared else 1

    if "skus" in cart:
        lines = []
        for line in cart["skus"]:
            count = int(line["count"])
            lines.append((line["vendor"], str(line["sku"]), count, count * per_sku(line.get("parts") or [])))
        return lines
    needed = {}
    for name, part in parts.items():
        key = (part["vendor"], str(part["sku"]))
        size = max(int(part.get("count_per_sku") or 1), 1)
        count, items = needed.get(key, (0, 0))
        needed[key] = (count + -(-int(part["count"]) // size), items + int(part["count"]))
    return [(vendor, sku, count, items) for (vendor, sku), (count, items) in sorted(needed.items())]


# --- what a script's apis are -------------------------------------------------------


def run(distributor_class, api, request, partcad_login=None):
    """The answer to one api: 'get' and 'login' for the catalogue, 'avail' and 'quote' for the store.

    A repository's 'get' says what went wrong on stderr and answers None, as
    PartCAD expects of a key it cannot have; a store's api raises, so that a
    quote that could not be made is a failure with its reason.
    """
    distributor = distributor_class(request)
    if api == "get":
        return {"result": pm.serve(distributor, request["key"])}
    if api == "login":
        result = pm.login(distributor, partcad_login)
        if isinstance(result, dict) and result.get("message"):
            result["message"] = distributor.login_message(result["message"])
        return {"result": result}
    try:
        if api == "avail":
            return distributor.avail(request)
        if api == "quote":
            return distributor.quote(request)
    except SiteError as e:
        raise RuntimeError(str(e)) from None
    if api == "caps":
        return {}
    if api == "order":
        raise RuntimeError(
            "%s: ordering is not implemented: put the quote's lines in a cart at %s"
            % (distributor.NAME, distributor.URL)
        )
    raise RuntimeError("%s: unknown api '%s'" % (distributor.NAME, api))
