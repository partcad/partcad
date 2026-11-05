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
import re
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
        asyncio.run(repository.login(check=True))


def test_with_nobody_to_use_a_browser_the_plugin_answers_with_what_to_do(tmp_path):
    ctx = _context(tmp_path)
    repository = ctx.get_project("//").get_repository("auth_repo")
    step = asyncio.run(repository.login(non_interactive=True))
    assert step["instructions"]["url"] == "https://example.com/login"
    assert step["instructions"]["capture"][0]["name"] == "token"


@pytest.mark.parametrize("non_interactive", [False, True])
def test_values_handed_over_answer_the_browser_and_are_checked_like_it(tmp_path, non_interactive):
    ctx = _context(tmp_path)
    repository = ctx.get_project("//").get_repository("auth_repo")
    done = asyncio.run(repository.login(non_interactive=non_interactive, values={"token": "good"}))
    assert done == {"parameters": {"token": "good"}, "message": "logged in"}
    with pytest.raises(RuntimeError, match="logging in failed"):
        asyncio.run(repository.login(non_interactive=non_interactive, values={"token": "bad"}))


def test_a_plugin_may_say_what_to_do_itself(tmp_path):
    (tmp_path / "partcad.yaml").write_text("name: //t\nrepositories:\n  r:\n    type: basic\n    path: r.py\n")
    (tmp_path / "r.py").write_text(
        'if __name__ == "login":\n'
        "    assert partcad_login.non_interactive\n"
        '    output = {"result": {"instructions": "Make a key at https://x/keys."}}\n'
        "else:\n    output = {}\n"
    )
    repository = pc.Context(str(tmp_path)).get_project("//").get_repository("r")
    step = asyncio.run(repository.login(non_interactive=True))
    assert step["instructions"]["instructions"] == "Make a key at https://x/keys."


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
    assert "instructions" not in spec
    assert plugin_login.browser_spec("https://x/l", capture, instructions=" Or a key. ")["instructions"] == "Or a key."

    # What to do without a browser goes to whoever has none, never to the browser.
    asked = dict(capture=capture, instructions="Or a key.")
    with pytest.raises(plugin_login.BrowserNeeded) as browser:
        plugin_login.LoginCallback({}).open_browser("https://x/l", **asked)
    assert "instructions" not in browser.value.spec
    with pytest.raises(plugin_login.InstructionsNeeded) as instructions:
        plugin_login.LoginCallback({"non_interactive": True}).open_browser("https://x/l", **asked)
    assert instructions.value.spec["instructions"] == "Or a key."

    # What '--set' hands over answers a call only when it is enough for it.
    two = capture + [{"name": "u", "cookie": {"url": "https://x/", "name": "u"}}]
    callback = plugin_login.LoginCallback({"values": {"t": "1"}, "non_interactive": True})
    assert callback.open_browser("https://x/l", two, require="any") == {"t": "1"}
    with pytest.raises(plugin_login.InstructionsNeeded):
        callback.open_browser("https://x/l", two)
    with pytest.raises(plugin_login.CheckOnly):
        plugin_login.LoginCallback({"check": True, "non_interactive": True}).open_browser("https://x/l", capture)
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


@pytest.mark.parametrize(
    "pattern",
    [r"^\s*log ?in\s*$", r"(?:a|b)+", r"x(?=y)", r"(?<!a)b", r"[(?i)]", r"\(?x", r"[]a]+", r"^[A-Za-z0-9_-]{16,}$"],
)
def test_a_pattern_both_languages_read_alike_is_taken(pattern):
    import sys

    sys.path.insert(0, str(__import__("pathlib").Path(pc.__file__).parent / "wrappers"))
    import plugin_login

    capture = [{"name": "t", "cookie": {"url": "https://x/", "name": "t"}, "match": pattern}]
    assert plugin_login.browser_spec("https://x/l", capture)["capture"][0]["match"] == pattern


@pytest.mark.parametrize(
    "pattern, said",
    [
        (r"(?i)token", "(?i)"),
        (r"(?P<n>x)", "(?P<"),
        (r"(?#note)x", "(?#n"),
        (r"(?>ab)", "(?>a"),
        (r"\Atoken\Z", "anchor"),
        (r"a++", "possessive"),
    ],
)
def test_a_pattern_only_python_reads_is_refused_before_the_browser_is(pattern, said):
    """The extension compiles it with JavaScript's RegExp, and would refuse it after the user was sent there."""
    import sys

    sys.path.insert(0, str(__import__("pathlib").Path(pc.__file__).parent / "wrappers"))
    import plugin_login

    try:
        re.compile(pattern)
    except re.error:
        # Atomic groups and possessive quantifiers came to Python in 3.11: an
        # older one refuses them itself, before the extension's syntax is asked.
        expected, said = "not a regular expression", ""
    else:
        expected = "JavaScript"

    capture = [{"name": "t", "cookie": {"url": "https://x/", "name": "t"}, "match": pattern}]
    with pytest.raises(ValueError, match=expected) as refused:
        plugin_login.browser_spec("https://x/l", capture)
    assert said in str(refused.value)
