#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'pc login' on the client: the listener the extension reports to, the loop of steps, the saved credentials."""

import json
import os
import re
import stat
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

from partcad_client import login as pc_login
from partcad_utils.user_config import save_parameter_overrides

SPEC = {
    "url": "https://example.com/login",
    "title": "Example",
    "capture": [
        {"name": "token", "cookie": {"url": "https://example.com/", "name": "t"}},
        {"name": "key", "ask": {"label": "Your API key", "secret": False}},
    ],
    "require": "all",
    "guide": [],
    "timeout": 600,
}


def _get(url, headers=None):
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=10) as answer:
        return answer.status, answer.read().decode("utf-8")


@pytest.fixture
def listener():
    with pc_login.LoginListener() as running:
        yield running


def test_the_start_page_hands_the_extension_the_spec_and_where_to_report(listener):
    step = listener.step(SPEC)
    status, page = _get(listener.start_url(step))
    assert status == 200
    found = re.search(r"<script type='application/json' id='partcad-login-spec'>(.*?)</script>", page, re.S)
    spec = json.loads(found.group(1))
    assert spec["url"] == "https://example.com/login"
    assert spec["callback"] == "http://127.0.0.1:%d/partcad/login/%s/done" % (listener.port, step.nonce)
    assert spec["manual"].endswith("/manual") and spec["cancel"].endswith("/cancel")


def test_a_spec_cannot_end_the_script_element_it_is_in(listener):
    step = listener.step(dict(SPEC, title="</script><script>alert(1)</script>"))
    _, page = _get(listener.start_url(step))
    assert page.count("</script>") == 1


def test_what_the_extension_sends_is_what_the_wait_returns(listener):
    step = listener.step(SPEC)
    query = urllib.parse.urlencode({"token": "abc", "key": "k=1&2", "other": "not asked for"})
    status, body = _get(
        "http://127.0.0.1:%d/partcad/login/%s/done?%s" % (listener.port, step.nonce, query),
        {"Accept": "application/json"},
    )
    assert (status, json.loads(body)) == (200, {"ok": True})
    assert listener.wait(step, 5) == {"token": "abc", "key": "k=1&2"}


def test_the_manual_page_asks_for_every_capture_and_submits_to_the_listener(listener):
    step = listener.step(SPEC)
    _, page = _get(listener.manual_url(step))
    assert "name='token'" in page and "name='key'" in page and "Your API key" in page
    assert "action='http://127.0.0.1:%d/partcad/login/%s/done'" % (listener.port, step.nonce) in page


def test_a_cancel_stops_the_wait(listener):
    step = listener.step(SPEC)
    _get("http://127.0.0.1:%d/partcad/login/%s/cancel" % (listener.port, step.nonce))
    with pytest.raises(pc_login.LoginCancelled):
        listener.wait(step, 5)


def test_nothing_coming_back_is_a_timeout(listener):
    with pytest.raises(pc_login.LoginTimedOut):
        listener.wait(listener.step(SPEC), 0.2)


def test_another_nonce_or_another_host_is_refused(listener):
    step = listener.step(SPEC)
    with pytest.raises(urllib.error.HTTPError) as missing:
        _get("http://127.0.0.1:%d/partcad/login/%s/start" % (listener.port, "0" * 32))
    assert missing.value.code == 404
    with pytest.raises(urllib.error.HTTPError) as rebound:
        _get(listener.start_url(step), {"Host": "evil.example:%d" % listener.port})
    assert rebound.value.code == 403


# --- the loop --------------------------------------------------------------------------


class _Opened:
    browser = "a browser"

    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _extension(values):
    """A stand-in for the browser with the extension in it: it reports 'values' as soon as it is opened."""
    opened = []

    def open_browser(url, spec):
        done = url.replace("/start", "/done") + "?" + urllib.parse.urlencode(values)
        threading.Thread(target=_get, args=(done,), daemon=True).start()
        opened.append(_Opened())
        return opened[-1]

    return open_browser, opened


def test_a_login_that_needs_the_browser_goes_round_once(monkeypatch):
    monkeypatch.setattr(pc_login.time, "sleep", lambda seconds: None)
    asked = []

    def ask(results, interactive):
        asked.append(list(results))
        if not results:
            return {"plugin": "//p:r", "status": "browser", "spec": SPEC}
        return {"plugin": "//p:r", "status": "done", "parameters": {"token": results[0]["token"]}, "message": "ok"}

    open_browser, opened = _extension({"token": "abc", "key": "k"})
    said = []
    answer = pc_login.login(ask, open_browser, said.append)

    assert answer["parameters"] == {"token": "abc"}
    assert asked == [[], [{"token": "abc", "key": "k"}]]
    assert opened[0].closed
    assert "sign in there" in said[0]


def test_without_a_browser_the_user_is_sent_to_the_manual_page():
    said = []

    def ask(results, interactive):
        return {"status": "browser", "spec": dict(SPEC, timeout=10)}

    def no_browser(url, spec):
        return None

    with pytest.raises(pc_login.LoginTimedOut):
        pc_login.login(ask, no_browser, said.append, timeout=0.2)
    assert "/manual" in said[0] and "enter what it asks for" in said[0]


def test_a_failed_step_fails_the_login():
    with pytest.raises(RuntimeError, match="no login method"):
        pc_login.login(lambda r, i: {"status": "failed", "message": "no login method"}, None, print)


def test_a_plugin_that_is_never_satisfied_is_stopped(monkeypatch):
    monkeypatch.setattr(pc_login.time, "sleep", lambda seconds: None)
    open_browser, _ = _extension({"token": "x"})
    with pytest.raises(RuntimeError, match="asked for the browser 5 times"):
        pc_login.login(lambda r, i: {"status": "browser", "spec": SPEC}, open_browser, lambda m: None)


# --- what is kept ----------------------------------------------------------------------


def test_the_credentials_are_saved_as_overrides_and_nothing_else_moves(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "# my settings\nthreadsMax: 4  # keep\nparameters:\n  //other:thing:\n    size: 3\n", encoding="utf-8"
    )
    save_parameter_overrides("//pub/universe/grabcad:grabcad_repo", {"session": "abc"}, str(path))
    save_parameter_overrides("//pub/universe/grabcad:grabcad_repo", {"session": "def"}, str(path))

    text = path.read_text(encoding="utf-8")
    assert "# my settings" in text and "threadsMax: 4  # keep" in text
    import yaml

    document = yaml.safe_load(text)
    assert document["parameters"] == {
        "//other:thing": {"size": 3},
        "//pub/universe/grabcad:grabcad_repo": {"session": "def"},
    }
    if os.name == "posix":
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_a_missing_configuration_file_is_made(tmp_path):
    path = tmp_path / "new" / "config.yaml"
    save_parameter_overrides("//p:r", {"token": "t"}, str(path))
    import yaml

    assert yaml.safe_load(path.read_text()) == {"parameters": {"//p:r": {"token": "t"}}}


def test_the_saved_overrides_reach_the_plugin_the_way_hand_written_ones_do(tmp_path, monkeypatch):
    """Read back through the configuration PartCAD builds, under the name a plugin's overrides are looked up by."""
    monkeypatch.setenv("HOME", str(tmp_path))
    from partcad_utils.user_config import UserConfig

    save_parameter_overrides("//p:repo", {"token": "t"})
    assert UserConfig().parameter_config.to_dict()["//p:repo"] == {"token": "t"}


def test_a_step_that_is_over_no_longer_has_a_start_page(listener):
    """The extension asks an earlier step's start page whether its login still waits."""
    step = listener.step(SPEC)
    assert _get(listener.start_url(step))[0] == 200
    _get("http://127.0.0.1:%d/partcad/login/%s/done?token=t" % (listener.port, step.nonce))
    with pytest.raises(urllib.error.HTTPError) as gone:
        _get(listener.start_url(step))
    assert gone.value.code == 404
