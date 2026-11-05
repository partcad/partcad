#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'pc login <package>:<plugin>': the client's half of a plugin's login.

A plugin's 'login' runs where every plugin runs, in the daemon's sandbox (see
'partcad_service_json_rpc.core.operations.plugin_login'). What it may ask for -
the user's browser, opened on the site's sign-in, with PartCAD's extension in
it to pick up what signing in leaves behind - can only happen here, on the
machine of whoever typed the command. So the login is a loop of steps:

1. ask the daemon for a step of the plugin's login ('plugin.login');
2. if the plugin needs the browser, run a listener on 127.0.0.1, open the
   browser on its start page, which hands the extension what to capture, and
   wait for the extension to send it back to the listener;
3. ask again, with that; until the plugin says it is logged in, and with what.

What it is logged in with is saved in the user's configuration file, under
'parameters', as overrides of the plugin's own parameters - the mechanism every
object's parameters already have, which hands them to the plugin in every
request from then on (see 'partcad_utils.user_config.save_parameter_overrides').

Cheap to import, like the rest of 'partcad_client'.
"""

import html
import json
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional

# How many times one 'pc login' goes round the loop: a plugin that asks for the
# browser again and again is not converging, and the user should hear so.
MAX_STEPS = 5
PREFIX = "/partcad/login/"


class LoginCancelled(Exception):
    """The user said no, in the browser."""


class LoginTimedOut(Exception):
    """Nothing came back from the browser in time."""


class _Step:
    def __init__(self, spec: dict):
        self.spec = spec
        self.nonce = secrets.token_hex(16)
        self.event = threading.Event()
        self.values: Optional[dict] = None
        self.cancelled = False

    def names(self):
        return [item.get("name") for item in self.spec.get("capture") or [] if item.get("name")]


class LoginListener:
    """The local HTTP listener the extension reports to (see the plugin documentation, "Logging in").

    Bound to 127.0.0.1 on a port the system picks. Every step has a nonce of
    its own, and a request for any other is a 404: the port can be found by
    anything on this machine, the nonce only by the browser it was handed to.
    """

    def __init__(self, host: str = "127.0.0.1"):
        self.host = host
        self._steps = {}
        self._server = None
        self._thread = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()

    def start(self):
        listener = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - the name http.server calls
                listener._answer(self)

            def log_message(self, *args):  # the terminal is the user's, not the listener's
                pass

        self._server = ThreadingHTTPServer((self.host, 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, name="pc-login-listener", daemon=True)
        self._thread.start()

    def stop(self):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    def _url(self, step: _Step, what: str) -> str:
        return "http://%s:%d%s%s/%s" % (self.host, self.port, PREFIX, step.nonce, what)

    def step(self, spec: dict) -> _Step:
        """Register a browser step: its start, done, manual and cancel URLs."""
        step = _Step(spec)
        self._steps[step.nonce] = step
        return step

    def start_url(self, step: _Step) -> str:
        return self._url(step, "start")

    def manual_url(self, step: _Step) -> str:
        return self._url(step, "manual")

    def wait(self, step: _Step, timeout: float) -> dict:
        """What the browser sent for 'step'. Raises LoginCancelled or LoginTimedOut."""
        if not step.event.wait(timeout):
            raise LoginTimedOut("nothing came back from the browser within %d seconds" % timeout)
        if step.cancelled:
            raise LoginCancelled("the login was cancelled in the browser")
        return dict(step.values or {})

    # -- requests --

    def _answer(self, request: BaseHTTPRequestHandler):
        # A request naming another host is a page that resolved its own name
        # to 127.0.0.1 (DNS rebinding), not the browser this was opened in.
        host = (request.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            return self._send(request, 403, "text/plain", "Forbidden")
        parts = urllib.parse.urlsplit(request.path)
        if not parts.path.startswith(PREFIX):
            return self._send(request, 404, "text/plain", "Not found")
        nonce, _, what = parts.path[len(PREFIX) :].partition("/")
        step = self._steps.get(nonce)
        if step is None:
            return self._send(request, 404, "text/plain", "Not found")
        query = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
        if what == "start":
            # Only while the step is waiting: the extension asks an earlier
            # step's start page whether its 'pc login' still waits, and
            # refuses a new one while it does - a step that is over must say so.
            if step.event.is_set():
                return self._send(request, 404, "text/plain", "Not found")
            return self._send(request, 200, "text/html", self._start_page(step))
        if what == "manual":
            return self._send(request, 200, "text/html", self._manual_page(step))
        if what == "done":
            names = set(step.names())
            if not step.event.is_set():
                step.values = {name: values[-1] for name, values in query.items() if name in names}
                step.event.set()
            if "json" in (request.headers.get("Accept") or ""):
                return self._send(request, 200, "application/json", json.dumps({"ok": True}))
            return self._send(
                request, 200, "text/html", self._page("Done", "PartCAD has it. You can close this window.")
            )
        if what == "cancel":
            if not step.event.is_set():
                step.cancelled = True
                step.event.set()
            return self._send(request, 200, "text/html", self._page("Cancelled", "The login was cancelled."))
        return self._send(request, 404, "text/plain", "Not found")

    @staticmethod
    def _send(request, status, content_type, body):
        data = body.encode("utf-8")
        request.send_response(status)
        request.send_header("Content-Type", content_type + "; charset=utf-8")
        request.send_header("Content-Length", str(len(data)))
        request.send_header("Cache-Control", "no-store")
        request.send_header("Referrer-Policy", "no-referrer")
        # The extension reports with a plain GET from its background; a page
        # cannot use this for anything without the nonce, which only the
        # browser it was handed to has.
        request.send_header("Access-Control-Allow-Origin", "*")
        request.end_headers()
        request.wfile.write(data)

    @staticmethod
    def _page(title, text, body=""):
        return (
            "<!doctype html><html><head><meta charset='utf-8'><title>PartCAD login: %s</title>"
            "<style>body{font-family:system-ui,sans-serif;max-width:40em;margin:4em auto;padding:0 1em;"
            "color:#222}code{background:#eee;padding:0 .2em}</style></head><body>"
            "<h1>%s</h1><p>%s</p>%s</body></html>" % (html.escape(title), html.escape(title), html.escape(text), body)
        )

    def _start_page(self, step: _Step) -> str:
        spec = dict(step.spec)
        spec["callback"] = self._url(step, "done")
        spec["manual"] = self._url(step, "manual")
        spec["cancel"] = self._url(step, "cancel")
        # '</' would end the script element early; JSON allows it escaped.
        data = json.dumps(spec).replace("</", "<\\/")
        title = spec.get("title") or spec.get("url")
        # The extension marks the page it took ('<html data-partcad-login=accepted>'),
        # which is when the note for a browser without it stops being true.
        body = (
            "<style>html[data-partcad-login=accepted] .partcad-no-extension{display:none}</style>"
            "<script type='application/json' id='partcad-login-spec'>%s</script>"
            "<p class='partcad-no-extension'>If nothing happens, PartCAD's extension is not in this browser: "
            "<a href='%s'>enter what is asked for by hand</a> instead.</p>" % (data, html.escape(spec["manual"]))
        )
        return self._page(title, "Starting the login to %s..." % title, body)

    def _manual_page(self, step: _Step) -> str:
        rows = []
        for item in step.spec.get("capture") or []:
            label = (item.get("ask") or {}).get("label") or _describe(item)
            secret = (item.get("ask") or {}).get("secret") or "ask" not in item
            rows.append(
                "<p><label>%s<br><input name='%s' type='%s' style='width:100%%' autocomplete='off'></label></p>"
                % (html.escape(label), html.escape(item["name"], quote=True), "password" if secret else "text")
            )
        form = (
            "<p>Sign in at <a href='%s' target='_blank' rel='noreferrer'>%s</a>, then copy each value here.</p>"
            "<form method='get' action='%s'>%s<p><button type='submit'>Done</button> "
            "<a href='%s'>Cancel</a></p></form>"
            % (
                html.escape(step.spec.get("url", ""), quote=True),
                html.escape(step.spec.get("url", "")),
                html.escape(self._url(step, "done"), quote=True),
                "".join(rows),
                html.escape(self._url(step, "cancel"), quote=True),
            )
        )
        return self._page(step.spec.get("title") or "PartCAD login", "Enter what the site gave you.", form)


def _describe(item: dict) -> str:
    """What a capture is, for a person who has to find it by hand."""
    if "cookie" in item:
        return "The '%s' cookie of %s" % (item["cookie"].get("name"), item["cookie"].get("url"))
    for store in ("localStorage", "sessionStorage"):
        if store in item:
            return "'%s' in the %s of %s" % (item[store].get("key"), store, item[store].get("origin"))
    if "redirect" in item:
        return "The '%s' in the address %s leads to" % (item["redirect"].get("param"), item["redirect"].get("url"))
    if "dom" in item:
        return "The value shown at %s" % item["dom"].get("url")
    return item.get("name", "")


# --- the loop ------------------------------------------------------------------------


def login(
    ask: Callable[[list, bool], dict],
    open_browser: Callable[[str, dict], object],
    say: Callable[[str], None],
    interactive: bool = True,
    manual: bool = False,
    timeout: Optional[float] = None,
) -> dict:
    """Log in, step by step, and return the daemon's last answer ({"status": "done", "parameters", ...}).

    'ask(browser_results, interactive)' asks the daemon for a step;
    'open_browser(url, spec)' opens the browser on 'url' and returns something
    with a 'close()', or None when it cannot (then the manual page is the way);
    'say' tells the user something. Raises RuntimeError for a login that failed.
    """
    results = []
    with LoginListener() as listener:
        for _ in range(MAX_STEPS):
            answer = ask(list(results), interactive)
            status = (answer or {}).get("status")
            if status == "done":
                return answer
            if status != "browser":
                raise RuntimeError((answer or {}).get("message") or "the login failed")
            spec = answer["spec"]
            step = listener.step(spec)
            title = spec.get("title") or spec.get("url")
            opened = None
            if not manual:
                opened = open_browser(listener.start_url(step), spec)
            if opened is None:
                say(
                    "Open %s in a browser, sign in to %s, and enter what it asks for."
                    % (listener.manual_url(step), title)
                )
            else:
                say(
                    "Opened %s for %s; sign in there. If the window does not take you there, open %s instead."
                    % (getattr(opened, "browser", "the browser"), title, listener.manual_url(step))
                )
            try:
                results.append(listener.wait(step, timeout or spec.get("timeout") or 600))
            finally:
                if opened is not None:
                    # A moment for the extension to close the window itself, which
                    # it does once the listener has answered; then make sure.
                    time.sleep(1)
                    opened.close()
        raise RuntimeError("the plugin asked for the browser %d times without being satisfied" % MAX_STEPS)
