#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The login extension as it is checked in, without a browser.

`browsers/chromium` and `browsers/firefox` are one extension written down
twice: every file but `manifest.json` is shared, and is kept as a copy in each
directory rather than as a symbolic link, because a link is a text file holding
a path on a Windows checkout and in a zip. So the copies can drift, and the
first place that would show is a store review or a user's browser. These say it
here instead:

* the manifests agree with each other on everything but how each browser starts
  the background, and with the release on their version;
* the shared files are byte for byte the same;
* everything a manifest names is there, and every permission it asks for is
  explained in the README, where a reviewer reads why;
* `browsers/build.py` packages exactly the directories, reproducibly, and
  refuses copies that differ;
* the rules in `common.js` -- what a spec may say and which origins it names --
  answer the way the README says, when Node.js is there to run them.

`test_login_e2e.py` drives the extension in a real browser; it is opt-in.
"""

import copy
import importlib.util
import json
import pathlib
import shutil
import subprocess
import zipfile

import pytest

# `tomllib` is only in the standard library from Python 3.11, and the CI matrix
# still runs 3.10 -- see the same fallback in tests/partcad_cli/unit/test_versions.py.
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
BROWSERS = REPO_ROOT / "browsers"
CHROMIUM = BROWSERS / "chromium"
FIREFOX = BROWSERS / "firefox"
BUMPVERSION = REPO_ROOT / "dev-tools" / "bumpversion.toml"
README = BROWSERS / "README.md"


def load_build():
    """`browsers/build.py`, which is a script rather than a package anyone imports."""
    spec = importlib.util.spec_from_file_location("partcad_browsers_build", BROWSERS / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def manifest(directory):
    return json.loads((directory / "manifest.json").read_text(encoding="utf-8"))


def without_background(data):
    data = copy.deepcopy(data)
    data.pop("background")
    data.pop("browser_specific_settings", None)
    data.pop("minimum_chrome_version", None)
    return data


def test_both_are_manifest_v3():
    for directory in (CHROMIUM, FIREFOX):
        assert manifest(directory)["manifest_version"] == 3, directory


def test_the_manifests_agree_on_everything_but_how_the_background_starts():
    """Same name, version, permissions, content scripts, icons.

    Chromium runs the background as a service worker; Firefox has no service
    workers for extensions and runs it as an event page from `background.scripts`
    (with `common.js` first, which the service worker imports itself). The
    browser-specific keys are each browser's own. Nothing else may differ.
    """
    assert without_background(manifest(CHROMIUM)) == without_background(manifest(FIREFOX))
    assert manifest(CHROMIUM)["background"] == {"service_worker": "background.js"}
    assert manifest(FIREFOX)["background"] == {"scripts": ["common.js", "background.js"]}


def test_the_version_is_the_release():
    current = tomllib.loads(BUMPVERSION.read_text(encoding="utf-8"))["tool"]["bumpversion"]["current_version"]
    for directory in (CHROMIUM, FIREFOX):
        assert manifest(directory)["version"] == current, (
            "%s/manifest.json is out of step with the release; dev-tools/bumpversion.toml moves both manifests"
            % directory.relative_to(REPO_ROOT).as_posix()
        )


def test_both_manifests_move_with_the_release():
    """Declared, so that they move; the test above only says that they have."""
    entries = tomllib.loads(BUMPVERSION.read_text(encoding="utf-8"))["tool"]["bumpversion"]["files"]
    declared = {entry["filename"] for entry in entries if entry["search"] == '"version": "{current_version}"'}
    assert {"browsers/chromium/manifest.json", "browsers/firefox/manifest.json"} <= declared


def test_the_firefox_identity():
    """The id is what `pc login` names the extension's file after in a Firefox profile.

    And 140 is the oldest Firefox it claims: an ESR, the first release that
    understands `data_collection_permissions` -- which addons.mozilla.org
    requires of a new extension -- and well past 127, from which an MV3
    extension's host permissions are granted when it is installed rather than
    asked for afterwards. Without that, nothing would be captured until the
    user went and granted them.
    """
    gecko = manifest(FIREFOX)["browser_specific_settings"]["gecko"]
    assert gecko["id"] == "login@partcad.org"
    assert int(gecko["strict_min_version"].split(".")[0]) >= 140
    assert gecko["data_collection_permissions"]["required"] == ["authenticationInfo"]


def test_everything_a_manifest_names_is_there():
    for directory in (CHROMIUM, FIREFOX):
        data = manifest(directory)
        named = list(data["icons"].values())
        named += data["background"].get("scripts", [])
        named += [data["background"]["service_worker"]] if "service_worker" in data["background"] else []
        for script in data["content_scripts"]:
            named += script["js"]
        missing = [name for name in named if not (directory / name).is_file()]
        assert not missing, "%s names files it does not have: %s" % (directory.name, missing)


def test_the_icons_are_images_and_not_lfs_pointers():
    """`.gitattributes` holds them out of LFS: a pointer file is an icon no browser can decode."""
    for directory in (CHROMIUM, FIREFOX):
        for icon in manifest(directory)["icons"].values():
            assert (directory / icon).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", "%s/%s" % (directory.name, icon)


def test_the_shared_files_are_identical():
    problems = load_build().check(BROWSERS)
    assert not problems, "\n".join(problems) + (
        "\nEdit the copy in browsers/chromium and copy it over the one in browsers/firefox (or the other way)."
    )


def test_no_symbolic_links():
    links = [path for path in BROWSERS.rglob("*") if path.is_symlink()]
    assert not links, "symbolic links do not survive a Windows checkout or a zip: %s" % links


def test_every_permission_is_explained_in_the_readme():
    """A store reviewer, and a user, reads the README for why each permission is asked for."""
    readme = README.read_text(encoding="utf-8")
    data = manifest(CHROMIUM)
    for permission in data["permissions"] + data["host_permissions"]:
        assert "`%s`" % permission in readme, "browsers/README.md does not explain `%s`" % permission


def test_build_packages_exactly_the_directories(tmp_path):
    build = load_build()
    version = manifest(CHROMIUM)["version"]
    written = build.build(out=tmp_path)
    assert [path.name for path in written] == [
        "partcad-login-chromium-%s.zip" % version,
        "partcad-login-firefox-%s.xpi" % version,
    ]
    for path, directory in zip(written, (CHROMIUM, FIREFOX)):
        with zipfile.ZipFile(path) as archive:
            assert sorted(archive.namelist()) == build.files(directory)
            # The manifest at the root of the archive, which is where every store looks.
            assert archive.read("manifest.json") == (directory / "manifest.json").read_bytes()
            for name in archive.namelist():
                assert archive.read(name) == (directory / name).read_bytes(), name


def test_build_is_reproducible(tmp_path):
    build = load_build()
    first = [path.read_bytes() for path in build.build(out=tmp_path / "one")]
    second = [path.read_bytes() for path in build.build(out=tmp_path / "two")]
    assert first == second


def test_build_refuses_copies_that_differ(tmp_path):
    build = load_build()
    root = tmp_path / "browsers"
    shutil.copytree(CHROMIUM, root / "chromium")
    shutil.copytree(FIREFOX, root / "firefox")
    with open(root / "firefox" / "content.js", "a", encoding="utf-8") as script:
        script.write("// a fix made for one browser only\n")
    (root / "chromium" / "extra.js").write_text("// in one directory only\n", encoding="utf-8")

    with pytest.raises(build.BuildError) as refused:
        build.build(root=root, out=tmp_path / "dist")
    assert "content.js" in str(refused.value)
    assert "extra.js" in str(refused.value)
    assert not (tmp_path / "dist").exists()

    assert build.main(["--check"]) == 0


def node():
    found = shutil.which("node")
    if not found:
        pytest.skip("Node.js is not installed")
    return found


@pytest.mark.parametrize("script", ["common.js", "background.js", "content.js"])
def test_the_scripts_parse(script):
    result = subprocess.run([node(), "--check", str(CHROMIUM / script)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


# Runs `common.js` in Node.js -- it needs nothing a browser has and Node.js has
# not -- and answers each case read from stdin with what the named function
# returned for it.
RULES = r"""
require(process.argv[1]);
const L = globalThis.PartcadLogin;
const cases = JSON.parse(require("fs").readFileSync(0, "utf8"));
const answers = cases.map(([name, ...args]) => {
  if (name === "isNamedOrigin") {
    const checked = L.validateSpec(args[0], args[1]);
    return checked.error ? "invalid spec: " + checked.error : L.isNamedOrigin(checked.spec, args[2]);
  }
  if (name === "accepts") {
    return L.accepts({ match: args[0] }, args[1]);
  }
  return L[name](...args);
});
process.stdout.write(JSON.stringify(answers));
"""

START = "http://127.0.0.1:50123/partcad/login/0123456789abcdef0123456789abcdef/start"
CALLBACK = "http://127.0.0.1:50123/partcad/login/0123456789abcdef0123456789abcdef/done"


def rules(*cases):
    result = subprocess.run(
        [node(), "-e", RULES, str(CHROMIUM / "common.js")],
        input=json.dumps(cases),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def spec(**overrides):
    base = {
        "url": "https://www.printables.com/login",
        "capture": [{"name": "token", "cookie": {"url": "https://www.printables.com/", "name": "access_token"}}],
        "callback": CALLBACK,
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    "glob, url, matches",
    [
        ("https://grabcad.com/*", "https://grabcad.com/login?next=/", True),
        ("https://grabcad.com/login*", "https://grabcad.com/", False),
        # `*` is the only wildcard; `?` and `.` are themselves.
        ("https://grabcad.com/a?b", "https://grabcad.com/a?b", True),
        ("https://grabcad.com/a?b", "https://grabcad.com/aXb", False),
        ("https://grab.cad.com/*", "https://grabXcad.com/", False),
        # The whole URL, not a part of it.
        ("https://grabcad.com/", "https://evil.example/?https://grabcad.com/", False),
        ("http://127.0.0.1/partcad/login/thingiverse*", "http://127.0.0.1/partcad/login/thingiverse#t=1", True),
    ],
)
def test_url_patterns_are_globs_over_the_whole_url(glob, url, matches):
    assert rules(["globMatch", glob, url]) == [matches]


def test_a_start_page_is_only_ever_on_the_loopback_interface():
    assert rules(
        ["startNonce", START],
        ["startNonce", "http://localhost:8080/partcad/login/abc/start"],
        ["startNonce", "http://[::1]:8080/partcad/login/abc/start"],
        ["startNonce", "http://example.com/partcad/login/abc/start"],
        ["startNonce", "https://127.0.0.1/partcad/login/abc/start"],
        ["startNonce", "http://127.0.0.1:8080/partcad/login/abc/done"],
    ) == ["0123456789abcdef0123456789abcdef", "abc", "abc", None, None, None]


def test_the_callback_must_be_on_the_start_pages_origin():
    elsewhere = "http://127.0.0.1:50124/partcad/login/0123456789abcdef0123456789abcdef/done"
    answers = rules(
        ["validateSpec", spec(callback=elsewhere), START],
        ["validateSpec", spec(callback="http://localhost:50123/partcad/login/x/done"), START],
        ["validateSpec", spec(callback="http://127.0.0.1:50123/somewhere/else"), START],
        ["validateSpec", spec(), START],
    )
    assert all("callback" in answer["error"] for answer in answers[:3]), answers
    assert answers[3]["spec"]["callback"] == CALLBACK


@pytest.mark.parametrize(
    "overrides, complaint",
    [
        ({"url": "javascript:alert(1)"}, "'url'"),
        ({"url": "file:///etc/passwd"}, "'url'"),
        ({"capture": []}, "'capture'"),
        ({"capture": [{"name": "a", "cookie": {"url": "https://x.example/", "name": "c"}, "ask": {}}]}, "exactly one"),
        ({"capture": [{"name": "a", "ask": {}}, {"name": "a", "ask": {}}]}, "twice"),
        ({"capture": [{"name": "a", "ask": {}, "match": "("}]}, "regular expression"),
        ({"capture": [{"name": "a", "localStorage": {"origin": "chrome://settings", "key": "k"}}]}, "storage"),
        ({"require": "most"}, "'require'"),
        ({"done_when": {"url": "https://x.example/*", "selector": "a"}}, "exactly one"),
        ({"done_when": {"fetch": {"url": "https://x.example/me", "status": 999}}}, "status"),
        ({"done_when": {"selector": "button", "contains": "["}}, "'contains'"),
        ({"guide": [{"url": "https://x.example/*", "selector": "button", "contains": "("}]}, "'contains'"),
        ({"guide": [{"url": "https://x.example/*", "selector": "button", "contains": 1}]}, "'contains'"),
        ({"timeout": -1}, "'timeout'"),
    ],
)
def test_a_spec_the_extension_cannot_honour_is_refused(overrides, complaint):
    (answer,) = rules(["validateSpec", spec(**overrides), START])
    assert complaint in answer.get("error", ""), answer


def test_a_spec_is_normalised():
    (answer,) = rules(
        [
            "validateSpec",
            spec(
                capture=[
                    {"name": "a", "localStorage": {"origin": "https://www.printables.com/some/path", "key": "k"}},
                    {"name": "b", "dom": {"url": "https://cults3d.com/*", "selector": "code"}},
                    # `match` belongs beside the source; inside it is accepted too.
                    {"name": "c", "ask": {"match": "^tt-"}},
                ],
                done_when={"fetch": {"url": "https://grabcad.com/me"}},
                guide=[
                    {"url": "https://makerworld.com/*", "selector": "button.MuiButton-root", "contains": "^log in$"},
                    {"url": "https://makerworld.com/*", "selector": "input[type=email]", "text": "Your e-mail"},
                ],
                unknown="ignored",
            ),
            START,
        ]
    )
    result = answer["spec"]
    assert result["guide"] == [
        {"url": "https://makerworld.com/*", "selector": "button.MuiButton-root", "contains": "^log in$", "text": ""},
        {"url": "https://makerworld.com/*", "selector": "input[type=email]", "contains": None, "text": "Your e-mail"},
    ]
    assert result["title"] == "www.printables.com"
    assert result["require"] == "all"
    assert result["timeout"] == 600
    assert result["done_when"] == {"fetch": {"url": "https://grabcad.com/me", "status": 200}}
    a, b, c = result["capture"]
    assert a["localStorage"] == {"origin": "https://www.printables.com", "key": "k"}
    assert b["dom"] == {
        "url": "https://cults3d.com/*",
        "selector": "code",
        "property": "textContent",
        "attribute": None,
    }
    assert c["ask"] == {"label": "c", "secret": False} and c["match"] == "^tt-"
    assert "unknown" not in result


def test_the_origins_a_spec_names():
    named = spec(
        capture=[
            {"name": "a", "cookie": {"url": "https://www.printables.com/", "name": "c"}},
            {"name": "b", "dom": {"url": "https://*.cults3d.com/en/*", "selector": "code"}},
            {"name": "c", "redirect": {"url": "http://127.0.0.1/partcad/login/thingiverse*", "param": "t"}},
        ],
        guide=[{"url": "https://grabcad.com/*", "selector": "a", "text": ""}],
        done_when={"fetch": {"url": "https://api.example.com/me"}},
    )
    origins = {
        "https://www.printables.com": True,
        "https://fr.cults3d.com": True,
        "http://127.0.0.1": True,
        "https://grabcad.com": True,
        "https://api.example.com": True,
        # Not the same origin as any of those.
        "http://www.printables.com": False,
        "https://printables.com": False,
        "http://127.0.0.1:8080": False,
        "https://cults3d.com.evil.example": False,
        "https://example.com": False,
    }
    answers = rules(*(["isNamedOrigin", named, START, origin] for origin in origins))
    assert dict(zip(origins, answers)) == origins


def test_done_when_selector_takes_contains():
    (answer,) = rules(["validateSpec", spec(done_when={"selector": "button", "contains": "log out"}), START])
    assert answer["spec"]["done_when"] == {"selector": "button", "contains": "log out"}
    (answer,) = rules(["validateSpec", spec(done_when={"selector": "a.user"}), START])
    assert answer["spec"]["done_when"] == {"selector": "a.user", "contains": None}


def test_a_redirect_value_comes_from_the_query_or_the_fragment():
    assert rules(
        ["paramFrom", "http://127.0.0.1/cb?access_token=q", "access_token"],
        ["paramFrom", "http://127.0.0.1/cb#access_token=f&token_type=bearer", "access_token"],
        ["paramFrom", "http://127.0.0.1/cb#/route?access_token=r", "access_token"],
        ["paramFrom", "http://127.0.0.1/cb?other=1", "access_token"],
    ) == ["q", "f", "r", None]


def test_match_is_what_tells_a_signed_in_value_from_a_visitors():
    jwt = r"^eyJ[\w-]+\.[\w-]+\.[\w-]+$"
    assert rules(
        ["accepts", jwt, "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhbm4ifQ.c2ln"],
        ["accepts", jwt, "visitor"],
        ["accepts", None, "anything"],
        ["accepts", None, ""],
        # Unanchored, as JavaScript's RegExp.test is.
        ["accepts", "tt-", "my tt-token"],
    ) == [True, False, True, False, True]
