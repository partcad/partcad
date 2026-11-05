#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""PartCAD's side of a plugin's 'login', inside the sandbox: the 'partcad_login' callback.

A plugin of any kind may answer the 'login' api (see 'pc login' and the
"Logging in" section of the plugin documentation). It is run with this object
in its globals as 'partcad_login', and the one thing it is for is
'open_browser': open the user's browser on a page of the site - in PartCAD's own
profile, with PartCAD's extension in it - and come back with what signing in
there left behind, a cookie, a token in storage, an API key on a page.

Where there is nobody to use a browser - an AI agent ran 'pc login --agent',
or called the login tool of 'pc mcp' - 'partcad_login.non_interactive' is
true, and 'open_browser' does not open anything: it raises
'InstructionsNeeded', and PartCAD prints, from what it was asked, what a
person would have done in the browser and how to hand the result over
('pc login --agent <plugin> --set <name>=<value>'). A plugin that knows better
ways in - an API key, an application of one's own, an environment variable -
says so in 'open_browser(instructions=...)', or answers {"instructions": "..."}
itself rather than calling it. Values handed over with '--set' answer the
call that asks for them, in either mode, and the plugin checks them as it
would what the browser brought.

The browser is on the machine of whoever ran 'pc login', and this runs in a
sandbox that may be on another one, so the call cannot simply wait for it.
It is a replay instead. The first time 'open_browser' is called it raises
'BrowserNeeded', carrying what the browser is to do; PartCAD does it, and runs
'login' again from the top with the result to hand, when the same call
returns it. The n-th call returns the n-th result. So a 'login' has to be the
same up to each call - which checking credentials and building a URL are.

'BrowserNeeded' is a 'BaseException', for the same reason 'KeyboardInterrupt'
is one: it is not a failure, and a plugin's 'except Exception' around its
whole body must not turn it into one.
"""

import re

# Where a capture's value may come from (see the documentation of 'open_browser').
CAPTURE_SOURCES = ("cookie", "localStorage", "sessionStorage", "dom", "redirect", "ask")
DONE_WHEN = ("url", "selector", "fetch")
REQUIRE = ("all", "any")
# How long a browser step may take, in seconds: long enough to sign up as well
# as sign in, and not so long that a forgotten window holds 'pc login' for a day.
MIN_TIMEOUT = 10
MAX_TIMEOUT = 3600
DEFAULT_TIMEOUT = 600


class BrowserNeeded(BaseException):
    """The plugin asked for the browser: PartCAD is to open it as 'spec' says, and run 'login' again."""

    def __init__(self, spec):
        super().__init__("the browser is needed: %s" % spec.get("url"))
        self.spec = spec


class InstructionsNeeded(BaseException):
    """The plugin asked for the browser where nobody is there to use one: PartCAD is to say what to do instead.

    'spec' is what the browser would have been asked, 'instructions' and all.
    A 'BaseException' like 'BrowserNeeded', and for the same reason.
    """

    def __init__(self, spec):
        super().__init__("the browser is needed, and there is nobody to use it: %s" % spec.get("url"))
        self.spec = spec


class CheckOnly(Exception):
    """The browser was asked for during a check ('pc login --check'), which opens nothing."""


def _string(value, what):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("open_browser: %s must be a non-empty string, not %r" % (what, value))
    return value


def _pattern(value, what):
    """A regular expression: 'match' on a capture, 'contains' on a guide step (the element's text)."""
    _string(value, what)
    try:
        re.compile(value)
    except re.error as e:
        raise ValueError("open_browser: %s is not a regular expression: %s" % (what, e))
    return value


def _url(value, what):
    _string(value, what)
    if not value.startswith(("https://", "http://")):
        raise ValueError("open_browser: %s must be an http(s) URL or pattern, not %r" % (what, value))
    return value


def _capture(item, index):
    if not isinstance(item, dict):
        raise ValueError("open_browser: capture[%d] must be a mapping" % index)
    _string(item.get("name"), "capture[%d].name" % index)
    sources = [key for key in CAPTURE_SOURCES if key in item]
    if len(sources) != 1:
        raise ValueError(
            "open_browser: capture '%s' must name exactly one of %s, not %s"
            % (item["name"], ", ".join(CAPTURE_SOURCES), ", ".join(sources) or "none")
        )
    source = item[sources[0]]
    if not isinstance(source, dict):
        raise ValueError("open_browser: capture '%s': '%s' must be a mapping" % (item["name"], sources[0]))
    where = "capture '%s'" % item["name"]
    if sources[0] == "cookie":
        _url(source.get("url"), where + ".cookie.url")
        _string(source.get("name"), where + ".cookie.name")
    elif sources[0] in ("localStorage", "sessionStorage"):
        _url(source.get("origin"), "%s.%s.origin" % (where, sources[0]))
        _string(source.get("key"), "%s.%s.key" % (where, sources[0]))
    elif sources[0] == "dom":
        _url(source.get("url"), where + ".dom.url")
        _string(source.get("selector"), where + ".dom.selector")
    elif sources[0] == "redirect":
        _url(source.get("url"), where + ".redirect.url")
        _string(source.get("param"), where + ".redirect.param")
    elif sources[0] == "ask":
        _string(source.get("label"), where + ".ask.label")
    # 'match' belongs beside the source, which is where the extension reads it;
    # one written inside the source is moved there, so either spelling works.
    if "match" in source and "match" not in item:
        item = dict(item)
        item[sources[0]] = {k: v for k, v in source.items() if k != "match"}
        item["match"] = source["match"]
    if "match" in item:
        _pattern(item["match"], where + ".match")
    return item


def browser_spec(
    url, capture, title=None, guide=None, require="all", done_when=None, timeout=DEFAULT_TIMEOUT, instructions=None
):
    """What 'open_browser' was asked, checked and as it travels: a mapping of plain values.

    Checked here, in the plugin's own run, so that a malformed request is the
    plugin's error, reported with its name, rather than a browser that opens
    and then waits for something it was never told how to find.
    """
    _url(url, "url")
    if not isinstance(capture, (list, tuple)) or not capture:
        raise ValueError("open_browser: 'capture' must be a non-empty list")
    capture = [_capture(item, i) for i, item in enumerate(capture)]
    names = [item["name"] for item in capture]
    if len(set(names)) != len(names):
        raise ValueError("open_browser: two captures have one name: %s" % ", ".join(names))
    if require not in REQUIRE:
        raise ValueError("open_browser: 'require' must be one of %s, not %r" % (", ".join(REQUIRE), require))
    if done_when is not None:
        if not isinstance(done_when, dict) or len([k for k in DONE_WHEN if k in done_when]) != 1:
            raise ValueError("open_browser: 'done_when' must have exactly one of %s" % ", ".join(DONE_WHEN))
    for i, step in enumerate(guide or []):
        if not isinstance(step, dict):
            raise ValueError("open_browser: guide[%d] must be a mapping" % i)
        _url(step.get("url"), "guide[%d].url" % i)
        _string(step.get("selector"), "guide[%d].selector" % i)
        _string(step.get("text"), "guide[%d].text" % i)
        if "contains" in step:
            _pattern(step["contains"], "guide[%d].contains" % i)
    if done_when is not None and "contains" in done_when:
        _pattern(done_when["contains"], "done_when.contains")
    try:
        timeout = int(timeout)
    except (TypeError, ValueError):
        raise ValueError("open_browser: 'timeout' must be a number of seconds, not %r" % (timeout,))
    spec = {
        "url": url,
        "title": title or url,
        "capture": capture,
        "require": require,
        "guide": list(guide or []),
        "timeout": max(MIN_TIMEOUT, min(MAX_TIMEOUT, timeout)),
    }
    if done_when is not None:
        spec["done_when"] = done_when
    if instructions is not None:
        # For whoever has no browser to use: shown instead of opening one, and
        # never sent to the extension, which reads only what it knows.
        spec["instructions"] = _string(instructions, "instructions").strip()
    return spec


class LoginCallback:
    """'partcad_login' in a plugin's 'login': PartCAD's callbacks, replayed.

    'check' is true for 'pc login --check', which only checks the credentials
    there are; 'non_interactive' for 'pc login --agent' and 'pc mcp', where
    nobody is there to use a browser; 'values' is what was handed over with
    '--set', by capture name.
    """

    BrowserNeeded = BrowserNeeded
    InstructionsNeeded = InstructionsNeeded
    CheckOnly = CheckOnly

    def __init__(self, state=None):
        state = state or {}
        self._results = [dict(result or {}) for result in state.get("browser") or []]
        self.check = bool(state.get("check", False))
        self.non_interactive = bool(state.get("non_interactive", False))
        self.interactive = not self.non_interactive
        self.values = {str(name): str(value) for name, value in (state.get("values") or {}).items() if value != ""}
        self._replayed = 0

    def _given(self, spec):
        """What '--set' handed over for this call, when it is enough to answer it; else None."""
        names = [item["name"] for item in spec["capture"]]
        given = {name: self.values[name] for name in names if name in self.values}
        if not given or (spec["require"] == "all" and len(given) < len(names)):
            return None
        return given

    def open_browser(
        self,
        url,
        capture,
        title=None,
        guide=None,
        require="all",
        done_when=None,
        timeout=DEFAULT_TIMEOUT,
        instructions=None,
    ):
        """Open the user's browser at 'url' and return {name: value} of what 'capture' names, once captured.

        'instructions' is for when there is nobody to use the browser: what
        else would do - an API key and where to make one, an environment
        variable - in a few plain sentences. PartCAD adds what the browser
        would have been asked to find, and how to hand it over.
        """
        spec = browser_spec(url, capture, title, guide, require, done_when, timeout, instructions)
        given = self._given(spec)
        if given is not None:
            return given
        # Counted apart from the calls '--set' answered: the n-th result is
        # what the browser brought for the n-th step PartCAD ran.
        index = self._replayed
        self._replayed += 1
        if index < len(self._results):
            return dict(self._results[index])
        if self.check:
            raise CheckOnly(
                "logging in needs the browser (%s), and this is only a check: run 'pc login' to log in" % spec["title"]
            )
        if self.non_interactive:
            raise InstructionsNeeded(spec)
        raise BrowserNeeded(spec)
