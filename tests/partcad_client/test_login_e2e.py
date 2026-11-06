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

Before anything is captured, the extension asks on a page of its own whether
the login is wanted (see browsers/README.md); the test says yes there, the
way a user does, through the browser's DevTools on a port it adds for that.
"""

import asyncio
import os
import subprocess
import sys
import textwrap
import threading
import time
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


def _pc(workspace, home, *args, wait=True):
    environment = dict(os.environ, HOME=str(home))
    # A DevTools port beside the pipe 'pc login' holds, for the test to say yes
    # on the extension's confirmation page; Chromium writes which port it took
    # into the profile, which is where '_confirm' finds it.
    environment["PC_LOGIN_BROWSER_ARGS"] = (
        environment.get("PC_LOGIN_BROWSER_ARGS", "--headless=new --no-sandbox") + " --remote-debugging-port=0"
    )
    environment["PC_LOGIN_PROFILE_DIR"] = str(home / "login-browser")
    # The plugin checks the session with the site this test serves on the
    # runner's 'localhost'. In the 'docker' sandbox - the default wherever a
    # Docker daemon answers, as on CI - 'localhost' is the container, and the
    # site is not there. What is tested is the login, not the sandbox's network.
    environment["PC_PYTHON_SANDBOX"] = "venv"
    # The 'pc' beside this interpreter: the one this checkout installed.
    pc = os.path.join(os.path.dirname(sys.executable), "pc.exe" if os.name == "nt" else "pc")
    command = [pc if os.path.exists(pc) else "pc", "--no-ansi", *args]
    if not wait:
        return subprocess.Popen(
            command, cwd=workspace, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
    return subprocess.run(command, cwd=workspace, env=environment, capture_output=True, text=True, timeout=900)


async def _press_continue(profile, timeout):
    """Find the extension's confirmation page over the browser's DevTools port, and press Continue once armed."""
    import aiohttp

    deadline = time.monotonic() + timeout
    port_file = profile / "DevToolsActivePort"
    # Not through a proxy the environment may name: this is the browser on this machine.
    async with aiohttp.ClientSession(trust_env=False) as http:
        page = None
        while page is None:
            assert time.monotonic() < deadline, "the confirmation page never opened"
            await asyncio.sleep(0.2)
            if not port_file.exists():
                continue
            port = int(port_file.read_text().split()[0])
            try:
                async with http.get("http://127.0.0.1:%d/json/list" % port) as answer:
                    targets = await answer.json()
            except aiohttp.ClientError:
                continue
            page = next((t for t in targets if t.get("url", "").split("#")[0].endswith("/confirm.html")), None)
        async with http.ws_connect(page["webSocketDebuggerUrl"]) as socket:
            press = (
                "new Promise((resolve) => { const tick = () => {"
                " const button = document.getElementById('continue');"
                " if (button && !button.disabled) { button.click(); resolve(true); } else { setTimeout(tick, 100); }"
                " }; tick(); })"
            )
            await socket.send_json(
                {"id": 1, "method": "Runtime.evaluate", "params": {"expression": press, "awaitPromise": True}}
            )
            while True:
                answer = await socket.receive_json(timeout=max(1, deadline - time.monotonic()))
                if answer.get("id") == 1:
                    assert "exceptionDetails" not in answer.get("result", {}), answer
                    return


def _login_confirming(workspace, home, *args):
    """'pc login', with Continue pressed on the extension's confirmation page as a user would."""
    running = _pc(workspace, home, *args, wait=False)
    try:
        asyncio.run(_press_continue(home / "login-browser" / "profile", timeout=300))
        output, _ = running.communicate(timeout=600)
    finally:
        if running.poll() is None:
            running.kill()
            running.communicate()
    return subprocess.CompletedProcess(running.args, running.returncode, output, "")


def test_pc_login_signs_in_in_the_browser_and_keeps_what_the_extension_brought(tmp_path, site):
    if not os.environ.get("PC_LOGIN_BROWSER"):
        pytest.skip("PC_LOGIN_BROWSER names no browser to sign in with")
    workspace, home = tmp_path / "package", tmp_path / "home"
    workspace.mkdir()
    home.mkdir()
    (workspace / "auth.py").write_text(PLUGIN)
    # The 'venv' sandbox (see '_pc') is built from this host's interpreter
    # whatever version a package asks for, so ask for that one: asked for the
    # default 3.11 on a 3.14 host, it installs what 3.11 needs - the
    # 'backports.zstd' that 3.14 has no release of - and fails before the login.
    (workspace / "partcad.yaml").write_text(textwrap.dedent("""
            pythonVersion: "%d.%d"
            repositories:
              auth_repo:
                type: basic
                path: auth.py
                parameters:
                  site: {type: string, default: "%s"}
                  session: {type: string, default: ""}
            """ % (sys.version_info[0], sys.version_info[1], site)))

    first = _login_confirming(workspace, home, "login", "//:auth_repo")
    assert first.returncode == 0, first.stdout + first.stderr
    assert "Logged in as ann" in first.stdout + first.stderr
    saved = yaml.safe_load((home / ".partcad" / "config.yaml").read_text())
    assert saved["parameters"]["//:auth_repo"] == {"session": SESSION}

    again = _pc(workspace, home, "login", "--check", "//:auth_repo")
    assert again.returncode == 0, again.stdout + again.stderr
    assert "Already logged in as ann" in again.stdout + again.stderr
    _pc(workspace, home, "daemon", "stop")
