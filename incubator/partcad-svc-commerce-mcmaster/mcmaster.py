#
# partcad-svc-commerce-mcmaster, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""McMaster-Carr as a PartCAD store and catalogue, through McMaster-Carr's Product Information API.

One script serves both of the package's plugins: the store provider 'mcmaster'
(PartCAD asks it 'avail' and 'quote') and the repository 'mcmaster_repo' behind
//pub/svc/commerce/mcmaster/products (PartCAD asks it 'get'). What the two
answer is distributor.py's; what this says is how McMaster-Carr is asked.

The API (https://www.mcmaster.com/help/api/) is for McMaster-Carr's approved
customers: McMaster-Carr issues each of them a client certificate and a
password, on request to eProcurement@mcmaster.com, and the account has to be
enabled for the API. Every request is made with that certificate; a login with
the account's user name and password gives a token for a day.

    POST /v1/login                       a token, for the certificate and the account
    PUT  /v1/products  {"URL": ...}      subscribe to a part: answers its information
    GET  /v1/products/{part}/price       its prices: [{Amount, MinimumQuantity, UnitOfMeasure}]
    GET  /v1/cad/{path}                  one of its CAD files, as its 'Links' name them

There is no search and no category tree in the API: a part is asked for by its
McMaster-Carr number, which is what the website shows on every product, and a
search answers the part numbers in what is searched for. Reading a part
subscribes the account to it (the API reads nothing it is not subscribed to);
McMaster-Carr caps how many subscriptions an account has, and how many it adds a
day. Prices are in US dollars, which is what McMaster-Carr is paid in; the API
says nothing of stock.

McMaster-Carr's terms are the user's to keep: what the API answers is for use
within their company, and its CAD models are to help decide whether to buy the
product - not to be redistributed. Nothing here puts a model anywhere but the
user's own PartCAD cache, and a package must never carry one.
"""

import base64
import hashlib
import importlib.util
import json
import os
import re
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

# When this plugin's answers stopped meaning what they meant before. PartCAD
# keys everything it caches of the catalogue on it, so raise it with any change
# to what is answered - here or in distributor.py.
#
# v1: McMaster-Carr parts by part number, with their CAD; the store.
CACHE_VERSION = 1


def _shared():
    """distributor.py, beside this script, under a name of this plugin's own."""
    name = "_partcad_mcmaster_distributor"
    if name not in sys.modules:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "distributor.py")
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


d = _shared()

API = "https://api.mcmaster.com"
WEB = "https://www.mcmaster.com"

# What a McMaster-Carr part number looks like: four or five digits, a letter, and
# one to four more ('91290A115', '4936K451'); some have a suffix ('6655K14-K').
PART_NUMBER = re.compile(r"^\d{3,5}[A-Z]\d{1,4}(?:-[A-Z0-9]{1,4})?$", re.IGNORECASE)

# 'Pack of 100', '100 per pack', 'Packs of 25'.
_PACK = re.compile(r"(?:packs?\s+of\s+(\d[\d,]*))|(?:(\d[\d,]*)\s+per\s+pack)", re.IGNORECASE)


class CertificateHttp(d.pm.Http):
    """plugin_models' Http, with McMaster-Carr's client certificate on every request."""

    def __init__(self, site, user_agent, context):
        super().__init__(site, user_agent)
        self.opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context))

    def request(self, url, headers=None, data=None, method=None, timeout=60):
        all_headers = {"User-Agent": self.user_agent, "Accept": "application/json, */*;q=0.5"}
        all_headers.update(headers or {})
        if data is not None and not isinstance(data, bytes):
            data = json.dumps(data).encode("utf-8")
            all_headers.setdefault("Content-Type", "application/json")
        last = None
        for attempt in range(3):
            try:
                request = urllib.request.Request(url, data=data, headers=all_headers, method=method)
                with self.opener.open(request, timeout=timeout) as answer:
                    return d.pm.Response(answer.status, dict(answer.headers), answer.read(), answer.geturl())
            except urllib.error.HTTPError as e:
                last = d.pm.Response(e.code, dict(e.headers or {}), e.read() if e.fp else b"", url)
                if e.code < 500 and e.code != 429:
                    return last
            except Exception as e:  # a timeout, a reset, a handshake the certificate failed
                last = d.pm.Response(0, {}, str(e).encode("utf-8"), url)
            time.sleep(1.0 * (attempt + 1))
        return last


def certificate_context(certificate, password):
    """An SSL context presenting the client certificate: a PKCS#12 (.pfx, .p12) or a PEM, by path or base64."""
    data = None
    if certificate and os.path.exists(os.path.expanduser(certificate)):
        with open(os.path.expanduser(certificate), "rb") as f:
            data = f.read()
    elif certificate:
        try:
            data = base64.b64decode(certificate, validate=True)
        except ValueError:
            raise d.SiteError("mcmaster: 'certificate' is neither a file there is nor a base64 certificate") from None
    if not data:
        return None
    context = ssl.create_default_context()
    if b"-----BEGIN" in data:
        pem = data
    else:
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.serialization import pkcs12
        except ImportError:
            raise d.SiteError(
                "mcmaster: reading a PKCS#12 certificate needs 'cryptography' (in the package's "
                "pythonRequirements); or convert it to PEM: openssl pkcs12 -in cert.pfx -out cert.pem -nodes"
            ) from None
        try:
            key, cert, chain = pkcs12.load_key_and_certificates(data, (password or "").encode("utf-8") or None)
        except ValueError as e:
            raise d.NeedsCredentials("mcmaster: the certificate could not be opened: %s" % e) from None
        pem = key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ) + b"".join(c.public_bytes(serialization.Encoding.PEM) for c in [cert] + list(chain or []))
        password = None
    # 'load_cert_chain' reads files only: one of the user's own, read and removed at once.
    descriptor, path = tempfile.mkstemp(suffix=".pem")
    try:
        with os.fdopen(descriptor, "wb") as f:
            f.write(pem)
        context.load_cert_chain(path, password=password or None)
    except ssl.SSLError as e:
        raise d.NeedsCredentials("mcmaster: the certificate could not be used: %s" % e) from None
    finally:
        os.unlink(path)
    return context


class McMaster(d.Distributor):
    NAME = "mcmaster"
    TITLE = "McMaster-Carr"
    URL = WEB
    DESC = (
        "McMaster-Carr's range, by McMaster-Carr part number: every part McMaster-Carr has a CAD model of is a "
        "part, bought from McMaster-Carr. The API has no search and no categories: ask for a part by its number "
        "('products:91290A115'), or search for the number."
    )
    VERSION = CACHE_VERSION
    VENDOR = "mcmaster"
    VENDOR_ALIASES = ("mcmaster-carr", "mcmaster carr", "mcmastercarr")
    PACKAGE = "//pub/svc/commerce/mcmaster"
    STORE = "mcmaster"
    CATALOGUE = "mcmaster_repo"
    CAD_SOURCE = "McMaster-Carr"
    CREDENTIALS = {
        "username": "MCMASTER_USERNAME",
        "password": "MCMASTER_PASSWORD",
        "certificate": "MCMASTER_CERTIFICATE",
        "certificate_password": "MCMASTER_CERTIFICATE_PASSWORD",
    }
    LOGIN_INSTRUCTIONS = (
        "McMaster-Carr's API is for approved customers: ask eProcurement@mcmaster.com for access, and McMaster-Carr "
        "sends a client certificate and its password, for an account enabled for the API. What is needed is the "
        "account's user name and password, the certificate - the path of the .pfx/.p12 (or .pem) file, or its "
        "content in base64 where the plugin runs in a container that cannot see the file - and the certificate's "
        "password."
    )

    def __init__(self, request=None):
        super().__init__(request)
        self.keys = self.credentials()
        self._api = None

    def cache_scope(self):
        # One price list, in US dollars, wherever the user is.
        return ""

    def api(self):
        """The Http every request to the API goes through: plugin_models', presenting the client certificate.

        Made when it is first needed, so that what needs no API - the
        catalogue's root - loads without a certificate.
        """
        if self._api is None:
            if not self.keys.get("certificate"):
                raise self.needs_credentials("McMaster-Carr's API")
            context = certificate_context(self.keys["certificate"], self.keys.get("certificate_password"))
            self._api = CertificateHttp(self.NAME, self.http.user_agent, context)
        return self._api

    # -- the wire --

    def token(self, keys=None, fresh=False):
        """A token for the account, from the cache while it lasts (a day)."""
        keys = keys or self.keys
        if not keys.get("username") or not keys.get("password") or not keys.get("certificate"):
            raise self.needs_credentials("McMaster-Carr's API")
        secret = "%s\n%s\n%s" % (keys["username"], keys["password"], keys["certificate"])
        path = os.path.join(self.api().root, "tokens", hashlib.sha256(secret.encode("utf-8")).hexdigest())
        if not fresh:
            try:
                with open(path, encoding="utf-8") as f:
                    kept = json.load(f)
                if kept.get("expires", 0) > time.time() + 300:
                    return kept["token"]
            except (OSError, ValueError, KeyError):
                pass
        response = self.api().request(
            API + "/v1/login", data={"UserName": keys["username"], "Password": keys["password"]}, method="POST"
        )
        if response.status in (400, 401, 403):
            raise d.NeedsCredentials(
                "mcmaster: McMaster-Carr did not take the login (HTTP %d: %s): %s again"
                % (response.status, said(response), self.login_command())
            )
        self.api().checked(response, "a login")
        answer = response.json()
        token = answer.get("AuthToken") if isinstance(answer, dict) else None
        if not token:
            raise d.SiteError("mcmaster: the login answered no token")
        expires = time.time() + 23 * 3600
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            descriptor = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as f:
                json.dump({"token": token, "expires": expires}, f)
            os.replace(path + ".tmp", path)
        except OSError:
            pass
        return token

    def ask(self, path, what, data=None, method=None, ttl=d.PRODUCT_TTL):
        for attempt in range(2):
            headers = {"Authorization": "Bearer " + self.token(fresh=attempt > 0)}
            try:
                return self.api().json(API + path, what, headers=headers, data=data, method=method, ttl=ttl)
            except d.NeedsCredentials:
                # An expired token is a 403 like any refusal: one more try with a new one.
                if attempt:
                    raise
        return None

    # -- the catalogue --

    def find_products(self, text, category, limit):
        found = []
        for word in re.split(r"[\s,;]+", text or ""):
            if PART_NUMBER.match(word) and len(found) < limit:
                try:
                    found.append(self.fetch_product(word.upper()))
                except d.NotFound:
                    continue
        return found

    def find_mpn(self, manufacturer, mpn):
        # McMaster-Carr sells under its own numbers only, and does not say whose a product is.
        return []

    def fetch_product(self, sku):
        sku = sku.strip().upper()
        if not PART_NUMBER.match(sku):
            raise d.NotFound("mcmaster: '%s' is not a McMaster-Carr part number" % sku)
        try:
            info = self.ask(
                "/v1/products",
                "part %s" % sku,
                data={"URL": "https://mcmaster.com/%s" % sku},
                method="PUT",
                ttl=d.PRODUCT_TTL,
            )
        except d.SiteError as e:
            if "HTTP 400" in str(e):
                raise d.NotFound("mcmaster: %s is not a McMaster-Carr part" % sku) from None
            raise
        if not isinstance(info, dict) or not info.get("PartNumber"):
            raise d.NotFound("mcmaster: %s is not a McMaster-Carr part" % sku)
        prices = self.ask("/v1/products/%s/price" % urllib.parse.quote(sku), "the price of %s" % sku, ttl=d.OFFER_TTL)
        return self.product_of(info, prices if isinstance(prices, list) else [])

    def product_of(self, info, prices):
        sku = str(info["PartNumber"])
        status = info.get("ProductStatus") or "Active"
        specs = [
            (s.get("Attribute"), ", ".join(str(v) for v in s.get("Values") or []))
            for s in info.get("Specifications") or []
            if isinstance(s, dict)
        ]
        units = " ".join(str(p.get("UnitOfMeasure") or "") for p in prices if isinstance(p, dict))
        pack = None
        for text in [units, info.get("DetailDescription") or ""] + [value for _, value in specs]:
            match = _PACK.search(text)
            if match:
                pack = d.whole(match.group(1) or match.group(2))
                break
        return d.Product(
            sku,
            mpn=sku,
            manufacturer="McMaster-Carr",
            title=info.get("FamilyDescription"),
            desc=info.get("DetailDescription"),
            url="%s/%s" % (WEB, sku),
            status=status,
            orderable=d.fold(status) == "active",
            pack=pack,
            breaks=[(p.get("MinimumQuantity"), p.get("Amount")) for p in prices if isinstance(p, dict)],
            currency="USD",
            specs=specs,
            files=self.models_in(info.get("Links")),
            extra={"suggested": suggested(info)},
        )

    def title_of(self, product):
        what = " ".join(w for w in (product.title, product.desc) if w)
        return "McMaster-Carr %s: %s" % (product.sku, what) if what else "McMaster-Carr %s" % product.sku

    def describe(self, product, file=None):
        text = super().describe(product, file)
        if product.extra.get("suggested"):
            text += " McMaster-Carr suggests %s instead." % product.extra["suggested"]
        return text

    @staticmethod
    def models_in(links):
        """The 3D CAD files among a part's links ('3-D STEP', ...), as Files; 2-D drawings are not models."""
        files = []
        for link in links or []:
            if not isinstance(link, dict) or not str(link.get("Key") or "").upper().startswith("3-D"):
                continue
            path = str(link.get("Value") or "")
            name = urllib.parse.unquote(path.rsplit("/", 1)[-1])
            if path.startswith("/v1/cad/") and d.pm.format_of(name):
                files.append(d.File(path, name, kind=link["Key"]))
        return files

    def download(self, model, file):
        what = "the %s of %s" % (file.extra.get("kind") or file.name, model.id)
        for attempt in range(2):
            headers = {"Authorization": "Bearer " + self.token(fresh=attempt > 0)}
            response = self.api().request(API + file.id, headers=headers, timeout=600)
            if response.status == 403 and not attempt:
                continue
            return self.api().checked(response, what).body
        return None

    # -- logging in --

    def whoami(self, credentials):
        if not all(credentials.get(k) for k in ("username", "password", "certificate")):
            return None
        if credentials.get("certificate") != self.keys.get("certificate"):
            self._api = None
        self.keys = dict(credentials)
        try:
            self.token(credentials, fresh=True)
        except d.NeedsCredentials:
            return None
        return credentials["username"]

    def login_spec(self):
        return {
            "url": WEB + "/help/api/",
            "title": "McMaster-Carr API",
            "capture": [
                {"name": "username", "ask": {"label": "Your McMaster-Carr user name", "secret": False}},
                {"name": "password", "ask": {"label": "Your McMaster-Carr password", "secret": True}},
                {
                    "name": "certificate",
                    "ask": {"label": "The path of the client certificate McMaster-Carr sent you", "secret": False},
                },
                {"name": "certificate_password", "ask": {"label": "The certificate's password", "secret": True}},
            ],
        }


def suggested(info):
    """What McMaster-Carr suggests instead of a discontinued part: the address of its page, or None."""
    for link in info.get("Links") or []:
        if isinstance(link, dict) and link.get("Key") == "SuggestedProduct":
            return link.get("Value")
    return None


def said(response):
    """What McMaster-Carr said in an error: {'ErrorMessage': 'LOGIN_FAILED', 'ErrorDescription': '...'}."""
    try:
        body = response.json()
    except ValueError:
        return ""
    if isinstance(body, dict):
        return ": ".join(str(body[k]) for k in ("ErrorMessage", "ErrorDescription") if body.get(k))
    return ""


# Last, so that everything above is defined when PartCAD runs this.
if __name__ in ("get", "login", "avail", "quote", "caps", "order"):
    output = d.run(McMaster, __name__, globals().get("request") or {}, globals().get("partcad_login"))
