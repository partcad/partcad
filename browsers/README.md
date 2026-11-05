# PartCAD Login, the browser extension

`pc login` logs a PartCAD plugin in to the site it works with -- GrabCAD, Printables, Thingiverse and so on -- by
opening the user's own browser on a profile of PartCAD's own, letting the user sign in the way they always do, and
taking from the browser exactly the values the plugin asked for: a cookie, a value in the page's storage, a value
shown on the page, an OAuth redirect's token, or something the user pastes. This directory is the extension that does
the taking. It captures credentials and nothing else: it does not click for the user, fill in forms, or work around a
site's bot checks.

* [`chromium/`](chromium) -- Chrome, Chromium, Microsoft Edge, Brave: a Manifest V3 extension with a service worker.
* [`firefox/`](firefox) -- Firefox 140 and later: Manifest V3 with an event page, id `login@partcad.org`.
* [`build.py`](build.py) -- checks the two and packages them for the stores.
* [`store/`](store) -- what a store submission carries besides the package.

Both directories are loadable as they are: there is no build step, no bundler and no minifier, and `pc login` loads
them unpacked. Every file but `manifest.json` is the same file in both, kept as a **copy** rather than a symbolic link
-- a link is a text file holding a path on a Windows checkout and in a zip. So edit the copy in one directory and copy
it over the other; `tests/browsers/test_extensions.py` and `build.py` both refuse copies that differ.

The protocol between PartCAD, its plugins and this extension is the plugin login contract; what follows is what the
extension does with its sections 2 to 4.

## How a login goes

1. `pc login` serves a start page on the loopback interface, `http://127.0.0.1:<port>/partcad/login/<nonce>/start`,
   carrying the request -- *the spec* -- in `<script type="application/json" id="partcad-login-spec">`, and starts the
   browser at it.
2. The content script recognises a start page by its address (`http:`, host `127.0.0.1`, `localhost` or `[::1]`, path
   `/partcad/login/<nonce>/start`, top-level frame only), reads the spec and hands it to the background. The background
   checks it, keeps it in `storage.session` (memory only, gone when the browser exits) and sends that tab to the spec's
   `url`. On the start page it says how that went: `<html data-partcad-login="accepted|refused">` and a
   `<p id="partcad-login-extension" role="status">` with the reason, which the start page can style or react to.
3. On every page of an origin the spec names, a banner along the bottom of the window says **PartCAD login:
   *title***, what to do next, which values are captured so far (by name -- a value is never shown or sent back to a
   page), an input for every `ask`, and **Done** and **Cancel**. The guide spotlights what to click.
4. Each value is taken as it appears: cookies through the cookie API (HttpOnly ones included), `localStorage` and
   `sessionStorage` and DOM values by the content script on a page of that origin or URL, `redirect` values from any
   tab's URL -- query string or fragment, and the page need not load -- and `ask` values from the banner.
5. Once the capture is complete -- per `require`, `match` and `done_when` -- the background requests
   `callback?<name>=<value>&...`. On a 200 it closes the window the login ran in. On anything else it says so on the
   banner and sends again every five seconds while the session lasts (and at once when Done is pressed).
6. **Cancel** requests `.../cancel` and closes the window. A session that runs past `timeout` ends: the banner goes and
   nothing is sent.

### What the spec's fields mean here

The contract defines the spec; these are the details it leaves to the extension.

* **URL patterns** (`url` of `dom`, `redirect` and guide steps, `done_when.url`) are globs over the whole URL with `*`
  as the only wildcard; `?` and `.` are themselves.
* **`match`** is a JavaScript regular expression, tested anywhere in the value (`RegExp.test`), so anchor it with `^`
  and `$` to mean the whole value. It goes beside the source (`{"name", "cookie": {...}, "match"}`); inside the source
  object is accepted too. A value that does not match is not captured -- for an `ask` the input is marked invalid.
* **`contains`** on a guide step or on `done_when.selector` is a case-insensitive JavaScript regular expression that the
  element's visible text has to match: its `innerText`, or failing that its `value`, `aria-label` or `title`. It is how
  a guide points at the button a component library renders with the same classes as every other button.
* **Cookies** are read fresh on every check rather than remembered, so a cookie that goes away (a logout) is no longer
  captured. Other values are kept once seen, since the page they came from may be gone.
* **`dom`** reads `attribute` when it is given, otherwise `property` (default `textContent`), of the first element that
  matches the selector. `dom` and `ask` values are trimmed of surrounding whitespace; other values are taken as they
  are.
* **`done_when`**: `url` holds while some tab is at a matching URL; `selector` holds once a page of a named origin has
  shown a matching element (with `contains`, one whose text matches); `fetch` requests the URL with the browser's own
  cookies, at most every two seconds once everything else is captured, and holds when the site answers `status`
  (default 200) **itself** -- a redirect is not followed, so a login page's 200 behind a 302 is not taken for "signed
  in".
* **Done** sends once the capture is complete when the spec has no `done_when`. With a `done_when` it does not bypass
  the condition; it checks it again at once.
* **`timeout`** defaults to 600 seconds and is capped at a day.

### The guide

On a page whose URL matches a step's `url`, the first step with a **visible** element matching its `selector` (and
`contains`) is shown: the element framed and everything else greyed out by the frame's shadow, an arrow beside it
nudging towards it, and the step's `text` in a label next to the arrow and in the banner. None of it takes a click --
`pointer-events: none` throughout -- so the user clicks the real element through it. It follows the page: scrolling,
resizing, DOM changes and single-page navigation. An element that is out of view is scrolled into it once. The banner
moves to the top of the window when the element is under it.

### Bot checks

When a page is Cloudflare's interactive check -- title "Just a moment...", an `input[id^='cf-chl-widget']`, or a
script from `/cdn-cgi/challenge-platform/` (other than `/cdn-cgi/challenge-platform/scripts/jsd/`, Cloudflare's
"JavaScript detections", which it puts on the ordinary pages of every site it protects) -- the banner says *Confirm you are human on this page -- the login
continues once the site lets you in* in place of the guide, and no step is spotlighted. That is all: the extension
never clicks, scripts or reads the check, and treats its cookies like any other cookie.

## Safety

* **Only while a session is active.** With no login in progress every listener returns at once; the content script
  asks the background once per page load and does nothing else.
* **Only for the origins the spec names**: the origin of its `url`, of every cookie's `url`, every storage `origin`,
  `done_when.fetch.url`, and the origin part of every URL pattern (`dom`, `redirect`, guide steps, `done_when.url`). No
  banner, guide or read anywhere else; a storage value is taken only from a page of exactly its origin and a DOM value
  only from a page matching its pattern, judged by the address the *browser* reports for the page, not the one the
  page reports. Values are never sent to a page.
* **Only to the callback of its own start page**: the spec's `callback` must be on the start page's origin and under
  `/partcad/login/`, and is requested without cookies and without following redirects. A spec is accepted only from a
  start page's top-level frame on the loopback interface, and its `url` must be `http` or `https`.
* **For as long as the spec's `timeout`**, after which the session and everything captured are dropped.
* **One session at a time.** A second start page is refused while the first login's start page still answers -- that
  is, while its `pc login` is still waiting -- and the user is told to finish or cancel that one. A login whose
  `pc login` has gone away is abandoned and the new one takes over.
* Everything it shows is in **closed shadow roots**, styled from inside, so the page's scripts cannot read what is
  typed into the banner and its CSS cannot reach in. Keys typed into the banner are not passed on to the page's own
  shortcuts.
* It is meant for **PartCAD's own browser profile** and refuses to run in private windows (`"incognito":
  "not_allowed"`).

## Permissions, and why

| Permission | Why |
| --- | --- |
| `<all_urls>` (host permission) | The sites a login names are whatever the plugin says -- every model site there is, and the loopback start page and callback. Reading a site's cookies with the cookie API, running the content script on its pages, requesting `done_when.fetch` with its cookies and the callback all need host access to it, and no fixed list could name them in advance. What the extension does with that access is limited by the rules above, not by the permission. |
| `cookies` | Reading the cookies a spec names, HttpOnly ones included, which page scripts cannot see; and noticing when they change. |
| `storage` | `storage.session` keeps the login in progress across the background being stopped and started again, in memory only. |
| `tabs` | Reading tab URLs (redirect captures, `done_when.url`), sending the start tab to the site, and closing the login's window. |
| `webNavigation` | Seeing a navigation's URL as it happens -- an OAuth redirect to a port nothing listens on is visible here, and its token with it, even though the page never loads. |
| `scripting` | Running the content script in a start page that finished loading before the extension did, which is what happens when the browser is started at that page (and always with `Extensions.loadUnpacked`). |
| `alarms` | Waking the background to end a session at its `timeout` when nothing else would. |

The Firefox build also declares `data_collection_permissions: {"required": ["authenticationInfo"]}`: what it takes is
authentication information, and it hands it to another program (PartCAD on the same computer), so it says so.
`web-ext lint` warns that Firefox for Android only understands that key from 142; the extension is not meant for
Android.

## Loading it (what `pc login`'s launcher passes)

**Chromium family.** On a profile of its own (`--user-data-dir`), with the unpacked `chromium/` directory:

```
--user-data-dir=<profile> --load-extension=<abs path>/chromium --disable-extensions-except=<abs path>/chromium
--no-first-run --no-default-browser-check <start page URL>
```

Google Chrome 137 and later ignore `--load-extension`; there, start the browser with `--remote-debugging-pipe
--enable-unsafe-extension-debugging` and send `Extensions.loadUnpacked {"path": "<abs path>/chromium"}` over the pipe
(file descriptors 3 and 4), keeping the pipe open while the browser runs. The start page can be on the command line
either way: when the extension arrives after the page has loaded, it finds the page and takes it over (the `scripting`
permission above). Both are loaded for one run of the browser only, so they are passed every time.

The extension relies on no particular id. An unpacked extension's id is derived from its directory -- the first 32
hex digits of the SHA-256 of the absolute path, written with the letters `a`-`p` -- which is how the tests find its
service worker; a store assigns its own. The manifest carries no `key`.

**Firefox.** Copy the `.xpi` into the profile as `<profile>/extensions/login@partcad.org.xpi` and set, in the profile's
`user.js`:

```
user_pref("extensions.autoDisableScopes", 0);        // enable it without the "new add-on" prompt
user_pref("extensions.startupScanScopes", 1);        // notice a replaced .xpi in the profile at startup
user_pref("xpinstall.signatures.required", false);   // unsigned: ESR, Developer Edition, Nightly, unbranded only
```

Release and Beta Firefox install signed extensions only, which is what the addons.mozilla.org job below produces.
(Any Firefox also takes an unsigned extension as a *temporary* add-on, over Marionette's `Addon:Install` or the
remote debugging protocol, for as long as it runs -- which is how `web-ext run` does it.) No test here starts a
Firefox yet, so these preferences are the documented ones rather than ones a test has proven.
Leave `privacy.firstparty.isolate` off in that profile: with it on, the cookie API wants a first-party domain the spec
does not give. Start Firefox with `-profile <profile> -no-remote <start page URL>`.

## Testing

From the repository root:

```bash
poetry run pytest tests/browsers                                     # static: manifests, copies, build.py, common.js
PC_TEST_BROWSER_E2E=1 poetry run pytest tests/browsers/test_login_e2e.py
```

The static tests always run, in the `Pytest` job like everything under `tests/`. The rules in `common.js` are tested
in Node.js when it is installed. The end-to-end test needs a Chromium-family browser: `PC_TEST_BROWSER` names one,
otherwise the first of Google Chrome, Chromium or Edge on `PATH`, then Playwright's Chromium. `PC_TEST_BROWSER_HEADED=1`
shows the windows. It speaks the DevTools protocol over a pipe with nothing but the standard library, loads the
extension with `--load-extension` or, when the browser ignores that, `Extensions.loadUnpacked`, and runs a stand-in
for `pc login`'s listener and a fake site on ephemeral ports -- so it runs in parallel under pytest-xdist. Screenshots
of each step are saved under the test's temporary directory, in `screenshots/`. It covers every capture source,
`match`, `require`, each `done_when`, `contains`, the banner and the guide (and that a click goes through it), bot
checks, the callback and its retry, Cancel, the window closing, and the safety rules.

There is no Firefox end-to-end test yet: the Firefox build is held to the Chromium one by the static tests and linted
with addons.mozilla.org's own linter, `npx web-ext lint --source-dir browsers/firefox`, in CI.

`python browsers/build.py` writes `browsers/dist/partcad-login-chromium-<version>.zip` and
`partcad-login-firefox-<version>.xpi` (`--out` to put them elsewhere, `--check` to only check). The archives are
reproducible. The version is PartCAD's: `dev-tools/bumpversion.toml` moves both manifests with the release.

## CI and publishing

`.github/workflows/browsers.yml` runs on the same gate as every other workflow here (`.github/actions/changed-scopes`,
bucket `browsers`): a change under `browsers/` or `tests/browsers/`, or to CI, packages both builds, lints the Firefox
one, runs the static tests and the end-to-end test in the runner's Google Chrome (which exercises
`Extensions.loadUnpacked`), and uploads the packages as the `partcad-login-extension` artifact and the screenshots as
`browsers-e2e-screenshots`.

On a release -- a push to `main`, as in `deploy.yml` -- it then publishes the packages that run built, to each store
**whose credentials are configured**. A store without them is skipped, not failed, with a notice saying what is
missing; one with only some of them gets a warning. A manual run on `main` with *publish* ticked does the same, for a
store set up after the release went out. Each store refuses a version it already has, so publishing the same release
twice fails at the store.

| Store | Repository secrets | Where they come from |
| --- | --- | --- |
| Chrome Web Store | `CHROME_PUBLISHER_ID`, `CHROME_EXTENSION_ID`, `CHROME_CLIENT_ID`, `CHROME_CLIENT_SECRET`, `CHROME_REFRESH_TOKEN` | The publisher and item ids from the developer dashboard (the item is created by hand the first time, with its listing and privacy tabs filled in). An OAuth client in a Google Cloud project with the Chrome Web Store API enabled, and a refresh token for the `https://www.googleapis.com/auth/chromewebstore` scope. The job uses API v2: upload, then submit for review. |
| Firefox Add-ons | `AMO_JWT_ISSUER`, `AMO_JWT_SECRET` | addons.mozilla.org, *Developer Hub > Manage API Keys*. Signed and submitted with `web-ext sign`. The repository variable `AMO_CHANNEL` picks `listed` (the default: the public listing, with `store/amo-metadata.json`, reviewed and then signed by Mozilla) or `unlisted` (signed for distribution by PartCAD itself, uploaded as the `partcad-login-firefox-signed` artifact -- what a release Firefox needs if `pc login` is to install it without the listing). One version goes to one channel. |
| Microsoft Edge Add-ons | `EDGE_PRODUCT_ID`, `EDGE_CLIENT_ID`, `EDGE_API_KEY` | Partner Center, *Microsoft Edge > Publish API* (API v1.1, the API-key one); the product is created by hand the first time. The Chromium package is uploaded to the draft and submitted for certification. |

## Deviations from the contract

Where the contract is silent or could be read two ways, the extension does this:

* **Named origins include the guide's and `done_when`'s.** Section 4 says the extension acts only for the origins the
  spec's `url` and captures name. A guide step on a page the extension may not act on could never be shown, so the
  origins of guide steps and of `done_when` count as named too.
* **The content script runs on every page and decides for itself whether a page is a start page**, instead of being
  declared for `http://127.0.0.1:*/partcad/login/*/start`: Chromium and Firefox disagree about ports in match patterns.
  It accepts `[::1]` as well as `127.0.0.1` and `localhost`, and only top-level frames. Everywhere else it does nothing
  unless a session is active and names the page's origin.
* **The callback must also be under `/partcad/login/`**, besides being on the start page's origin.
* **`match` is also accepted inside the source object**, which is how an earlier wording ("every source may add
  `match`") reads.
* **Done does not bypass `done_when`**; it re-checks it. **`done_when.fetch` does not follow redirects.** **`done_when.selector`
  holds once it has been seen** on a page of a named origin (present, not necessarily visible).
* **Cancel closes the login window** as well, like a successful callback.
* **A refused or failed callback is retried** every five seconds while the session lasts, and shown on the banner.
* **One session at a time** is enforced by refusing a second start page while the first `pc login` still answers its
  start page, and by abandoning the first when it no longer does.
* **The start page is marked** with `data-partcad-login` and a `#partcad-login-extension` status line -- an addition,
  for the start page to use.
* **`dom` and `ask` values are trimmed**, and **`timeout` is capped at a day.**
