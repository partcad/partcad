#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The user's web browser, opened by 'pc login' with PartCAD's extension in it.

A plugin's 'login' may ask for the browser (see 'partcad.wrappers.plugin_login'):
the user signs in to the site there, and PartCAD's extension picks up what that
leaves behind and hands it to the listener 'pc login' runs (see
'partcad_client.login'). This module finds that browser and starts it.

**Which browser.** The user's default one - the one they are signed in to things
in, and trust with passwords - found the way each system records it: the
registry on Windows, LaunchServices on macOS, 'xdg-settings' on Linux. A browser
that cannot be given the extension (Safari, or anything unknown) is passed over
for another one that is installed, and with none, 'pc login' falls back to a
page of its own where the values are pasted by hand.

**Which profile.** Never the user's everyday one. PartCAD keeps a profile of
its own per browser, under '~/.partcad/browser/<browser>/', and the extension
lives only there: it can read any site's cookies, which is what it is for, and
that is a power to keep to the window it was opened for. The profile is kept,
so a site signed in to once stays signed in, and the next 'pc login' is often
over before the window is drawn. A browser confined by snap or flatpak cannot
read a hidden directory of the home, so its profile is where the confinement
lets it write instead.

**How the extension gets in.** Every Chromium-family browser is started with
its DevTools protocol on a pipe, and asked to load the unpacked extension
('Extensions.loadUnpacked'); Google Chrome no longer honours the older
'--load-extension' flag, and this works for all of them. A browser too old for
that is started again with the flag. Firefox is started with its WebDriver BiDi
protocol and asked to install it as a temporary add-on, which release Firefox
allows unsigned; failing that, the extension is put in the profile, where a
Firefox that accepts unsigned extensions loads it. Where none of that is
possible, the window opens anyway, and the page it opens on says what to do.

Kept out of 'partcad' and cheap to import, like the rest of 'partcad_client':
it is a client's business - a window on the screen of whoever ran the command -
and a daemon must never be asked to do it (see "Command boundary" in
src/partcad_cli/AGENTS.md).
"""

import json
import os
import plistlib
import re
import select
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# The browsers PartCAD knows, by what each system calls them: Linux .desktop
# ids, macOS bundle ids, Windows ProgIds and executable names. Each is
# (kind, family, name). 'family' is what decides how the extension is put in.
_KINDS = {
    "chrome": ("chromium", "Google Chrome"),
    "chromium": ("chromium", "Chromium"),
    "edge": ("chromium", "Microsoft Edge"),
    "brave": ("chromium", "Brave"),
    "vivaldi": ("chromium", "Vivaldi"),
    "opera": ("chromium", "Opera"),
    "firefox": ("firefox", "Firefox"),
    "safari": ("safari", "Safari"),
}

_IDENTIFIERS = [
    # (pattern, kind), first match wins; matched against a lower-cased id.
    (r"chrome[-_ ]?for[-_ ]?testing|google-chrome|^chrome\b|com\.google\.chrome|chromehtml|chrome\.exe", "chrome"),
    (r"chromium|org\.chromium|chromiumhtm", "chromium"),
    (r"edge|msedge|microsoft\.edgemac|msedgehtm", "edge"),
    (r"brave", "brave"),
    (r"vivaldi", "vivaldi"),
    (r"opera", "opera"),
    (r"firefox|org\.mozilla|librewolf|waterfox", "firefox"),
    (r"safari", "safari"),
]


def kind_of(identifier: str) -> Optional[str]:
    """The browser kind an identifier names - a .desktop id, a bundle id, a ProgId, an executable."""
    identifier = (identifier or "").lower()
    for pattern, kind in _IDENTIFIERS:
        if re.search(pattern, identifier):
            return kind
    return None


@dataclass
class Browser:
    """A browser that can be started: how, and what it is."""

    kind: str
    command: List[str]  # what starts it, before its own arguments ('flatpak run <app>' is two words and more)
    confinement: str = ""  # 'snap', 'flatpak' or ''
    app_id: str = ""  # the snap's or the flatpak's name, for where its profile can be

    @property
    def family(self) -> str:
        return _KINDS.get(self.kind, ("other", self.kind))[0]

    @property
    def name(self) -> str:
        return _KINDS.get(self.kind, ("other", self.kind))[1]

    def __str__(self):
        return self.name


# --- which browser is the default ------------------------------------------------


def _desktop_dirs() -> List[Path]:
    home = Path.home()
    data_home = Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share")
    data_dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    dirs = [data_home / "applications"] + [Path(d) / "applications" for d in data_dirs.split(":") if d]
    dirs += [
        Path("/var/lib/snapd/desktop/applications"),
        Path("/var/lib/flatpak/exports/share/applications"),
        home / ".local/share/flatpak/exports/share/applications",
    ]
    return dirs


def _exec_of_desktop(desktop_id: str) -> Optional[List[str]]:
    """The command a .desktop file runs, field codes removed."""
    for directory in _desktop_dirs():
        path = directory / desktop_id
        if not path.is_file():
            continue
        in_entry = False
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("["):
                in_entry = line == "[Desktop Entry]"
            elif in_entry and line.startswith("Exec="):
                try:
                    words = shlex.split(line[len("Exec=") :])
                except ValueError:
                    return None
                return [w for w in words if not re.fullmatch(r"%[a-zA-Z]", w)]
    return None


def _run(command, timeout=5) -> str:
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _linux_default() -> Optional[Browser]:
    desktop_id = _run(["xdg-settings", "get", "default-web-browser"]) or _run(
        ["xdg-mime", "query", "default", "x-scheme-handler/https"]
    )
    if desktop_id:
        command = _exec_of_desktop(desktop_id)
        kind = kind_of(desktop_id) or (kind_of(command[0]) if command else None)
        if command and kind:
            return _linux_browser(kind, command, desktop_id)
    for name in (os.environ.get("BROWSER") or "").split(":"):
        if name and kind_of(name) and shutil.which(name):
            return _linux_browser(kind_of(name), [shutil.which(name)], name)
    return None


def _linux_browser(kind, command, identifier="") -> Browser:
    """A Linux browser, with its confinement worked out from how it is started."""
    if command and os.path.basename(command[0]) == "flatpak":
        app = next((w for w in command[1:] if "." in w and not w.startswith("-")), "")
        return Browser(kind, command, "flatpak", app)
    resolved = os.path.realpath(shutil.which(command[0]) or command[0]) if command else ""
    if resolved.startswith("/snap/") or identifier.endswith(".desktop") and "_" in identifier:
        snap = identifier.split("_", 1)[0] if "_" in identifier else os.path.basename(command[0])
        return Browser(kind, command, "snap", snap)
    return Browser(kind, command)


def _macos_default() -> Optional[Browser]:
    plist = Path.home() / "Library/Preferences/com.apple.LaunchServices/com.apple.launchservices.secure.plist"
    bundle_id = "com.apple.safari"
    try:
        with open(plist, "rb") as f:
            for handler in plistlib.load(f).get("LSHandlers", []):
                if handler.get("LSHandlerURLScheme") == "https" and handler.get("LSHandlerRoleAll"):
                    bundle_id = handler["LSHandlerRoleAll"]
                    break
    except (OSError, plistlib.InvalidFileException, ValueError):
        pass
    kind = kind_of(bundle_id)
    if kind is None:
        return None
    app = _macos_app(bundle_id)
    executable = _macos_executable(app) if app else None
    return Browser(kind, [executable]) if executable else None


def _macos_app(bundle_id: str) -> Optional[str]:
    found = _run(["mdfind", "kMDItemCFBundleIdentifier == '%s'" % bundle_id]).splitlines()
    return next((path for path in found if path.endswith(".app")), None)


def _macos_executable(app: str) -> Optional[str]:
    try:
        with open(os.path.join(app, "Contents", "Info.plist"), "rb") as f:
            name = plistlib.load(f).get("CFBundleExecutable")
    except (OSError, plistlib.InvalidFileException, ValueError):
        return None
    path = os.path.join(app, "Contents", "MacOS", name or "")
    return path if name and os.path.isfile(path) else None


def _windows_default() -> Optional[Browser]:
    try:
        import winreg
    except ImportError:
        return None
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice",
        ) as key:
            prog_id = winreg.QueryValueEx(key, "ProgId")[0]
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, prog_id + r"\shell\open\command") as key:
            command_line = winreg.QueryValueEx(key, "")[0]
    except OSError:
        return None
    executable = _windows_executable(command_line)
    kind = kind_of(prog_id) or (kind_of(os.path.basename(executable)) if executable else None)
    return Browser(kind, [executable]) if kind and executable else None


def _windows_executable(command_line: str) -> Optional[str]:
    """The program a registry command line runs: the quoted first word, or the first word."""
    command_line = command_line.strip()
    if command_line.startswith('"'):
        return command_line[1:].split('"', 1)[0]
    match = re.match(r"(.+?\.exe)\b", command_line, re.IGNORECASE)
    return match.group(1) if match else (command_line.split() or [None])[0]


def default_browser() -> Optional[Browser]:
    """The user's default browser, as this system records it, or None when it cannot tell."""
    if sys.platform == "win32":
        return _windows_default()
    if sys.platform == "darwin":
        return _macos_default()
    return _linux_default()


# Where each browser usually is, for when the default one will not do.
_INSTALLED = {
    "win32": [
        ("chrome", r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
        ("chrome", r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
        ("chrome", r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ("edge", r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe"),
        ("edge", r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe"),
        ("brave", r"%PROGRAMFILES%\BraveSoftware\Brave-Browser\Application\brave.exe"),
        ("firefox", r"%PROGRAMFILES%\Mozilla Firefox\firefox.exe"),
        ("firefox", r"%PROGRAMFILES(X86)%\Mozilla Firefox\firefox.exe"),
    ],
    "darwin": [
        ("chrome", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        ("edge", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        ("brave", "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
        ("chromium", "/Applications/Chromium.app/Contents/MacOS/Chromium"),
        ("firefox", "/Applications/Firefox.app/Contents/MacOS/firefox"),
    ],
    "linux": [
        ("chrome", "google-chrome"),
        ("chrome", "google-chrome-stable"),
        ("chromium", "chromium"),
        ("chromium", "chromium-browser"),
        ("edge", "microsoft-edge"),
        ("brave", "brave-browser"),
        ("firefox", "firefox"),
        ("firefox", "firefox-esr"),
    ],
}


def installed_browsers() -> List[Browser]:
    """The browsers PartCAD can put its extension in that are installed here, best first."""
    platform = sys.platform if sys.platform in _INSTALLED else "linux"
    found = []
    for kind, where in _INSTALLED[platform]:
        path = os.path.expandvars(where) if platform == "win32" else where
        resolved = path if os.path.isabs(path) and os.path.isfile(path) else shutil.which(path)
        if resolved and all(b.command[0] != resolved for b in found):
            found.append(_linux_browser(kind, [resolved]) if platform == "linux" else Browser(kind, [resolved]))
    return found


def browser_named(name_or_path: str) -> Optional[Browser]:
    """The browser the user named: a path, a command on PATH, or a kind ('firefox', 'edge')."""
    resolved = name_or_path if os.path.isfile(name_or_path) else shutil.which(name_or_path)
    if resolved:
        kind = kind_of(os.path.basename(resolved)) or kind_of(name_or_path) or "chromium"
        return _linux_browser(kind, [resolved]) if sys.platform.startswith("linux") else Browser(kind, [resolved])
    return next((b for b in installed_browsers() if b.kind == name_or_path.lower()), None)


def choose(name_or_path: Optional[str] = None) -> Optional[Browser]:
    """The browser to log in with: the one named, else the default, else one that can take the extension."""
    if name_or_path:
        return browser_named(name_or_path)
    browser = default_browser()
    if browser is not None and browser.family in ("chromium", "firefox"):
        return browser
    return next(iter(installed_browsers()), None)


# --- PartCAD's profile, and the extension in it ------------------------------------


def extension_source(family: str) -> Optional[Path]:
    """The unpacked extension for a family of browsers, as this installation of PartCAD carries it."""
    here = Path(__file__).resolve().parent
    for candidate in (here / "browsers" / family, here.parent.parent / "browsers" / family):
        if (candidate / "manifest.json").is_file():
            return candidate
    return None


def profile_root(browser: Browser) -> Path:
    """Where PartCAD keeps its own profile of 'browser', somewhere that browser can write."""
    home = Path.home()
    if browser.confinement == "snap" and browser.app_id:
        return home / "snap" / browser.app_id / "common" / "partcad-login"
    if browser.confinement == "flatpak" and browser.app_id:
        return home / ".var" / "app" / browser.app_id / "data" / "partcad-login"
    base = os.environ.get("PC_LOGIN_PROFILE_DIR")
    return Path(base) if base else home / ".partcad" / "browser" / browser.kind


def _prepare(browser: Browser):
    """(profile directory, extension directory) for 'browser', the extension copied in afresh."""
    root = profile_root(browser)
    profile = root / "profile"
    profile.mkdir(parents=True, exist_ok=True)
    source = extension_source(browser.family)
    if source is None:
        return profile, None
    # A copy beside the profile, rather than the one in the installation: a
    # confined browser cannot read site-packages, and a copy refreshed every
    # time is never the extension of a PartCAD that was upgraded since.
    extension = root / "extension"
    shutil.rmtree(extension, ignore_errors=True)
    shutil.copytree(source, extension)
    return profile, extension


# --- starting it ---------------------------------------------------------------------


@dataclass
class Opened:
    """A browser 'pc login' started, and whether the extension is in it."""

    browser: Browser
    process: Optional[object] = None
    extension: bool = False
    note: str = ""
    _close: Optional[object] = field(default=None, repr=False)

    def close(self):
        """End the browser if it is still running: the login is over, whichever way it went."""
        if self._close is not None:
            try:
                self._close()
            except Exception:
                pass
        process = self.process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=5)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass


_CHROMIUM_ARGUMENTS = [
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-default-apps",
    "--disable-sync",
    "--password-store=basic",
]


def _extra_arguments() -> List[str]:
    """Arguments the environment adds - 'PC_LOGIN_BROWSER_ARGS' - for a test that runs headless."""
    return shlex.split(os.environ.get("PC_LOGIN_BROWSER_ARGS", ""))


def open_browser(url: str, browser: Browser) -> Opened:
    """Start 'browser' on PartCAD's profile, with the extension, at 'url'."""
    profile, extension = _prepare(browser)
    if browser.family == "chromium":
        return _open_chromium(url, browser, profile, extension)
    if browser.family == "firefox":
        return _open_firefox(url, browser, profile, extension)
    process = subprocess.Popen(browser.command + [url], **_detached())
    return Opened(browser, process, False, "%s cannot be given PartCAD's extension" % browser.name)


def _detached() -> dict:
    """How to start a browser that outlives nothing it should not and prints nowhere."""
    options = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform == "win32":
        options["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        options["start_new_session"] = True
    return options


def _forget_last_session(profile: Path) -> None:
    """Start PartCAD's Chromium profile with no tabs of a login that is over.

    The profile is kept for its sign-ins, not for its tabs: without this, a
    login that ended with the browser killed rather than closed comes back,
    window and all, beside the one this login opens. Only PartCAD's profile is
    ever touched.
    """
    default = profile / "Default"
    shutil.rmtree(default / "Sessions", ignore_errors=True)
    for name in ("Current Session", "Current Tabs", "Last Session", "Last Tabs"):
        try:
            (default / name).unlink()
        except OSError:
            pass
    preferences = default / "Preferences"
    try:
        settings = json.loads(preferences.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    settings.setdefault("profile", {}).update({"exit_type": "Normal", "exited_cleanly": True})
    settings.setdefault("session", {})["restore_on_startup"] = 5  # the New Tab page, not the last session
    try:
        preferences.write_text(json.dumps(settings), encoding="utf-8")
    except OSError:
        pass


def _open_chromium(url, browser, profile, extension) -> Opened:
    _forget_last_session(profile)
    arguments = ["--user-data-dir=%s" % profile] + _CHROMIUM_ARGUMENTS + _extra_arguments()
    if extension is not None and sys.platform != "win32":
        opened = _open_chromium_over_pipe(url, browser, arguments, extension)
        if opened is not None:
            return opened
    # The flag, which every Chromium honoured until Google Chrome 137 stopped:
    # still the way in for the others, for an older Chrome, and on Windows,
    # where the pipe is not set up here.
    flags = []
    if extension is not None:
        flags = ["--load-extension=%s" % extension, "--disable-extensions-except=%s" % extension]
        if browser.kind == "chrome":
            flags.append("--disable-features=DisableLoadExtensionCommandLineSwitch")
    process = subprocess.Popen(browser.command + arguments + flags + [url], **_detached())
    note = "" if extension is not None else "PartCAD's extension is not in this installation"
    return Opened(browser, process, extension is not None, note)


class _DevToolsPipe:
    """Chromium's DevTools protocol on the pipe it reads from descriptor 3 and writes to 4."""

    def __init__(self, to_browser: int, from_browser: int):
        self._out = to_browser
        self._in = from_browser
        self._buffer = b""
        self._next = 0
        self._lock = threading.Lock()

    def call(self, method, params=None, timeout=20.0):
        with self._lock:
            self._next += 1
            ident = self._next
            message = json.dumps({"id": ident, "method": method, "params": params or {}}).encode() + b"\0"
            os.write(self._out, message)
            deadline = time.monotonic() + timeout
            while True:
                while b"\0" in self._buffer:
                    raw, self._buffer = self._buffer.split(b"\0", 1)
                    answer = json.loads(raw.decode("utf-8", "replace"))
                    if answer.get("id") == ident:
                        if "error" in answer:
                            raise RuntimeError(answer["error"].get("message", str(answer["error"])))
                        return answer.get("result", {})
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("%s: no answer from the browser" % method)
                ready, _, _ = select.select([self._in], [], [], remaining)
                if ready:
                    chunk = os.read(self._in, 1 << 16)
                    if not chunk:
                        raise RuntimeError("the browser closed its DevTools pipe")
                    self._buffer += chunk

    def close(self):
        for descriptor in (self._out, self._in):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _spawn_with_pipe(command):
    """Start 'command' with a pipe on descriptors 3 (to it) and 4 (from it): (pid, DevToolsPipe)."""
    to_read, to_write = os.pipe()
    from_read, from_write = os.pipe()
    devnull = os.open(os.devnull, os.O_RDWR)
    actions = [
        (os.POSIX_SPAWN_DUP2, devnull, 0),
        (os.POSIX_SPAWN_DUP2, devnull, 1),
        (os.POSIX_SPAWN_DUP2, devnull, 2),
        (os.POSIX_SPAWN_DUP2, to_read, 3),
        (os.POSIX_SPAWN_DUP2, from_write, 4),
    ]
    executable = shutil.which(command[0]) or command[0]
    try:
        try:
            # Its own session, so the terminal's Ctrl-C ends 'pc login' and
            # not the browser the user is signing in with.
            pid = os.posix_spawn(executable, command, os.environ, file_actions=actions, setsid=True)
        except NotImplementedError:
            pid = os.posix_spawn(executable, command, os.environ, file_actions=actions)
    finally:
        for descriptor in (to_read, from_write, devnull):
            os.close(descriptor)
    return pid, _DevToolsPipe(to_write, from_read)


class _SpawnedProcess:
    """The little of 'subprocess.Popen' that 'Opened' uses, for a process 'os.posix_spawn' started."""

    def __init__(self, pid):
        self.pid = pid
        self.returncode = None

    def poll(self):
        if self.returncode is None:
            try:
                pid, status = os.waitpid(self.pid, os.WNOHANG)
            except ChildProcessError:
                self.returncode = 0
                return 0
            if pid:
                self.returncode = os.waitstatus_to_exitcode(status)
        return self.returncode

    def wait(self, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        while self.poll() is None:
            if deadline is not None and time.monotonic() > deadline:
                raise subprocess.TimeoutExpired(str(self.pid), timeout)
            time.sleep(0.05)
        return self.returncode

    def terminate(self):
        try:
            os.kill(self.pid, 15)
        except ProcessLookupError:
            pass

    def kill(self):
        try:
            os.kill(self.pid, 9)
        except ProcessLookupError:
            pass


def _open_chromium_over_pipe(url, browser, arguments, extension) -> Optional[Opened]:
    """Start a Chromium with DevTools on a pipe and load the extension through it; None if it would not."""
    if not hasattr(os, "posix_spawn"):
        return None
    command = browser.command + arguments + ["--remote-debugging-pipe", "--enable-unsafe-extension-debugging"]
    try:
        pid, pipe = _spawn_with_pipe(command + ["about:blank"])
    except (OSError, NotImplementedError):
        return None
    process = _SpawnedProcess(pid)
    try:
        pipe.call("Extensions.loadUnpacked", {"path": str(extension)})
        pipe.call("Target.createTarget", {"url": url})
    except Exception:
        pipe.close()
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        return None

    def close():
        try:
            pipe.call("Browser.close", timeout=5)
        finally:
            pipe.close()

    # The pipe is kept open for as long as the login runs: the browser ends
    # when it closes.
    return Opened(browser, process, True, "", close)


# --- Firefox ---------------------------------------------------------------------------

FIREFOX_EXTENSION_ID = "login@partcad.org"

_FIREFOX_PREFERENCES = {
    # Honoured only by the Firefox builds that may run unsigned extensions
    # (ESR, Developer Edition, Nightly, unbranded); release Firefox ignores it,
    # and is given the extension over WebDriver BiDi instead.
    "xpinstall.signatures.required": False,
    "extensions.autoDisableScopes": 0,
    "extensions.enabledScopes": 15,
    "browser.shell.checkDefaultBrowser": False,
    "browser.aboutwelcome.enabled": False,
    "datareporting.policy.dataSubmissionEnabled": False,
    "toolkit.telemetry.reportingpolicy.firstRun": False,
    "browser.startup.homepage_override.mstone": "ignore",
}


def _write_firefox_profile(profile: Path, extension: Optional[Path]) -> Optional[Path]:
    """Preferences, and the extension as an XPI in the profile. Returns the XPI."""
    lines = ["user_pref(%s, %s);" % (json.dumps(k), json.dumps(v)) for k, v in _FIREFOX_PREFERENCES.items()]
    (profile / "user.js").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if extension is None:
        return None
    xpi = profile.parent / ("%s.xpi" % FIREFOX_EXTENSION_ID)
    signed = extension / "signed.xpi"
    if signed.is_file():
        shutil.copyfile(signed, xpi)
    else:
        with zipfile.ZipFile(xpi, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(extension.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(extension).as_posix())
    installed = profile / "extensions"
    installed.mkdir(exist_ok=True)
    shutil.copyfile(xpi, installed / xpi.name)
    return xpi


def _open_firefox(url, browser, profile, extension) -> Opened:
    xpi = _write_firefox_profile(profile, extension)
    command = browser.command + ["-profile", str(profile), "-no-remote", "-new-instance"] + _extra_arguments()
    if xpi is not None:
        opened = _open_firefox_over_bidi(url, browser, command, xpi)
        if opened is not None:
            return opened
    process = subprocess.Popen(command + [url], **_detached())
    note = "" if xpi is not None else "PartCAD's extension is not in this installation"
    return Opened(browser, process, xpi is not None, note)


def _open_firefox_over_bidi(url, browser, command, xpi) -> Optional[Opened]:
    """Start Firefox with WebDriver BiDi, install the XPI as a temporary add-on, open 'url'; None if not."""
    with tempfile.TemporaryFile() as log:
        try:
            process = subprocess.Popen(
                command + ["--remote-debugging-port", "0"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=log,
                start_new_session=sys.platform != "win32",
            )
        except OSError:
            return None
        endpoint = None
        deadline = time.monotonic() + 30
        while endpoint is None and time.monotonic() < deadline and process.poll() is None:
            time.sleep(0.2)
            log.seek(0)
            match = re.search(rb"WebDriver BiDi listening on (ws://\S+)", log.read())
            if match:
                endpoint = match.group(1).decode()
    if endpoint is None:
        _stop(process)
        return None
    try:
        import asyncio

        asyncio.run(_bidi_install(endpoint.rstrip("/") + "/session", str(xpi), url))
    except Exception:
        _stop(process)
        return None
    return Opened(browser, process, True)


async def _bidi_install(endpoint, xpi, url):
    import aiohttp

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(endpoint) as socket:
            ident = 0

            async def call(method, params):
                nonlocal ident
                ident += 1
                await socket.send_json({"id": ident, "method": method, "params": params})
                while True:
                    answer = await socket.receive_json(timeout=30)
                    if answer.get("id") == ident:
                        if answer.get("type") == "error":
                            raise RuntimeError(answer.get("message") or answer.get("error"))
                        return answer.get("result", {})

            await call("session.new", {"capabilities": {}})
            await call("webExtension.install", {"extensionData": {"type": "archivePath", "path": xpi}})
            tree = await call("browsingContext.getTree", {})
            contexts = tree.get("contexts") or []
            if contexts:
                await call("browsingContext.navigate", {"context": contexts[0]["context"], "url": url})
            else:
                await call("browsingContext.create", {"type": "window"})
            # The session is ended, not the browser: without this, Firefox stays
            # under remote control, with the stripes to say so.
            await call("session.end", {})


def _stop(process):
    try:
        process.terminate()
        process.wait(timeout=5)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass
