#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The PartCAD extension, end to end, in a real editor: `pc ide install`, `pc ide workspace`, `pc ide view`.

What a person does on a first afternoon, done by the commands a person types:

1. `pc ide install` puts this tree's extension into an editor -- VSCodium, or
   any editor built on VS Code -- with a profile of its own;
2. `pc ide workspace examples` opens `./examples` as the workspace, which has to
   land in the PartCAD workbench;
3. `pc ide view --design-3d -a :logo` shows the logo assembly on the 3D tab, and
   it has to be drawn with nothing going wrong on the daemon's side (what `pc`
   printed, and what the extension logged of what the daemon told it) or in the
   viewer's JavaScript -- whichever of WebGL, WebGPU and the software painter the
   window ends up drawing with;
4. `pc ide view --analysis-fea :cantilever` opens the FEA tab on the cantilever,
   which runs the analysis, and that has to come back without an error either --
   unless this machine has no container runtime that can run a Linux image, the
   one excuse `pc test` accepts for an analysis that could not run (macOS and
   Windows runners; see `container_runtime`). Where the example's own `unless:`
   leaves the cantilever out (64-bit Arm, Apple silicon included), there is
   nothing to open: this step is not tried, and the test is reported as skipped
   once everything else has passed (see `excluded_here`).

The editor is driven over the Chrome DevTools protocol, which every editor built
on Electron speaks when started with `--remote-debugging-port`. Not through
Playwright: the viewer is a webview, and the page that draws it is an
out-of-process frame inside another out-of-process frame, which Playwright's
`connect_over_cdp` does not reach. Attaching to the webview's own target does,
and `Runtime.enable` replays what the webview logged before anybody attached --
which is what makes it possible to check for errors after the fact rather than
race the window as it starts.

**Off unless asked for.** It downloads an editor, builds the extension, starts a
daemon and builds a CAD sandbox if there is none, and runs a finite element
analysis: minutes on a warm machine, the better part of an hour on a cold one.
`PC_TEST_IDE_E2E=1` turns it on. Then:

* `PC_TEST_IDE_EDITOR` names the editor's launcher (`codium`, `code`, the
  PartCAD IDE's `partcad-ide`, or a path). Unset, VSCodium is downloaded from its
  GitHub release into `~/.cache/partcad/ide-e2e` -- and stock VS Code from
  Microsoft where that cannot be had -- for Linux, macOS or Windows, x64 or
  arm64. `GITHUB_TOKEN` is sent with the release lookup when it is set.
* `PC_TEST_IDE_VSIX` names the `.vsix` to install. Unset, it is built from
  `ide/vscode` (`npm run vsce-package`, which needs its `node_modules`).
* On Linux with no `DISPLAY`, an `Xvfb` is started for the duration.

CI runs it in the `IDE (end to end)` job of `.github/workflows/test.yml`.

Run it as::

    PC_TEST_IDE_E2E=1 poetry run pytest tests/ide/test_ide_e2e.py -p no:error-for-skips --dist no -s

The examples' daemon is stopped before and after, so that the one serving the
test has the test's environment -- the viewer port above all
(`PARTCAD_IDE_PORT`), which is what keeps this run off a PartCAD IDE the person
running it has open.
"""

import asyncio
import contextlib
import glob
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
EXAMPLES = os.path.join(REPO, "examples")
EXTENSION = os.path.join(REPO, "ide", "vscode")
CACHE = os.path.join(os.path.expanduser("~"), ".cache", "partcad", "ide-e2e")

# What is shown, named the way a person in './examples' names it.
LOGO = "//produce_assembly_assy:logo"
CANTILEVER = "//feature_cae:cantilever"

# How long each thing may take. Building is the slow part: the first show in a
# fresh sandbox installs the CAD stack, and the first FEA run installs a mesher
# and a solver.
WINDOW_TIMEOUT = 180
BUILD_TIMEOUT = 3600

pytestmark = pytest.mark.skipif(
    os.environ.get("PC_TEST_IDE_E2E") != "1",
    reason="the IDE end-to-end test runs only with PC_TEST_IDE_E2E=1 (see its docstring)",
)


# ---------------------------------------------------------------------------
# The editor, the extension and a display
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _github_headers() -> dict:
    """Headers for GitHub's API: a CI token where there is one, which is what keeps a shared runner under its rate limit."""
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "partcad-ide-e2e"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = "Bearer %s" % token
    return headers


def _download(url: str, dest: str) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "partcad-ide-e2e"})
    with urllib.request.urlopen(request, timeout=600) as response, open(dest + ".part", "wb") as out:  # nosec B310
        shutil.copyfileobj(response, out)
    os.replace(dest + ".part", dest)


def _unpack(archive: str, into: str) -> None:
    """A tarball or a zip, keeping what an application needs of it.

    On macOS a zip is unpacked by `ditto`, not by `zipfile`: an application bundle
    is made of symlinks and executable bits, and `zipfile` keeps neither.
    """
    os.makedirs(into, exist_ok=True)
    if archive.endswith((".tar.gz", ".tgz")):
        with tarfile.open(archive) as tar:
            tar.extractall(into, filter="data")
    elif sys.platform == "darwin":
        subprocess.run(["ditto", "-x", "-k", archive, into], check=True)
    else:
        with zipfile.ZipFile(archive) as zipped:
            zipped.extractall(into)


def _machine() -> str:
    """This machine's architecture, as both editors name their builds."""
    machine = platform.machine().lower()
    return {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(machine, machine)


def _platform() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform == "win32":
        return "win32"
    pytest.skip("no editor is downloaded for %s; name one with PC_TEST_IDE_EDITOR" % sys.platform)


# Where each build keeps its command line launcher, by platform: the one
# `pc ide install` and `pc ide workspace` are given, as a person would be.
_VSCODIUM_LAUNCHER = {
    "linux": ("bin", "codium"),
    "darwin": ("VSCodium.app", "Contents", "Resources", "app", "bin", "codium"),
    "win32": ("bin", "codium.cmd"),
}
_VSCODE_LAUNCHER = {
    "linux": ("VSCode-linux-%s", "bin", "code"),
    "darwin": ("Visual Studio Code.app", "Contents", "Resources", "app", "bin", "code"),
    "win32": ("bin", "code.cmd"),
}


def _vscodium() -> str:
    """VSCodium's launcher, downloaded from its latest GitHub release."""
    request = urllib.request.Request(
        "https://api.github.com/repos/VSCodium/vscodium/releases/latest", headers=_github_headers()
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # nosec B310
        release = json.load(response)
    system, machine, version = _platform(), _machine(), release["tag_name"]
    wanted = {
        "linux": "VSCodium-linux-%s-%s.tar.gz",
        "darwin": "VSCodium-darwin-%s-%s.zip",
        "win32": "VSCodium-win32-%s-%s.zip",
    }[system] % (machine, version)
    url = next(a["browser_download_url"] for a in release["assets"] if a["name"] == wanted)
    root = os.path.join(CACHE, "vscodium-%s-%s-%s" % (system, machine, version))
    launcher = os.path.join(root, *_VSCODIUM_LAUNCHER[system])
    if not os.path.exists(launcher):
        archive = os.path.join(CACHE, wanted)
        _download(url, archive)
        _unpack(archive, root)
        os.remove(archive)
    return launcher


def _vscode() -> str:
    """Stock VS Code's launcher, for where VSCodium's release cannot be reached."""
    system, machine = _platform(), _machine()
    build, archive_name = {
        "linux": ("linux-%s" % machine, "vscode.tar.gz"),
        "darwin": ("darwin-universal", "vscode.zip"),
        "win32": ("win32-%s-archive" % machine, "vscode.zip"),
    }[system]
    root = os.path.join(CACHE, "vscode-%s" % build)
    launcher = os.path.join(root, *(part.replace("%s", machine) for part in _VSCODE_LAUNCHER[system]))
    if not os.path.exists(launcher):
        archive = os.path.join(CACHE, archive_name)
        _download("https://update.code.visualstudio.com/latest/%s/stable" % build, archive)
        _unpack(archive, root)
        os.remove(archive)
    return launcher


@pytest.fixture(scope="module")
def editor() -> str:
    named = os.environ.get("PC_TEST_IDE_EDITOR")
    if named:
        return shutil.which(named) or named
    _platform()
    os.makedirs(CACHE, exist_ok=True)
    try:
        return _vscodium()
    except Exception as e:  # pylint: disable=broad-except
        print("VSCodium could not be downloaded (%s); using VS Code" % e)
        return _vscode()


@pytest.fixture(scope="module")
def vsix() -> str:
    named = os.environ.get("PC_TEST_IDE_VSIX")
    if named:
        return os.path.abspath(named)
    if not os.path.isdir(os.path.join(EXTENSION, "node_modules")):
        pytest.skip("no PC_TEST_IDE_VSIX, and ide/vscode has no node_modules to build one with (npm ci)")
    npm = shutil.which("npm")
    if npm is None:
        pytest.skip("no PC_TEST_IDE_VSIX, and no npm to build one with")
    subprocess.run([npm, "run", "vsce-package"], cwd=EXTENSION, check=True, stdout=subprocess.DEVNULL)
    return os.path.join(EXTENSION, "partcad.vsix")


@pytest.fixture(scope="module")
def display():
    """A display to open the window on: the one there is, or an Xvfb of our own."""
    if sys.platform != "linux" or os.environ.get("DISPLAY"):
        yield os.environ.get("DISPLAY")
        return
    xvfb = shutil.which("Xvfb")
    if xvfb is None:
        pytest.skip("no DISPLAY and no Xvfb to make one")
    number = next(n for n in range(90, 200) if not os.path.exists("/tmp/.X11-unix/X%d" % n))
    server = subprocess.Popen(
        [xvfb, ":%d" % number, "-screen", "0", "1600x1000x24", "-nolisten", "tcp"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 30
        while not os.path.exists("/tmp/.X11-unix/X%d" % number):
            assert server.poll() is None, "Xvfb exited"
            assert time.time() < deadline, "Xvfb did not start"
            time.sleep(0.2)
        yield ":%d" % number
    finally:
        server.terminate()
        server.wait(timeout=30)


# ---------------------------------------------------------------------------
# `pc`, and the editor's DevTools
# ---------------------------------------------------------------------------


def _pc_executable() -> str:
    """The `pc` of this interpreter's environment: the checkout under test."""
    found = os.path.join(os.path.dirname(sys.executable), "pc.exe" if sys.platform == "win32" else "pc")
    return found if os.path.exists(found) else shutil.which("pc")


def pc(env: dict, *args: str, cwd: str = EXAMPLES, timeout: float = BUILD_TIMEOUT) -> str:
    """Run `pc --no-ansi <args>` and return everything it printed; fail on a non-zero exit."""
    completed = subprocess.run(
        [_pc_executable(), "--no-ansi", *args],
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
    )
    print("$ pc %s\n%s" % (" ".join(args), completed.stdout))
    assert completed.returncode == 0, "pc %s exited %d:\n%s" % (" ".join(args), completed.returncode, completed.stdout)
    return completed.stdout


def daemon_errors(output: str) -> list:
    """The lines of `pc` output that say the daemon, or the viewer, had a problem."""
    problems = []
    for line in output.splitlines():
        if " ERROR:" in line or line.startswith("ERROR:") or "CRITICAL:" in line:
            problems.append(line)
        # Not an error to `pc` -- a show is a side effect and never fails the
        # command -- but the whole point here.
        if "No PartCAD IDE with an open Digital Thread detected" in line or "Failed to show" in line:
            problems.append(line)
    return problems


class DevTools:
    """Just enough of the Chrome DevTools protocol, over `aiohttp`, to read the editor's webviews."""

    def __init__(self, port: int):
        self.port = port

    def targets(self) -> list:
        with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % self.port, timeout=5) as response:  # nosec
            return json.load(response)

    def partcad_webviews(self) -> list:
        return [
            t
            for t in self.targets()
            if t.get("type") == "iframe" and "extensionId=PartCAD.partcad-official" in t.get("url", "")
        ]

    def workbench(self) -> dict:
        return next(t for t in self.targets() if t.get("type") == "page" and "workbench" in t.get("url", ""))

    def session(self, target: dict, expressions=()) -> tuple:
        """Attach to a target: what it logged so far, and the value of each expression."""
        return asyncio.run(self._session(target["webSocketDebuggerUrl"], list(expressions)))

    async def _session(self, url: str, expressions: list) -> tuple:
        import aiohttp

        events, values = [], []
        async with aiohttp.ClientSession() as http:
            async with http.ws_connect(url, max_msg_size=0) as ws:
                counter = 0

                async def call(method, params=None):
                    nonlocal counter
                    counter += 1
                    mine = counter
                    await ws.send_json({"id": mine, "method": method, "params": params or {}})
                    while True:
                        message = await asyncio.wait_for(ws.receive_json(), 30)
                        if message.get("id") == mine:
                            if "error" in message:
                                raise RuntimeError("%s: %s" % (method, message["error"]))
                            return message["result"]
                        events.append(message)

                # Replays what was logged before anybody attached.
                await call("Runtime.enable")
                with contextlib.suppress(asyncio.TimeoutError):
                    while True:
                        events.append(await asyncio.wait_for(ws.receive_json(), 0.5))
                for expression in expressions:
                    result = await call("Runtime.evaluate", {"expression": expression, "returnByValue": True})
                    values.append(result.get("result", {}).get("value"))
        return events, values


def js_errors(events: list) -> list:
    """What a webview said went wrong: console errors and uncaught exceptions."""
    errors = []
    for event in events:
        params = event.get("params", {})
        if event.get("method") == "Runtime.consoleAPICalled" and params.get("type") in ("error", "assert"):
            errors.append(
                "console.%s: %s"
                % (params["type"], " ".join(str(a.get("value", a.get("description", ""))) for a in params["args"]))
            )
        if event.get("method") == "Runtime.exceptionThrown":
            details = params.get("exceptionDetails", {})
            errors.append(
                "uncaught: %s" % (details.get("exception", {}).get("description") or details.get("text") or details)
            )
    return errors


# The viewer's document is the webview's inner frame ('active-frame'), which has
# the outer one's origin, so it is reached through it.
_VIEWER = "document.getElementById('active-frame')?.contentDocument"

# What the viewer shows, read off its DOM: which pane is on screen, whether the
# 3D view has drawn, what the FEA pane says, and whether anything was trapped
# into the overlay ('host.ts' puts every uncaught error there).
VIEWER_PROBE = """(() => {
    const d = %s;
    if (!d || !d.getElementById('pane-3d')) return null;
    const text = (id) => d.getElementById(id)?.innerText ?? null;
    const fea = d.getElementById('pane-fea');
    return {
        overlay: text('overlay'),
        failure: d.getElementById('overlay')?.classList.contains('failure') ?? false,
        drawn: !!d.querySelector('#pane-3d canvas'),
        fea: fea ? {
            text: fea.innerText,
            busy: [...fea.querySelectorAll('.placeholder')].map((p) => p.innerText),
            errors: [...fea.querySelectorAll('.error')].map((p) => p.innerText),
            severities: [...fea.querySelectorAll('.cae-severity')].map((p) => p.innerText),
            model: !!fea.querySelector('.cae-canvas, canvas, img'),
        } : null,
    };
})()""" % _VIEWER

SIDEBAR_TITLE = "document.querySelector('.part.sidebar .title-label')?.innerText ?? null"


def wait_for(what: str, probe, timeout: float, interval: float = 2.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            last = probe()
        except Exception as e:  # pylint: disable=broad-except
            last = e
        else:
            if last:
                return last
        time.sleep(interval)
    raise AssertionError("timed out waiting for %s (last: %r)" % (what, last))


def extension_log_errors(user_data_dir: str) -> list:
    """`[error]` lines the PartCAD extension logged: what the daemon told it went wrong, among others."""
    errors = []
    for path in glob.glob(os.path.join(user_data_dir, "logs", "*", "window*", "exthost", "PartCAD.*", "*.log")):
        with open(path, encoding="utf-8", errors="replace") as f:
            errors += [line.rstrip() for line in f if "[error]" in line]
    return errors


# ---------------------------------------------------------------------------
# The test
# ---------------------------------------------------------------------------


@pytest.fixture
def session(editor, vsix, display):
    """An editor profile of its own, the environment every process here runs in, and clean-up."""
    root = tempfile.mkdtemp(prefix="partcad-ide-e2e-")
    user_data_dir = os.path.join(root, "user")
    extensions_dir = os.path.join(root, "extensions")
    os.makedirs(os.path.join(user_data_dir, "User"))
    with open(os.path.join(user_data_dir, "User", "settings.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "security.workspace.trust.enabled": False,
                # The service of this checkout, not one the extension would
                # otherwise offer to download.
                "partcad.servicePath": os.path.join(
                    os.path.dirname(_pc_executable()),
                    "partcad-json-rpc.exe" if sys.platform == "win32" else "partcad-json-rpc",
                ),
                "workbench.startupEditor": "none",
                "telemetry.telemetryLevel": "off",
                "extensions.autoUpdate": False,
                "extensions.autoCheckUpdates": False,
                "update.mode": "none",
                "chat.disableAIFeatures": True,
            },
            f,
        )
    env = dict(os.environ)
    env.update(
        {
            "PARTCAD_IDE_PORT": str(_free_port()),
            # Nothing here can answer a dialog.
            "PARTCAD_EXTENSION_NO_PROMPTS": "1",
        }
    )
    if display:
        env["DISPLAY"] = display
    devtools = DevTools(_free_port())
    profile = ["--extensions-dir", extensions_dir, "--user-data-dir", user_data_dir]
    window = profile + [
        "--remote-debugging-port=%d" % devtools.port,
        "--skip-welcome",
        "--skip-release-notes",
        "--disable-workspace-trust",
    ]
    if sys.platform.startswith("linux"):
        # Chromium's sandbox needs unprivileged user namespaces or a setuid
        # helper, and on Linux this has neither for certain: an editor unpacked
        # from a tarball has no setuid `chrome-sandbox`, and GitHub's Ubuntu
        # 24.04 runners restrict unprivileged user namespaces -- where the window
        # dies before it writes a single log line. Electron also refuses to run
        # as root with the sandbox on. `build-ide-standalone.yml` passes the same
        # flag for the same reason, and so does `@vscode/test-electron`.
        window.append("--no-sandbox")

    # The daemon serving './examples' has to be one started with this
    # environment, or it shows on whatever port it was started with.
    pc(env, "daemon", "stop", timeout=120)
    state = {
        "editor": editor,
        "vsix": vsix,
        "env": env,
        "profile": profile,
        "window": window,
        "devtools": devtools,
        "user_data_dir": user_data_dir,
        "extensions_dir": extensions_dir,
        # Every screenshot `pc ide state` reported, for the artifacts below.
        "screenshots": [],
    }
    try:
        yield state
    finally:
        with contextlib.suppress(Exception):
            browser = json.load(urllib.request.urlopen("http://127.0.0.1:%d/json/version" % devtools.port, timeout=5))
            asyncio.run(_close(browser["webSocketDebuggerUrl"]))
        with contextlib.suppress(Exception):
            pc(env, "daemon", "stop", timeout=120)
        keep_artifacts(state)
        shutil.rmtree(root, ignore_errors=True)


def keep_artifacts(state: dict) -> None:
    """Copy the editor's logs and the viewer's screenshots to `PC_TEST_IDE_ARTIFACTS`, when it is set.

    What a red CI cell is read by: the extension's own log (what the daemon told
    it), the editor's renderer and extension host logs, and what the viewer was
    showing each time it was asked.
    """
    target = os.environ.get("PC_TEST_IDE_ARTIFACTS")
    if not target:
        return
    os.makedirs(target, exist_ok=True)
    with contextlib.suppress(Exception):
        shutil.copytree(os.path.join(state["user_data_dir"], "logs"), os.path.join(target, "logs"), dirs_exist_ok=True)
    for screenshot in state["screenshots"]:
        with contextlib.suppress(Exception):
            shutil.copy2(screenshot, target)


async def _close(url: str) -> None:
    import aiohttp

    async with aiohttp.ClientSession() as http:
        async with http.ws_connect(url) as ws:
            await ws.send_json({"id": 1, "method": "Browser.close"})
            with contextlib.suppress(Exception):
                await asyncio.wait_for(ws.receive_json(), 10)


def test_install_open_view_and_analyse_in_a_real_editor(session):
    env, devtools = session["env"], session["devtools"]
    # Asked before anything starts: it builds a context of its own, and the
    # daemon is not running yet to share the examples' caches with.
    cantilever_left_out = excluded_here(CANTILEVER)

    # 1. The extension, from a package, into the editor's own profile.
    pc(env, "ide", "install", "--with", session["editor"], "--vsix", session["vsix"], "--", *session["profile"])
    installed = os.listdir(session["extensions_dir"])
    assert any(name.lower().startswith("partcad.partcad-official-") for name in installed), installed

    # 2. './examples' as the workspace, in the PartCAD workbench.
    pc(env, "ide", "workspace", "--with", session["editor"], EXAMPLES, "--", *session["window"])
    try:
        wait_for("the editor's DevTools", lambda: devtools.workbench(), WINDOW_TIMEOUT)
    except AssertionError as e:
        raise AssertionError("%s\n%s" % (e, editor_startup_report(session["user_data_dir"]))) from None
    title = wait_for(
        "the PartCAD workbench",
        lambda: (lambda value: value if value and value.strip().upper() == "PARTCAD" else None)(
            devtools.session(devtools.workbench(), [SIDEBAR_TITLE])[1][0]
        ),
        WINDOW_TIMEOUT,
    )
    assert title.strip().upper() == "PARTCAD"
    # The request was taken, by this window.
    requests = os.path.join(env.get("HOME") or os.path.expanduser("~"), ".partcad", "ide", "requests")
    assert not glob.glob(os.path.join(requests, "*.json"))
    # The extension is up when its viewer port answers `pc ide state`.
    wait_for(
        "the PartCAD extension to listen",
        lambda: subprocess.run(
            [_pc_executable(), "--no-ansi", "ide", "state", "--json", "--timeout", "10"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0,
        WINDOW_TIMEOUT,
    )

    # 3. The logo assembly, on the 3D tab.
    output = pc(env, "ide", "view", "--design-3d", "-a", LOGO)
    assert daemon_errors(output) == []

    def viewer_state():
        viewer = json.loads(pc(env, "ide", "state", "--json", timeout=120))["viewer"]
        if viewer.get("screenshot"):
            session["screenshots"].append(viewer["screenshot"])
        return viewer

    viewer = wait_for(
        "the logo on the 3D tab",
        lambda: (lambda v: v if (v.get("subject") or {}).get("name") == "logo" and v.get("subTab") == "3d" else None)(
            viewer_state()
        ),
        WINDOW_TIMEOUT,
    )
    assert viewer["tab"] == "design"
    assert viewer["screenshot"] and os.path.getsize(viewer["screenshot"]) > 1000, viewer

    def viewer_webview():
        for target in devtools.partcad_webviews():
            events, (probe,) = devtools.session(target, [VIEWER_PROBE])
            if probe is not None:
                return target, events, probe
        return None

    _, events, probe = wait_for("the Digital Thread's webview", viewer_webview, WINDOW_TIMEOUT)
    assert probe["drawn"], probe
    assert not probe["failure"], probe["overlay"]
    for target in devtools.partcad_webviews():
        assert js_errors(devtools.session(target)[0]) == [], target["url"]

    # 4. The cantilever, on the FEA tab: selecting it runs the analysis -- where
    # this machine has a cantilever to select.
    excused = False
    if cantilever_left_out is None:
        output = pc(env, "ide", "view", "--analysis-fea", CANTILEVER)
        assert daemon_errors(output) == []

        def analysed():
            found = viewer_webview()
            if found is None:
                return None
            _, _, probe = found
            fea = probe["fea"]
            running = any(text.startswith(("Running", "Waiting", "Select this tab", "Asking")) for text in fea["busy"])
            return None if running or not (fea["errors"] or fea["model"] or fea["severities"] or fea["busy"]) else probe

        probe = wait_for("the FEA result", analysed, BUILD_TIMEOUT, interval=5)
        viewer = viewer_state()
        assert (viewer["subject"]["name"], viewer["tab"], viewer["subTab"]) == ("cantilever", "analysis", "fea")
        excused = probe["fea"]["errors"] and not container_runtime()
        if excused:
            # The one excuse `pc test` accepts for an analysis that came back with
            # nothing (see `CaeTest._verdict`): no container runtime that can run a
            # Linux image -- macOS, and Windows' Windows-container daemon -- so the
            # solver the implementation's image carries could never have been had.
            # Everything else about the tab still has to hold.
            print("NOTE: the FEA was not run, and is excused -- no container runtime here:\n%s" % probe["fea"]["text"])
        else:
            assert probe["fea"]["errors"] == [], probe["fea"]["text"]
        assert "error" not in [severity.lower() for severity in probe["fea"]["severities"]], probe["fea"]["text"]
        assert not probe["failure"], probe["overlay"]
        for target in devtools.partcad_webviews():
            assert js_errors(devtools.session(target)[0]) == [], target["url"]

    # What the extension heard from the daemon over the whole session -- less the
    # one line saying the excused analysis did not run, when it was excused.
    logged = extension_log_errors(session["user_data_dir"])
    if excused:
        logged = [line for line in logged if "failed to fetch the 'fea' tab" not in line]
    assert logged == []

    # Last, so that everything this machine could check has been: a skip says
    # what was not tried, and must not stand in for what was.
    if cantilever_left_out is not None:
        pytest.skip(
            "%s is excluded here by 'unless' (%s), so the FEA tab was not tried; everything else passed"
            % (CANTILEVER, cantilever_left_out)
        )


def editor_startup_report(user_data_dir: str) -> str:
    """What the editor said as it started, for a window that never answered: the end of its main log, or that there is none.

    No log at all means it died before it got that far -- on Linux, most often
    the Chromium sandbox (see `--no-sandbox` in `session`).
    """
    logs = sorted(glob.glob(os.path.join(user_data_dir, "logs", "*", "main.log")))
    if not logs:
        return "The editor wrote no log under %s: it did not get as far as starting." % user_data_dir
    with open(logs[-1], encoding="utf-8", errors="replace") as f:
        tail = f.readlines()[-40:]
    return "The end of %s:\n%s" % (logs[-1], "".join(tail))


def excluded_here(path: str):
    """The `unless:` clause that leaves the object at `path` out on this machine, or None if it is here.

    PartCAD's own answer, from a context over './examples', rather than a guess
    from `platform.machine()`: asking the declaration is what keeps this test and
    the example from drifting apart, which is why `test_part_example_kicad` asks
    the same way. A package left out leaves everything in it out.
    """
    import partcad

    package, _, name = path.rpartition(":")
    project = partcad.init(EXAMPLES).get_project(package)
    if project.skipped:
        return project.skipped_by
    for kind in ("sketch", "part", "assembly", "scene"):
        clause = project.get_skipped_object_clause(kind, name)
        if clause is not None:
            return clause
    return None


def container_runtime() -> bool:
    """Whether this machine could have run the analysis's container: `pc test`'s own question, asked the same way."""
    if os.environ.get("PC_PYTHON_SANDBOX") == "remote":
        return True
    from partcad import runtime

    return runtime.docker_available()
