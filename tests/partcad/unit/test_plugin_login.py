#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A plugin's 'login', through the sandbox it really runs in.

Every kind of plugin PartCAD runs a script for may answer 'login' (see
'Plugin.login' and 'wrappers/plugin_login.py'): a repository and a provider are
both tried here, each with a script that checks the token it has and otherwise
asks for the browser through 'partcad_login.open_browser' - which does not
return the first time, but comes back as a browser step, and returns what the
browser brought when PartCAD runs it again.
"""

import asyncio
import textwrap

import pytest

import partcad as pc
from partcad.plugin import LoginUnsupported

SCRIPT = textwrap.dedent("""
    def login(request, partcad_login):
        token = request["parameters"].get("token")
        if token == "good":
            return {"parameters": {"token": token}, "message": "already in"}
        try:
            got = partcad_login.open_browser(
                url="https://example.com/login",
                title="Example",
                capture=[{"name": "token", "cookie": {"url": "https://example.com/", "name": "t"}}],
            )
        except Exception:
            # The signal to open the browser is not an Exception, so a plugin
            # that catches everything still lets it through.
            raise
        if got.get("token") != "good":
            raise RuntimeError("the site did not take %r" % got.get("token"))
        return {"parameters": {"token": got["token"]}, "message": "logged in"}

    if __name__ == "login":
        output = {"result": login(request, partcad_login)}
    elif __name__ == "get":
        output = {"result": None}
    else:
        output = {}
    """)

PACKAGE = textwrap.dedent("""
    name: //login_test
    repositories:
      auth_repo:
        type: basic
        path: auth.py
        parameters:
          token:
            type: string
            default: "{token}"
      plain_repo:
        type: basic
        path: plain.py
    providers:
      auth_store:
        type: store
        path: auth.py
        parameters:
          token:
            type: string
            default: "{token}"
    """)


def _context(tmp_path, token=""):
    (tmp_path / "partcad.yaml").write_text(PACKAGE.format(token=token))
    (tmp_path / "auth.py").write_text(SCRIPT)
    (tmp_path / "plain.py").write_text('output = {"result": None} if __name__ == "get" else {}\n')
    return pc.Context(str(tmp_path))


@pytest.mark.parametrize("kind", ["repository", "provider"])
def test_without_credentials_the_plugin_asks_for_the_browser_then_takes_what_it_brought(tmp_path, kind):
    ctx = _context(tmp_path)
    project = ctx.get_project("//")
    plugin = project.get_repository("auth_repo") if kind == "repository" else project.get_provider("auth_store")

    step = asyncio.run(plugin.login())
    assert step == {
        "browser": {
            "url": "https://example.com/login",
            "title": "Example",
            "capture": [{"name": "token", "cookie": {"url": "https://example.com/", "name": "t"}}],
            "require": "all",
            "guide": [],
            "timeout": 600,
        }
    }

    done = asyncio.run(plugin.login(browser=[{"token": "good"}]))
    assert done == {"parameters": {"token": "good"}, "message": "logged in"}


def test_credentials_that_work_need_no_browser(tmp_path):
    ctx = _context(tmp_path, token="good")
    repository = ctx.get_project("//").get_repository("auth_repo")
    assert asyncio.run(repository.login()) == {"parameters": {"token": "good"}, "message": "already in"}


def test_a_check_that_would_need_the_browser_fails(tmp_path):
    ctx = _context(tmp_path)
    repository = ctx.get_project("//").get_repository("auth_repo")
    with pytest.raises(RuntimeError, match="logging in failed"):
        asyncio.run(repository.login(interactive=False))


def test_what_the_site_did_not_take_fails_the_login(tmp_path):
    ctx = _context(tmp_path)
    repository = ctx.get_project("//").get_repository("auth_repo")
    with pytest.raises(RuntimeError, match="logging in failed"):
        asyncio.run(repository.login(browser=[{"token": "bad"}]))


def test_a_script_with_no_login_says_so(tmp_path):
    ctx = _context(tmp_path)
    repository = ctx.get_project("//").get_repository("plain_repo")
    with pytest.raises(LoginUnsupported, match="has no login method"):
        asyncio.run(repository.login())


def test_a_spec_is_checked_in_the_plugin_and_says_what_is_wrong():
    """Run where the plugin runs, so a malformed request is the plugin's error, named."""
    import sys

    sys.path.insert(0, str(__import__("pathlib").Path(pc.__file__).parent / "wrappers"))
    import plugin_login

    capture = [{"name": "t", "cookie": {"url": "https://x/", "name": "t"}}]
    spec = plugin_login.browser_spec(
        "https://x/login",
        [{"name": "t", "cookie": {"url": "https://x/", "name": "t", "match": "^a"}}],
        guide=[{"url": "https://x/*", "selector": "button", "contains": "log ?in", "text": "Sign in"}],
    )
    # 'match' written inside the source is moved beside it, where the extension reads it.
    assert spec["capture"] == [{"name": "t", "cookie": {"url": "https://x/", "name": "t"}, "match": "^a"}]
    for bad, message in (
        ({"capture": [{"name": "t"}]}, "exactly one of"),
        ({"capture": capture + capture}, "two captures have one name"),
        ({"capture": [dict(capture[0], match="(")]}, "not a regular expression"),
        (
            {"capture": capture, "guide": [{"url": "https://x/*", "selector": "b", "text": "t", "contains": "["}]},
            "contains",
        ),
        ({"capture": capture, "require": "some"}, "'require'"),
        ({"capture": capture, "done_when": {"url": "https://x/*", "fetch": {}}}, "exactly one of"),
    ):
        with pytest.raises(ValueError, match=message):
            plugin_login.browser_spec("https://x/login", **bad)
