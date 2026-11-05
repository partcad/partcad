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
import os
import plistlib
import sys
import textwrap
import time
import types
import zipfile
from pathlib import Path

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


def test_chrome_on_windows_is_passed_over_for_one_that_takes_the_extension(monkeypatch):
    chrome, firefox = pc_browser.Browser("chrome", ["chrome.exe"]), pc_browser.Browser("firefox", ["firefox.exe"])
    monkeypatch.setattr(pc_browser.sys, "platform", "win32")
    monkeypatch.setattr(pc_browser, "default_browser", lambda: chrome)
    monkeypatch.setattr(pc_browser, "installed_browsers", lambda: [chrome, firefox])
    assert pc_browser.choose() is firefox
    # ... and opened all the same when it is all there is: its page says what to do by hand.
    monkeypatch.setattr(pc_browser, "installed_browsers", lambda: [chrome])
    assert pc_browser.choose() is chrome
    monkeypatch.setattr(pc_browser.sys, "platform", "linux")
    assert pc_browser.choose() is chrome and pc_browser.supported(chrome)


def test_with_no_default_known_an_installed_one_that_takes_the_extension_is_used(monkeypatch):
    brave = pc_browser.Browser("brave", ["/x/brave"])
    monkeypatch.setattr(pc_browser, "default_browser", lambda: None)
    monkeypatch.setattr(pc_browser, "installed_browsers", lambda: [brave])
    assert pc_browser.choose() is brave
    monkeypatch.setattr(pc_browser, "installed_browsers", lambda: [])
    assert pc_browser.choose() is None


def test_a_named_browser_is_used_whatever_it_is(monkeypatch):
    monkeypatch.setattr(pc_browser, "browser_named", lambda name: pc_browser.Browser("safari", [name]))
    assert pc_browser.choose("/Applications/Safari").kind == "safari"


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
    # Google Chrome 137 and later ignore the flag: no extension is promised.
    assert (loaded / "manifest.json").is_file() and not opened.extension
    assert "137" in opened.note

    brave = pc_browser.open_browser("http://127.0.0.1:1/start", pc_browser.Browser("brave", ["/usr/bin/brave"]))
    assert brave.extension and not brave.note


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


def test_firefox_without_bidi_promises_the_extension_only_when_it_is_signed(extension, monkeypatch):
    """Release and Beta Firefox load only signed extensions, whatever the profile says."""
    monkeypatch.setattr(pc_browser.subprocess, "Popen", _Recorded())
    monkeypatch.setattr(pc_browser, "_open_firefox_over_bidi", lambda *a: None)
    firefox = pc_browser.Browser("firefox", ["/usr/bin/firefox"])

    unsigned = pc_browser.open_browser("http://127.0.0.1:1/start", firefox)
    assert not unsigned.extension and "unsigned" in unsigned.note

    (extension / "source" / "firefox" / "signed.xpi").write_bytes(b"PK\x03\x04signed")
    signed = pc_browser.open_browser("http://127.0.0.1:1/start", firefox)
    assert signed.extension and not signed.note
    installed = extension / "profiles" / "profile" / "extensions" / "login@partcad.org.xpi"
    assert installed.read_bytes() == b"PK\x03\x04signed"


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


# --- what each system records, read the long way round -----------------------------


def test_a_desktop_file_is_found_in_whichever_data_directory_has_it(tmp_path, monkeypatch):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    _desktop(second, "firefox.desktop", "/usr/lib/firefox/firefox %u")
    _desktop(second, "broken.desktop", "/usr/bin/browser 'unterminated")
    monkeypatch.setattr(pc_browser, "_desktop_dirs", lambda: [first, second])

    assert pc_browser._exec_of_desktop("firefox.desktop") == ["/usr/lib/firefox/firefox"]
    # An Exec line no shell could split is no command at all.
    assert pc_browser._exec_of_desktop("broken.desktop") is None
    assert pc_browser._exec_of_desktop("missing.desktop") is None


def test_run_answers_what_a_command_printed_and_nothing_for_one_that_will_not_run():
    assert pc_browser._run([sys.executable, "-c", "print('  firefox.desktop  ')"]) == "firefox.desktop"
    assert pc_browser._run([str(Path(sys.executable).parent / "no-such-program")]) == ""


@pytest.mark.skipif(sys.platform == "win32", reason="an executable on PATH is a file with its mode bit set here")
def test_on_linux_with_nothing_recorded_the_browser_variable_is_asked(tmp_path, monkeypatch):
    program = tmp_path / "bin" / "firefox"
    program.parent.mkdir()
    program.write_text("#!/bin/sh\n")
    program.chmod(0o755)
    monkeypatch.setattr(pc_browser, "_run", lambda command, timeout=5: "")
    monkeypatch.setenv("PATH", str(program.parent))
    monkeypatch.setenv("BROWSER", "w3m:firefox")

    browser = pc_browser._linux_default()

    assert (browser.kind, browser.command) == ("firefox", [str(program)])
    monkeypatch.setenv("BROWSER", "")
    assert pc_browser._linux_default() is None


def test_on_macos_a_default_partcad_does_not_know_is_no_default(tmp_path, monkeypatch):
    monkeypatch.setattr(pc_browser.Path, "home", lambda: tmp_path)
    # Found or not, an app PartCAD does not know is not asked for.
    monkeypatch.setattr(pc_browser, "_macos_app", lambda bundle_id: pytest.fail("asked for %s" % bundle_id))
    plist = tmp_path / "Library/Preferences/com.apple.LaunchServices/com.apple.launchservices.secure.plist"
    plist.parent.mkdir(parents=True)
    handlers = [{"LSHandlerURLScheme": "https", "LSHandlerRoleAll": "com.example.reader"}]
    plist.write_bytes(plistlib.dumps({"LSHandlers": handlers}))
    assert pc_browser._macos_default() is None


def test_on_macos_an_app_is_found_by_its_bundle_id_and_run_by_its_executable(tmp_path, monkeypatch):
    app = tmp_path / "Firefox.app"
    monkeypatch.setattr(pc_browser, "_run", lambda command, timeout=5: "/x/Notes.txt\n%s\n" % app)
    assert pc_browser._macos_app("org.mozilla.firefox") == str(app)
    # No Info.plist, or one naming a program that is not there: no executable.
    assert pc_browser._macos_executable(str(app)) is None
    (app / "Contents").mkdir(parents=True)
    (app / "Contents" / "Info.plist").write_bytes(plistlib.dumps({"CFBundleExecutable": "firefox"}))
    assert pc_browser._macos_executable(str(app)) is None


class _Registry:
    """The two keys '_windows_default' reads, as 'winreg' would hand them over."""

    HKEY_CURRENT_USER, HKEY_CLASSES_ROOT = "HKCU", "HKCR"

    def __init__(self, values):
        self.values = values

    def OpenKey(self, root, path):  # noqa: N802 - winreg's own name
        if (root, path) not in self.values:
            raise OSError("no such key")

        class Key:
            def __enter__(self):
                return (root, path)

            def __exit__(self, *exc):
                return False

        return Key()

    def QueryValueEx(self, key, name):  # noqa: N802 - winreg's own name
        return self.values[key][name], 1


def test_on_windows_the_default_is_what_the_registry_says_opens_https(monkeypatch):
    choice = r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice"
    registry = _Registry(
        {
            ("HKCU", choice): {"ProgId": "MSEdgeHTM"},
            ("HKCR", r"MSEdgeHTM\shell\open\command"): {"": '"C:\\Edge\\msedge.exe" --single-argument %1'},
        }
    )
    monkeypatch.setitem(sys.modules, "winreg", registry)
    browser = pc_browser._windows_default()
    assert (browser.kind, browser.command) == ("edge", ["C:\\Edge\\msedge.exe"])

    registry.values.pop(("HKCU", choice))
    assert pc_browser._windows_default() is None


def test_the_default_is_asked_of_the_system_this_is(monkeypatch):
    for platform, reader in (("win32", "_windows_default"), ("darwin", "_macos_default"), ("linux", "_linux_default")):
        monkeypatch.setattr(pc_browser, "sys", types.SimpleNamespace(platform=platform))
        monkeypatch.setattr(pc_browser, reader, lambda platform=platform: platform)
        assert pc_browser.default_browser() == platform


def test_installed_browsers_are_found_where_each_system_puts_them(tmp_path, monkeypatch):
    found = {"chromium": "/usr/bin/chromium", "firefox": "/usr/bin/firefox", "firefox-esr": "/usr/bin/firefox"}
    monkeypatch.setattr(pc_browser, "sys", types.SimpleNamespace(platform="linux"))
    monkeypatch.setattr(pc_browser.shutil, "which", lambda name: found.get(name))
    browsers = pc_browser.installed_browsers()
    # One browser per program, however many names it answers to.
    assert [(b.kind, b.command) for b in browsers] == [
        ("chromium", ["/usr/bin/chromium"]),
        ("firefox", ["/usr/bin/firefox"]),
    ]
    assert pc_browser.browser_named("firefox").command == ["/usr/bin/firefox"]
    assert pc_browser.browser_named("vivaldi") is None

    program_files = tmp_path / "Program Files"
    chrome = program_files / "Google" / "Chrome" / "Application" / "chrome.exe"
    chrome.parent.mkdir(parents=True)
    chrome.write_text("")
    monkeypatch.setattr(pc_browser, "sys", types.SimpleNamespace(platform="win32"))
    # The registry's paths, as they would expand there, with this system's separator.
    monkeypatch.setattr(
        pc_browser.os.path,
        "expandvars",
        lambda path: path.replace("%PROGRAMFILES%", str(program_files)).replace("\\", "/"),
    )
    monkeypatch.setattr(pc_browser.shutil, "which", lambda name: None)
    # Compared as paths: the separators are this system's, not the registry's.
    assert [(b.kind, [Path(c) for c in b.command]) for b in pc_browser.installed_browsers()] == [("chrome", [chrome])]


def test_a_browser_named_by_its_path_is_known_by_its_file_name(tmp_path):
    program = tmp_path / "brave-browser"
    program.write_text("")
    browser = pc_browser.browser_named(str(program))
    assert (browser.kind, browser.command) == ("brave", [str(program)])


def test_the_extension_is_the_one_this_installation_carries():
    chromium = pc_browser.extension_source("chromium")
    assert chromium is not None and (chromium / "manifest.json").is_file()
    assert pc_browser.extension_source("safari") is None


# --- starting it, with what there is and is not ------------------------------------


def test_without_the_extension_the_window_opens_and_says_so(extension, monkeypatch):
    popen = _Recorded()
    monkeypatch.setattr(pc_browser.subprocess, "Popen", popen)
    monkeypatch.setattr(pc_browser, "extension_source", lambda family: None)

    for browser in (pc_browser.Browser("brave", ["/usr/bin/brave"]), pc_browser.Browser("firefox", ["/usr/bin/ff"])):
        opened = pc_browser.open_browser("http://127.0.0.1:1/start", browser)
        assert not opened.extension and "not in this installation" in opened.note
    assert not any("--load-extension" in " ".join(command) for command in popen.commands)

    safari = pc_browser.open_browser("http://127.0.0.1:1/start", pc_browser.Browser("safari", ["/usr/bin/safari"]))
    assert not safari.extension and "Safari cannot be given" in safari.note
    assert popen.commands[-1] == ["/usr/bin/safari", "http://127.0.0.1:1/start"]


class _Process:
    def __init__(self, running=True, refuses=False):
        self.running, self.refuses, self.calls = running, refuses, []

    def poll(self):
        return None if self.running else 0

    def terminate(self):
        self.calls.append("terminate")
        if self.refuses:
            raise OSError("not permitted")
        self.running = False

    def wait(self, timeout=None):
        self.calls.append("wait")
        return 0

    def kill(self):
        self.calls.append("kill")
        raise OSError("gone already")


def test_closing_ends_the_browser_however_it_will_end(extension):
    browser = pc_browser.Browser("brave", ["/usr/bin/brave"])
    closed = []

    def close():
        closed.append(True)
        raise RuntimeError("the pipe broke")

    stubborn = _Process(refuses=True)
    pc_browser.Opened(browser, stubborn, True, "", close).close()
    # A close that fails still ends the process: terminated, and killed when that will not do.
    assert closed == [True] and stubborn.calls == ["terminate", "kill"]

    polite = _Process()
    pc_browser.Opened(browser, polite).close()
    assert polite.calls == ["terminate", "wait"]

    gone = _Process(running=False)
    pc_browser.Opened(browser, gone).close()
    assert gone.calls == []


# --- the DevTools pipe, and Chromium on it -------------------------------------------

posix_only = pytest.mark.skipif(
    sys.platform == "win32", reason="the DevTools pipe is set up with posix_spawn, and only off Windows"
)


@posix_only
def test_the_devtools_pipe_matches_answers_to_calls_and_says_what_went_wrong():
    to_read, to_write = os.pipe()
    from_read, from_write = os.pipe()
    pipe = pc_browser._DevToolsPipe(to_write, from_read)
    try:
        # An event first, which answers nothing, then the answer, in one read.
        os.write(from_write, b'{"method": "Target.targetCreated"}\0{"id": 1, "result": {"id": "abc"}}\0')
        assert pipe.call("Extensions.loadUnpacked", {"path": "/x"}) == {"id": "abc"}
        sent = os.read(to_read, 1 << 16)
        assert json.loads(sent.rstrip(b"\0")) == {
            "id": 1,
            "method": "Extensions.loadUnpacked",
            "params": {"path": "/x"},
        }

        os.write(from_write, b'{"id": 2, "error": {"code": -32000, "message": "Method not available."}}\0')
        with pytest.raises(RuntimeError, match="Method not available"):
            pipe.call("Extensions.loadUnpacked")
        with pytest.raises(TimeoutError, match="no answer"):
            pipe.call("Target.createTarget", timeout=0.2)
        os.close(from_write)
        with pytest.raises(RuntimeError, match="closed its DevTools pipe"):
            pipe.call("Browser.close", timeout=10)
    finally:
        pipe.close()
        pipe.close()  # twice is harmless
        os.close(to_read)


FAKE_CHROMIUM = textwrap.dedent("""
    # A stand-in for a Chromium: DevTools on descriptors 3 and 4 when asked for
    # them, every call written down, and Extensions.loadUnpacked refused when
    # FAKE_BROWSER_MODE says so.
    import json, os, sys

    def record(entry):
        with open(os.environ["FAKE_BROWSER_LOG"], "a") as log:
            log.write(json.dumps(entry) + "\\n")

    record({"argv": sys.argv[1:]})
    if "--remote-debugging-pipe" not in sys.argv:
        sys.exit(0)
    buffer = b""
    while True:
        chunk = os.read(3, 65536)
        if not chunk:
            sys.exit(0)
        buffer += chunk
        while b"\\0" in buffer:
            raw, buffer = buffer.split(b"\\0", 1)
            call = json.loads(raw)
            record({"call": call["method"], "params": call["params"]})
            if os.environ.get("FAKE_BROWSER_MODE") == "refuse" and call["method"] == "Extensions.loadUnpacked":
                answer = {"id": call["id"], "error": {"code": -32000, "message": "Method not available."}}
            else:
                answer = {"id": call["id"], "result": {"id": "abcdef"}}
            os.write(4, json.dumps(answer).encode() + b"\\0")
            if call["method"] == "Browser.close":
                sys.exit(0)
    """)


def _stand_in(tmp_path, monkeypatch, source, mode="ok"):
    script = tmp_path / "stand_in_browser.py"
    script.write_text(source)
    log = tmp_path / "browser.log"
    monkeypatch.setenv("FAKE_BROWSER_LOG", str(log))
    monkeypatch.setenv("FAKE_BROWSER_MODE", mode)
    return [sys.executable, str(script)], log


def _entries(log):
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def _wait_for(predicate, timeout=60):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.05)


@posix_only
def test_a_chromium_gets_the_extension_over_its_devtools_pipe(extension, tmp_path, monkeypatch):
    command, log = _stand_in(tmp_path, monkeypatch, FAKE_CHROMIUM)

    opened = pc_browser.open_browser("http://127.0.0.1:1/start", pc_browser.Browser("chrome", command))
    try:
        assert opened.extension and not opened.note
        calls = [entry for entry in _entries(log) if "call" in entry]
        loaded = extension / "profiles" / "extension"
        assert calls == [
            {"call": "Extensions.loadUnpacked", "params": {"path": str(loaded)}},
            {"call": "Target.createTarget", "params": {"url": "http://127.0.0.1:1/start"}},
        ]
        argv = _entries(log)[0]["argv"]
        assert "--remote-debugging-pipe" in argv and "--enable-unsafe-extension-debugging" in argv
        assert argv[-1] == "about:blank"
    finally:
        opened.close()
    # Asked to close, over the same pipe, and ended (by itself, or by the
    # terminate that follows if it is still on its way out).
    assert _entries(log)[-1]["call"] == "Browser.close"
    assert opened.process.wait(timeout=30) is not None


@posix_only
def test_a_chromium_that_refuses_the_pipe_is_started_again_with_the_flag(extension, tmp_path, monkeypatch):
    command, log = _stand_in(tmp_path, monkeypatch, FAKE_CHROMIUM, mode="refuse")

    opened = pc_browser.open_browser("http://127.0.0.1:1/start", pc_browser.Browser("brave", command))
    try:
        assert opened.extension
        _wait_for(lambda: len([entry for entry in _entries(log) if "argv" in entry]) == 2)
        first, second = [entry["argv"] for entry in _entries(log) if "argv" in entry]
        assert "--remote-debugging-pipe" in first
        loaded = extension / "profiles" / "extension"
        assert "--load-extension=%s" % loaded in second and second[-1] == "http://127.0.0.1:1/start"
    finally:
        opened.close()


@posix_only
def test_a_spawned_browser_that_will_not_stop_is_killed():
    pid = os.posix_spawn(sys.executable, [sys.executable, "-c", "import time; time.sleep(120)"], os.environ)
    process = pc_browser._SpawnedProcess(pid)
    assert process.poll() is None
    with pytest.raises(pc_browser.subprocess.TimeoutExpired):
        process.wait(timeout=0.2)
    process.kill()
    assert process.wait(timeout=60) == -9
    # Not this process's child: nothing to wait for.
    assert pc_browser._SpawnedProcess(os.getpid()).poll() == 0


# --- Firefox, over WebDriver BiDi ------------------------------------------------------

FAKE_FIREFOX = textwrap.dedent("""
    # A stand-in for Firefox: WebDriver BiDi on a websocket when asked for it,
    # every command written down. FAKE_BROWSER_MODE: 'ok'; 'refuse' the
    # extension; 'no-bidi', exit without listening; 'no-window', no context.
    import asyncio, json, os, sys

    def record(entry):
        with open(os.environ["FAKE_BROWSER_LOG"], "a") as log:
            log.write(json.dumps(entry) + "\\n")

    record({"argv": sys.argv[1:]})
    mode = os.environ.get("FAKE_BROWSER_MODE", "ok")
    if "--remote-debugging-port" not in sys.argv or mode == "no-bidi":
        sys.exit(0)

    from aiohttp import web

    async def session(request):
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        async for message in socket:
            call = json.loads(message.data)
            record({"call": call["method"], "params": call["params"]})
            await socket.send_json({"type": "event", "method": "log.entryAdded", "params": {}})
            if mode == "refuse" and call["method"] == "webExtension.install":
                await socket.send_json({"type": "error", "id": call["id"], "message": "not signed"})
                continue
            result = {}
            if call["method"] == "browsingContext.getTree":
                result = {"contexts": [] if mode == "no-window" else [{"context": "tab-1"}]}
            await socket.send_json({"type": "success", "id": call["id"], "result": result})
        return socket

    async def main():
        app = web.Application()
        app.router.add_get("/session", session)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        print("WebDriver BiDi listening on ws://127.0.0.1:%d" % port, file=sys.stderr, flush=True)
        await asyncio.sleep(600)

    asyncio.run(main())
    """)


@posix_only
@pytest.mark.parametrize("mode", ["ok", "no-window"])
def test_firefox_gets_the_extension_over_webdriver_bidi(extension, tmp_path, monkeypatch, mode):
    command, log = _stand_in(tmp_path, monkeypatch, FAKE_FIREFOX, mode=mode)

    opened = pc_browser.open_browser("http://127.0.0.1:1/start", pc_browser.Browser("firefox", command))
    try:
        assert opened.extension and not opened.note
        calls = [(entry["call"], entry["params"]) for entry in _entries(log) if "call" in entry]
        xpi = str(extension / "profiles" / "login@partcad.org.xpi")
        opening = (
            ("browsingContext.navigate", {"context": "tab-1", "url": "http://127.0.0.1:1/start"})
            if mode == "ok"
            else ("browsingContext.create", {"type": "window"})
        )
        assert calls == [
            ("session.new", {"capabilities": {}}),
            ("webExtension.install", {"extensionData": {"type": "archivePath", "path": xpi}}),
            ("browsingContext.getTree", {}),
            opening,
            ("session.end", {}),
        ]
        assert _entries(log)[0]["argv"][-2:] == ["--remote-debugging-port", "0"]
    finally:
        opened.close()
    assert opened.process.poll() is not None


@posix_only
@pytest.mark.parametrize("mode", ["refuse", "no-bidi"])
def test_firefox_that_will_not_take_it_over_bidi_is_started_plainly(extension, tmp_path, monkeypatch, mode):
    command, log = _stand_in(tmp_path, monkeypatch, FAKE_FIREFOX, mode=mode)

    opened = pc_browser.open_browser("http://127.0.0.1:1/start", pc_browser.Browser("firefox", command))
    try:
        assert not opened.extension and "unsigned" in opened.note
        _wait_for(lambda: len([entry for entry in _entries(log) if "argv" in entry]) == 2)
        plain = [entry["argv"] for entry in _entries(log) if "argv" in entry][1]
        assert "--remote-debugging-port" not in plain and plain[-1] == "http://127.0.0.1:1/start"
    finally:
        opened.close()
