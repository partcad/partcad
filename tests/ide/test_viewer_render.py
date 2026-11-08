#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The IDE's 3D view draws a finish as a shaded `pc render` does, on WebGL and on WebGPU.

`raster_scene.finished_light` says how a face whose CMF finish states its roughness
and metalness is lit, and the 3D view says the same thing three ways: a patch to
three's Phong shader under WebGL, a lighting model of its own under WebGPU, and the
same arithmetic on the CPU in the canvas painter (`ide/vscode/src/webview/finish.ts`).
The painter's arithmetic is pinned by the extension's own tests; the two shaders
cannot be checked without a GPU, which is what this is for.

A sphere is drawn with the view's own materials under the view's own light rig, in
a real Chromium-family browser (SwiftShader where there is no GPU), into a
floating point target before tone mapping, and each sampled pixel is compared with
what `finished_light` says it is at that point. Rough and smooth, metal and not,
drawn with an image, and switched off as the Opacity slider below 100% switches
it - and with no finish at all, which holds the harness itself to three's Phong.

**Off unless asked for**: `PC_TEST_IDE_RENDER=1`. It needs the extension's
`node_modules` (`npm ci` in `ide/vscode`), `npx` to fetch the pinned esbuild that
bundles the page, and a browser: `PC_TEST_BROWSER`, or the first of Google Chrome
or Chromium on `PATH`, then Playwright's. CI runs it in the `IDE (end to end)` job
on Linux. Where the browser has no WebGPU adapter, the WebGPU half is skipped and
says why.

    PC_TEST_IDE_RENDER=1 poetry run pytest tests/ide/test_viewer_render.py -p no:error-for-skips --dist no
"""

import asyncio
import contextlib
import functools
import glob
import http.server
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("PC_TEST_IDE_RENDER") != "1",
    reason="set PC_TEST_IDE_RENDER=1 to draw the 3D view's finishes in a real browser",
)

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
EXTENSION = os.path.join(REPO, "ide", "vscode")
ENTRY = os.path.join(os.path.dirname(__file__), "viewer_render", "entry.ts")
# Pinned, like every tool a CI job fetches. Bump it deliberately.
ESBUILD = "esbuild@0.24.0"

GOLDENROD = 0xDAA520
COPPER = 0xB87333
RED = 0xFF0000
SLATE = 0x336699
CASES = [
    {"color": GOLDENROD},
    {"color": GOLDENROD, "finish": {"roughness": 0.5, "metallic": 0.0}},
    {"color": COPPER, "finish": {"roughness": 0.3, "metallic": 1.0}},
    {"color": RED, "finish": {"roughness": 0.15, "metallic": 0.5}},
    {"color": SLATE, "finish": {"roughness": 0.9, "metallic": 0.0}},
    {"color": COPPER, "finish": {"roughness": 0.3, "metallic": 1.0}, "plain": True},
    {"color": COPPER, "finish": {"roughness": 0.3, "metallic": 1.0}, "textured": True},
    {"color": RED, "finish": {"roughness": 0.15, "metallic": 0.5}, "textured": True},
]

# How far a pixel may be from 'finished_light': float arithmetic in a shader
# against numpy's, and a sphere of triangles against a sphere. Measured at
# well under these on SwiftShader (a median of 0.05%, the 95th percentile at
# 0.6% for the sharpest highlight).
MEDIAN = 0.005
PERCENTILE_95 = 0.02


def _find_browser():
    named = os.environ.get("PC_TEST_BROWSER")
    if named:
        return shutil.which(named) or named
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    roots = [
        os.environ.get("PLAYWRIGHT_BROWSERS_PATH"),
        "/opt/pw-browsers",
        os.path.expanduser("~/.cache/ms-playwright"),
    ]
    for root in filter(None, roots):
        for candidate in sorted(glob.glob(os.path.join(root, "chromium-*", "chrome-linux*", "chrome")), reverse=True):
            return candidate
    return None


def _free_port():
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="module")
def page_dir():
    """The page and its bundle, in a directory of their own."""
    npx = shutil.which("npx")
    if npx is None:
        pytest.fail("npx is needed to bundle the page")
    if not os.path.isdir(os.path.join(EXTENSION, "node_modules", "three")):
        pytest.fail("the extension's dependencies are not installed: run 'npm ci' in ide/vscode")
    root = tempfile.mkdtemp(prefix="partcad-viewer-render-")
    env = dict(os.environ, NODE_PATH=os.path.join(EXTENSION, "node_modules"))
    bundled = subprocess.run(
        [
            npx,
            "--yes",
            ESBUILD,
            ENTRY,
            "--bundle",
            "--format=iife",
            "--log-level=warning",
            "--resolve-extensions=.ts,.js",
            "--outfile=%s" % os.path.join(root, "bundle.js"),
        ],
        cwd=EXTENSION,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=600,
    )
    assert bundled.returncode == 0, "esbuild failed:\n%s" % bundled.stdout
    with open(os.path.join(root, "index.html"), "w", encoding="utf-8") as page:
        # 'surface.ts' reports to the extension host, which a plain page stands in for.
        page.write(
            "<!doctype html><html><body>"
            "<script>window.acquireVsCodeApi = () => ({ postMessage() {}, getState() {}, setState() {} });</script>"
            '<script src="bundle.js"></script></body></html>'
        )
    yield root
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture(scope="module")
def page_url(page_dir):
    """The page, served from this machine: WebGPU is offered to a secure context, which 'localhost' is."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=page_dir)
    handler.log_message = lambda *args: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "http://localhost:%d/index.html" % server.server_address[1]
    server.shutdown()


@pytest.fixture(scope="module")
def browser(page_url):
    """A headless browser on a profile of its own, on the page, with its DevTools port."""
    binary = _find_browser()
    if binary is None:
        pytest.fail("no Chromium-family browser found; set PC_TEST_BROWSER")
    port = _free_port()
    profile = tempfile.mkdtemp(prefix="partcad-viewer-render-profile-")
    process = subprocess.Popen(
        [
            binary,
            "--headless=new",
            "--remote-debugging-port=%d" % port,
            "--user-data-dir=%s" % profile,
            "--no-first-run",
            "--no-default-browser-check",
            "--no-sandbox",
            "--no-proxy-server",
            # A GPU where there is none: SwiftShader, for WebGL and for WebGPU.
            "--use-gl=angle",
            "--use-angle=swiftshader",
            "--enable-unsafe-swiftshader",
            "--enable-unsafe-webgpu",
            "--enable-features=Vulkan",
            "--use-webgpu-adapter=swiftshader",
            page_url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 60
        while True:
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % port, timeout=5) as response:  # nosec
                    pages = [t for t in json.load(response) if t.get("type") == "page" and t.get("url") == page_url]
                if pages:
                    break
            except OSError:
                pass
            if time.monotonic() > deadline or process.poll() is not None:
                pytest.fail("the browser did not open the page (%s)" % binary)
            time.sleep(0.25)
        yield pages[0]["webSocketDebuggerUrl"]
    finally:
        process.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(10)
        shutil.rmtree(profile, ignore_errors=True)


def _evaluate(url: str, expression: str):
    """The value of 'expression', awaited, in the page at DevTools 'url', once the page has loaded its bundle.

    The browser lists the page as soon as it opens it, before its script has
    run, so 'run' is waited for rather than assumed - with a minute of headroom,
    since the bundle is three twice over (its core and its WebGPU build).
    """

    async def session():
        import aiohttp

        async with aiohttp.ClientSession() as http_session:
            async with http_session.ws_connect(url, max_msg_size=0) as ws:
                counter = 0

                async def evaluate(text):
                    nonlocal counter
                    counter += 1
                    mine = counter
                    params = {"expression": text, "awaitPromise": True, "returnByValue": True}
                    await ws.send_json({"id": mine, "method": "Runtime.evaluate", "params": params})
                    while True:
                        message = await asyncio.wait_for(ws.receive_json(), 300)
                        if message.get("id") == mine:
                            break
                    if "exceptionDetails" in message.get("result", {}):
                        raise RuntimeError(message["result"]["exceptionDetails"])
                    return message["result"]["result"].get("value")

                deadline = time.monotonic() + 60
                while await evaluate("typeof run === 'function' && typeof surface === 'function'") is not True:
                    if time.monotonic() > deadline:
                        raise RuntimeError("the page did not load its bundle")
                    await asyncio.sleep(0.2)
                return await evaluate(expression)

    return asyncio.run(session())


def _expected(case, points, eye):
    """What 'raster_scene' draws each point of the unit sphere as, for 'case': three's frame turned into PartCAD's."""
    import numpy as np

    import partcad as pc

    render = os.path.join(os.path.dirname(pc.__file__), "builtin", "render")
    if render not in sys.path:
        sys.path.append(render)
    import raster_scene

    def to_partcad(vectors):
        vectors = np.asarray(vectors, dtype=np.float64)
        # glTF's (x, y, z) is PartCAD's (x, -z, y).
        return np.stack([vectors[:, 0], -vectors[:, 2], vectors[:, 1]], axis=1)

    p = to_partcad(points)
    n = p / np.linalg.norm(p, axis=1, keepdims=True)
    eye = to_partcad([eye])[0]
    c = case["color"]
    channels = np.array([(c >> 16) & 255, (c >> 8) & 255, c & 255]) / 255.0
    albedo = np.repeat([raster_scene.srgb_to_linear(channels)], len(p), axis=0)
    irradiance = raster_scene.diffuse(p, n, 1.0)
    if "finish" in case and not case.get("plain"):
        finish = case["finish"]
        roughness = np.full(len(p), finish["roughness"])
        metallic = np.full(len(p), finish["metallic"])
        lit = raster_scene.finished_light(p, n, eye, 1.0, albedo, roughness, metallic, irradiance)
        # A one-pixel image of the colour is that colour, as '_textured' tints a metal by it.
        return albedo * lit[0][:, None] + lit[1]
    return albedo * (irradiance / np.pi)[:, None] + raster_scene.specular(p, n, eye, 1.0)[:, None]


@pytest.mark.parametrize("backend", ["webgl", "webgpu"])
def test_the_3d_view_draws_a_finish_as_the_shaded_render_does(browser, backend):
    import numpy as np

    answer = _evaluate(browser, "run(%s, %s)" % (json.dumps(backend), json.dumps(CASES)))
    if answer.get("unavailable"):
        pytest.skip("%s is not available in this browser: %s" % (backend, answer["unavailable"]))
    failures = []
    for case, drawn in zip(CASES, answer["drawn"], strict=True):
        points = [sample["p"] for sample in drawn["samples"]]
        assert len(points) > 40, "too little of the sphere was sampled"
        got = np.array([sample["rgb"] for sample in drawn["samples"]])
        want = _expected(case, points, drawn["eye"])
        relative = np.abs(got - want) / np.maximum(want, 1e-3)
        median, high = float(np.median(relative)), float(np.percentile(relative, 95))
        print("%s %s: median %.4f, 95th percentile %.4f" % (backend, json.dumps(case), median, high))
        if median > MEDIAN or high > PERCENTILE_95:
            failures.append("%s: median %.4f, 95th percentile %.4f" % (json.dumps(case), median, high))
    assert not failures, "drawn otherwise than 'finished_light' says, on %s:\n%s" % (backend, "\n".join(failures))


def test_a_window_without_webgl_draws_with_webgpu_even_where_it_cannot_present(browser):
    """No WebGL: the pane draws with WebGPU, off the screen where the window cannot present a WebGPU canvas.

    SwiftShader - what a browser with no GPU has for WebGPU - loses its device
    the moment a canvas asks it for a frame, and draws into a texture well; so
    the pane draws there and copies each frame onto a 2D canvas
    ('offscreenSurface' in 'surface.ts'). At an odd width, whose rows three may
    hand back padded, the frame still has the box in the middle of it.
    """
    answer = _evaluate(browser, "surface()")
    print("surface: %s" % json.dumps(answer))
    if answer["backend"] == "software":
        pytest.skip("this browser gives no WebGPU adapter: the pane draws with the painter")
    assert answer["backend"] == "webgpu"
    red, green, blue, alpha = answer["centre"]
    assert alpha == 255 and red > 150 and green < 40 and blue < 40, "the box is not where it was drawn: %s" % answer
