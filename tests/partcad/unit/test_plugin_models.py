#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests of plugin_models, the toolkit PartCAD gives a repository plugin for a model site.

It runs in the plugin's sandbox, where PartCAD itself is not importable, so it
is loaded here by path, the way a plugin script reaches it. Nothing here
touches the network: a site is a stand-in, and HTTP is answered from a table.
The tests at the end hold it to the rest of PartCAD: the formats it offers are
part types PartCAD builds, and the names it writes are the names PartCAD reads.
"""

import base64
import importlib.util
import io
import json
import os
import zipfile

import pytest

import partcad as pc

_WRAPPERS = os.path.join(os.path.dirname(os.path.abspath(pc.__file__)), "wrappers")
_SPEC = importlib.util.spec_from_file_location("plugin_models_under_test", os.path.join(_WRAPPERS, "plugin_models.py"))
rm = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rm)


# --- names -------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, base, parameters",
    [
        ("763622", "763622", {}),
        ("763622;format=stl", "763622", {"format": "stl"}),
        ("763622;file=1,format=stl", "763622", {"file": "1", "format": "stl"}),
        # A comma with no '=' after it continues the value, as PartCAD reads it.
        ("763622;file=a,b.stl", "763622", {"file": "a,b.stl"}),
        ("763622;file=a=b.stl", "763622", {"file": "a=b.stl"}),
    ],
)
def test_a_name_is_read_the_way_partcad_reads_it(name, base, parameters):
    assert rm.parse_name(name) == (base, parameters)


def test_a_name_is_written_the_way_partcad_writes_it():
    """Sorted, so a hit is asked for under the key PartCAD will ask with."""
    assert rm.format_name("763622", {"format": "stl", "file": "1"}) == "763622;file=1,format=stl"
    assert rm.format_name("763622", {}) == "763622"
    assert rm.format_name("763622", {"file": ""}) == "763622"


@pytest.mark.parametrize(
    "value, fmt",
    [
        ("STEP", "step"),
        ("stp", "step"),
        (".stl", "stl"),
        ("glb", "glb"),
        ("3MF", "3mf"),
        ("IGS", "iges"),
        ("skp", None),
    ],
)
def test_a_format_is_named_as_loosely_as_people_write_it(value, fmt):
    assert rm.normalize_format(value) == fmt


# --- a site ------------------------------------------------------------------


class Site(rm.Site):
    NAME = "test"
    TITLE = "Test"
    URL = "https://example.com"
    DESC = "A stand-in"

    def __init__(self, models, usable=lambda f: True, found=()):
        super().__init__({})
        self.models = models
        self._usable = usable
        self.found = list(found)
        self.asked = []

    def valid_id(self, model_id):
        return model_id.isdigit()

    def model(self, model_id):
        self.asked.append(model_id)
        if model_id not in self.models:
            raise rm.NotFound("test: model %s: not found" % model_id)
        return self.models[model_id]

    def download(self, model, file):
        return ("%s/%s" % (model.id, file.name)).encode()

    def search(self, text, limit):
        return self.found

    def usable(self, file):
        return self._usable(file)


def _model(model_id="1", names=("clip.stl", "clip.step", "base.stl", "notes.txt"), **kw):
    return rm.Model(
        model_id,
        title="Cable clip",
        url="https://example.com/%s" % model_id,
        author="Ann",
        license="CC BY 4.0",
        files=[rm.File(str(100 + i), name) for i, name in enumerate(names)],
        **kw,
    )


def test_a_model_name_alone_is_its_best_file():
    site = Site({"1": _model()})
    config = site.get("objects/part/1")
    assert config["type"] == "step"
    assert config["path"].endswith("/clip.step")
    assert config["desc"] == "Cable clip: clip.step"
    assert config["parameters"]["file"]["default"] == "101"
    assert config["parameters"]["format"]["default"] == "step"
    assert config["url"] == "https://example.com/1" and config["author"] == "Ann"


def test_a_format_chooses_the_best_file_of_it():
    site = Site({"1": _model()})
    config = site.get("objects/part/1;format=stl")
    assert config["type"] == "stl" and config["path"].endswith("/clip.stl")


def test_a_file_is_named_by_its_id_or_its_name():
    site = Site({"1": _model()})
    assert site.get("objects/part/1;file=102")["path"].endswith("/base.stl")
    assert site.get("objects/part/1;file=base.stl")["path"].endswith("/base.stl")
    assert site.get("objects/part/1;file=BASE.STL")["path"].endswith("/base.stl")


def test_a_file_and_a_format_that_disagree_are_refused(capsys):
    site = Site({"1": _model()})
    assert rm.serve(site, "objects/part/1;file=base.stl,format=step") is None
    assert "base.stl of 1 is stl, not step" in capsys.readouterr().err.replace("'", "")


def test_what_is_not_there_is_said_so(capsys):
    site = Site({"1": _model()})
    assert rm.serve(site, "objects/part/1;file=nope.stl") is None
    assert "has no file 'nope.stl'" in capsys.readouterr().err
    assert rm.serve(site, "objects/part/1;format=obj") is None
    assert "has no obj file (it has step, stl)" in capsys.readouterr().err
    assert rm.serve(site, "objects/part/1;file=notes.txt") is None
    assert "not a file PartCAD reads" in capsys.readouterr().err
    assert rm.serve(site, "objects/part/1;colour=red") is None
    assert "unknown parameter colour" in capsys.readouterr().err
    assert rm.serve(site, "objects/part/1;format=skp") is None
    assert "unknown format 'skp'" in capsys.readouterr().err


def test_nonsense_costs_no_request(capsys):
    site = Site({})
    assert rm.serve(site, "objects/part/not-a-number") is None
    assert site.asked == []
    assert "is not a Test model id" in capsys.readouterr().err


def test_nothing_is_listed():
    site = Site({"1": _model()})
    assert site.get("objects/part") == {}
    assert site.get("objects/sketch") == {}
    assert site.get("deps") == []
    assert site.asked == []


def test_the_package_is_not_manufacturable_and_says_what_it_does():
    meta = Site({}).get("meta")
    assert meta["manufacturable"] is False
    assert meta["objectKinds"] == ["part"]
    assert meta["searchKinds"] == ["part"]
    assert meta["instanceKinds"] == ["part"]


def test_a_file_is_served_from_the_path_its_part_names():
    site = Site({"1": _model()})
    path = site.get("objects/part/1;file=base.stl")["path"]
    assert base64.b64decode(site.get("files/" + path)) == b"1/base.stl"


def test_a_usable_file_is_preferred_to_a_better_format():
    """Without a sign-in, the best file is the best one that can be had."""
    site = Site({"1": _model()}, usable=lambda f: f.format != "step")
    assert site.get("objects/part/1")["path"].endswith("/clip.stl")


def test_a_stand_in_is_chosen_only_when_there_is_nothing_else():
    model = _model(names=("clip.stl",))
    model.files.append(rm.File("preview-9", "preview-9.glb", fallback=True))
    assert Site({"1": model}).get("objects/part/1")["type"] == "stl"
    assert Site({"1": model}, usable=lambda f: f.fallback).get("objects/part/1")["type"] == "gltf"


def _with_preview(**kw):
    model = _model(names=("clip.stl", "clip.step"), **kw)
    model.files.append(rm.File("preview-9", "preview-9.glb", fallback=True))
    return model


def _preferring(models, usable=lambda f: True, **parameters):
    site = Site(models, usable=usable)
    site.request = {"parameters": parameters}
    site.PREVIEWS = True
    return site


def test_a_part_names_its_source_and_a_preview_is_asked_for_by_it():
    config = _preferring({"1": _with_preview()}).get("objects/part/1;source=preview")
    assert config["type"] == "gltf" and config["parameters"]["source"]["default"] == "preview"
    original = _preferring({"1": _with_preview()}).get("objects/part/1")
    assert original["type"] == "step" and original["parameters"]["source"]["default"] == "original"
    assert original["parameters"]["source"]["enum"] == ["auto", "original", "preview"]


def test_source_original_never_falls_back_to_a_preview():
    site = _preferring({"1": _with_preview()}, usable=lambda f: f.fallback, source="original")
    # The original is chosen even though it cannot be had: the download says why.
    assert site.get("objects/part/1")["type"] == "step"


def test_the_plugins_source_is_every_parts_default_and_a_part_overrides_it():
    site = _preferring({"1": _with_preview()}, source="preview")
    assert site.get("objects/part/1")["type"] == "gltf"
    assert site.get("objects/part/1;source=original")["type"] == "step"


def test_formats_restrict_and_order_what_is_taken():
    site = _preferring({"1": _with_preview()}, formats="stl, 3mf")
    assert site.get("objects/part/1")["type"] == "stl"
    # A part's own format is honoured whatever the plugin prefers.
    assert site.get("objects/part/1;format=step")["type"] == "step"
    assert _preferring({"1": _with_preview()}, formats="glb").get("objects/part/1")["type"] == "gltf"


def test_what_the_preferences_rule_out_is_said_so(capsys):
    site = _preferring({"1": _model(names=("clip.step",))}, formats="stl")
    assert rm.serve(site, "objects/part/1") is None
    assert "has no stl file (it has step)" in capsys.readouterr().err
    no_previews = Site({"1": _model(names=("clip.step",))})
    assert rm.serve(no_previews, "objects/part/1;source=preview") is None
    assert "Test has no previews" in capsys.readouterr().err


def test_a_preference_that_means_nothing_is_refused(capsys):
    for parameters, said in (({"formats": "dwg"}, "unknown format 'dwg'"), ({"source": "best"}, "'source' is one of")):
        assert rm.serve(_preferring({"1": _model()}, **parameters), "objects/part/1") is None
        assert said in capsys.readouterr().err


def test_a_named_file_must_be_of_the_source_named():
    with pytest.raises(rm.SiteError, match="is a preview, not an original"):
        _preferring({"1": _with_preview()}).resolve("1", {"file": "preview-9", "source": "original"})


def test_a_search_names_only_what_the_preferences_take():
    site = _preferring({"1": _with_preview()}, source="preview")
    site.found = [rm.Model("1", title="Cable clip")]
    hits = site.get("search/part?q=clip")
    assert [config["type"] for config in hits.values()] == ["gltf"]


# --- search ------------------------------------------------------------------


def test_a_search_names_a_part_per_file_one_format_each():
    """'clip.step' and 'clip.stl' are one part in two formats; 'base.stl' is another."""
    site = Site({"1": _model()}, found=[rm.Model("1", title="Cable clip")])
    hits = site.get("search/part?q=clip")
    assert list(hits) == ["1;file=101", "1;file=102"]
    assert hits["1;file=101"]["type"] == "step"
    assert hits["1;file=102"]["desc"] == "Cable clip: base.stl"


def test_a_search_says_at_most_as_many_as_asked():
    site = Site({"1": _model(), "2": _model("2")}, found=[rm.Model("1"), rm.Model("2")])
    assert list(site.get("search/part?q=clip&limit=3")) == ["1;file=101", "1;file=102", "2;file=101"]


def test_a_model_with_no_file_partcad_reads_is_not_a_hit():
    site = Site(
        {"1": _model(names=("clip.skp", "clip.blend")), "2": _model("2")},
        found=[rm.Model("1"), rm.Model("2")],
    )
    assert list(site.get("search/part?q=clip")) == ["2;file=101", "2;file=102"]


def test_a_search_asks_for_more_models_than_hits_and_reads_only_as_many_as_it_needs():
    unreadable = {str(i): _model(str(i), names=("x.skp",)) for i in range(1, 6)}
    readable = {str(i): _model(str(i), names=("x.stl",)) for i in range(6, 40)}
    site = Site({**unreadable, **readable}, found=[rm.Model(str(i)) for i in range(1, 40)])
    site.search = lambda text, limit: site.found[:limit]

    hits = site.get("search/part?q=x&limit=3")

    assert list(hits) == ["6;file=100", "7;file=100", "8;file=100"]
    # Asked the site for three times as many, and read them a batch at a time.
    assert len(site.asked) == 8


def test_a_search_whose_finds_could_not_be_read_says_so(capsys):
    site = Site({}, found=[rm.Model("7", title="Gone")])
    assert site.get("search/part?q=x") == {}
    assert "1 model found for 'x' could not be read; the first: test: model 7: not found" in capsys.readouterr().err


def test_a_search_that_finds_nothing_says_nothing(capsys):
    assert Site({}, found=[]).get("search/part?q=x") == {}
    assert capsys.readouterr().err == ""


def test_an_empty_search_asks_nothing():
    site = Site({}, found=[rm.Model("1")])
    assert site.get("search/part?q=") == {}
    assert site.get("search/assembly?q=clip") == {}


# --- HTTP --------------------------------------------------------------------


class Wire:
    """Answers requests from a table: {url: (status, headers, body)}."""

    def __init__(self, table):
        self.table = table
        self.asked = []

    def __call__(self, url, headers=None, data=None, method=None, timeout=60):
        self.asked.append(url)
        status, response_headers, body = self.table[url]
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        return rm.Response(status, response_headers, body, url)


@pytest.fixture
def http(tmp_path, monkeypatch):
    monkeypatch.setenv("PARTCAD_TEST_CACHE", str(tmp_path))
    return rm.Http("test", "PartCAD-test")


def test_json_is_cached(http, monkeypatch):
    wire = Wire({"https://x/a": (200, {}, {"a": 1})})
    monkeypatch.setattr(http, "request", wire)
    assert http.json("https://x/a", "a") == {"a": 1}
    assert http.json("https://x/a", "a") == {"a": 1}
    assert wire.asked == ["https://x/a"]


def test_a_404_is_remembered(http, monkeypatch):
    wire = Wire({"https://x/a": (404, {}, b"no")})
    monkeypatch.setattr(http, "request", wire)
    for _ in range(2):
        with pytest.raises(rm.NotFound):
            http.json("https://x/a", "a")
    assert wire.asked == ["https://x/a"]


def test_a_bot_check_is_reported_as_one(http, monkeypatch):
    page = b"<html><title>Just a moment...</title><script src='/cdn-cgi/challenge-platform/x'></script>"
    monkeypatch.setattr(http, "request", Wire({"https://x/a": (403, {"cf-mitigated": "challenge"}, page)}))
    with pytest.raises(rm.Refused) as refused:
        http.json("https://x/a", "thing 1")
    assert "turned away by a Cloudflare bot check" in str(refused.value)
    assert "do not pretend to be a browser" in str(refused.value)


@pytest.mark.parametrize("status", [202, 405])
def test_an_aws_waf_challenge_is_a_bot_check_whatever_its_status(http, monkeypatch, status):
    """AWS WAF challenges with a 202 and an empty body, which would otherwise pass for an empty answer."""
    wire = Wire({"https://x/a": (status, {"x-amzn-waf-action": "challenge"}, b"")})
    monkeypatch.setattr(http, "request", wire)
    with pytest.raises(rm.Refused) as refused:
        http.json("https://x/a", "thing 1")
    assert "turned away by an AWS WAF bot check (challenge)" in str(refused.value)
    with pytest.raises(rm.Refused):
        http.probe("https://x/a", "thing 1")


def test_what_preview_means_is_the_sites_to_say():
    class Plain(rm.Site):
        NAME, TITLE = "plain", "Plain"

    class Own(rm.Site):
        NAME, TITLE = "own", "Own"
        PREVIEW_DESCRIPTION = "the GLB %s converts every model to, which needs a token"

    file = rm.File("1", "a.stl")
    file.format = "stl"
    assert "Plain's own mesh of it, coarser and needing no login" in Plain().parameters(file)["source"]["desc"]
    assert "the GLB Own converts every model to, which needs a token" in Own().parameters(file)["source"]["desc"]


def test_a_sign_in_that_is_wanted_is_not_remembered_as_missing(http, monkeypatch):
    wire = Wire({"https://x/a": (401, {}, b"{}")})
    monkeypatch.setattr(http, "request", wire)
    for _ in range(2):
        with pytest.raises(rm.NeedsCredentials):
            http.json("https://x/a", "a")
    assert len(wire.asked) == 2


def test_what_a_site_says_of_a_refusal_is_passed_on(http, monkeypatch):
    monkeypatch.setattr(http, "request", Wire({"https://x/a": (403, {}, {"code": 1, "error": "Token expired"})}))
    with pytest.raises(rm.NeedsCredentials) as refused:
        http.json("https://x/a", "a")
    assert "did not accept the one given (HTTP 403: Token expired)" in str(refused.value)


def test_credentials_stay_on_their_host():
    """A download link that redirects to a CDN does not take the token along."""
    import urllib.request

    handler = rm._SameHostRedirects()
    request = urllib.request.Request(
        "https://api.example.com/files/1", headers={"Authorization": "Bearer secret", "Cookie": "s=1"}
    )
    elsewhere = handler.redirect_request(request, None, 302, "Found", {}, "https://cdn.example.net/1.stl")
    assert elsewhere.get_header("Authorization") is None and elsewhere.get_header("Cookie") is None
    same = handler.redirect_request(request, None, 302, "Found", {}, "https://api.example.com/files/2")
    assert same.get_header("Authorization") == "Bearer secret"


def test_the_user_agent_says_what_it_is():
    agent = Site({}).http.user_agent
    assert "PartCAD-test" in agent and "compatible" in agent and "Chrome" not in agent


def test_a_credential_comes_from_the_parameter_then_the_environment(monkeypatch):
    monkeypatch.setenv("TEST_TOKEN", "from-env")
    assert rm.credential({"parameters": {"token": "from-param"}}, "token", "TEST_TOKEN") == "from-param"
    assert rm.credential({"parameters": {"token": ""}}, "token", "TEST_TOKEN") == "from-env"
    monkeypatch.delenv("TEST_TOKEN")
    assert rm.credential({}, "token", "TEST_TOKEN") == ""


def test_a_member_of_an_archive_is_found_by_its_name():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("files/Clip.STL", b"solid")
    assert rm.read_zip_member(buffer.getvalue(), "Clip.STL") == b"solid"
    assert rm.read_zip_member(buffer.getvalue(), "clip.stl") == b"solid"
    assert rm.read_zip_member(buffer.getvalue(), "other.stl") is None


# --- logging in ----------------------------------------------------------------


class BrowserNeeded(BaseException):
    """What PartCAD's callback raises the first time: not an Exception, so nothing in the plugin catches it."""


class Callback:
    """PartCAD's 'partcad_login', replaying: raises the first time, returns what the browser sent after."""

    def __init__(self, results=()):
        self.results = list(results)
        self.calls = []

    def open_browser(self, **spec):
        self.calls.append(spec)
        if len(self.calls) > len(self.results):
            raise BrowserNeeded(spec)
        return self.results[len(self.calls) - 1]


class LoginSite(Site):
    CREDENTIALS = {"token": "TEST_TOKEN"}

    def __init__(self, token="", accepted=("good",), unreachable=False):
        super().__init__({})
        self.request = {"parameters": {"token": token}}
        self.accepted = accepted
        self.unreachable = unreachable
        self.asked = []

    def whoami(self, credentials):
        self.asked.append(credentials["token"])
        if self.unreachable:
            raise rm.Refused("test: turned away")
        return "ann" if credentials["token"] in self.accepted else None

    def login_spec(self):
        return {"url": "https://example.com/login", "title": "Log in", "capture": [{"name": "token"}]}


@pytest.fixture
def no_token(monkeypatch):
    monkeypatch.delenv("TEST_TOKEN", raising=False)


def test_credentials_the_site_takes_are_returned_without_a_browser(no_token):
    callback = Callback()
    result = rm.login(LoginSite(token="good"), callback)
    assert result == {"parameters": {"token": "good"}, "message": "Already logged in to Test as ann"}
    assert callback.calls == []


def test_without_credentials_the_browser_is_asked_for_and_the_plugin_stops_there(no_token):
    callback = Callback()
    with pytest.raises(BrowserNeeded):
        rm.login(LoginSite(), callback)
    assert callback.calls[0]["url"] == "https://example.com/login"


def test_stale_credentials_are_replaced_by_what_the_browser_brings_back(no_token):
    site = LoginSite(token="stale")
    result = rm.login(site, Callback([{"token": " good "}]))
    assert result == {"parameters": {"token": "good"}, "message": "Logged in to Test as ann"}
    assert site.asked == ["stale", "good"]


def test_what_the_site_does_not_take_fails_the_login(no_token):
    with pytest.raises(RuntimeError, match="does not take what the login captured"):
        rm.login(LoginSite(), Callback([{"token": "bad"}]))
    with pytest.raises(RuntimeError, match="came back with nothing"):
        rm.login(LoginSite(), Callback([{"token": ""}]))


def test_fresh_credentials_that_cannot_be_checked_are_saved_and_said_so(no_token):
    result = rm.login(LoginSite(unreachable=True), Callback([{"token": "new"}]))
    assert result["parameters"] == {"token": "new"}
    assert "could not be checked from here" in result["message"]


def test_saved_credentials_that_cannot_be_checked_are_not_taken_for_rejected_ones(no_token):
    with pytest.raises(RuntimeError, match="turned away"):
        rm.login(LoginSite(token="maybe", unreachable=True), Callback())


class AgentCallback(Callback):
    """'partcad_login' of 'pc login --agent': nobody at the screen."""

    non_interactive = True


def test_with_nobody_at_the_screen_the_browser_request_carries_instructions(no_token):
    class Site_(LoginSite):
        LOGIN_INSTRUCTIONS = "Or make an API key at https://example.com/keys."

    site, callback = Site_(), AgentCallback()
    with pytest.raises(BrowserNeeded):
        rm.login(site, callback)
    assert site.non_interactive is True
    text = callback.calls[0]["instructions"]
    assert text.startswith("Or make an API key at https://example.com/keys.")
    assert "TEST_TOKEN" in text and "'token'" in text


def test_an_older_partcad_is_not_handed_instructions(no_token):
    callback = Callback()
    with pytest.raises(BrowserNeeded):
        rm.login(LoginSite(), callback)
    assert "instructions" not in callback.calls[0]


def test_a_partcad_without_login_is_told_to_upgrade():
    with pytest.raises(RuntimeError, match="upgrade PartCAD"):
        rm.login(LoginSite(), None)


def test_the_environment_counts_as_credentials(monkeypatch):
    monkeypatch.setenv("TEST_TOKEN", "good")
    site = LoginSite()
    site.request = {"parameters": {}}
    assert rm.login(site, Callback())["parameters"] == {"token": "good"}


def test_a_probe_tells_a_refusal_from_a_bot_check(http, monkeypatch):
    monkeypatch.setattr(http, "request", Wire({"https://x/me": (401, {}, {"error": "no"})}))
    assert http.probe("https://x/me", "me") == (401, {"error": "no"})
    monkeypatch.setattr(http, "request", Wire({"https://x/me": (403, {"cf-mitigated": "challenge"}, b"")}))
    with pytest.raises(rm.Refused):
        http.probe("https://x/me", "me")


def test_a_graphql_failure_is_said_in_its_own_words_and_not_kept(http, monkeypatch):
    wire = Wire({"https://x/q": (200, {}, {"errors": [{"message": "Cannot query field 'x'"}], "data": None})})
    monkeypatch.setattr(http, "request", wire)
    for _ in range(2):
        http.json("https://x/q", "q", valid=lambda value: not value.get("errors"))
    assert len(wire.asked) == 2
    monkeypatch.setattr(http, "request", Wire({"https://x/e": (400, {}, {"errors": [{"message": "Bad field"}]})}))
    with pytest.raises(rm.SiteError, match="HTTP 400: Bad field"):
        http.json("https://x/e", "e")


def test_two_accounts_on_one_machine_see_their_own_answers(http, monkeypatch):
    wire = Wire({"https://x/mine": (200, {}, {"mine": True})})
    monkeypatch.setattr(http, "request", wire)
    http.json("https://x/mine", "mine", headers={"Authorization": "Bearer ann"})
    http.json("https://x/mine", "mine", headers={"Authorization": "Bearer bob"})
    http.json("https://x/mine", "mine", headers={"Authorization": "Bearer ann", "Accept": "x"})
    assert len(wire.asked) == 2


def test_a_model_that_is_found_and_not_served_is_listed_when_the_site_says_why():
    class Selling(Site):
        def unserved(self, model):
            return "on sale; this site gives nobody another user's files"

    site = Selling({"1": _model(names=("x.skp",))}, found=[rm.Model("1")])
    assert site.get("search/part?q=x") == {
        "1": {
            "desc": "Cable clip (on sale; this site gives nobody another user's files)",
            "url": "https://example.com/1",
        }
    }


# --- held to the rest of PartCAD ------------------------------------------------------


def test_every_format_offered_is_a_part_type_partcad_builds_from_that_file():
    from partcad_client import object_types

    for name, part_type, extensions in rm.FORMATS:
        known = object_types.part_type_extensions(part_type)
        assert known, "%s: PartCAD has no part type '%s'" % (name, part_type)
        assert extensions[0] in known, "%s: '.%s' is not a file of '%s' (%s)" % (name, extensions[0], part_type, known)


def test_every_native_format_partcad_reads_is_offered():
    """A reader added to '//builtin/import' is a format a model site's files may come in: offer it."""
    from partcad_client import object_types

    offered = {part_type for _, part_type, _ in rm.FORMATS}
    missing = sorted(set(object_types.BUILTIN_PART_TYPE_EXTENSION) - offered)
    assert not missing, "plugin_models.FORMATS does not offer: %s" % ", ".join(missing)


def test_the_characters_a_name_reserves_are_partcads():
    from partcad_utils import utils

    assert rm.RESERVED_IN_NAMES == utils.RESERVED_IN_NAMES


@pytest.mark.parametrize(
    "parameters",
    [
        {"file": "1234567"},
        {"file": "clip;v2.stl", "format": "stl"},
        {"file": "a,b=c.stl"},
        {"file": "a,b.stl"},
        {"file": "100%25 done.stl"},
        {"file": "x#1?.stl", "source": "preview"},
    ],
)
def test_a_name_written_here_is_read_by_partcad_as_it_was_meant(parameters):
    from partcad_utils import utils

    name = rm.format_name("763622", parameters)
    assert name == utils.format_parameterized_name("763622", parameters)
    assert utils.parse_parameterized_name(name) == ("763622", parameters)
    assert rm.parse_name(name) == ("763622", parameters)


def test_a_site_reads_the_key_taken_apart_when_partcad_sends_it():
    asked = []

    class Site(rm.Site):
        NAME, TITLE = "test", "Test"

        def resolve(self, base, parameters):
            asked.append((base, parameters))
            return {"type": "stl"}

    key = "objects/part/763622;file=clip%3Bv2.stl"
    query = {"what": "object", "kind": "part", "name": "763622", "parameters": {"file": "clip;v2.stl"}}
    assert Site({"key": key, "query": query}).get(key) == {"type": "stl"}
    # Asked by key alone, it takes the key apart the same way.
    assert Site({"key": key}).get(key) == {"type": "stl"}
    # A query for another key is not this one's.
    Site({"key": "objects/part/1", "query": dict(query, name="1")}).get(key)
    assert asked == [("763622", {"file": "clip;v2.stl"})] * 3


def test_a_key_is_taken_apart_here_as_partcad_takes_it_apart():
    """The fallback for a PartCAD that sends no query reads every key the way PartCAD would have sent it."""
    from partcad.project_external_repository import query_of

    for key in [
        "meta",
        "deps",
        "objects/part",
        "objects/part/763622",
        "objects/part/763622;file=a%2Cb=c.stl,format=stl",
        "objects/sketch/1",
        "search/part?q=hinge",
        "search/part?q=hinge%20clip&limit=7",
        "search/part?q=&limit=x",
        "files/models/1/clip.stl",
    ]:
        assert rm.query_of(key) == query_of(key), key


def test_a_package_scoped_to_a_subfolder_is_answered_from_the_query():
    """A subfolder prefixes the key and not the query: every key is read from the query when there is one."""
    asked = []

    class Site(rm.Site):
        NAME, TITLE = "test", "Test"

        def find(self, text, limit=None):
            asked.append(("find", text, limit))
            return {"1;file=101": {"type": "stl"}}

        def resolve(self, base, parameters):
            asked.append(("resolve", base, parameters))
            return {"type": "stl"}

        def file(self, path):
            asked.append(("file", path))
            return "Zm9v"

    def get(key, query):
        return Site({"key": key, "query": dict(query, subfolder="motors")}).get(key)

    assert get("motors/meta", {"what": "meta"})["searchKinds"] == ["part"]
    assert get("motors/deps", {"what": "deps"}) == []
    assert get("motors/objects/part", {"what": "objects", "kind": "part"}) == {}
    assert get("motors/search/part?q=clip&limit=3", {"what": "search", "kind": "part", "text": "clip", "limit": 3})
    assert get("motors/objects/part/1", {"what": "object", "kind": "part", "name": "1", "parameters": {}})
    assert get("motors/files/a/b.stl", {"what": "file", "path": "a/b.stl"}) == "Zm9v"
    assert asked == [("find", "clip", 3), ("resolve", "1", {}), ("file", "a/b.stl")]


def test_threads_storing_one_key_at_once_each_store_it_whole(http):
    """A search reads models on a pool of threads, and two of them can store one key."""
    import concurrent.futures

    contents = [bytes([i]) * 65536 for i in range(16)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda content: http._remember("json", "https://x/shared", content), contents * 4))
    path = http._path("json", "https://x/shared")
    with open(path, "rb") as f:
        assert f.read() in contents
    assert [name for name in os.listdir(os.path.dirname(path)) if name.endswith(".tmp")] == []


def test_a_cache_that_cannot_be_written_costs_a_miss_not_the_answer(tmp_path, monkeypatch):
    """A read-only home in a sandbox, a full disk: the site answered, and that answer is what was asked for."""
    blocked = tmp_path / "cache"
    blocked.write_text("a file where the cache directory should be")
    monkeypatch.setenv("PARTCAD_TEST_CACHE", str(blocked))
    http = rm.Http("test", "PartCAD-test")
    wire = Wire({"https://x/a": (200, {}, {"a": 1})})
    monkeypatch.setattr(http, "request", wire)
    assert http.json("https://x/a", "a") == {"a": 1}
    assert http.json("https://x/a", "a") == {"a": 1}
    assert wire.asked == ["https://x/a", "https://x/a"]


@pytest.mark.parametrize("model_id", ["763622", "bolt-m8_1", "_leading", "a/b c:\u00fc", "x" * 201])
def test_a_file_is_served_whatever_its_model_is_called(model_id):
    """The path a part names carries its model's id back to the site, whatever characters it holds."""

    class AnyId(Site):
        def valid_id(self, model_id):
            return True

    site = AnyId({model_id: _model(model_id)})
    path = site.resolve(model_id, {"file": "base.stl"})["path"]
    assert base64.b64decode(site.get("files/" + path)) == ("%s/base.stl" % model_id).encode()
    # The ids the sites have - digits and slugs - are spelled as they were.
    if model_id in ("763622", "bolt-m8_1"):
        assert path.startswith(model_id + "/")
