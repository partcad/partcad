#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The login extension in a real browser, from `pc login`'s start page to its callback.

Each test starts a Chromium-family browser on a profile of its own with the
unpacked extension from `browsers/chromium`, a stub of `pc login`'s listener
(contract section 3) and a fake site, and then does what a user would: clicks
what the guide points at, types into the site and the banner, follows an OAuth
redirect. What it checks is what the contract promises -- every capture source,
`match`, `require`, each kind of `done_when`, the banner and the guide, the
callback carrying the values, the window closing -- and the safety rules of
section 4.

Opt-in, because it needs a browser: `PC_TEST_BROWSER_E2E=1`, and
`PC_TEST_BROWSER` to pick one (otherwise the first of Google Chrome, Chromium
or Edge on `PATH`, then Playwright's Chromium). `PC_TEST_BROWSER_HEADED=1` shows
the window instead of running headless. Screenshots of what the user would see
are saved under each test's temporary directory, in `screenshots/`.

The test opens the login in a window of its own beside the browser's first
one, so that "the window the login ran in is closed" can be told apart from
"the browser went away".
"""

import json
import os
import time
import urllib.parse

import pytest

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("PC_TEST_BROWSER_E2E") != "1",
        reason="set PC_TEST_BROWSER_E2E=1 to drive a real browser with the login extension",
    ),
    pytest.mark.skipif(
        not hasattr(os, "posix_spawn"),
        reason="the harness hands the browser its DevTools pipe as file descriptors 3 and 4",
    ),
]

# Long enough that no test runs into it unless it means to.
TIMEOUT = 120


def wait_for(probe, message, timeout=15):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = probe()
        except Exception as error:  # a page in the middle of navigating answers nothing
            last = error
        else:
            if last:
                return last
        time.sleep(0.1)
    raise AssertionError("%s (last seen: %r)" % (message, last))


def stays_false(probe, seconds=2.0):
    """`probe()` stays falsy for `seconds` -- for "nothing was sent yet"."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        assert not probe()
        time.sleep(0.1)


def banner_shows(tab, predicate=lambda banner: True):
    def probe():
        banner = tab.banner()
        return banner if banner and predicate(banner) else None

    return probe


def captured(tab, *names):
    return wait_for(
        banner_shows(tab, lambda banner: all(banner["captured"].get(name) for name in names)),
        "the banner never showed %s as captured" % ", ".join(names),
    )


def window_closed(browser, tab):
    wait_for(lambda: not browser.has_target(tab.target_id), "the login window was not closed")
    # And only that window: the browser's own first window is still there.
    assert browser.targets("page"), "the browser closed every window, not only the login's"


def same_box(a, b, slack):
    return all(abs(a[key] - b[key]) <= slack for key in ("x", "y", "width", "height"))


def spot_on(tab, selector):
    """The guide's spotlight sits on the element, padded by 6 pixels on each side."""
    element = tab.rect(selector)
    guide = tab.guide()
    if not guide:
        return None
    padded = {
        "x": element["x"] - 6,
        "y": element["y"] - 6,
        "width": element["width"] + 12,
        "height": element["height"] + 12,
    }
    return guide if same_box(guide["spot"], padded, 2) else None


def log_in(tab, site):
    """Fill the fake site's login form the way a user does: click, type, press Enter."""
    wait_for(lambda: tab.url() == site.url + "/login", "not on the login page")
    tab.click("input[type=email]")
    tab.type("ann@example.com")
    tab.click("input[type=password]")
    tab.type("correct horse")
    tab.press_enter()
    wait_for(lambda: tab.url() == site.url + "/account", "the login did not land on the account page")


CONFIRM_PAGE = "/confirm.html"


def on_confirm_page(tab):
    """The tab is at the extension's confirmation page, showing a request."""
    url = tab.url() or ""
    if not (url.startswith("chrome-extension://") and url.split("#")[0].endswith(CONFIRM_PAGE)):
        return False
    return tab.evaluate("!document.getElementById('request').hidden")


def confirm(tab):
    """Say yes on the confirmation page the start page handed the tab to, as a user does: a real click."""
    wait_for(lambda: on_confirm_page(tab), "the start page did not hand over to the confirmation page")
    # Continue is armed a moment after the page is in view.
    wait_for(lambda: tab.evaluate("!document.getElementById('continue').disabled"), "Continue was never armed")
    tab.click("#continue")
    return tab


def start_login(browser, start_url):
    """Open `pc login`'s start page in a window of its own and confirm the login it asks for."""
    return confirm(browser.open_window(start_url))


def test_every_source_is_captured_and_sent(browser, listeners, site, closed_port, screenshots):
    """The whole contract in one login: six sources, `match`, `done_when.fetch`, the guide, the callback."""
    spec = {
        "url": site.url + "/",
        "title": "Log in to the Test Site",
        "capture": [
            {
                "name": "token",
                "cookie": {"url": site.url + "/", "name": "access_token"},
                # The visitor cookie of the same name is not the shape of a JWT.
                "match": r"^eyJ[\w-]+\.[\w-]+\.[\w-]+$",
            },
            {"name": "auth", "localStorage": {"origin": site.url, "key": "auth"}},
            {"name": "s", "sessionStorage": {"origin": site.url, "key": "s"}},
            {"name": "api_key", "dom": {"url": site.url + "/account*", "selector": "code.api-key"}},
            {
                "name": "user",
                "dom": {"url": site.url + "/account*", "selector": "a.user-menu", "attribute": "data-user"},
            },
            {
                "name": "access_token",
                "redirect": {
                    "url": "http://127.0.0.1:%d/partcad/login/thingiverse*" % closed_port,
                    "param": "access_token",
                },
            },
            {"name": "app_token", "ask": {"label": "Your App Token", "secret": True}, "match": "^tt-"},
        ],
        "require": "all",
        "done_when": {"fetch": {"url": site.url + "/api/me", "status": 200}},
        "guide": [
            {"url": site.url + "/", "selector": "a[href='/login']", "text": "Click 'Log in'"},
            {"url": site.url + "/login*", "selector": "input[type=email]", "text": "Enter your e-mail"},
        ],
        "timeout": TIMEOUT,
    }
    listener = listeners(spec)
    tab = start_login(browser, listener.start_url)

    # The start page hands the spec over and the tab goes to the site.
    wait_for(lambda: tab.url() == site.url + "/", "the start page did not send the tab to the site")

    # The banner: fixed, styled despite a CSP that forbids inline styles, and
    # showing the title, the guide's text and the one ask input -- a password field.
    banner = wait_for(banner_shows(tab, lambda b: b["guide"]), "no banner with the guide's text")
    assert banner["title"] == "PartCAD login: Log in to the Test Site"
    assert banner["guide"] == "Click 'Log in'"
    assert banner["position"] == "fixed"
    assert banner["background"] == "rgb(29, 32, 38)", "the banner's styles did not apply under the site's CSP"
    assert banner["asks"] == {"app_token": "password"}
    assert banner["doneDisabled"] is True

    # The guide: the link spotlighted, everything else greyed, an animated
    # pointer and the text beside it, none of it in the way of a click.
    guide = wait_for(lambda: spot_on(tab, "a[href='/login']"), "the guide did not spotlight the 'Log in' link")
    assert guide["label"] == "Click 'Log in'" and guide["labelShown"]
    assert "rgba(10, 12, 16, 0.55)" in guide["shadow"], "the rest of the page is not greyed out"
    assert guide["pointerAnimation"] == "partcad-nudge"
    assert set(guide["pointerEvents"]) == {"none"}
    tab.screenshot(screenshots / "01-guide-home.png")

    # The visitor cookie is there, and is not taken for a signed-in user's.
    assert browser.session_state()["values"] == {}
    assert banner["captured"]["token"] is False

    # The guide follows the page: scrolled, resized, rearranged.
    tab.evaluate("window.scrollBy(0, 30)")
    wait_for(lambda: spot_on(tab, "a[href='/login']"), "the spotlight did not follow a scroll")
    tab.send(
        "Emulation.setDeviceMetricsOverride", {"width": 900, "height": 700, "deviceScaleFactor": 1, "mobile": False}
    )
    wait_for(lambda: spot_on(tab, "a[href='/login']"), "the spotlight did not follow a resize")
    tab.evaluate("document.body.prepend(Object.assign(document.createElement('h2'), {textContent: 'News'}))")
    wait_for(lambda: spot_on(tab, "a[href='/login']"), "the spotlight did not follow the page changing")
    tab.send("Emulation.clearDeviceMetricsOverride")
    tab.evaluate("window.scrollTo(0, 0)")

    # A real click on the spotlighted link reaches it through the overlay.
    wait_for(lambda: spot_on(tab, "a[href='/login']"), "the spotlight did not settle")
    tab.click("a[href='/login']")
    wait_for(lambda: tab.url() == site.url + "/login", "the click did not reach the link under the overlay")

    # The next step, on the next page.
    wait_for(lambda: spot_on(tab, "input[type=email]"), "the guide did not move on to the e-mail field")
    assert tab.guide()["label"] == "Enter your e-mail"
    tab.screenshot(screenshots / "02-guide-login.png")

    log_in(tab, site)

    # Cookie (HttpOnly), both storages and both DOM values -- trimmed of the
    # whitespace around the API key in the page.
    captured(tab, "token", "auth", "s", "api_key", "user")
    tab.screenshot(screenshots / "03-account.png")
    assert not listener.done, "sent before the redirect and the ask were captured"

    # The OAuth redirect lands on a port nothing listens on; its URL is enough.
    tab.click("#oauth")
    wait_for(lambda: "/partcad/login/thingiverse#" in tab.address(), "the OAuth redirect did not happen")
    wait_for(
        lambda: "access_token" in browser.session_state()["values"], "the redirect's access_token was not captured"
    )
    tab.navigate(site.url + "/account")
    captured(tab, "access_token")

    # The ask: a value not of the shape `match` wants does not count ...
    tab.in_shadow("partcad-login-banner", "function () { this.querySelector('input[data-name=app_token]').focus(); }")
    tab.type("wrong")
    wait_for(banner_shows(tab, lambda b: b["invalid"]["app_token"]), "a value `match` refuses is not marked")
    assert tab.banner()["captured"]["app_token"] is False
    assert not listener.done
    tab.screenshot(screenshots / "04-ask.png")
    # ... and one that is completes the capture, which `done_when` then lets through.
    tab.in_shadow("partcad-login-banner", "function () { this.querySelector('input[data-name=app_token]').select(); }")
    tab.type("tt-secret-1")

    wait_for(lambda: listener.done, "the callback was never requested")
    (done,) = listener.done
    assert done["values"] == {
        "token": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhbm4ifQ.c2lnbmF0dXJl",
        "auth": '{"user": "ann", "token": "ls-real"}',
        "s": "ss-real",
        "api_key": "KEY-real",
        "user": "ann-real",
        "access_token": "oauth-abc",
        "app_token": "tt-secret-1",
    }
    assert "application/json" in done["headers"].get("Accept", "")
    window_closed(browser, tab)
    assert browser.session_state() is None


def test_done_button_sends_when_there_is_no_done_when(browser, listeners, site, screenshots):
    """`require: any`, no `done_when`: complete is not enough, the user's Done is the signal."""
    spec = {
        "url": site.url + "/welcome",
        "title": "Paste a code",
        "capture": [
            {"name": "never", "cookie": {"url": site.url + "/", "name": "never-set"}},
            {"name": "code", "ask": {"label": "The code"}},
        ],
        "require": "any",
        "timeout": TIMEOUT,
    }
    listener = listeners(spec)
    tab = start_login(browser, listener.start_url)
    banner = wait_for(banner_shows(tab), "no banner")
    assert banner["asks"] == {"code": "text"}
    assert banner["doneDisabled"] is True

    tab.in_shadow("partcad-login-banner", "function () { this.querySelector('input[data-name=code]').focus(); }")
    tab.type("abc-123")
    wait_for(banner_shows(tab, lambda b: b["captured"]["code"] and not b["doneDisabled"]), "Done did not enable")
    tab.screenshot(screenshots / "done-enabled.png")
    stays_false(lambda: listener.done)

    tab.click_in_shadow("partcad-login-banner", "button.done")
    wait_for(lambda: listener.done, "Done did not send")
    assert listener.done[0]["values"] == {"code": "abc-123"}
    window_closed(browser, tab)


@pytest.mark.parametrize(
    "done_when",
    [
        pytest.param(lambda site: {"url": site.url + "/welcome*"}, id="url"),
        pytest.param(lambda site: {"selector": ".user-menu"}, id="selector"),
    ],
)
def test_done_when_holds_back_until_it_holds(browser, listeners, site, done_when):
    """Complete on arrival, and still not sent until the condition is met."""
    spec = {
        "url": site.url + "/",
        "title": "Wait for the welcome page",
        "capture": [{"name": "lang", "cookie": {"url": site.url + "/", "name": "lang"}}],
        "done_when": done_when(site),
        "timeout": TIMEOUT,
    }
    listener = listeners(spec)
    tab = start_login(browser, listener.start_url)
    captured(tab, "lang")
    stays_false(lambda: listener.done)

    tab.navigate(site.url + "/welcome")
    wait_for(lambda: listener.done, "the callback was not requested once done_when held")
    assert listener.done[0]["values"] == {"lang": "en"}
    window_closed(browser, tab)


def test_contains_picks_an_element_out_by_its_text(browser, listeners, site, screenshots):
    """`contains` on a guide step and on `done_when.selector`: the words on an element, not its markup.

    A component library's buttons share every class; the guide has to point at
    the visible one that says "Log In" (in whatever case), and `done_when` has to
    wait for one that says "Log Out" rather than for any button at all.
    """
    spec = {
        "url": site.url + "/buttons",
        "title": "Find the button",
        "capture": [{"name": "lang", "cookie": {"url": site.url + "/", "name": "lang"}}],
        "guide": [
            {
                "url": site.url + "/buttons",
                "selector": "button.MuiButton-root",
                "contains": "^log in$",
                "text": "Click 'Log In'",
            }
        ],
        "done_when": {"selector": "button.MuiButton-root", "contains": "^log out$"},
        "timeout": TIMEOUT,
    }
    listener = listeners(spec)
    tab = start_login(browser, listener.start_url)
    guide = wait_for(lambda: spot_on(tab, "#b-login"), "the guide did not pick the button by its text")
    assert guide["label"] == "Click 'Log In'"
    tab.screenshot(screenshots / "contains.png")

    # Complete, and buttons on the page -- but none that says "Log Out".
    captured(tab, "lang")
    stays_false(lambda: listener.done)

    tab.navigate(site.url + "/welcome")
    wait_for(lambda: listener.done, "done_when.selector with contains did not hold on the page that says it")
    assert listener.done[0]["values"] == {"lang": "en"}
    window_closed(browser, tab)


CHALLENGE_TEXT = "Confirm you are human on this page \u2014 the login continues once the site lets you in."


@pytest.mark.parametrize("marker", ["title", "input", "script"])
def test_a_bot_check_is_named_and_left_alone(browser, listeners, site, screenshots, marker):
    """A site's "Verify you are human" page: the banner says so, and nothing else happens.

    No guide over it, though the spec has a step that matches the page: the user
    has the check to do, and PartCAD does not work around one. Once the site lets
    the user through, the guide is back.
    """
    challenge = site.url + "/challenge/" + marker
    spec = {
        "url": challenge,
        "title": "Through the check",
        "capture": [{"name": "x", "ask": {}}],
        "guide": [{"url": site.url + "/*", "selector": "h1", "text": "Look here"}],
        "timeout": TIMEOUT,
    }
    listener = listeners(spec)
    tab = start_login(browser, listener.start_url)
    banner = wait_for(banner_shows(tab, lambda b: b["challenge"]), "the bot check was not recognised")
    assert banner["guide"] == CHALLENGE_TEXT
    assert tab.guide() is None, "the guide spotlit something on a bot check"
    tab.screenshot(screenshots / ("challenge-%s.png" % marker))

    tab.navigate(site.url + "/welcome")
    wait_for(banner_shows(tab, lambda b: b["guide"] == "Look here" and not b["challenge"]), "the guide did not return")
    wait_for(lambda: spot_on(tab, "h1"), "no spotlight after the check")


def test_cloudflares_script_on_an_ordinary_page_is_not_a_bot_check(browser, listeners, site):
    """`/cdn-cgi/challenge-platform/scripts/jsd/` is on every page of a site Cloudflare protects; the guide stays."""
    spec = {
        "url": site.url + "/challenge/detections",
        "capture": [{"name": "x", "ask": {}}],
        "guide": [{"url": site.url + "/*", "selector": "h1", "text": "Look here"}],
        "timeout": TIMEOUT,
    }
    tab = start_login(browser, listeners(spec).start_url)
    wait_for(banner_shows(tab, lambda b: b["guide"] == "Look here"), "the guide gave way to a check that is not there")
    assert not tab.banner()["challenge"]
    wait_for(lambda: spot_on(tab, "h1"), "no spotlight")


def test_cancel_tells_pc_login_and_closes_the_window(browser, listeners, site):
    listener = listeners({"url": site.url + "/", "capture": [{"name": "x", "ask": {}}], "timeout": TIMEOUT})
    tab = start_login(browser, listener.start_url)
    wait_for(banner_shows(tab), "no banner")
    tab.click_in_shadow("partcad-login-banner", "button.cancel")
    wait_for(lambda: listener.cancelled, "Cancel did not reach the listener")
    window_closed(browser, tab)
    assert not listener.done
    assert browser.session_state() is None


def test_nothing_is_taken_from_an_origin_the_spec_does_not_name(browser, listeners, site, screenshots):
    """The same names, the same shapes, on another origin: no banner, and none of it captured."""
    spec = {
        "url": site.url + "/",
        "title": "Only the real site",
        "capture": [
            {"name": "token", "cookie": {"url": site.url + "/", "name": "access_token"}, "match": "^eyJ"},
            {"name": "auth", "localStorage": {"origin": site.url, "key": "auth"}},
            {"name": "api_key", "dom": {"url": site.url + "/account*", "selector": "code.api-key"}},
        ],
        "timeout": TIMEOUT,
    }
    listener = listeners(spec)
    tab = start_login(browser, listener.start_url)
    wait_for(banner_shows(tab), "no banner on the named site")

    # Sign in to the look-alike, which serves every value under the same names.
    tab.navigate(site.decoy_url + "/login")
    wait_for(lambda: tab.url() == site.decoy_url + "/login", "not on the look-alike")
    log_in_decoy = site.decoy_url + "/account"
    tab.click("input[type=email]")
    tab.type("ann@example.com")
    tab.press_enter()
    wait_for(lambda: tab.url() == log_in_decoy, "the look-alike login did not land on its account page")
    wait_for(lambda: tab.evaluate("localStorage.getItem('auth')"), "the look-alike did not set its storage")
    time.sleep(2)
    assert tab.evaluate("document.querySelector('partcad-login-banner')") is None, "a banner on an unnamed origin"
    assert tab.evaluate("document.querySelector('partcad-login-guide')") is None
    assert browser.session_state()["values"] == {}
    tab.screenshot(screenshots / "unnamed-origin.png")

    # A page carrying a spec is not a start page unless it is `pc login`'s.
    tab.navigate(site.url + "/not-a-start-page")
    time.sleep(1)
    assert browser.session_state()["spec"]["title"] == "Only the real site"

    # The real site, and only its values.
    tab.navigate(site.url + "/login")
    log_in(tab, site)
    captured(tab, "token", "auth", "api_key")
    tab.click_in_shadow("partcad-login-banner", "button.done")
    wait_for(lambda: listener.done, "Done did not send")
    assert listener.done[0]["values"] == {
        "token": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhbm4ifQ.c2lnbmF0dXJl",
        "auth": '{"user": "ann", "token": "ls-real"}',
        "api_key": "KEY-real",
    }
    window_closed(browser, tab)


def refused(tab):
    return tab.evaluate("document.documentElement.getAttribute('data-partcad-login')") == "refused"


def start_message(tab):
    return tab.evaluate("document.getElementById('partcad-login-extension').textContent")


def test_a_spec_is_refused_unless_it_is_safe(browser, listeners, site):
    """A callback on another origin, or a start URL that is not a web page, starts nothing."""
    elsewhere = listeners({"url": site.url + "/", "capture": [{"name": "x", "ask": {}}]})
    spec = {"url": site.url + "/", "capture": [{"name": "x", "ask": {}}], "timeout": TIMEOUT}

    listener = listeners(spec, callback=elsewhere.base + "/done")
    tab = browser.open_window(listener.start_url)
    wait_for(lambda: refused(tab), "a callback on another origin was accepted")
    assert "callback" in start_message(tab)
    assert tab.url() == listener.start_url
    assert browser.session_state() is None

    hostile = listeners(dict(spec, url="javascript:alert(1)"))
    tab = browser.open_window(hostile.start_url)
    wait_for(lambda: refused(tab), "a javascript: URL was accepted")
    assert browser.session_state() is None
    assert not elsewhere.done and not listener.done and not hostile.done
    assert not [path for path, _ in elsewhere.requests if not path.endswith("/start")]


def test_a_session_expires_after_its_timeout(browser, listeners, site):
    listener = listeners({"url": site.url + "/", "capture": [{"name": "x", "ask": {}}], "timeout": 3})
    tab = start_login(browser, listener.start_url)
    wait_for(banner_shows(tab), "no banner")
    wait_for(lambda: tab.banner() is None, "the banner outlived the session's timeout", timeout=10)
    assert browser.session_state() is None
    assert not listener.done


def test_one_session_at_a_time(browser, listeners, site):
    """A second start page waits while the first login's `pc login` is still waiting."""
    first = listeners({"url": site.url + "/", "title": "First", "capture": [{"name": "x", "ask": {}}]})
    second = listeners({"url": site.url + "/welcome", "title": "Second", "capture": [{"name": "y", "ask": {}}]})

    one = start_login(browser, first.start_url)
    wait_for(banner_shows(one), "no banner for the first login")

    two = browser.open_window(second.start_url)
    wait_for(lambda: refused(two), "a second login was started over the first")
    assert "First" in start_message(two)
    assert browser.session_state()["spec"]["title"] == "First"

    # The first `pc login` gives up: its start page stops answering. The second
    # one can now have the browser.
    first.close()
    two.reload()
    confirm(two)
    wait_for(lambda: two.url() == site.url + "/welcome", "the second login did not start")
    assert browser.session_state()["spec"]["title"] == "Second"
    # The first login's page is on the same site, so it now shows the second
    # login's banner; nothing of the first is left.
    wait_for(banner_shows(one, lambda b: b["title"] == "PartCAD login: Second"), "the abandoned login's banner stayed")


def test_a_refused_callback_is_shown_and_tried_again(browser, listeners, site):
    """`pc login` answering anything but 200 is said on the banner, and the values are sent again."""
    listener = listeners({"url": site.url + "/", "capture": [{"name": "x", "ask": {}}], "timeout": TIMEOUT})
    listener.done_status = 500
    tab = start_login(browser, listener.start_url)
    wait_for(banner_shows(tab), "no banner")
    tab.in_shadow("partcad-login-banner", "function () { this.querySelector('input[data-name=x]').focus(); }")
    tab.type("value")
    wait_for(banner_shows(tab, lambda b: not b["doneDisabled"]), "Done did not enable")
    tab.click_in_shadow("partcad-login-banner", "button.done")
    wait_for(banner_shows(tab, lambda b: "HTTP 500" in b["status"]), "the refusal is not on the banner")
    assert browser.has_target(tab.target_id), "the window closed although PartCAD did not take the login"

    listener.done_status = 200
    wait_for(lambda: len(listener.done) == 2, "the values were not sent again", timeout=20)
    assert listener.done[1]["values"] == {"x": "value"}
    window_closed(browser, tab)


@pytest.mark.parametrize("flags", [True, False], ids=["load-extension", "loadUnpacked"])
def test_a_start_page_the_browser_opens_with_is_taken(launch, listeners, site, flags):
    """What `pc login` does: start the browser at the start page.

    With `--load-extension` the extension is there before the page loads. With
    `Extensions.loadUnpacked` -- Google Chrome 137 and later -- it arrives after,
    and finds the page already open.
    """
    listener = listeners({"url": site.url + "/", "capture": [{"name": "x", "ask": {}}], "timeout": TIMEOUT})
    browser = launch(start_url=listener.start_url, flags=flags)
    asked = wait_for(
        lambda: [t for t in browser.targets("page") if t["url"].split("#")[0].endswith(CONFIRM_PAGE)],
        "the start page the browser opened with did not hand its spec over",
    )[0]
    tab = confirm(browser.tab(asked["targetId"]))
    wait_for(lambda: tab.url() == site.url + "/", "the confirmed login did not open the site")
    wait_for(banner_shows(tab), "no banner")


# --- The confirmation ---------------------------------------------------------------
#
# A start page is any page on the loopback interface at `pc login`'s path, and
# nothing proves `pc login` served it. So nothing is captured until the user
# has said yes on the extension's own page, which says what would be taken and
# where it would go.


def page_text(tab):
    return tab.evaluate("document.getElementById('request').innerText")


def test_nothing_is_taken_until_the_login_is_confirmed(browser, listeners, site, screenshots):
    # Signed in to the site already: a capture would be complete the moment it began.
    signed_in = browser.open_window(site.url + "/login")
    log_in(signed_in, site)
    spec = {
        "url": site.url + "/",
        "title": "Already signed in",
        "capture": [
            {"name": "token", "cookie": {"url": site.url + "/", "name": "access_token"}, "match": "^eyJ"},
            {"name": "key", "ask": {"label": "Your API key"}},
        ],
        "require": "any",
        "done_when": {"url": site.url + "/*"},
        "timeout": TIMEOUT,
    }
    listener = listeners(spec)
    tab = browser.open_window(listener.start_url)
    wait_for(lambda: on_confirm_page(tab), "the start page did not hand over to the confirmation page")

    # What would be taken, from where, and where it would go -- before any of it is.
    text = page_text(tab)
    assert "Already signed in" in text
    assert site.url in text
    assert "token: the cookie “access_token” of %s/" % site.url in text
    assert "key: what you type in for “Your API key”" in text
    assert "http://" + urllib.parse.urlsplit(listener.base).netloc in text
    tab.screenshot(screenshots / "confirm.png")
    stays_false(lambda: listener.done, seconds=3)
    assert browser.session_state() is None

    confirm(tab)
    wait_for(lambda: listener.done, "the confirmed login did not send what was already there")
    assert listener.done[0]["values"] == {"token": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhbm4ifQ.c2lnbmF0dXJl"}


def test_a_login_said_no_to_tells_pc_login_and_takes_nothing(browser, listeners, site):
    signed_in = browser.open_window(site.url + "/login")
    log_in(signed_in, site)
    spec = {
        "url": site.url + "/",
        "capture": [{"name": "token", "cookie": {"url": site.url + "/", "name": "access_token"}}],
        "done_when": {"url": site.url + "/*"},
        "timeout": TIMEOUT,
    }
    listener = listeners(spec)
    tab = browser.open_window(listener.start_url)
    wait_for(lambda: on_confirm_page(tab), "the start page did not hand over to the confirmation page")
    # Cancel is what Enter presses: it has the focus.
    assert tab.evaluate("document.activeElement.id") == "cancel"
    tab.click("#cancel")
    wait_for(lambda: listener.cancelled, "Cancel did not reach the listener")
    wait_for(lambda: not browser.has_target(tab.target_id), "the declined login's tab was not closed")
    stays_false(lambda: listener.done)
    assert browser.session_state() is None
    # And the request is gone: the same page asked again is asked afresh.
    assert json.loads(browser.background("chrome.storage.session.get('pending').then((s) => JSON.stringify(s))")) == {}


def test_only_the_confirmation_page_can_say_yes(browser, listeners, site):
    """A yes from anywhere but confirm.html in a tab -- a content script, from a web page -- starts nothing."""
    listener = listeners({"url": site.url + "/", "capture": [{"name": "x", "ask": {}}], "timeout": TIMEOUT})
    tab = browser.open_window(listener.start_url)
    wait_for(lambda: on_confirm_page(tab), "the start page did not hand over to the confirmation page")
    token = tab.evaluate("location.hash.slice(1)")

    # The background's own handler, asked as a content script in the site's
    # page would ask it, and as something with the right URL but no tab.
    for sender in ({"tab": {"id": -1}, "url": site.url + "/"}, {"url": tab.url()}):
        answer = browser.background(
            "HANDLERS.confirm({ type: 'confirm', token: %s }, %s).then((a) => JSON.stringify(a))"
            % (json.dumps(token), json.dumps(sender))
        )
        assert json.loads(answer) == {"ok": False, "error": "Only the extension's own page can confirm a login."}
    assert browser.session_state() is None

    # The request is still there for the user to answer.
    confirm(tab)
    wait_for(lambda: tab.url() == site.url + "/", "the confirmed login did not open the site")


def test_a_confirmation_page_cannot_say_yes_to_what_it_was_not_showing(browser, listeners, site):
    """The same start page asking for something else is a new request: the page still showing the old one is stale."""
    listener = listeners(
        {"url": site.url + "/", "title": "Shown", "capture": [{"name": "x", "ask": {}}], "timeout": TIMEOUT}
    )
    shown = browser.open_window(listener.start_url)
    wait_for(lambda: on_confirm_page(shown), "the start page did not hand over to the confirmation page")
    assert "Shown" in page_text(shown)

    # The same start page, now asking for a cookie the first page never named.
    listener.spec["title"] = "Swapped"
    listener.spec["capture"] = [{"name": "token", "cookie": {"url": site.url + "/", "name": "access_token"}}]
    swapped = browser.open_window(listener.start_url)
    wait_for(lambda: on_confirm_page(swapped), "the changed request was not asked about")
    assert "Swapped" in page_text(swapped) and "access_token" in page_text(swapped)
    assert shown.evaluate("location.hash") != swapped.evaluate("location.hash")

    # Continue on the page that showed the first request starts nothing.
    wait_for(lambda: shown.evaluate("!document.getElementById('continue').disabled"), "Continue was never armed")
    shown.click("#continue")
    wait_for(lambda: shown.evaluate("!document.getElementById('gone').hidden"), "the stale page was not told")
    assert browser.session_state() is None

    # The one that shows it can.
    confirm(swapped)
    wait_for(lambda: browser.session_state(), "the shown request did not start")
    assert browser.session_state()["spec"]["title"] == "Swapped"


def test_the_same_request_again_keeps_its_page(browser, listeners, site):
    """The start page reloaded, asking for the same thing, is the same request: the page already open still answers it."""
    listener = listeners({"url": site.url + "/", "capture": [{"name": "x", "ask": {}}], "timeout": TIMEOUT})
    first = browser.open_window(listener.start_url)
    wait_for(lambda: on_confirm_page(first), "the start page did not hand over to the confirmation page")
    again = browser.open_window(listener.start_url)
    wait_for(lambda: on_confirm_page(again), "the same request was not asked about again")
    assert first.evaluate("location.hash") == again.evaluate("location.hash")
    confirm(first)
    wait_for(lambda: first.url() == site.url + "/", "the request did not start from the page first opened")
