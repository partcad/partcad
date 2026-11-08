#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Where this machine is, asked of its operating system's location service - only when the user said PartCAD may.

PartCAD uses a location for one thing: telling which of a store's shops is
nearest (see 'partcad.locality'), for someone who orders the manufacturing of
parts or handles such orders. It is the user's to give - typed into
'location', or asked of this machine when 'locationAccess' says so - and this
module is the asking. Each system has a service of its own for it, and each
asks the user for its own permission, in its own way, the first time:

- **Windows**: the Windows location service, through .NET's
  ``GeoCoordinateWatcher`` in Windows PowerShell. Whether it answers is
  Settings > Privacy & security > Location, "Let desktop apps access your
  location".
- **macOS**: Core Location - through ``CoreLocationCLI`` where one is installed
  (it is an application of its own, with its own entry in the privacy
  settings), and otherwise through ``osascript``, which macOS attributes to
  the application that started it: the PartCAD IDE, the editor, the terminal.
- **Linux**: GeoClue, through ``libgeoclue`` where the desktop has it
  installed (GNOME, KDE and most others do), and otherwise through its
  ``where-am-i`` demo. GeoClue asks the desktop's agent, which is where GNOME
  shows its own question and its "Location Services" switch.

A failure is an answer and not an exception: the user can always type the
location in, and the reason - denied, switched off, no service, no answer in
time - is what they need to be told. :func:`open_settings` opens the page of
the system's settings where access is granted.

What is kept of an answer is rounded to about a kilometre (see
'partcad_utils.user_locale.rounded_location') before anything writes it down:
enough to pick a shop, and not enough to find a front door.

A client's business and never a daemon's, like everything in
'partcad_client': a daemon can be on another machine, which is not where the
user is. Cheap to import - nothing is loaded until something is asked.
"""

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import asdict, dataclass
from typing import Callable, List, Optional, Tuple

# How long the service is given to answer, in seconds. A first answer can take
# a while - a Wi-Fi scan, a network lookup, a permission question the user has
# to read - and an answer that never comes has to end somewhere.
DEFAULT_TIMEOUT = 30.0

# Why nothing was found, as the JSON reports it.
DENIED = "denied"  # the user, or a policy, said no
DISABLED = "disabled"  # the location service is switched off
UNAVAILABLE = "unavailable"  # there is no service to ask on this machine
TIMEOUT = "timeout"  # the service did not answer in time
FAILED = "failed"  # the service answered with something else

# What the user is told for each, after what the service itself said.
REASONS = {
    DENIED: "This computer did not let PartCAD know where it is. Allow it in the system's location settings "
    "('pc system locale settings'), or type the location in.",
    DISABLED: "Location services are switched off on this computer. Switch them on in the system's settings "
    "('pc system locale settings'), or type the location in.",
    UNAVAILABLE: "There is no location service on this computer that PartCAD can ask. Type the location in.",
    TIMEOUT: "The location service did not answer in time. Try again, or type the location in.",
    FAILED: "The location service could not say where this computer is. Type the location in.",
}

# The name a location request is made under, where the system wants one: the
# desktop file GeoClue's agent looks the application up by.
DESKTOP_ID = "partcad"


@dataclass
class Located:
    """What the location service said: a place, or why there is none."""

    latitude: Optional[float] = None
    longitude: Optional[float] = None
    # How far off the system says the place may be, in metres.
    accuracy: Optional[float] = None
    # Which service answered, or was asked: 'windows', 'corelocation',
    # 'corelocationcli', 'geoclue', 'where-am-i'.
    method: str = ""
    # One of the reasons above when nothing was found.
    reason: str = ""
    detail: str = ""

    @property
    def found(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    def message(self) -> str:
        """What to tell the user about a failure: the reason, and what the service itself said."""
        if self.found:
            return ""
        message = REASONS.get(self.reason, REASONS[FAILED])
        return "%s (%s)" % (message, self.detail) if self.detail else message

    def to_dict(self) -> dict:
        answer = asdict(self)
        answer["found"] = self.found
        if not self.found:
            answer["message"] = self.message()
        return answer


def _answer(text: str, method: str) -> Located:
    """A location from what a helper printed: the last line of JSON in it, as each helper below prints one."""
    for line in reversed((text or "").strip().splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        if data.get("reason"):
            return Located(method=method, reason=str(data["reason"]), detail=str(data.get("detail") or ""))
        try:
            latitude, longitude = float(data["latitude"]), float(data["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
            continue
        accuracy = data.get("accuracy", data.get("h_accuracy"))
        try:
            accuracy = float(accuracy) if accuracy is not None else None
        except (TypeError, ValueError):
            accuracy = None
        return Located(latitude, longitude, accuracy, method)
    return Located(method=method, reason=FAILED, detail=_last_line(text))


def _last_line(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return lines[-1][:200] if lines else ""


def _run(command: List[str], timeout: float, input_text: str = None, env: dict = None) -> Tuple[int, str]:
    """Run a helper, and return its exit status and what it printed - both streams, as text."""
    options = {}
    if sys.platform == "win32":
        options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    completed = subprocess.run(
        command,
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
        **options,
    )
    return completed.returncode, (completed.stdout or "") + "\n" + (completed.stderr or "")


def _helper(command: List[str], method: str, timeout: float, input_text: str = None, env: dict = None) -> Located:
    """Ask a helper, which is given a few seconds beyond the service's own timeout to say so itself."""
    try:
        _status, output = _run(command, timeout + 15, input_text, env)
    except subprocess.TimeoutExpired:
        return Located(method=method, reason=TIMEOUT)
    except OSError as e:
        return Located(method=method, reason=UNAVAILABLE, detail=str(e))
    return _answer(output, method)


# ---- Windows ------------------------------------------------------------------

# .NET Framework's location API, which is Windows PowerShell's (5.1, part of
# every Windows) and not PowerShell 7's. Numbers are written in the invariant
# culture: a Dutch Windows writes '52,37' otherwise.
_WINDOWS_SCRIPT = r"""
$timeout = %(timeout)f
try { Add-Type -AssemblyName System.Device } catch {
  Write-Output '{"reason":"unavailable","detail":"System.Device is not available"}'; exit 0
}
$watcher = New-Object System.Device.Location.GeoCoordinateWatcher([System.Device.Location.GeoPositionAccuracy]::Default)
$watcher.Start($false)
$deadline = [DateTime]::UtcNow.AddSeconds($timeout)
$invariant = [Globalization.CultureInfo]::InvariantCulture
while ([DateTime]::UtcNow -lt $deadline) {
  if ($watcher.Permission -eq 'Denied') { $watcher.Stop(); Write-Output '{"reason":"denied"}'; exit 0 }
  if ($watcher.Status -eq 'Ready') {
    $at = $watcher.Position.Location
    if (-not $at.IsUnknown) {
      $watcher.Stop()
      Write-Output ('{"latitude":' + $at.Latitude.ToString('R', $invariant) + ',"longitude":' + `
        $at.Longitude.ToString('R', $invariant) + ',"accuracy":' + $at.HorizontalAccuracy.ToString('R', $invariant) + '}')
      exit 0
    }
  }
  if ($watcher.Status -eq 'Disabled') { $watcher.Stop(); Write-Output '{"reason":"disabled"}'; exit 0 }
  Start-Sleep -Milliseconds 200
}
$watcher.Stop()
Write-Output '{"reason":"timeout"}'
"""


def _windows_powershell() -> Optional[str]:
    root = os.environ.get("SystemRoot", r"C:\Windows")
    candidate = os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    return candidate if os.path.isfile(candidate) else shutil.which("powershell.exe")


def _locate_windows(timeout: float) -> Located:
    powershell = _windows_powershell()
    if not powershell:
        return Located(method="windows", reason=UNAVAILABLE, detail="Windows PowerShell was not found")
    # Encoded, so that nothing in the script has to survive a command line.
    script = _WINDOWS_SCRIPT % {"timeout": timeout}
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    command = [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded]
    return _helper(command, "windows", timeout)


# ---- macOS --------------------------------------------------------------------

# Core Location from JavaScript for Automation. The location manager answers
# on the run loop, so the script turns it until there is an answer, a refusal
# or no time left. A kilometre is all that is asked for.
_MACOS_SCRIPT = r"""
ObjC.import('CoreLocation');
ObjC.import('Foundation');
function run() {
  var timeout = %(timeout)f;
  if (!$.CLLocationManager.locationServicesEnabled) return JSON.stringify({reason: 'disabled'});
  var manager = $.CLLocationManager.alloc.init;
  manager.desiredAccuracy = 1000;
  try { manager.requestWhenInUseAuthorization; } catch (e) {}
  manager.startUpdatingLocation;
  var deadline = Date.now() + timeout * 1000;
  while (Date.now() < deadline) {
    $.NSRunLoop.currentRunLoop.runUntilDate($.NSDate.dateWithTimeIntervalSinceNow(0.25));
    var status = $.CLLocationManager.authorizationStatus;
    if (status == 1 || status == 2) { manager.stopUpdatingLocation; return JSON.stringify({reason: 'denied'}); }
    var at = manager.location;
    if (at && !at.isNil()) {
      var coordinate = at.coordinate;
      manager.stopUpdatingLocation;
      return JSON.stringify({latitude: coordinate.latitude, longitude: coordinate.longitude,
                             accuracy: at.horizontalAccuracy});
    }
  }
  manager.stopUpdatingLocation;
  return JSON.stringify({reason: 'timeout'});
}
"""


def _locate_macos(timeout: float) -> Located:
    cli = shutil.which("CoreLocationCLI")
    if cli:
        located = _helper([cli, "--json"], "corelocationcli", timeout)
        if located.found or located.reason in (DENIED, DISABLED):
            return located
    osascript = shutil.which("osascript") or "/usr/bin/osascript"
    if not os.path.isfile(osascript):
        return Located(method="corelocation", reason=UNAVAILABLE, detail="osascript was not found")
    return _helper([osascript, "-l", "JavaScript", "-"], "corelocation", timeout, _MACOS_SCRIPT % {"timeout": timeout})


# ---- Linux --------------------------------------------------------------------

# GClueAccuracyLevel: a neighbourhood, which is what a nearest shop needs.
_GCLUE_ACCURACY_NEIGHBORHOOD = 5

_WHERE_AM_I = (
    "/usr/libexec/geoclue-2.0/demos/where-am-i",
    "/usr/lib/geoclue-2.0/demos/where-am-i",
    "/usr/lib/x86_64-linux-gnu/geoclue-2.0/demos/where-am-i",
    "/usr/lib/aarch64-linux-gnu/geoclue-2.0/demos/where-am-i",
)


def _geoclue_library():
    """libgeoclue and the GLib it is built on, loaded - or None where the desktop has no GeoClue library."""
    import ctypes

    try:
        geoclue = ctypes.CDLL("libgeoclue-2.so.0")
        gio = ctypes.CDLL("libgio-2.0.so.0")
        gobject = ctypes.CDLL("libgobject-2.0.so.0")
        glib = ctypes.CDLL("libglib-2.0.so.0")
    except OSError:
        return None
    return geoclue, gio, gobject, glib


def _geoclue_reason(message: str) -> str:
    lowered = message.lower()
    if "cancel" in lowered:
        return TIMEOUT
    if any(word in lowered for word in ("denied", "rejected", "disallowed", "not allowed", "not authorized")):
        return DENIED
    if "disabled" in lowered:
        return DISABLED
    if any(word in lowered for word in ("serviceunknown", "service unknown", "not provided by any", "no such")):
        return UNAVAILABLE
    return FAILED


def _locate_geoclue(timeout: float, library=None) -> Optional[Located]:
    """GeoClue through its own library, or None where there is no such library to load."""
    import ctypes

    library = library or _geoclue_library()
    if library is None:
        return None
    geoclue, gio, gobject, glib = library

    class GError(ctypes.Structure):
        _fields_ = [("domain", ctypes.c_uint32), ("code", ctypes.c_int), ("message", ctypes.c_char_p)]

    geoclue.gclue_simple_new_sync.restype = ctypes.c_void_p
    geoclue.gclue_simple_new_sync.argtypes = [
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.POINTER(GError)),
    ]
    geoclue.gclue_simple_get_location.restype = ctypes.c_void_p
    geoclue.gclue_simple_get_location.argtypes = [ctypes.c_void_p]
    for name in ("gclue_location_get_latitude", "gclue_location_get_longitude", "gclue_location_get_accuracy"):
        getattr(geoclue, name).restype = ctypes.c_double
        getattr(geoclue, name).argtypes = [ctypes.c_void_p]
    gio.g_cancellable_new.restype = ctypes.c_void_p
    gio.g_cancellable_cancel.argtypes = [ctypes.c_void_p]
    gobject.g_object_unref.argtypes = [ctypes.c_void_p]
    glib.g_error_free.argtypes = [ctypes.POINTER(GError)]

    answer = {}

    def ask():
        error = ctypes.POINTER(GError)()
        simple = geoclue.gclue_simple_new_sync(
            DESKTOP_ID.encode(), _GCLUE_ACCURACY_NEIGHBORHOOD, cancellable, ctypes.byref(error)
        )
        if not simple:
            message = error.contents.message.decode("utf-8", "replace") if error else ""
            if error:
                glib.g_error_free(error)
            answer["located"] = Located(method="geoclue", reason=_geoclue_reason(message), detail=message)
            return
        try:
            at = geoclue.gclue_simple_get_location(simple)
            if not at:
                answer["located"] = Located(method="geoclue", reason=FAILED)
                return
            answer["located"] = Located(
                geoclue.gclue_location_get_latitude(at),
                geoclue.gclue_location_get_longitude(at),
                geoclue.gclue_location_get_accuracy(at),
                "geoclue",
            )
        finally:
            gobject.g_object_unref(simple)

    # GeoClue's synchronous call runs a loop of its own until there is a
    # location, which may be never; cancelling it is what ends that loop, and
    # it is done from here because the call does not come back to be told.
    cancellable = gio.g_cancellable_new()
    worker = threading.Thread(target=ask, name="geoclue", daemon=True)
    timer = threading.Timer(timeout, gio.g_cancellable_cancel, args=(cancellable,))
    timer.daemon = True
    worker.start()
    timer.start()
    worker.join(timeout + 5)
    timer.cancel()
    if worker.is_alive():
        # Still inside GeoClue, cancelled or not. A daemon thread does not keep
        # the process alive, and the cancellable it holds is left to it.
        return Located(method="geoclue", reason=TIMEOUT)
    gobject.g_object_unref(cancellable)
    return answer.get("located") or Located(method="geoclue", reason=FAILED)


def _parse_where_am_i(text: str) -> Located:
    latitude = re.search(r"Latitude:\s*(-?\d+(?:\.\d+)?)", text or "")
    longitude = re.search(r"Longitude:\s*(-?\d+(?:\.\d+)?)", text or "")
    accuracy = re.search(r"Accuracy:\s*(\d+(?:\.\d+)?)", text or "")
    if latitude and longitude:
        return Located(
            float(latitude.group(1)),
            float(longitude.group(1)),
            float(accuracy.group(1)) if accuracy else None,
            "where-am-i",
        )
    reason = _geoclue_reason(text or "")
    return Located(method="where-am-i", reason=FAILED if reason == TIMEOUT else reason, detail=_last_line(text))


def _locate_linux(timeout: float) -> Located:
    located = _locate_geoclue(timeout)
    if located is not None:
        return located
    for demo in _WHERE_AM_I:
        if os.access(demo, os.X_OK):
            # The C locale, for a '.' in its numbers.
            env = dict(os.environ, LC_ALL="C")
            command = [demo, "-t", str(int(max(timeout, 1))), "-a", str(_GCLUE_ACCURACY_NEIGHBORHOOD)]
            try:
                _status, output = _run(command, timeout + 15, env=env)
            except subprocess.TimeoutExpired:
                return Located(method="where-am-i", reason=TIMEOUT)
            except OSError as e:
                return Located(method="where-am-i", reason=UNAVAILABLE, detail=str(e))
            return _parse_where_am_i(output)
    return Located(
        method="geoclue",
        reason=UNAVAILABLE,
        detail="GeoClue is not installed: neither libgeoclue-2-0 nor its where-am-i demo",
    )


# ---- what is asked ------------------------------------------------------------


def _locator() -> Optional[Callable[[float], Located]]:
    if sys.platform == "win32":
        return _locate_windows
    if sys.platform == "darwin":
        return _locate_macos
    if sys.platform.startswith("linux"):
        return _locate_linux
    return None


def service() -> Optional[str]:
    """The location service this machine would be asked through ('windows', 'corelocation', 'geoclue'), or None.

    Whether one is *installed*, not whether it will answer: that is the user's
    and the system's to decide, and is found out by asking.
    """
    if sys.platform == "win32":
        return "windows" if _windows_powershell() else None
    if sys.platform == "darwin":
        return "corelocation"
    if sys.platform.startswith("linux"):
        if _geoclue_library() is not None or any(os.access(demo, os.X_OK) for demo in _WHERE_AM_I):
            return "geoclue"
    return None


def locate(timeout: float = DEFAULT_TIMEOUT) -> Located:
    """Ask this machine's location service where it is. Never raises: a failure is a 'Located' with a reason."""
    locator = _locator()
    if locator is None:
        return Located(reason=UNAVAILABLE, detail="no location service is known on %s" % sys.platform)
    try:
        return locator(max(float(timeout), 1.0))
    except Exception as e:  # pylint: disable=broad-except  # an answer, whatever went wrong
        return Located(reason=FAILED, detail=str(e))


# Where each system lets the user decide which applications may know where it is.
WINDOWS_SETTINGS = "ms-settings:privacy-location"
MACOS_SETTINGS = "x-apple.systempreferences:com.apple.preference.security?Privacy_LocationServices"


def settings_command() -> Optional[List[str]]:
    """The command that opens this system's location settings, or None where there is none to open."""
    if sys.platform == "win32":
        return ["explorer.exe", WINDOWS_SETTINGS]
    if sys.platform == "darwin":
        return ["open", MACOS_SETTINGS]
    if sys.platform.startswith("linux"):
        # GNOME's own panel; GNOME 40 and older kept it under "privacy".
        control_center = shutil.which("gnome-control-center")
        if control_center:
            return [control_center, "location"]
    return None


def open_settings() -> Tuple[bool, str]:
    """Open the page of the system's settings where location access is granted; whether it did, and what was run."""
    command = settings_command()
    if command is None:
        return False, "This system has no location settings PartCAD knows how to open."
    options = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform == "win32":
        options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        options["start_new_session"] = True
    try:
        subprocess.Popen(command, **options)
    except OSError as e:
        return False, "Could not run %s: %s" % (" ".join(command), e)
    return True, " ".join(command)
