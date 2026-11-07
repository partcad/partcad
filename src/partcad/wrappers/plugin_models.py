#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The toolkit PartCAD gives a repository plugin for a model site.

A plugin script imports it - ``import plugin_models`` - wherever PartCAD runs
it: it is one of PartCAD's wrappers, which every sandbox can reach, beside
``plugin_login``. It used to be a file every plugin carried a copy of
(``remote_models.py``, kept byte-identical by a digest in each repository);
here it is one file, tested against the rest of PartCAD, which is what lets
it know exactly what PartCAD builds and how PartCAD spells a name. A plugin
says how its site is asked - a ``Site`` with ``model``, ``download``,
``search`` and ``login_spec`` - and this says what PartCAD is answered.
Raise the plugin's own CACHE_VERSION when what it answers changes.

What PartCAD hands the plugin, beyond the key, is the key taken apart
(``request["query"]``, see ``project_external_repository.query_of``), so a
name's parameters arrive decoded and nothing here has to parse a name PartCAD
wrote. What it writes - the names of search hits - it spells the way PartCAD
does ('format_name'), and a test in PartCAD holds the two together.

A model site's catalog is not something to list, so none of these packages
lists anything: ``objects/part`` is empty and so is ``deps``. What they do is
answer for a name. A model is a part per file of it that PartCAD reads, and
the name says which:

    763622                        the model's best file
    763622;format=stl             its best STL
    763622;file=1234567           that file, by its id on the site
    763622;file=clip.stl          or by its name
    763622;source=preview         the site's own mesh of it, where the site has
                                  one (see 'Site.PREVIEW_DESCRIPTION')

Which file is "best" is the plugin's to say - an exact format before a mesh, a
file that can be had with the credentials there are before one that cannot,
the designer's own before the site's preview - and the user's to change, for
every model at once, with the plugin's parameters 'formats' (which formats to
take, best first) and 'source' ('auto', 'original' or 'preview'). Those are
set in ~/.partcad/config.yaml, or with an 'enrich' of the plugin; a part's own
parameters, in its name or an enrich's 'with', override them for that part.

Every one of those is resolved by the plugin, not by PartCAD applying the
parameters to the base declaration (the package says so with
``instanceKinds``), because another file is another ``path`` and maybe another
``type``. And a search (``searchKinds``) answers with names of that form, one
per file, so a hit is everything needed to fetch its geometry.

The geometry itself comes through the plugin too, as ``files/<path>``: the
plugin is where the user's credentials are, and a sandbox that is a container
sees none of the environment PartCAD runs in.

And it answers ``login`` (``pc login <package>:<plugin>``): it checks the
credentials it was given and returns them if the site still takes them, and
otherwise asks PartCAD to open the user's browser on the site's sign-in, with
PartCAD's extension in it to pick up what signing in leaves behind - a cookie,
a token in storage, an API key on a page - and checks that instead. PartCAD
saves what it returns as the user's own parameters of the plugin, which is
where every later request reads them from (see 'Site.login'). With nobody at
the screen ('pc login --agent', or 'pc mcp'), PartCAD prints what a person
would do in that browser instead, with what the site says of any other way in
(see 'Site.LOGIN_INSTRUCTIONS').
"""

import base64
import concurrent.futures
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import zipfile

# --- the file formats PartCAD reads ------------------------------------------
#
# (format, PartCAD part type, file extensions), best first. A model usually
# comes in several, and an exact boundary representation is worth more than a
# mesh of it; among the meshes, 3MF knows its units and STL does not. A '.glb'
# is a glTF with its buffers inside it - a '.gltf' names files beside it, which
# a single file cannot bring along. OpenUSD - a '.usdz' is how Sketchfab and
# Apple's AR Quick Look hand one out, a stage packed with its textures - is
# after glTF: a scene format first, whose geometry is a mesh like any other
# here. OpenSCAD is last, because a '.scad' on a
# model site is usually the customizable source of the STLs beside it, and may
# 'use <>' files that do not come with it.
#
# IGES is an exact format too, after STEP and BREP. The native documents of
# CAD applications - SolidWorks, Inventor, CATIA, Fusion, FreeCAD, ACIS, Creo
# View - PartCAD reads through a converter it downloads on first use
# ('//builtin/import'); they come after the meshes, so that they are taken
# only when a model has nothing else, or when they are asked for.
FORMATS = (
    ("step", "step", ("step", "stp")),
    ("brep", "brep", ("brep", "brp")),
    ("iges", "iges", ("iges", "igs")),
    ("3mf", "3mf", ("3mf",)),
    ("stl", "stl", ("stl",)),
    ("obj", "obj", ("obj",)),
    ("glb", "gltf", ("glb",)),
    ("usd", "usd", ("usdz", "usd", "usdc", "usda")),
    ("sldprt", "sldprt", ("sldprt",)),
    ("ipt", "ipt", ("ipt",)),
    ("catpart", "catpart", ("catpart",)),
    ("f3d", "f3d", ("f3d",)),
    ("fcstd", "fcstd", ("fcstd",)),
    ("sat", "sat", ("sat", "sab")),
    ("pvz", "pvz", ("pvz",)),
    ("scad", "scad", ("scad",)),
)
FORMAT_NAMES = tuple(name for name, _, _ in FORMATS)
_FORMAT_OF_EXTENSION = {ext: name for name, _, exts in FORMATS for ext in exts}
_PART_TYPE = {name: part_type for name, part_type, _ in FORMATS}
_RANK = {name: index for index, (name, _, _) in enumerate(FORMATS)}

# The parameters every model part takes. A site may add its own.
PARAMETERS = ("file", "format", "source")

# Which of a model's files: 'original' is what the designer uploaded; 'preview'
# is the site's own mesh of it - coarser, and needing no login - where the site
# has one; 'auto' is the best original that can be had, else a preview.
SOURCES = ("auto", "original", "preview")

# How many hits a search answers with when it is not told.
DEFAULT_LIMIT = 20
# And the most it answers with when it is: every hit may cost a request for the
# model's files, and a site's patience is not endless.
MAX_LIMIT = 100
# How many requests for models' files a search has in flight at once.
WORKERS = 4
# How many more models a search asks the site for than the hits it is to answer
# with: a model with no file PartCAD reads is not a hit, and on GrabCAD most of
# the first page can be SolidWorks and IGES only.
OVERSAMPLE = 3

DAY = 24 * 3600


def format_of(filename):
    """The format of a file by its extension, or None for one PartCAD does not read."""
    _, dot, ext = (filename or "").rpartition(".")
    return _FORMAT_OF_EXTENSION.get(ext.lower()) if dot else None


def normalize_format(value):
    """'STP' is 'step', 'glb' is 'glb'; None for a format that is not one of FORMATS."""
    value = (value or "").strip().lower().lstrip(".")
    if value in _RANK:
        return value
    return _FORMAT_OF_EXTENSION.get(value)


def part_type_of(fmt):
    return _PART_TYPE[fmt]


# --- names -------------------------------------------------------------------
#
# The grammar is PartCAD's (partcad_utils.utils.parse_parameterized_name and
# format_parameterized_name), restated here because a plugin runs in a sandbox
# that has no PartCAD in it. The names this answers with have to be the ones
# PartCAD would spell, or a search hit would be asked for under another key.


# The characters a reference reserves, and their escapes: the same as
# 'partcad_utils.utils.RESERVED_IN_NAMES', which a test in PartCAD holds this to.
RESERVED_IN_NAMES = ":;,=#%*?[]"
_ESCAPE = re.compile("%(" + "|".join("%02X" % ord(c) for c in RESERVED_IN_NAMES) + ")", re.IGNORECASE)


def _unescape(text):
    """'text' with the escapes of the reserved characters decoded, and nothing else."""
    if "%" not in text:
        return text
    return _ESCAPE.sub(lambda match: chr(int(match.group(1), 16)), text)


def _escape_value(value):
    """'value' as a name has to spell it to be read back as this one value (as PartCAD spells it)."""
    if _ESCAPE.search(value):
        value = value.replace("%", "%25")
    if "," in value and "=" in value:
        value = value.replace(",", "%2C")
    return value


def parse_name(name):
    """'<base>;<param>=<value>,...' as (base, {param: value}), as PartCAD reads it.

    A fragment with no '=' continues the value before it, so a file name with
    a comma in it survives, and the escapes of reserved characters are
    decoded. A plugin is handed the name already taken apart
    (``request["query"]``); this is for one that is asked by key alone.
    """
    base, _, suffix = name.partition(";")
    parameters = {}
    last = None
    for pair in suffix.split(",") if suffix else []:
        if "=" not in pair and last is not None:
            parameters[last] += "," + pair
            continue
        parameter, _, value = pair.partition("=")
        parameters[parameter] = value
        last = parameter
    return _unescape(base), {_unescape(k): _unescape(v) for k, v in parameters.items()}


def format_name(base, parameters):
    """The name of the instance of 'base' with these parameters: sorted and escaped, as PartCAD writes it."""
    items = sorted((k, v) for k, v in parameters.items() if v is not None and v != "")
    if not items:
        return base
    return base + ";" + ",".join("%s=%s" % (k, _escape_value(str(v))) for k, v in items)


def query_of(key):
    """The key taken apart, as PartCAD sends it in ``request["query"]``.

    For a PartCAD that sends the key alone (the same grammar as
    ``project_external_repository.query_of``, which a test in PartCAD holds
    this to).
    """
    path, _, query_string = key.partition("?")
    head, _, rest = path.partition("/")
    if head == "search" and rest:
        arguments = urllib.parse.parse_qs(query_string, keep_blank_values=True)
        query = {"what": "search", "kind": rest, "text": (arguments.get("q") or [""])[0]}
        try:
            limit = int((arguments.get("limit") or [""])[0])
        except ValueError:
            limit = 0
        if limit > 0:
            query["limit"] = limit
        return query
    if head == "objects" and rest:
        kind, _, name = rest.partition("/")
        if not name:
            return {"what": "objects", "kind": kind}
        base, parameters = parse_name(name)
        return {"what": "object", "kind": kind, "name": base, "parameters": parameters}
    if head == "files" and rest:
        return {"what": "file", "path": rest}
    return {"what": key}


# --- what can go wrong, said the way the user can act on it -------------------


class SiteError(Exception):
    """Something the site said or did, in words that say what to do about it."""


class NotFound(SiteError):
    pass


class Refused(SiteError):
    """The site would not answer an automated client, or not this one."""


class NeedsCredentials(SiteError):
    pass


class LoginFailed(SiteError):
    """Logging in did not come to credentials the site takes."""


def warn(message):
    """Say something to the user. PartCAD reports a plugin's stderr, line by line."""
    print(message, file=sys.stderr)


# --- HTTP ----------------------------------------------------------------------

# A fetch that produced nothing is remembered too, for a while, so that a run
# that was refused or throttled leaves something behind and the next one is not
# the same burst again. A 404 is an answer and is kept for a day; anything else
# is the absence of one and is kept for five minutes.
_NEGATIVE_TTL = {"missing": DAY, "unavailable": 300, "refused": 300}
_RETRIES = 3


def cache_dir(site):
    """$PARTCAD_<SITE>_CACHE, else partcad-<site> under the XDG cache directory."""
    base = os.environ.get("PARTCAD_%s_CACHE" % site.upper())
    if not base:
        xdg = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
        base = os.path.join(xdg, "partcad-" + site)
    return base


class Response:
    def __init__(self, status, headers, body, url):
        self.status = status
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.body = body or b""
        self.url = url

    def text(self):
        return self.body.decode("utf-8", "replace")

    def json(self):
        return json.loads(self.body.decode("utf-8"))


def bot_check(response):
    """What turned the request away, if it was a bot check rather than the site; else None.

    These plugins identify themselves and do not pretend to be a browser, so a
    site that admits only browsers turns them away. That is reported as what it
    is, with nothing tried to get past it.

    AWS WAF says so in a header, and on any status: its challenge is a 202 with
    an empty body, which would otherwise pass for an answer with nothing in it.
    """
    waf = (response.headers.get("x-amzn-waf-action") or "").lower()
    if waf in ("challenge", "captcha"):
        return "an AWS WAF bot check (%s)" % waf
    if response.status not in (401, 403, 429, 503):
        return None
    text = response.body[:8192].decode("latin-1", "replace")
    if response.headers.get("cf-mitigated") or "Just a moment..." in text or "/cdn-cgi/challenge-platform/" in text:
        return "a Cloudflare bot check"
    if "Request blocked" in text and "cloudfront" in text.lower():
        return "CloudFront, which blocked the request"
    return None


# The request headers that say who is asking, and so key the cache apart.
_CREDENTIAL_HEADERS = ("Authorization", "Cookie")


class _SameHostRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects, but keep credentials on the host they were given for.

    A download link is commonly a redirect to a CDN, and urllib hands every
    header of the request on to wherever the redirect points.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlsplit(newurl).netloc != urllib.parse.urlsplit(req.full_url).netloc:
            for header in ("Authorization", "Cookie"):
                new.remove_header(header)
        return new


_OPENER = urllib.request.build_opener(_SameHostRedirects())


class Http:
    """Requests to one site, with an on-disk cache of what it answered."""

    def __init__(self, site, user_agent):
        self.site = site
        self.user_agent = user_agent
        self.root = cache_dir(site)

    # -- the wire --

    def request(self, url, headers=None, data=None, method=None, timeout=60):
        """One request, retried on what retrying can help; the Response whatever its status."""
        all_headers = {"User-Agent": self.user_agent, "Accept": "application/json, */*;q=0.5"}
        all_headers.update(headers or {})
        if data is not None and not isinstance(data, bytes):
            data = json.dumps(data).encode("utf-8")
            all_headers.setdefault("Content-Type", "application/json")
        last = None
        for attempt in range(_RETRIES):
            delay = 1.0 * (attempt + 1)
            try:
                request = urllib.request.Request(url, data=data, headers=all_headers, method=method)
                with _OPENER.open(request, timeout=timeout) as answer:
                    return Response(answer.status, dict(answer.headers), answer.read(), answer.geturl())
            except urllib.error.HTTPError as e:
                last = Response(e.code, dict(e.headers or {}), e.read() if e.fp else b"", url)
                if e.code == 429:
                    delay = max(delay, _retry_after(e.headers, delay))
                elif e.code < 500 or bot_check(last):
                    return last
            except Exception as e:  # a timeout, a reset, a name that did not resolve
                last = Response(0, {}, str(e).encode("utf-8"), url)
            time.sleep(delay)
        return last

    def checked(self, response, what):
        """'response' if it is a 2xx; otherwise the SiteError that says why not."""
        # Before the status: a bot check can answer 2xx (see 'bot_check').
        refused_by = bot_check(response)
        if 200 <= response.status < 300 and not refused_by:
            return response
        if refused_by:
            raise Refused(
                "%s: %s was turned away by %s. These plugins do not pretend to be a browser; "
                "try again later or from another network, and see the README for what %s admits."
                % (self.site, what, refused_by, self.site)
            )
        if response.status == 404:
            raise NotFound("%s: %s: not found" % (self.site, what))
        if response.status == 0:
            raise SiteError("%s: %s could not be fetched: %s" % (self.site, what, response.text()[:200]))
        said = _said(response)
        if response.status in (401, 403):
            raise NeedsCredentials(
                "%s: %s: the site wants a sign-in, or did not accept the one given (HTTP %d%s)"
                % (self.site, what, response.status, ": " + said if said else "")
            )
        raise SiteError("%s: %s: HTTP %d%s" % (self.site, what, response.status, ": " + said if said else ""))

    # -- the cache --

    def _path(self, kind, key):
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return os.path.join(self.root, kind, digest[:2], digest)

    def _negative(self, key):
        path = self._path("missing", key)
        try:
            with open(path, "r", encoding="utf-8") as f:
                reason, message = f.read().split("\n", 1)
            if time.time() - os.path.getmtime(path) < _NEGATIVE_TTL.get(reason, 0):
                return reason, message
        except (OSError, ValueError):
            pass
        return None

    def _remember(self, kind, key, content):
        """Keep 'content' for 'key', if the cache can be written: a cache that cannot costs a miss, not the answer."""
        try:
            self._store(self._path(kind, key), content)
        except OSError:
            # A read-only home in a sandbox, a full disk: the site has answered
            # by now, and that answer is what the request was for.
            pass

    @staticmethod
    def _store(path, content):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # A file of its own per write, not per process: 'find' reads models on
        # a pool of threads, and two of them can store one key - a model a
        # search lists twice, or a page two models share.
        fd, temporary = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(content)
            os.replace(temporary, path)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def json(self, url, what, headers=None, data=None, method=None, ttl=DAY, valid=None):
        """The JSON at 'url', from the cache when it is younger than 'ttl' seconds.

        'valid(value)', when given, says whether an answer is worth keeping: a
        GraphQL API answers a failure with a 200 and 'errors' in it, and that
        kept for a day is a day of the same failure.

        The cache is keyed on who asks as well as on what is asked - a digest of
        the credentials sent, never the credentials - since what an account is
        shown is that account's: two accounts on one machine see their own.
        """
        who = "".join("%s=%s;" % (k, v) for k, v in sorted((headers or {}).items()) if k in _CREDENTIAL_HEADERS)
        key = "%s %s %s %s" % (
            method or ("POST" if data is not None else "GET"),
            url,
            json.dumps(data, sort_keys=True),
            hashlib.sha256(who.encode("utf-8")).hexdigest()[:16] if who else "",
        )
        path = self._path("json", key)
        if ttl and os.path.exists(path) and time.time() - os.path.getmtime(path) < ttl:
            try:
                with open(path, "rb") as f:
                    return json.loads(f.read().decode("utf-8"))
            except (OSError, ValueError):
                pass
        negative = self._negative(key)
        if negative is not None:
            reason, message = negative
            raise {"missing": NotFound, "refused": Refused}.get(reason, SiteError)(message)
        response = self.request(url, headers=headers, data=data, method=method)
        try:
            self.checked(response, what)
            value = response.json()
        except ValueError:
            error = SiteError("%s: %s did not answer with JSON" % (self.site, what))
            self._remember("missing", key, ("unavailable\n" + str(error)).encode("utf-8"))
            raise error
        except SiteError as e:
            reason = {NotFound: "missing", Refused: "refused"}.get(type(e), "unavailable")
            if not isinstance(e, NeedsCredentials):
                self._remember("missing", key, (reason + "\n" + str(e)).encode("utf-8"))
            raise
        if ttl and (valid is None or valid(value)):
            self._remember("json", key, response.body)
        return value

    def probe(self, url, what, headers=None, data=None):
        """Ask 'url' as somebody, uncached: (status, JSON or None). Raises SiteError only when nobody answered.

        For 'whoami': a 401 or a 403 is an answer here - the site does not take
        the credentials - while a bot check or no answer at all says nothing
        about them, and is raised as what it is.
        """
        response = self.request(url, headers=headers, data=data)
        refused_by = bot_check(response)
        if refused_by:
            raise Refused("%s: %s was turned away by %s" % (self.site, what, refused_by))
        if response.status == 0:
            raise SiteError("%s: %s could not be fetched: %s" % (self.site, what, response.text()[:200]))
        try:
            body = response.json()
        except ValueError:
            body = None
        return response.status, body

    def download(self, url, what, headers=None):
        """The bytes at 'url'. Not cached here: PartCAD keeps what 'files/' answers."""
        return self.checked(self.request(url, headers=headers, timeout=600), what).body


def _said(response):
    """What a site said in a JSON error, briefly, or ''. A GraphQL API's 'errors' included."""
    try:
        body = response.json()
    except ValueError:
        return ""
    if isinstance(body, dict):
        for key in ("error", "message", "msg", "detail"):
            if isinstance(body.get(key), str) and body[key].strip():
                return body[key].strip()[:200]
        errors = body.get("errors")
        if isinstance(errors, list):
            messages = [e.get("message") for e in errors if isinstance(e, dict) and isinstance(e.get("message"), str)]
            if messages:
                return "; ".join(messages)[:200]
    return ""


def _retry_after(headers, default):
    value = headers.get("Retry-After") if headers else None
    try:
        return min(float(value), 60.0) if value else default
    except (TypeError, ValueError):
        return default


def credential(request, parameter, environment):
    """A credential: the repository's parameter (which the user's config may set), else the environment.

    Never written into anything this answers: PartCAD caches the answers, and
    a cache can be shared.
    """
    value = ((request or {}).get("parameters") or {}).get(parameter) or os.environ.get(environment) or ""
    return str(value).strip()


def read_zip_member(archive, name):
    """The bytes of the member of the zip 'archive' whose name, or base name, is 'name'."""
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        members = [m for m in z.namelist() if not m.endswith("/")]
        for candidate in (name, name.lower()):
            for member in members:
                if member == candidate or member.rsplit("/", 1)[-1] == candidate:
                    return z.read(member)
                if member.lower() == candidate or member.rsplit("/", 1)[-1].lower() == candidate:
                    return z.read(member)
    return None


def is_zip(data):
    return data[:4] == b"PK\x03\x04"


# --- models and their files ----------------------------------------------------


class File:
    """One file of a model.

    'id' is what the site knows it by and 'name' what it is called; either
    names it in a part name. A 'fallback' is a file that stands in for the
    model's own when those cannot be had - a site's preview mesh, 'source:
    preview' - and is chosen only then, unless asked for. 'extra' is the
    site's own business.
    """

    def __init__(self, id, name, size=None, fallback=False, **extra):
        self.id = str(id)
        self.name = name
        self.size = size
        self.fallback = fallback
        self.format = format_of(name)
        self.extra = extra

    def __repr__(self):
        return "File(%r, %r)" % (self.id, self.name)


class Model:
    def __init__(self, id, title=None, url=None, author=None, license=None, files=None, desc=None):
        self.id = str(id)
        self.title = title
        self.url = url
        self.author = author
        self.license = license
        self.files = files
        self.desc = desc


def file_token(file_id):
    """A short, path-safe stand-in for a file's id, which may be any text."""
    return hashlib.sha1(file_id.encode("utf-8")).hexdigest()[:12]


def _safe(text, limit=80):
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text or "").strip("_") or "file"
    if len(text) <= limit:
        return text
    stem, dot, ext = text.rpartition(".")
    return (stem[: limit - len(ext) - 1] + "." + ext) if dot and len(ext) < 8 else text[:limit]


def file_path(model, file):
    """Where the plugin serves a file from, as 'files/<this>': the model, a token for the file, its name.

    The model's id is quoted rather than made safe, because 'Site.file' reads
    it back to ask the site for the model again: an id with a '/', a space or
    a letter outside ASCII in it would otherwise come back as another id. The
    ids of the sites there are - digits, slugs - are spelled as they were.
    """
    return "%s/%s/%s" % (urllib.parse.quote(model.id, safe=""), file_token(file.id), _safe(file.name))


class Site:
    """A model site, as a plugin serves it. Each plugin's script makes one."""

    NAME = None  # 'thingiverse': its cache directory, its User-Agent, its messages
    TITLE = None  # 'Thingiverse'
    URL = None
    DESC = None
    VERSION = 1  # the plugin's CACHE_VERSION, which its User-Agent carries
    # Where the plugin is, for its User-Agent: whoever reads a site's logs can
    # see who asked. Defaults to github.com/partcad/partcad-repo-<NAME>.
    HOMEPAGE = None
    # Parameters a part of this site takes beyond PARAMETERS, {name: description}.
    EXTRA_PARAMETERS = {}
    # Whether the site has preview meshes of its own ('source: preview').
    PREVIEWS = False
    # What 'preview' means on this site, for the 'source' parameter's
    # description: '%s' is the site's TITLE.
    PREVIEW_DESCRIPTION = "%s's own mesh of it, coarser and needing no login, where it has one"
    # For whoever logs in with nobody at the screen ('pc login --agent'): any
    # other way in than signing in with a browser - an API key and the page
    # that makes one - and what can be had without logging in at all.
    LOGIN_INSTRUCTIONS = None

    def __init__(self, request=None):
        self.request = request or {}
        self.non_interactive = False
        self._preferences = None
        self.http = Http(
            self.NAME,
            "Mozilla/5.0 (compatible; PartCAD-%s/%s; +%s)"
            % (self.NAME, self.VERSION, self.HOMEPAGE or "https://github.com/partcad/partcad-repo-" + self.NAME),
        )

    # -- what a site implements --

    def valid_id(self, model_id):
        """Whether 'model_id' could name a model at all, so nonsense costs no request."""
        return bool(model_id)

    def model(self, model_id):
        """The Model, with its files. Raises SiteError."""
        raise NotImplementedError

    def download(self, model, file):
        """The file's bytes. Raises SiteError."""
        raise NotImplementedError

    def search(self, text, limit):
        """The models the site finds for 'text', best first; a Model's 'files' may be None."""
        raise NotImplementedError

    def usable(self, file):
        """Whether 'file' can be downloaded as things stand - with the credentials there are."""
        return True

    def unserved(self, model):
        """Why a model a search found cannot be served as a part, when that is worth listing; else None.

        A hit is ordinarily a name to instantiate, and a model with no file
        PartCAD reads is left out. A site that finds models it may never hand
        over - Cults3D gives nobody another user's files - can say so here, and
        the model is listed with that, a link and no 'type': found, not served.
        """
        return None

    # -- what PartCAD is answered --

    def meta(self):
        return {
            "desc": self.DESC,
            "url": self.URL,
            # What a model site serves is somebody's upload: there is nothing
            # in it to say it is made to be manufactured, or what of.
            "manufacturable": False,
            "objectKinds": ["part"],
            "searchKinds": ["part"],
            "instanceKinds": ["part"],
        }

    def parameters(self, file):
        declared = {
            "file": {
                "type": "string",
                "default": file.id,
                "desc": "Which of the model's files: its id on %s, or its name." % self.TITLE,
            },
            "format": {
                "type": "string",
                "default": file.format,
                "enum": list(FORMAT_NAMES),
                "desc": "The format to take the model in, when 'file' does not say: its best file of that format.",
            },
            "source": {
                "type": "string",
                "default": "preview" if file.fallback else "original",
                "enum": list(SOURCES),
                "desc": "Which of the model's files, when 'file' does not say: 'original' (what the designer "
                "uploaded), 'preview' (%s) or 'auto' (the best original that can be had, else a preview)."
                % (self.PREVIEW_DESCRIPTION % self.TITLE),
            },
        }
        for name, desc in self.EXTRA_PARAMETERS.items():
            declared[name] = {"type": "string", "default": "", "desc": desc}
        return declared

    def part_config(self, model, file):
        title = model.title or "%s model %s" % (self.TITLE, model.id)
        config = {
            "type": part_type_of(file.format),
            "path": file_path(model, file),
            "desc": "%s: %s" % (title, file.name),
            "parameters": self.parameters(file),
        }
        if model.url:
            config["url"] = model.url
        if model.author:
            config["author"] = model.author
        if model.license:
            config["license"] = model.license
        return config

    def unserved_hit(self, model, reason):
        """A hit for a model that is found and not served: what it is, why, where. No 'type', so not an object."""
        config = {"desc": "%s (%s)" % (model.title or "%s model %s" % (self.TITLE, model.id), reason)}
        if model.url:
            config["url"] = model.url
        return config

    def preferences(self):
        """(formats, source): the plugin's 'formats' and 'source' parameters, as the user set them.

        'formats' is which formats to take a model in, best first ('stl,3mf'
        for meshes only); empty is all of them, best first. 'source' is which
        of a model's files: see SOURCES. Both are a default for every model,
        which a part's own 'format', 'file' and 'source' override.
        """
        if self._preferences is None:
            parameters = (self.request or {}).get("parameters") or {}
            formats = []
            for value in re.split(r"[\s,;]+", str(parameters.get("formats") or "").strip()):
                if not value:
                    continue
                fmt = normalize_format(value)
                if fmt is None:
                    raise SiteError(
                        "%s: unknown format '%s' in 'formats'; PartCAD reads %s"
                        % (self.NAME, value, ", ".join(FORMAT_NAMES))
                    )
                if fmt not in formats:
                    formats.append(fmt)
            source = str(parameters.get("source") or "auto").strip().lower()
            if source not in SOURCES:
                raise SiteError("%s: 'source' is one of %s, not '%s'" % (self.NAME, ", ".join(SOURCES), source))
            self._preferences = (tuple(formats) or FORMAT_NAMES, source)
        return self._preferences

    @staticmethod
    def _of_source(file, source):
        return source == "auto" or file.fallback == (source == "preview")

    def _rank(self, fmt):
        formats = self.preferences()[0]
        return formats.index(fmt) if fmt in formats else len(formats) + _RANK[fmt]

    def choose(self, model, wanted_file=None, wanted_format=None, wanted_source=None):
        """The file a name means: the one it names, else the best of the format and source it names, else the best.

        What the name leaves open, the plugin's 'formats' and 'source' decide.
        """
        files = model.files or []
        if wanted_file:
            for match in (
                lambda f: f.id == wanted_file,
                lambda f: f.name == wanted_file,
                lambda f: f.name.lower() == wanted_file.lower(),
            ):
                found = [f for f in files if match(f)]
                if found:
                    file = found[0]
                    if file.format is None:
                        raise SiteError(
                            "%s: '%s' of %s is not a file PartCAD reads (it reads %s)"
                            % (self.NAME, file.name, model.id, ", ".join(FORMAT_NAMES))
                        )
                    if wanted_format and file.format != wanted_format:
                        raise SiteError(
                            "%s: '%s' of %s is %s, not %s"
                            % (self.NAME, file.name, model.id, file.format, wanted_format)
                        )
                    if wanted_source and not self._of_source(file, wanted_source):
                        raise SiteError(
                            "%s: '%s' of %s is %s, not %s"
                            % (
                                self.NAME,
                                file.name,
                                model.id,
                                "a preview" if file.fallback else "an original",
                                "a preview" if wanted_source == "preview" else "an original",
                            )
                        )
                    return file
            raise NotFound(
                "%s: %s has no file '%s'. It has: %s"
                % (self.NAME, model.id, wanted_file, ", ".join(f.name for f in files) or "no files")
            )
        formats, source = self.preferences()
        source = wanted_source or source
        formats = (wanted_format,) if wanted_format else formats
        candidates = [f for f in files if f.format in formats and self._of_source(f, source)]
        if not candidates:
            readable = [f for f in files if f.format]
            if not readable:
                raise NotFound(
                    "%s: %s has no file PartCAD reads (it reads %s; the model has %s)"
                    % (self.NAME, model.id, ", ".join(FORMAT_NAMES), ", ".join(f.name for f in files) or "no files")
                )
            wanted = []
            if source == "preview":
                wanted.append("preview")
            elif source == "original":
                wanted.append("original")
            if wanted_format or formats != FORMAT_NAMES:
                wanted.append("/".join(formats))
            if source == "preview" and not self.PREVIEWS:
                why = "%s has no previews" % self.TITLE
            else:
                why = "it has %s" % ", ".join(
                    sorted(
                        {"%s%s" % (f.format, " (preview)" if f.fallback else "") for f in readable},
                        key=lambda text: (text.endswith("(preview)"), _RANK[text.split()[0]]),
                    )
                )
            raise NotFound("%s: %s has no %s file (%s)" % (self.NAME, model.id, " ".join(wanted), why))
        return min(candidates, key=lambda f: self._preference(f, files))

    def _preference(self, file, files):
        return (not self.usable(file), file.fallback, self._rank(file.format), files.index(file))

    def listed(self, model):
        """The files of a model a search names: the best class there is, one per stem.

        A CAD model on a model site is often uploaded several times over -
        'bracket.step', 'bracket.stl', 'bracket.igs' - and that is one part in
        three formats, not three parts. Only files that can be had now are
        named when there are any, and a stand-in only when there is nothing
        else.
        """
        formats, source = self.preferences()
        files = [f for f in (model.files or []) if f.format in formats and self._of_source(f, source)]
        if not files:
            return []
        best = min((not self.usable(f), f.fallback) for f in files)
        files = [f for f in files if (not self.usable(f), f.fallback) == best]
        by_stem = {}
        for f in files:
            stem = f.name.rsplit(".", 1)[0].lower()
            if stem not in by_stem or self._preference(f, files) < self._preference(by_stem[stem], files):
                by_stem[stem] = f
        return [f for f in files if by_stem.get(f.name.rsplit(".", 1)[0].lower()) is f]

    def resolve(self, base, parameters):
        """The declaration of the part 'base;parameters' names."""
        unknown = sorted(set(parameters) - set(PARAMETERS) - set(self.EXTRA_PARAMETERS))
        if unknown:
            raise SiteError(
                "%s: unknown parameter%s %s; a part takes %s"
                % (
                    self.NAME,
                    "s" if len(unknown) > 1 else "",
                    ", ".join(unknown),
                    ", ".join(PARAMETERS + tuple(self.EXTRA_PARAMETERS)),
                )
            )
        if not self.valid_id(base):
            raise NotFound("%s: '%s' is not a %s model id" % (self.NAME, base, self.TITLE))
        wanted_format = None
        if parameters.get("format"):
            wanted_format = normalize_format(parameters["format"])
            if wanted_format is None:
                raise SiteError(
                    "%s: unknown format '%s'; PartCAD reads %s"
                    % (self.NAME, parameters["format"], ", ".join(FORMAT_NAMES))
                )
        wanted_source = None
        if parameters.get("source"):
            wanted_source = str(parameters["source"]).strip().lower()
            if wanted_source not in SOURCES:
                raise SiteError(
                    "%s: 'source' is one of %s, not '%s'" % (self.NAME, ", ".join(SOURCES), parameters["source"])
                )
        model = self.model(base)
        file = self.choose(model, parameters.get("file") or None, wanted_format, wanted_source)
        return self.part_config(model, file)

    def file(self, path):
        """The base64 content of 'files/<path>'."""
        quoted, _, rest = path.partition("/")
        model_id = urllib.parse.unquote(quoted)
        token, _, _ = rest.partition("/")
        model = self.model(model_id)
        for file in model.files or []:
            if file_token(file.id) == token:
                return base64.b64encode(self.download(model, file)).decode("ascii")
        raise NotFound("%s: %s has no file %s any more" % (self.NAME, model_id, path))

    def find(self, text, limit=None):
        """A search for parts answered: {name: config}, best first."""
        text = (text or "").strip()
        limit = min(limit or DEFAULT_LIMIT, MAX_LIMIT)
        if not text:
            return {}
        models = self.search(text, min(limit * OVERSAMPLE, MAX_LIMIT))

        def complete(model):
            if model.files is not None:
                return model, None
            try:
                full = self.model(model.id)
            except SiteError as e:
                return model, e
            for attr in ("title", "url", "author", "license"):
                if getattr(full, attr) is None:
                    setattr(full, attr, getattr(model, attr))
            return full, None

        # A hit is a name to instantiate, so a model with no file PartCAD reads
        # - a GrabCAD model that is SolidWorks and IGES only - is not one, and
        # neither is one whose files could not be read. Models are read a few
        # at a time, in the site's order, until there are hits enough.
        hits, failures = {}, []
        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for start in range(0, len(models), WORKERS * 2):
                for model, error in pool.map(complete, models[start : start + WORKERS * 2]):
                    if error is not None:
                        failures.append(str(error))
                        continue
                    listed = self.listed(model)
                    reason = None if listed else self.unserved(model)
                    if reason:
                        hits[model.id] = self.unserved_hit(model, reason)
                    for file in listed:
                        hits[format_name(model.id, {"file": file.id})] = self.part_config(model, file)
                        if len(hits) >= limit:
                            break
                    if len(hits) >= limit:
                        break
                if len(hits) >= limit:
                    break
        if not hits and failures:
            # Found something and could serve none of it: that is worth saying,
            # where finding nothing is not.
            warn(
                "%s: %d model%s found for '%s' could not be read; the first: %s"
                % (self.NAME, len(failures), "" if len(failures) == 1 else "s", text, failures[0])
            )
        return hits

    # -- logging in --
    #
    # The repository parameters that are this site's credentials, each with the
    # environment variable that may give it instead: {"token": "SITE_TOKEN"}.
    CREDENTIALS = {}

    def credentials(self):
        """The credentials the plugin was given, {parameter: value}; a value is '' when there is none."""
        return {name: credential(self.request, name, env) for name, env in self.CREDENTIALS.items()}

    def whoami(self, credentials):
        """Whom 'credentials' sign in as on the site, or None when the site does not take them.

        Raises SiteError when the site cannot be asked - which is not the same
        as being told no, and must not be read as one.
        """
        raise NotImplementedError

    def login_spec(self):
        """What the browser is asked to do: the arguments of 'partcad_login.open_browser'."""
        raise NotImplementedError

    def credentials_from(self, captured):
        """The credentials in what the browser captured, {parameter: value}."""
        return {name: str(captured.get(name) or "").strip() for name in self.CREDENTIALS}

    def login_instructions(self):
        """What 'pc login --agent' says beside the browser's request: LOGIN_INSTRUCTIONS, and the environment."""
        lines = [self.LOGIN_INSTRUCTIONS.strip()] if self.LOGIN_INSTRUCTIONS else []
        if self.CREDENTIALS:
            lines.append(
                "The plugin also reads %s from the environment it runs in (which a container sandbox does not "
                "see), and the plugin's parameter%s %s from ~/.partcad/config.yaml, where 'pc login' keeps %s."
                % (
                    " and ".join(self.CREDENTIALS.values()),
                    "s" if len(self.CREDENTIALS) > 1 else "",
                    " and ".join("'%s'" % name for name in self.CREDENTIALS),
                    "them" if len(self.CREDENTIALS) > 1 else "it",
                )
            )
        return "\n\n".join(lines)

    def login(self, partcad_login):
        """'login' answered: the credentials there are if the site takes them, else new ones from the browser.

        'partcad_login.open_browser' is PartCAD's callback. It does not return
        the first time it is called: PartCAD opens the browser, waits for the
        extension to send what it captured, and runs this again from the top
        with that to hand, when the call returns it. So nothing before it may
        be anything that must not happen twice - and checking credentials is
        not.
        """
        # Nobody at the screen ('pc login --agent'): the browser is not opened,
        # and what is asked of it is told to whoever is there instead. A site
        # whose sign-in is no good to do by hand may ask for something else.
        self.non_interactive = bool(getattr(partcad_login, "non_interactive", False))
        current = self.credentials()
        if any(current.values()):
            who = self.whoami(current)
            if who:
                return {"parameters": current, "message": "Already logged in to %s as %s" % (self.TITLE, who)}
        spec = dict(self.login_spec())
        if hasattr(partcad_login, "non_interactive"):  # a PartCAD that takes 'instructions'
            instructions = self.login_instructions()
            if instructions and "instructions" not in spec:
                spec["instructions"] = instructions
        captured = partcad_login.open_browser(**spec)
        fresh = self.credentials_from(captured)
        if not any(fresh.values()):
            raise LoginFailed("%s: the browser came back with nothing to log in with" % self.NAME)
        try:
            who = self.whoami(fresh)
        except SiteError as e:
            # Just signed in, in the browser, so very likely right; that it
            # cannot be checked from here is worth saying, not worth losing.
            return {
                "parameters": fresh,
                "message": "Saved the %s credentials; they could not be checked from here: %s" % (self.TITLE, e),
            }
        if not who:
            raise LoginFailed("%s: the site does not take what the login captured; run 'pc login' again" % self.NAME)
        return {"parameters": fresh, "message": "Logged in to %s as %s" % (self.TITLE, who)}

    def get(self, key):
        """One key of the repository protocol; None for a key there is no answer to.

        Read from the key taken apart, ``request["query"]``, when PartCAD sent
        it for this key - which is also the key without the subfolder of a
        package scoped to one - and from the key itself otherwise.
        """
        query = self.request.get("query") if self.request.get("key") == key else None
        if not isinstance(query, dict) or "what" not in query:
            query = query_of(key)
        what = query["what"]
        if what == "meta":
            return self.meta()
        if what == "deps":
            return []
        if what == "search":
            return self.find(query.get("text"), query.get("limit")) if query.get("kind") == "part" else {}
        if what == "objects":
            # Nothing is listed: a model site's catalog is not something to
            # enumerate, and PartCAD is told so by 'objectKinds'.
            return {}
        if what == "object":
            if query.get("kind") != "part":
                return None
            return self.resolve(str(query.get("name") or ""), dict(query.get("parameters") or {}))
        if what == "file":
            return self.file(query.get("path") or "")
        return None


def login(site, partcad_login):
    """'site.login(partcad_login)', with what went wrong raised as the one line the user reads.

    Not caught and turned into None the way 'serve' does it: a login that did
    not happen has to fail the command, and PartCAD reports the exception.
    PartCAD's own signal to open the browser is not an Exception, so it passes
    through untouched.
    """
    if partcad_login is None:
        raise RuntimeError("%s: this PartCAD has no 'pc login'; upgrade PartCAD" % site.NAME)
    try:
        return site.login(partcad_login)
    except SiteError as e:
        raise RuntimeError(str(e)) from None


def serve(site, key):
    """'site.get(key)', with what went wrong said on stderr rather than raised."""
    try:
        return site.get(key)
    except SiteError as e:
        warn(str(e))
    except Exception as e:  # a site changed under us: say what, and where
        frame = traceback.extract_tb(e.__traceback__)[-1]
        warn(
            "%s: unexpected %s answering '%s': %s (%s:%d)"
            % (site.NAME, type(e).__name__, key, e, os.path.basename(frame.filename), frame.lineno)
        )
    return None
