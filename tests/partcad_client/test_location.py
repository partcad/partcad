#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Asking this machine's location service where it is: what each system's helper is run as, and how it is read.

The services themselves are not here - none of them answers on a test runner -
so what is tested is everything on this side of them: which helper is asked on
which system, what is made of what it prints, and that a failure of any kind is
an answer with a reason rather than an exception. The GeoClue library itself was
exercised against a real GeoClue (with its demo agent and its static source);
see the module's docstring.
"""

import base64
import json
import subprocess

import pytest

from partcad_client import location as pc_location


@pytest.fixture
def ran(monkeypatch):
    """What `_run` was asked to run, and what it is made to print."""
    calls = []
    answer = {"output": "", "raise": None}

    def run(command, timeout, input_text=None, env=None):
        calls.append({"command": command, "timeout": timeout, "input": input_text, "env": env})
        if answer["raise"]:
            raise answer["raise"]
        return 0, answer["output"]

    monkeypatch.setattr(pc_location, "_run", run)
    return calls, answer


# ---- reading what a helper printed ---------------------------------------------


def test_a_location_is_the_last_json_line_printed():
    located = pc_location._answer('noise\n{"latitude": 52.37, "longitude": 4.89, "accuracy": 65}\n', "windows")
    assert (located.latitude, located.longitude, located.accuracy, located.method) == (52.37, 4.89, 65.0, "windows")
    assert located.found and located.message() == ""


def test_a_reason_is_reported_with_what_the_user_can_do_about_it():
    located = pc_location._answer('{"reason": "denied"}', "corelocation")
    assert not located.found and located.reason == pc_location.DENIED
    assert "pc system locale settings" in located.message()
    assert located.to_dict()["found"] is False


@pytest.mark.parametrize("printed", ["", "garbage", '{"latitude": 95, "longitude": 4}', '{"latitude": "north"}'])
def test_anything_else_is_a_failure_and_not_an_exception(printed):
    located = pc_location._answer(printed, "geoclue")
    assert not located.found and located.reason == pc_location.FAILED


def test_core_location_cli_s_own_spelling_of_the_accuracy_is_read():
    located = pc_location._answer('{"latitude": 1.5, "longitude": 2.5, "h_accuracy": 10}', "corelocationcli")
    assert located.accuracy == 10.0


# ---- Windows -------------------------------------------------------------------


def test_windows_asks_the_location_service_through_windows_powershell(monkeypatch, ran):
    calls, answer = ran
    monkeypatch.setattr(pc_location.sys, "platform", "win32")
    monkeypatch.setattr(pc_location, "_windows_powershell", lambda: r"C:\ps\powershell.exe")
    answer["output"] = '{"latitude":52.37,"longitude":4.89,"accuracy":40}'

    located = pc_location.locate(12)

    assert located.found and located.method == "windows"
    command = calls[0]["command"]
    assert command[0] == r"C:\ps\powershell.exe" and "-EncodedCommand" in command
    script = base64.b64decode(command[-1]).decode("utf-16-le")
    assert "GeoCoordinateWatcher" in script and "$timeout = 12.000000" in script
    # The helper has its own timeout, and is given more than it to say so.
    assert calls[0]["timeout"] > 12


def test_windows_without_powershell_has_no_service(monkeypatch, ran):
    monkeypatch.setattr(pc_location.sys, "platform", "win32")
    monkeypatch.setattr(pc_location, "_windows_powershell", lambda: None)
    assert pc_location.locate().reason == pc_location.UNAVAILABLE
    assert pc_location.service() is None


# ---- macOS ---------------------------------------------------------------------


def test_macos_asks_core_location_through_osascript(monkeypatch, ran):
    calls, answer = ran
    monkeypatch.setattr(pc_location.sys, "platform", "darwin")
    monkeypatch.setattr(pc_location.shutil, "which", lambda name: "/usr/bin/osascript" if name == "osascript" else None)
    monkeypatch.setattr(pc_location.os.path, "isfile", lambda path: True)
    answer["output"] = '{"latitude":37.33,"longitude":-122.03,"accuracy":100}\n'

    located = pc_location.locate(5)

    assert located.found and located.method == "corelocation"
    assert calls[0]["command"] == ["/usr/bin/osascript", "-l", "JavaScript", "-"]
    assert "CLLocationManager" in calls[0]["input"]


def test_macos_prefers_core_location_cli_and_falls_back_when_it_cannot_answer(monkeypatch, ran):
    calls, answer = ran
    monkeypatch.setattr(pc_location.sys, "platform", "darwin")
    monkeypatch.setattr(pc_location.shutil, "which", lambda name: "/opt/bin/" + name)
    monkeypatch.setattr(pc_location.os.path, "isfile", lambda path: True)
    answer["output"] = "unknown option --json"

    located = pc_location.locate(5)

    assert [call["command"][0] for call in calls] == ["/opt/bin/CoreLocationCLI", "/opt/bin/osascript"]
    assert located.method == "corelocation"


def test_macos_takes_core_location_cli_s_refusal_as_the_answer(monkeypatch, ran):
    calls, answer = ran
    monkeypatch.setattr(pc_location.sys, "platform", "darwin")
    monkeypatch.setattr(pc_location.shutil, "which", lambda name: "/opt/bin/" + name)
    answer["output"] = '{"reason": "denied"}'

    assert pc_location.locate(5).reason == pc_location.DENIED
    assert len(calls) == 1


# ---- Linux ---------------------------------------------------------------------


def test_linux_without_geoclue_says_what_to_install(monkeypatch, ran):
    monkeypatch.setattr(pc_location.sys, "platform", "linux")
    monkeypatch.setattr(pc_location, "_geoclue_library", lambda: None)
    monkeypatch.setattr(pc_location.os, "access", lambda path, mode: False)

    located = pc_location.locate(3)

    assert located.reason == pc_location.UNAVAILABLE and "GeoClue" in located.detail
    assert pc_location.service() is None


def test_linux_falls_back_on_geoclue_s_demo(monkeypatch, ran):
    calls, answer = ran
    monkeypatch.setattr(pc_location.sys, "platform", "linux")
    monkeypatch.setattr(pc_location, "_geoclue_library", lambda: None)
    demo = pc_location._WHERE_AM_I[0]
    monkeypatch.setattr(pc_location.os, "access", lambda path, mode: path == demo)
    answer["output"] = (
        "Client object: /org/freedesktop/GeoClue2/Client/2\n\nNew location:\n"
        "Latitude:    52.399350\xb0\nLongitude:   4.892340\xb0\nAccuracy:    3050.000000 meters\n"
    )

    located = pc_location.locate(7)

    assert (located.latitude, located.longitude, located.accuracy) == (52.39935, 4.89234, 3050.0)
    assert located.method == "where-am-i"
    assert calls[0]["command"][:3] == [demo, "-t", "7"]
    # Numbers with a '.', whatever the user's locale writes them with.
    assert calls[0]["env"]["LC_ALL"] == "C"
    assert pc_location.service() == "geoclue"


@pytest.mark.parametrize(
    "message, reason",
    [
        ("Operation was cancelled", pc_location.TIMEOUT),
        ("Agent rejected 'partcad' for user '1000'", pc_location.DENIED),
        ("'partcad' disallowed by configuration for UID 1000", pc_location.DENIED),
        ("Could not connect: No such file or directory", pc_location.UNAVAILABLE),
        ("GDBus.Error:org.freedesktop.DBus.Error.ServiceUnknown: no geoclue", pc_location.UNAVAILABLE),
    ],
)
def test_geoclue_s_errors_are_read_as_reasons(message, reason):
    assert pc_location._geoclue_reason(message) == reason


# ---- whatever goes wrong -------------------------------------------------------


@pytest.mark.parametrize(
    "error, reason",
    [
        (subprocess.TimeoutExpired("helper", 1), pc_location.TIMEOUT),
        (FileNotFoundError("helper"), pc_location.UNAVAILABLE),
    ],
)
def test_a_helper_that_hangs_or_is_missing_is_an_answer(monkeypatch, ran, error, reason):
    _calls, answer = ran
    answer["raise"] = error
    monkeypatch.setattr(pc_location.sys, "platform", "win32")
    monkeypatch.setattr(pc_location, "_windows_powershell", lambda: "powershell.exe")
    assert pc_location.locate(1).reason == reason


def test_an_unknown_system_has_no_service(monkeypatch):
    monkeypatch.setattr(pc_location.sys, "platform", "sunos5")
    assert pc_location.locate().reason == pc_location.UNAVAILABLE
    assert pc_location.service() is None
    assert pc_location.settings_command() is None
    assert pc_location.open_settings()[0] is False


def test_a_located_place_is_reported_as_json():
    reported = json.loads(json.dumps(pc_location.Located(1.0, 2.0, None, "geoclue").to_dict()))
    assert reported == {
        "latitude": 1.0,
        "longitude": 2.0,
        "accuracy": None,
        "method": "geoclue",
        "reason": "",
        "detail": "",
        "found": True,
    }


# ---- the settings page ---------------------------------------------------------


@pytest.mark.parametrize(
    "platform, expected",
    [
        ("win32", ["explorer.exe", pc_location.WINDOWS_SETTINGS]),
        ("darwin", ["open", pc_location.MACOS_SETTINGS]),
        ("linux", ["/usr/bin/gnome-control-center", "location"]),
    ],
)
def test_each_system_s_location_settings_are_opened_its_own_way(monkeypatch, platform, expected):
    monkeypatch.setattr(pc_location.sys, "platform", platform)
    monkeypatch.setattr(pc_location.shutil, "which", lambda name: "/usr/bin/" + name)
    assert pc_location.settings_command() == expected

    started = []
    monkeypatch.setattr(pc_location.subprocess, "Popen", lambda command, **options: started.append(command))
    assert pc_location.open_settings() == (True, " ".join(expected))
    assert started == [expected]


def test_a_linux_desktop_without_gnome_s_settings_is_told_so(monkeypatch):
    monkeypatch.setattr(pc_location.sys, "platform", "linux")
    monkeypatch.setattr(pc_location.shutil, "which", lambda name: None)
    opened, detail = pc_location.open_settings()
    assert not opened and "no location settings" in detail
