#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What the end-to-end test of the login extension drives a real browser with.

Three pieces, each as small as the test lets it be:

* `DevTools`: a Chromium-family browser on a throwaway profile, spoken to over
  the DevTools protocol on `--remote-debugging-pipe` -- file descriptors 3 and
  4, so there is no port to choose and nothing else on the machine can reach
  it. The standard library is all it needs, which is why it is not Playwright:
  the test job installs nothing but pytest. It is also the channel `pc login`
  uses to load the extension into a Google Chrome that ignores
  `--load-extension` (137 and later), so when the flag does not take, the
  extension is loaded the same way here (`Extensions.loadUnpacked`).
* `Listener`: a stand-in for `pc login`'s listener, section 3 of the contract
  -- the start page carrying the spec, `done`, `manual` and `cancel`, and 404
  for anything else.
* `Site`: a fake site to log in to, with every kind of value a spec can capture
  and a Content-Security-Policy that forbids inline styles, which is the kind of
  page that breaks an extension whose banner is styled the simple way. The same
  server answers as a second, *unnamed* origin when it is reached as
  `localhost` instead of `127.0.0.1`, serving look-alike values the extension
  must not take.

Nothing here binds a fixed port: every server takes an ephemeral one, so tests
can run side by side under pytest-xdist, each with its own browser and profile.
"""

import base64
import glob
import hashlib
import html
import json
import os
import pathlib
import secrets
import shutil
import signal
import socket
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CHROMIUM_EXTENSION = REPO_ROOT / "browsers" / "chromium"

# The value the fake site signs a user in with: three base64url segments, the
# shape of a JWT, which is what the test's `match` asks for. The visitor cookie
# the site hands out before that ("visitor") does not have it.
SIGNED_IN_TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhbm4ifQ.c2lnbmF0dXJl"


def find_browser():
    """The browser to test with: `PC_TEST_BROWSER`, or the first one installed."""
    named = os.environ.get("PC_TEST_BROWSER")
    if named:
        return shutil.which(named) or named
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge"):
        found = shutil.which(name)
        if found:
            return found
    roots = [os.environ.get("PLAYWRIGHT_BROWSERS_PATH"), os.path.expanduser("~/.cache/ms-playwright")]
    for root in filter(None, roots):
        for candidate in sorted(glob.glob(os.path.join(root, "chromium-*", "chrome-linux*", "chrome")), reverse=True):
            return candidate
    return None


class DevToolsError(Exception):
    pass


def unpacked_extension_id(path):
    """The id a Chromium-family browser gives the unpacked extension in `path`.

    The first 128 bits of the SHA-256 of the absolute path, written with the
    letters a-p for the hex digits 0-f.
    """
    digest = hashlib.sha256(str(pathlib.Path(path).resolve()).encode("utf-8")).hexdigest()[:32]
    return digest.translate(str.maketrans("0123456789abcdef", "abcdefghijklmnop"))


def _high_fd(fd):
    """A duplicate of `fd` well above 4, so that moving it to 3 or 4 cannot clobber another."""
    import fcntl  # POSIX only, like the rest of this harness; imported here so collection works anywhere

    high = fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 10)
    os.close(fd)
    return high


class DevTools:
    """A browser on its own profile, driven over the DevTools protocol on a pipe."""

    def __init__(
        self, binary, profile, log_path, extension=CHROMIUM_EXTENSION, headless=True, start_url=None, flags=True
    ):
        to_browser_read, to_browser_write = (_high_fd(fd) for fd in os.pipe())
        from_browser_read, from_browser_write = (_high_fd(fd) for fd in os.pipe())
        log = _high_fd(os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644))
        self.log_path = pathlib.Path(log_path)
        self.extension = pathlib.Path(extension)
        self.flags = flags
        args = [
            binary,
            "--user-data-dir=%s" % profile,
            "--remote-debugging-pipe",
            # What lets `Extensions.loadUnpacked` work, for a browser that
            # ignores the flag below.
            "--enable-unsafe-extension-debugging",
        ]
        if flags:
            # Not with `--disable-extensions-except`: Google Chrome 137 and
            # later ignore `--load-extension` but still honour that one, and
            # an extension `Extensions.loadUnpacked` then loads stays disabled
            # - its id comes back, and its service worker never starts.
            args += ["--load-extension=%s" % self.extension]
        args += [
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-search-engine-choice-screen",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-sync",
            "--password-store=basic",
            "--use-mock-keychain",
            # Local servers only, whatever proxy the machine is configured with.
            "--no-proxy-server",
            # The test runs as root in containers, where Chrome refuses to start
            # sandboxed; it only ever loads the pages this module serves.
            "--no-sandbox",
            "--window-size=1280,900",
        ]
        if headless:
            args.append("--headless=new")
        args.append(start_url or "about:blank")
        self.pid = os.posix_spawn(
            binary,
            args,
            dict(os.environ),
            file_actions=[
                (os.POSIX_SPAWN_DUP2, to_browser_read, 3),
                (os.POSIX_SPAWN_DUP2, from_browser_write, 4),
                (os.POSIX_SPAWN_DUP2, log, 1),
                (os.POSIX_SPAWN_DUP2, log, 2),
                (os.POSIX_SPAWN_OPEN, 0, os.devnull, os.O_RDONLY, 0),
            ],
            setpgroup=0,
        )
        for fd in (to_browser_read, from_browser_write, log):
            os.close(fd)
        self._out = to_browser_write
        self._in = from_browser_read
        self._lock = threading.Lock()
        self._cond = threading.Condition()
        self._next = 0
        self._responses = {}
        self.events = []
        self._closed = False
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()
        self.extension_id = None

    def _read(self):
        buffer = bytearray()
        while True:
            try:
                chunk = os.read(self._in, 1 << 20)
            except OSError:
                chunk = b""
            if not chunk:
                break
            buffer += chunk
            while True:
                end = buffer.find(b"\0")
                if end < 0:
                    break
                message = json.loads(bytes(buffer[:end]))
                del buffer[: end + 1]
                with self._cond:
                    if "id" in message:
                        self._responses[message["id"]] = message
                    else:
                        self.events.append(message)
                    self._cond.notify_all()
        with self._cond:
            self._closed = True
            self._cond.notify_all()

    def send(self, method, params=None, session=None, timeout=30):
        with self._lock:
            self._next += 1
            ident = self._next
            message = {"id": ident, "method": method, "params": params or {}}
            if session:
                message["sessionId"] = session
            data = json.dumps(message).encode() + b"\0"
            while data:
                written = os.write(self._out, data)
                data = data[written:]
        deadline = time.monotonic() + timeout
        with self._cond:
            while ident not in self._responses:
                remaining = deadline - time.monotonic()
                if self._closed or remaining <= 0:
                    raise DevToolsError("%s: no answer (%s)" % (method, "browser gone" if self._closed else "timeout"))
                self._cond.wait(remaining)
            response = self._responses.pop(ident)
        if "error" in response:
            raise DevToolsError("%s: %s" % (method, response["error"]))
        return response.get("result", {})

    def targets(self, kind=None):
        found = self.send("Target.getTargets")["targetInfos"]
        return [target for target in found if kind is None or target["type"] == kind]

    def worker(self):
        """The extension's service worker target, if it is running.

        Matched by the extension's id: the browser runs service workers of its
        own component extensions too, some of them also called background.js.
        """
        for target in self.targets("service_worker"):
            if target["url"] == "chrome-extension://%s/background.js" % self.extension_id:
                return target
        return None

    def load_extension(self, timeout=30, flag_grace=5):
        """Wait for the extension; load it over the pipe if the flags did not take.

        `--load-extension` names an unpacked extension by its directory, and
        its id is derived from that path -- which is how a launcher can know it
        before the browser says. Google Chrome 137 and later ignore the flag,
        and there `Extensions.loadUnpacked` is the way in: tried once the flag
        has had `flag_grace` seconds, with `timeout` seconds for the worker
        from when the browser answers it -- a browser that is slow to start
        is slow to answer, too.
        """
        self.extension_id = unpacked_extension_id(self.extension)
        if self.flags:
            grace = time.monotonic() + flag_grace
            while time.monotonic() < grace:
                if self.worker():
                    return self.extension_id
                time.sleep(0.2)
        self.extension_id = self.send("Extensions.loadUnpacked", {"path": str(self.extension)})["id"]
        deadline = time.monotonic() + timeout
        while True:
            if self.worker():
                return self.extension_id
            if time.monotonic() >= deadline:
                break
            time.sleep(0.2)
        raise AssertionError(
            "the extension's service worker never started; the browser's log ends:\n%s" % self.log_tail()
        )

    def log_tail(self, size=2000):
        """The end of what the browser wrote to its log, for a failure to show."""
        try:
            return self.log_path.read_text(errors="replace")[-size:]
        except OSError as error:
            return "(no log: %s)" % error

    def background(self, expression):
        """Evaluate `expression` in the extension's service worker."""
        target = wait_for(self.worker, "the extension's service worker is not running", timeout=10)
        session = self.send("Target.attachToTarget", {"targetId": target["targetId"], "flatten": True})["sessionId"]
        try:
            # Without this the evaluation can land before the worker's own
            # context exists, where there is no `chrome` at all.
            self.send("Runtime.enable", session=session)
            result = self.send(
                "Runtime.evaluate",
                {"expression": expression, "returnByValue": True, "awaitPromise": True},
                session=session,
            )
        finally:
            try:
                self.send("Target.detachFromTarget", {"sessionId": session})
            except DevToolsError:
                pass
        if "exceptionDetails" in result:
            raise DevToolsError(result["exceptionDetails"])
        return result["result"].get("value")

    def session_state(self):
        """The extension's login session as the background keeps it, or None.

        Read from `storage.session`, which is where the background keeps it
        between one wake of its worker and the next.
        """
        return json.loads(
            self.background("chrome.storage.session.get('session').then((s) => JSON.stringify(s.session || null))")
        )

    def open_window(self, url):
        target = self.send("Target.createTarget", {"url": url, "newWindow": True})["targetId"]
        return Tab(self, target)

    def tab(self, target_id):
        return Tab(self, target_id)

    def has_target(self, target_id):
        return any(target["targetId"] == target_id for target in self.targets())

    def close(self):
        try:
            self.send("Browser.close", timeout=5)
        except DevToolsError:
            pass
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            pid, _ = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                break
            time.sleep(0.1)
        else:
            os.killpg(self.pid, signal.SIGKILL)
            os.waitpid(self.pid, 0)
        for fd in (self._out, self._in):
            try:
                os.close(fd)
            except OSError:
                pass


def wait_for(probe, message, timeout=15, interval=0.1):
    """`probe()` once it answers something truthy; fail with `message` if it never does."""
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = probe()
        except DevToolsError as error:
            last = error
        else:
            if last:
                return last
        time.sleep(interval)
    raise AssertionError("%s (last seen: %r)" % (message, last))


def _find(node, predicate):
    if predicate(node):
        return node
    for child in node.get("children", []) + node.get("shadowRoots", []):
        found = _find(child, predicate)
        if found:
            return found
    return None


class Tab:
    """One page target, with what the test does to and reads from it."""

    def __init__(self, devtools, target_id):
        self.devtools = devtools
        self.target_id = target_id
        self.session = devtools.send("Target.attachToTarget", {"targetId": target_id, "flatten": True})["sessionId"]
        self.send("Page.enable")

    def send(self, method, params=None, timeout=30):
        return self.devtools.send(method, params, session=self.session, timeout=timeout)

    def evaluate(self, expression):
        result = self.send("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
        if "exceptionDetails" in result:
            raise DevToolsError(result["exceptionDetails"])
        return result["result"].get("value")

    def url(self):
        return self.evaluate("location.href")

    def address(self):
        """The URL the tab is at as the browser reports it -- an error page's included."""
        return self.devtools.send("Target.getTargetInfo", {"targetId": self.target_id})["targetInfo"]["url"]

    def navigate(self, url):
        self.send("Page.navigate", {"url": url})

    def reload(self):
        self.send("Page.reload")

    def in_shadow(self, tag, function, *args):
        """Call `function` with `this` set to the closed shadow root of the <tag> element.

        The page's own scripts cannot reach a closed shadow root, which is the
        point of it; the DevTools protocol can.
        """
        document = self.send("DOM.getDocument", {"depth": -1, "pierce": True})["root"]
        host = _find(document, lambda node: node.get("localName") == tag)
        if not host or not host.get("shadowRoots"):
            return None
        root = self.send("DOM.resolveNode", {"backendNodeId": host["shadowRoots"][0]["backendNodeId"]})
        result = self.send(
            "Runtime.callFunctionOn",
            {
                "objectId": root["object"]["objectId"],
                "functionDeclaration": function,
                "arguments": [{"value": arg} for arg in args],
                "returnByValue": True,
                "awaitPromise": True,
            },
        )
        if "exceptionDetails" in result:
            raise DevToolsError(result["exceptionDetails"])
        return result["result"].get("value")

    def banner(self):
        """What the banner shows, or None when there is none."""
        return self.in_shadow(
            "partcad-login-banner",
            """function () {
                const text = (selector) => (this.querySelector(selector) || {}).textContent || "";
                const done = this.querySelector("button.done");
                return {
                    title: text(".title"),
                    guide: text(".guide"),
                    status: text(".status"),
                    captured: Object.fromEntries([...this.querySelectorAll(".capture")].map(
                        (chip) => [chip.dataset.name, chip.dataset.captured === "true"])),
                    asks: Object.fromEntries([...this.querySelectorAll(".ask input")].map(
                        (input) => [input.dataset.name, input.type])),
                    invalid: Object.fromEntries([...this.querySelectorAll(".ask input")].map(
                        (input) => [input.dataset.name, input.getAttribute("aria-invalid") === "true"])),
                    doneDisabled: done ? done.disabled : null,
                    position: getComputedStyle(this.host).position,
                    edge: this.host.getAttribute("data-edge") || "bottom",
                    rect: this.host.getBoundingClientRect().toJSON(),
                    // A constructed sheet or a <style>: either way, styles that
                    // took. A bar with no styles has no background colour.
                    background: getComputedStyle(this.querySelector(".bar")).backgroundColor,
                    challenge: this.host.getAttribute("data-challenge") === "true",
                };
            }""",
        )

    def guide(self):
        """Where the guide overlay is and what it shows, or None when there is none."""
        return self.in_shadow(
            "partcad-login-guide",
            """function () {
                const spot = this.querySelector(".spot");
                const pointer = this.querySelector(".pointer");
                const label = this.querySelector(".label");
                const styleOf = (node) => getComputedStyle(node);
                return {
                    spot: spot.getBoundingClientRect().toJSON(),
                    shadow: styleOf(spot).boxShadow,
                    pointer: pointer.getBoundingClientRect().toJSON(),
                    pointerAnimation: styleOf(pointer).animationName,
                    direction: pointer.getAttribute("data-direction"),
                    label: label.textContent,
                    labelShown: styleOf(label).display !== "none",
                    pointerEvents: [this.host, spot, pointer, label].map((node) => styleOf(node).pointerEvents),
                };
            }""",
        )

    def rect(self, selector):
        return self.evaluate("document.querySelector(%s).getBoundingClientRect().toJSON()" % json.dumps(selector))

    def click_at(self, x, y):
        for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
            self.send(
                "Input.dispatchMouseEvent",
                {"type": kind, "x": x, "y": y, "button": "left", "buttons": 1, "clickCount": 1},
            )

    def click(self, selector):
        """A real click, at the middle of the element -- through whatever overlay is on top of it."""
        rect = self.rect(selector)
        self.click_at(rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2)

    def click_in_shadow(self, tag, selector):
        rect = self.in_shadow(
            tag, "function (s) { return this.querySelector(s).getBoundingClientRect().toJSON(); }", selector
        )
        self.click_at(rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2)

    def type(self, text):
        self.send("Input.insertText", {"text": text})

    def press_enter(self):
        for kind in ("keyDown", "keyUp"):
            self.send(
                "Input.dispatchKeyEvent",
                {"type": kind, "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13, "text": "\r"},
            )

    def screenshot(self, path):
        data = self.send("Page.captureScreenshot", {"format": "png"})["data"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(data))
        return path


class Server:
    """An HTTP server on an ephemeral loopback port, in a thread of its own."""

    def __init__(self, handler):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _respond(handler, status, body, content_type="text/html; charset=utf-8", headers=()):
    data = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-store")
    for name, value in headers:
        handler.send_header(name, value)
    handler.end_headers()
    handler.wfile.write(data)


class Listener:
    """A stand-in for `pc login`'s listener: section 3 of the contract, and a record of what reached it."""

    def __init__(self, spec, callback=None, done_status=200):
        self.nonce = secrets.token_hex(16)
        self.done = []
        self.cancelled = []
        self.requests = []
        self.done_status = done_status
        listener = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                split = urllib.parse.urlsplit(self.path)
                listener.requests.append((split.path, dict(self.headers)))
                prefix = "/partcad/login/%s/" % listener.nonce
                if not split.path.startswith(prefix):
                    return _respond(self, 404, "not found")
                action = split.path[len(prefix) :]
                if action == "start":
                    return _respond(self, 200, listener.start_page())
                if action == "done":
                    values = dict(urllib.parse.parse_qsl(split.query, keep_blank_values=True))
                    listener.done.append({"values": values, "headers": dict(self.headers)})
                    if "application/json" in self.headers.get("Accept", ""):
                        return _respond(self, listener.done_status, '{"ok": true}', "application/json")
                    return _respond(self, listener.done_status, "<p>Done -- you can close this window.</p>")
                if action == "manual":
                    fields = "".join(
                        '<label>%s <input name="%s"></label>' % (html.escape(c["name"]), html.escape(c["name"]))
                        for c in listener.spec["capture"]
                    )
                    return _respond(self, 200, '<form action="done">%s<button>Send</button></form>' % fields)
                if action == "cancel":
                    listener.cancelled.append(True)
                    return _respond(self, 200, "<p>Cancelled.</p>")
                return _respond(self, 404, "not found")

        self.server = Server(Handler)
        self.base = "http://127.0.0.1:%d/partcad/login/%s" % (self.server.port, self.nonce)
        self.start_url = self.base + "/start"
        self.spec = dict(spec)
        self.spec.setdefault("callback", callback or self.base + "/done")
        self.spec.setdefault("manual", self.base + "/manual")

    def start_page(self):
        # "</" escaped, so that nothing in the spec can close the <script> it is in.
        data = json.dumps(self.spec).replace("</", "<\\/")
        title = html.escape(self.spec.get("title", "the site"))
        return (
            "<!doctype html><title>PartCAD login</title>"
            '<script type="application/json" id="partcad-login-spec">%s</script>'
            "<p>Starting the login to %s&hellip; If nothing happens, the PartCAD extension is not installed in "
            'this browser: <a href="%s/manual">enter the values by hand</a>.</p>' % (data, title, self.base)
        )

    def close(self):
        self.server.close()


# A Content-Security-Policy as strict about styles as many real sites are:
# inline <style> elements and style="" attributes are refused. Scripts may be
# inline, because the site's own pages set their storage with one.
SITE_CSP = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self'; img-src 'self' data:"


class Site:
    """The fake site the extension logs in to.

    Reached as 127.0.0.1 it is the site the spec names. Reached as localhost --
    another origin, and another cookie jar -- it is a look-alike the spec does
    not name, serving values of the same names and shapes that must not be
    taken.
    """

    def __init__(self, redirect_uri):
        self.redirect_uri = redirect_uri
        site = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def cookies(self):
                jar = {}
                for part in self.headers.get("Cookie", "").split(";"):
                    name, _, value = part.strip().partition("=")
                    if name:
                        jar[name] = value
                return jar

            def decoy(self):
                return self.headers.get("Host", "").startswith("localhost")

            def signed_in(self):
                return self.cookies().get("access_token", "").startswith("eyJ")

            def page(self, body, status=200, headers=(), title="Test site"):
                headers = [("Content-Security-Policy", SITE_CSP)] + list(headers)
                if "lang" not in self.cookies():
                    headers.append(("Set-Cookie", "lang=en; Path=/; SameSite=Lax"))
                document = (
                    "<!doctype html><html><head><title>%s</title></head><body>"
                    '<nav><a href="/">Home</a> <a href="/login">Log in</a></nav>%s</body></html>' % (title, body)
                )
                return _respond(self, status, document, headers=headers)

            def redirect(self, location, headers=()):
                self.send_response(303 if self.command == "POST" else 302)
                self.send_header("Location", location)
                self.send_header("Content-Length", "0")
                for name, value in headers:
                    self.send_header(name, value)
                self.end_headers()

            def do_GET(self):
                path = urllib.parse.urlsplit(self.path).path
                if path == "/":
                    headers = []
                    if "access_token" not in self.cookies():
                        # What a visitor gets before signing in. Same name as the
                        # real thing, and not the shape the spec's `match` wants.
                        headers.append(("Set-Cookie", "access_token=visitor; Path=/; HttpOnly; SameSite=Lax"))
                    spacer = "".join("<p>Filler paragraph %d.</p>" % n for n in range(60))
                    return self.page("<h1>Welcome</h1><div id='filler'>%s</div>" % spacer, headers=headers)
                if path == "/login":
                    return self.page(
                        '<form action="/session" method="post">'
                        '<p><label>E-mail <input type="email" name="email"></label></p>'
                        '<p><label>Password <input type="password" name="password"></label></p>'
                        '<p><button type="submit">Log in</button></p></form>'
                    )
                if path == "/account":
                    if not self.signed_in():
                        return self.redirect("/login")
                    which = "decoy" if self.decoy() else "real"
                    return self.page(
                        '<script>localStorage.setItem(\'auth\', \'{"user": "ann", "token": "ls-%s"}\');'
                        "sessionStorage.setItem('s', 'ss-%s');</script>"
                        '<h1>Your account</h1><p>API key: <code class="api-key">\n  KEY-%s  \n</code></p>'
                        '<p><a class="user-menu" data-user="ann-%s" href="/account">ann</a></p>'
                        '<p><a id="oauth" href="/oauth/authorize">Connect the app</a></p>'
                        % (which, which, which, which)
                    )
                if path == "/welcome":
                    return self.page(
                        '<h1>Welcome back</h1><p><a class="user-menu" href="/account">ann</a></p>'
                        '<p><button class="MuiButtonBase-root MuiButton-root">Log Out</button></p>'
                    )
                if path == "/buttons":
                    # Buttons nothing in CSS tells apart, the way a component
                    # library renders them: only their words differ. The first
                    # "Log In" is hidden, so the guide must pass over it.
                    button = '<button class="MuiButtonBase-root MuiButton-root" id="%s"%s>%s</button> '
                    return self.page(
                        "<h1>Choose</h1><p>"
                        + button % ("b-hidden", " hidden", "Log In")
                        + button % ("b-signup", "", "Sign Up")
                        + button % ("b-help", "", "Help")
                        + button % ("b-login", "", "LOG IN")
                        + "</p>"
                    )
                if path.startswith("/challenge/"):
                    # What Cloudflare's interactive check looks like from
                    # outside its widget, one marker at a time: the title, the
                    # widget's response field, the script that runs it.
                    marker = path.rsplit("/", 1)[-1]
                    body = "<h1>Performing security verification</h1><p>Verify you are human.</p>"
                    if marker == "input":
                        body += '<input type="hidden" id="cf-chl-widget-a1b2c_response" name="cf-turnstile-response">'
                    if marker == "script":
                        body += '<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1"></script>'
                    if marker == "detections":
                        # Not a check: what Cloudflare adds to every ordinary
                        # page of a site it protects.
                        body = '<h1>A page</h1><script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>'
                    title = "Just a moment..." if marker == "title" else "Test site"
                    return self.page(body, title=title)
                if path.startswith("/cdn-cgi/challenge-platform/"):
                    return _respond(self, 200, "/* the check's own script */", "text/javascript")
                if path == "/api/me":
                    if self.signed_in():
                        return _respond(self, 200, '{"user": "ann"}', "application/json")
                    return _respond(self, 401, '{"error": "not signed in"}', "application/json")
                if path == "/oauth/authorize":
                    return self.redirect(site.redirect_uri + "#access_token=oauth-abc&token_type=bearer")
                if path == "/not-a-start-page":
                    # A spec where only `pc login`'s start page may hand one over.
                    spec = json.dumps({"url": "http://127.0.0.1:1/", "capture": [{"name": "x", "ask": {}}]})
                    return self.page('<script type="application/json" id="partcad-login-spec">%s</script>' % spec)
                return _respond(self, 404, "not found")

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                self.rfile.read(length)
                if urllib.parse.urlsplit(self.path).path == "/session":
                    token = SIGNED_IN_TOKEN if not self.decoy() else "eyJkZWNveSJ9.eyJkZWNveSJ9.ZGVjb3k"
                    return self.redirect(
                        "/account", headers=[("Set-Cookie", "access_token=%s; Path=/; HttpOnly; SameSite=Lax" % token)]
                    )
                return _respond(self, 404, "not found")

        self.server = Server(Handler)
        self.url = "http://127.0.0.1:%d" % self.server.port
        self.decoy_url = "http://localhost:%d" % self.server.port

    def close(self):
        self.server.close()


@pytest.fixture
def closed_port():
    """A loopback port nothing answers on, held for the whole test.

    Bound and never listened on: a connection to it is refused, and no other
    process can take the port while the test relies on that.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    yield probe.getsockname()[1]
    probe.close()


@pytest.fixture
def site(closed_port):
    server = Site("http://127.0.0.1:%d/partcad/login/thingiverse" % closed_port)
    yield server
    server.close()


@pytest.fixture
def listeners():
    """Makes stub listeners, and closes whichever the test left open."""
    made = []

    def make(spec, **kwargs):
        listener = Listener(spec, **kwargs)
        made.append(listener)
        return listener

    yield make
    for listener in made:
        try:
            listener.close()
        except OSError:
            pass


@pytest.fixture
def launch(tmp_path):
    """Starts the browser, with the extension in it, once per test; closes it after."""
    binary = find_browser()
    if not binary:
        pytest.fail("PC_TEST_BROWSER_E2E is set, but no Chromium-family browser was found; set PC_TEST_BROWSER")
    headless = os.environ.get("PC_TEST_BROWSER_HEADED") != "1"
    started = []

    def start(**kwargs):
        assert not started, "one browser per test"
        devtools = DevTools(binary, tmp_path / "profile", tmp_path / "browser.log", headless=headless, **kwargs)
        started.append(devtools)
        devtools.load_extension()
        return devtools

    yield start
    for devtools in started:
        devtools.close()


@pytest.fixture
def browser(launch):
    return launch()


@pytest.fixture
def screenshots(tmp_path):
    """Where the test's screenshots go: under its own temporary directory, for whoever reads the run."""
    directory = tmp_path / "screenshots"
    directory.mkdir()
    return directory
