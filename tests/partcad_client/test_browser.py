#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Which browser 'pc login' opens, on each system, and how it is started with PartCAD's extension.

Nothing here starts a browser: what each system records is written into a
temporary home, and what would be run is recorded instead of run.
"""

import json
import plistlib
import zipfile

import pytest

from partcad_client import browser as pc_browser


@pytest.mark.parametrize(
    "identifier, kind",
    [
        ("google-chrome.desktop", "chrome"),
        ("com.google.Chrome", "chrome"),
        ("ChromeHTML", "chrome"),
        ("chromium_chromium.desktop", "chromium"),
        ("MSEdgeHTM", "edge"),
        ("com.microsoft.edgemac", "edge"),
        ("brave-browser.desktop", "brave"),
        ("FirefoxURL-308046B0AF4A39CB", "firefox"),
        ("org.mozilla.firefox.desktop", "firefox"),
        ("com.apple.Safari", "safari"),
        ("emacs.desktop", None),
    ],
)
def test_a_browser_is_known_by_what_each_system_calls_it(identifier, kind):
    assert pc_browser.kind_of(identifier) == kind


def _desktop(directory, name, exec_line):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(
        "[Desktop Entry]\nName=Browser\nExec=%s\n[Desktop Action new-window]\nExec=other --new-window\n" % exec_line
    )


def test_on_linux_the_default_is_what_xdg_settings_names(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path / "none"))
    _desktop(tmp_path / "share" / "applications", "google-chrome.desktop", "/usr/bin/google-chrome-stable %U")
    monkeypatch.setattr(pc_browser, "_run", lambda command, timeout=5: "google-chrome.desktop")

    browser = pc_browser._linux_default()

    assert (browser.kind, browser.family, browser.command) == ("chrome", "chromium", ["/usr/bin/google-chrome-stable"])
    assert browser.confinement == ""


def test_a_flatpak_browser_is_started_through_flatpak_and_keeps_its_profile_where_it_may(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setattr(pc_browser.Path, "home", lambda: tmp_path)
    _desktop(
        tmp_path / "share" / "applications",
        "org.mozilla.firefox.desktop",
        "/usr/bin/flatpak run --branch=stable --arch=x86_64 --command=firefox org.mozilla.firefox @@u %u @@",
    )
    monkeypatch.setattr(pc_browser, "_run", lambda command, timeout=5: "org.mozilla.firefox.desktop")

    browser = pc_browser._linux_default()

    assert browser.kind == "firefox" and browser.confinement == "flatpak" and browser.app_id == "org.mozilla.firefox"
    assert browser.command[:2] == ["/usr/bin/flatpak", "run"]
    assert pc_browser.profile_root(browser) == tmp_path / ".var/app/org.mozilla.firefox/data/partcad-login"


def test_a_snap_browser_keeps_its_profile_where_its_confinement_lets_it_write(tmp_path, monkeypatch):
    monkeypatch.setattr(pc_browser.Path, "home", lambda: tmp_path)
    browser = pc_browser._linux_browser("chromium", ["/snap/bin/chromium"], "chromium_chromium.desktop")
    assert browser.confinement == "snap" and browser.app_id == "chromium"
    assert pc_browser.profile_root(browser) == tmp_path / "snap/chromium/common/partcad-login"


def test_an_unconfined_browser_keeps_its_profile_under_partcad(tmp_path, monkeypatch):
    monkeypatch.setattr(pc_browser.Path, "home", lambda: tmp_path)
    monkeypatch.delenv("PC_LOGIN_PROFILE_DIR", raising=False)
    browser = pc_browser.Browser("edge", ["/usr/bin/microsoft-edge"])
    assert pc_browser.profile_root(browser) == tmp_path / ".partcad/browser/edge"


def test_on_macos_the_default_is_what_launchservices_records(tmp_path, monkeypatch):
    monkeypatch.setattr(pc_browser.Path, "home", lambda: tmp_path)
    preferences = tmp_path / "Library/Preferences/com.apple.LaunchServices"
    preferences.mkdir(parents=True)
    with open(preferences / "com.apple.launchservices.secure.plist", "wb") as f:
        plistlib.dump(
            {
                "LSHandlers": [
                    {"LSHandlerURLScheme": "mailto", "LSHandlerRoleAll": "com.apple.mail"},
                    {"LSHandlerURLScheme": "https", "LSHandlerRoleAll": "org.mozilla.firefox"},
                ]
            },
            f,
        )
    app = tmp_path / "Firefox.app"
    (app / "Contents/MacOS").mkdir(parents=True)
    (app / "Contents/MacOS/firefox").write_text("")
    with open(app / "Contents/Info.plist", "wb") as f:
        plistlib.dump({"CFBundleExecutable": "firefox"}, f)
    monkeypatch.setattr(pc_browser, "_macos_app", lambda bundle_id: str(app))

    browser = pc_browser._macos_default()

    assert browser.kind == "firefox" and browser.command == [str(app / "Contents/MacOS/firefox")]


def test_on_macos_with_nothing_recorded_the_default_is_safari(tmp_path, monkeypatch):
    monkeypatch.setattr(pc_browser.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(pc_browser, "_macos_app", lambda bundle_id: None)
    assert pc_browser._macos_default() is None  # Safari, which is passed over for one that takes the extension


@pytest.mark.parametrize(
    "command_line, executable",
    [
        (
            r'"C:\Program Files\Google\Chrome\Application\chrome.exe" --single-argument %1',
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        ),
        (r"C:\Progra~1\Mozilla~1\firefox.exe -osint -url %1", r"C:\Progra~1\Mozilla~1\firefox.exe"),
    ],
)
def test_on_windows_the_program_is_read_off_the_registry_command_line(command_line, executable):
    assert pc_browser._windows_executable(command_line) == executable


def test_a_browser_that_cannot_take_the_extension_is_passed_over(monkeypatch):
    monkeypatch.setattr(pc_browser, "default_browser", lambda: pc_browser.Browser("safari", ["/Applications/Safari"]))
    monkeypatch.setattr(pc_browser, "installed_browsers", lambda: [pc_browser.Browser("edge", ["/x/msedge"])])
    assert pc_browser.choose().kind == "edge"


# --- starting it ---------------------------------------------------------------------


@pytest.fixture
def extension(tmp_path, monkeypatch):
    source = tmp_path / "source"
    (source / "chromium").mkdir(parents=True)
    (source / "firefox").mkdir(parents=True)
    for family in ("chromium", "firefox"):
        (source / family / "manifest.json").write_text(json.dumps({"name": "PartCAD login", "version": "1"}))
        (source / family / "background.js").write_text("// background")
    monkeypatch.setattr(pc_browser, "extension_source", lambda family: source / family)
    monkeypatch.setenv("PC_LOGIN_PROFILE_DIR", str(tmp_path / "profiles"))
    monkeypatch.delenv("PC_LOGIN_BROWSER_ARGS", raising=False)
    return tmp_path


class _Recorded:
    def __init__(self):
        self.commands = []

    def __call__(self, command, **options):
        self.commands.append(command)
        return self

    def poll(self):
        return 0


def test_a_chromium_falls_back_to_the_flag_when_the_pipe_will_not_do(extension, monkeypatch):
    popen = _Recorded()
    monkeypatch.setattr(pc_browser.subprocess, "Popen", popen)
    monkeypatch.setattr(pc_browser, "_open_chromium_over_pipe", lambda *a: None)

    opened = pc_browser.open_browser("http://127.0.0.1:1/start", pc_browser.Browser("chrome", ["/usr/bin/chrome"]))

    command = popen.commands[0]
    profile = extension / "profiles" / "profile"
    loaded = extension / "profiles" / "extension"
    assert command[0] == "/usr/bin/chrome" and command[-1] == "http://127.0.0.1:1/start"
    assert "--user-data-dir=%s" % profile in command
    assert "--load-extension=%s" % loaded in command
    assert "--disable-features=DisableLoadExtensionCommandLineSwitch" in command
    assert (loaded / "manifest.json").is_file() and opened.extension


def test_firefox_gets_a_profile_of_its_own_with_the_extension_in_it(extension, monkeypatch):
    popen = _Recorded()
    monkeypatch.setattr(pc_browser.subprocess, "Popen", popen)
    monkeypatch.setattr(pc_browser, "_open_firefox_over_bidi", lambda *a: None)

    pc_browser.open_browser("http://127.0.0.1:1/start", pc_browser.Browser("firefox", ["/usr/bin/firefox"]))

    profile = extension / "profiles" / "profile"
    command = popen.commands[0]
    assert command[:5] == ["/usr/bin/firefox", "-profile", str(profile), "-no-remote", "-new-instance"]
    assert 'user_pref("xpinstall.signatures.required", false);' in (profile / "user.js").read_text()
    with zipfile.ZipFile(profile / "extensions" / "login@partcad.org.xpi") as xpi:
        assert sorted(xpi.namelist()) == ["background.js", "manifest.json"]


def test_a_login_that_is_over_leaves_no_tabs_behind_and_keeps_its_sign_ins(tmp_path):
    profile = tmp_path / "profile"
    (profile / "Default" / "Sessions").mkdir(parents=True)
    (profile / "Default" / "Sessions" / "Tabs_1").write_text("tabs")
    (profile / "Default" / "Cookies").write_text("signed in")
    (profile / "Default" / "Preferences").write_text(json.dumps({"profile": {"exit_type": "Crashed"}, "x": 1}))

    pc_browser._forget_last_session(profile)

    assert not (profile / "Default" / "Sessions").exists()
    assert (profile / "Default" / "Cookies").read_text() == "signed in"
    settings = json.loads((profile / "Default" / "Preferences").read_text())
    assert settings["profile"]["exit_type"] == "Normal" and settings["session"]["restore_on_startup"] == 5
    assert settings["x"] == 1
