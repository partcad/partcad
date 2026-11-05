#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'pc login' end to end: the CLI, the daemon, the plugin in its sandbox, a real browser, the extension.

Opt-in (PC_TEST_LOGIN_E2E=1), and one process: it starts a browser, a daemon
and a sandboxed plugin, which is the whole point and nothing the parallel suite
should do. The browser is PC_LOGIN_BROWSER (a Chromium-family one; headless
unless PC_LOGIN_BROWSER_ARGS says otherwise).

The site is local: a sign-in page that sets a session cookie when it is
loaded - a user who signs in at once - and a 'who am I' that answers 200 only
with that cookie. The plugin is a script in a temporary package that asks for
the cookie, waits for 'who am I' in the browser, and checks what came back
against the site itself; what it returns has to arrive in the configuration
file, and a second 'pc login --check' has to find it good.
"""

import os
import subprocess
import sys
import textwrap
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import yaml

pytestmark = pytest.mark.skipif(
    os.environ.get("PC_TEST_LOGIN_E2E") != "1", reason="starts a browser, a daemon and a sandbox: PC_TEST_LOGIN_E2E=1"
)

SESSION = "signed-in-0123456789"

PLUGIN = textwrap.dedent("""
    import urllib.request

    def whoami(site, session):
        request = urllib.request.Request(site + "/api/me", headers={"Cookie": "session=" + session})
        try:
            with urllib.request.urlopen(request, timeout=10) as answer:
                return answer.read().decode() if answer.status == 200 else None
        except Exception:
            return None

    def login(request, partcad_login):
        site = request["parameters"]["site"]
        session = request["parameters"].get("session")
        if session and whoami(site, session):
            return {"parameters": {"session": session}, "message": "Already logged in as " + whoami(site, session)}
        got = partcad_login.open_browser(
            url=site + "/login",
            title="Local site",
            capture=[{"name": "session", "cookie": {"url": site + "/", "name": "session"}, "match": "^signed-in-"}],
            done_when={"fetch": {"url": site + "/api/me", "status": 200}},
            guide=[{"url": site + "/login*", "selector": "button", "contains": "sign in", "text": "Sign in"}],
            timeout=60,
        )
        who = whoami(site, got["session"])
        if not who:
            raise RuntimeError("the site did not take the session")
        return {"parameters": {"session": got["session"]}, "message": "Logged in as " + who}

    if __name__ == "login":
        output = {"result": login(request, partcad_login)}
    else:
        output = {}
    """)


class _Site(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.startswith("/login"):
            body = b"<html><body><h1>Example</h1><button>Help</button><button>Sign in</button></body></html>"
            self.send_response(200)
            self.send_header("Set-Cookie", "session=%s; Path=/; HttpOnly" % SESSION)
        elif self.path.startswith("/api/me") and ("session=%s" % SESSION) in (self.headers.get("Cookie") or ""):
            body = b"ann"
            self.send_response(200)
        else:
            body = b""
            self.send_response(401)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    # 'localhost', not 127.0.0.1: the listener 'pc login' runs is on 127.0.0.1,
    # and the extension tells its own pages from the site's by origin.
    yield "http://localhost:%d" % server.server_address[1]
    server.shutdown()


def _pc(workspace, home, *args):
    environment = dict(os.environ, HOME=str(home))
    environment.setdefault("PC_LOGIN_BROWSER_ARGS", "--headless=new --no-sandbox")
    # The 'pc' beside this interpreter: the one this checkout installed.
    pc = os.path.join(os.path.dirname(sys.executable), "pc.exe" if os.name == "nt" else "pc")
    return subprocess.run(
        [pc if os.path.exists(pc) else "pc", "--no-ansi", *args],
        cwd=workspace,
        env=environment,
        capture_output=True,
        text=True,
        timeout=900,
    )


def test_pc_login_signs_in_in_the_browser_and_keeps_what_the_extension_brought(tmp_path, site):
    if not os.environ.get("PC_LOGIN_BROWSER"):
        pytest.skip("PC_LOGIN_BROWSER names no browser to sign in with")
    workspace, home = tmp_path / "package", tmp_path / "home"
    workspace.mkdir()
    home.mkdir()
    (workspace / "auth.py").write_text(PLUGIN)
    (workspace / "partcad.yaml").write_text(textwrap.dedent("""
            repositories:
              auth_repo:
                type: basic
                path: auth.py
                parameters:
                  site: {type: string, default: "%s"}
                  session: {type: string, default: ""}
            """ % site))

    first = _pc(workspace, home, "login", "//:auth_repo")
    assert first.returncode == 0, first.stdout + first.stderr
    assert "Logged in as ann" in first.stdout + first.stderr
    saved = yaml.safe_load((home / ".partcad" / "config.yaml").read_text())
    assert saved["parameters"]["//:auth_repo"] == {"session": SESSION}

    again = _pc(workspace, home, "login", "--check", "//:auth_repo")
    assert again.returncode == 0, again.stdout + again.stderr
    assert "Already logged in as ann" in again.stdout + again.stderr
    _pc(workspace, home, "daemon", "stop")
