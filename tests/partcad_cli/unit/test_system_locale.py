#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc system locale`: where the user is, read from and written to their own configuration file.

These are the commands the IDE's first-run question runs, so what is pinned
here is what it relies on: `show --json` says whether the question was asked
(and is not fooled by an address configured by hand), `set` writes only what it
was given and removes what it was given blank, and `locate` reports a failure
as JSON the IDE can show rather than as an exit code alone.
"""

import json

import pytest
import yaml
from click.testing import CliRunner

from partcad_cli.click.command import cli
from partcad_client import location as pc_location
from partcad_utils import user_locale


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    for name in ("LC_ALL", "LC_MESSAGES", "LANGUAGE"):
        monkeypatch.delenv(name, raising=False)
    for name in ("PC_COUNTRY", "PC_LANGUAGE", "PC_CURRENCY", "PC_LOCATION", "PC_LOCATION_ACCESS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("PC_MANUFACTURING_ORDERS", raising=False)
    monkeypatch.setenv("LANG", "nl_NL.UTF-8")
    monkeypatch.setattr(user_locale, "_os_locale_name", lambda: "")
    return tmp_path


def _pc(*args):
    result = CliRunner().invoke(cli, ["--no-ansi", "system", "locale", *args])
    return result


def _show():
    result = _pc("show", "--json")
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def _file(home):
    return yaml.safe_load((home / ".partcad" / "config.yaml").read_text())


def test_nobody_has_been_asked_on_a_new_machine(home):
    shown = _show()
    assert shown["asked"] is False and shown["manufacturingOrders"] is None
    assert shown["locationAccess"] is False
    assert shown["configured"] == {
        "country": None,
        "language": None,
        "currency": None,
        "location": None,
        "address": {},
    }
    # What leaving everything blank means: what PartCAD works out itself.
    assert shown["detected"] == {"country": "NL", "language": "nl", "currency": "EUR"}
    assert shown["resolved"]["country"] == "NL"


def test_an_address_typed_into_the_file_is_not_an_answer_to_the_question(home):
    (home / ".partcad").mkdir()
    (home / ".partcad" / "config.yaml").write_text("user:\n  city: Utrecht\n")
    shown = _show()
    assert shown["asked"] is False
    assert shown["configured"]["address"] == {"city": "Utrecht"}


def test_set_writes_what_it_is_given(home):
    result = _pc(
        "set",
        "--manufacturing-orders",
        "place,handle",
        "--country",
        "gb",
        "--currency",
        "eur",
        "--location",
        "51.5072,-0.1276",
        "--location-access",
        "--line1",
        "1 Example Street",
        "--city",
        "London",
        "--zip-code",
        "SW1A 1AA",
        "--address-country",
        "gb",
        "--json",
    )
    assert result.exit_code == 0, result.output
    assert _file(home) == {
        "country": "GB",
        "currency": "EUR",
        "location": {"latitude": 51.5072, "longitude": -0.1276},
        "locationAccess": True,
        "manufacturingOrders": ["place", "handle"],
        "user": {"line1": "1 Example Street", "city": "London", "zipCode": "SW1A 1AA", "countryCode": "GB"},
    }
    shown = json.loads(result.stdout)
    assert shown["asked"] is True and shown["resolved"]["currency"] == "EUR"


def test_leaving_it_blank_records_the_answer_and_nothing_else(home):
    result = _pc("set", "--manufacturing-orders", "none")
    assert result.exit_code == 0, result.output
    assert _file(home) == {"manufacturingOrders": []}
    assert _show()["asked"] is True


def test_a_blank_value_removes_the_option(home):
    (home / ".partcad").mkdir()
    (home / ".partcad" / "config.yaml").write_text(
        "# mine\ncountry: GB\nlocation: '1,2'\nuser:\n  location: [3, 4]\n  city: London\n  firstName: Ann\n"
    )
    result = _pc("set", "--country", "", "--location", "", "--city", " ")
    assert result.exit_code == 0, result.output
    text = (home / ".partcad" / "config.yaml").read_text()
    assert "# mine" in text
    # Both places a location is read from: either left behind would still be one.
    assert yaml.safe_load(text) == {"user": {"firstName": "Ann"}}


def test_a_blank_answer_is_how_somebody_asks_to_be_asked_again(home):
    _pc("set", "--manufacturing-orders", "place")
    _pc("set", "--manufacturing-orders", "")
    assert _show()["asked"] is False


@pytest.mark.parametrize(
    "option, value",
    [
        ("--country", "Netherlands"),
        ("--language", "Dutch"),
        ("--currency", "euro"),
        ("--location", "north"),
        ("--address-country", "NLD"),
        ("--manufacturing-orders", "sell"),
    ],
)
def test_what_is_not_a_value_is_refused_and_nothing_is_written(home, option, value):
    result = _pc("set", option, value)
    assert result.exit_code != 0
    assert not (home / ".partcad" / "config.yaml").exists()


def test_set_with_nothing_to_set_says_so(home):
    result = _pc("set")
    assert result.exit_code != 0
    assert "Nothing to set" in result.output


def test_show_for_a_person(home):
    _pc("set", "--manufacturing-orders", "handle", "--city", "Utrecht")
    result = _pc("show")
    assert result.exit_code == 0, result.output
    assert "Used for: handling manufacturing orders" in result.stdout
    assert "Country: NL (worked out from this computer's language and region)" in result.stdout
    assert "Address: Utrecht" in result.stdout


def test_locate_saves_a_location_rounded_to_a_kilometre(home, monkeypatch):
    monkeypatch.setattr(pc_location, "locate", lambda timeout: pc_location.Located(52.373091, 4.892341, 30, "fake"))
    result = _pc("locate", "--save", "--json", "--timeout", "4")
    assert result.exit_code == 0, result.output
    answer = json.loads(result.stdout)
    assert answer["found"] and answer["location"] == {"latitude": 52.37, "longitude": 4.89}
    assert _file(home) == {"location": {"latitude": 52.37, "longitude": 4.89}}

    # Asked again from the same place, the file is left alone: writing it
    # restarts the daemon that read it, and the IDE asks every day.
    before = (home / ".partcad" / "config.yaml").stat().st_mtime_ns
    (home / ".partcad" / "config.yaml").touch()
    touched = (home / ".partcad" / "config.yaml").stat().st_mtime_ns
    result = _pc("locate", "--save", "--json")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["unchanged"] is True
    assert (home / ".partcad" / "config.yaml").stat().st_mtime_ns == touched >= before


def test_locate_reports_why_it_found_nothing_and_saves_nothing(home, monkeypatch):
    monkeypatch.setattr(
        pc_location, "locate", lambda timeout: pc_location.Located(method="fake", reason=pc_location.DENIED)
    )
    result = _pc("locate", "--save", "--json")
    assert result.exit_code == 1
    answer = json.loads(result.stdout)
    assert answer["found"] is False and answer["reason"] == "denied"
    assert "pc system locale settings" in answer["message"]
    assert not (home / ".partcad" / "config.yaml").exists()


def test_settings_opens_the_system_s_page(home, monkeypatch):
    monkeypatch.setattr(pc_location, "open_settings", lambda: (True, "open x-apple.systempreferences:..."))
    result = _pc("settings", "--json")
    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"opened": True, "detail": "open x-apple.systempreferences:..."}

    monkeypatch.setattr(pc_location, "open_settings", lambda: (False, "nothing to open"))
    assert _pc("settings").exit_code == 1


def test_what_the_editor_s_form_sends_is_what_set_takes(home):
    """The list `setArguments` builds in ide/vscode/src/locale.ts, as its test pins it."""
    result = CliRunner().invoke(
        cli,
        [
            "--no-ansi",
            "system",
            "locale",
            "set",
            "--manufacturing-orders",
            "place,handle",
            "--country",
            "GB",
            "--language",
            "",
            "--currency",
            "EUR",
            "--location",
            "51.5072, -0.1276",
            "--location-access",
            "--line1",
            "1 Example Street",
            "--line2",
            "",
            "--city",
            "London",
            "--state-code",
            "",
            "--zip-code",
            "SW1A 1AA",
            "--address-country",
            "GB",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    shown = json.loads(result.stdout)
    assert shown["asked"] is True and shown["locationAccess"] is True
    assert shown["configured"]["location"] == {"latitude": 51.5072, "longitude": -0.1276}
    assert shown["configured"]["address"] == {
        "line1": "1 Example Street",
        "city": "London",
        "zipCode": "SW1A 1AA",
        "countryCode": "GB",
    }

    # And "leave blank", which `leaveBlankArguments` builds.
    result = _pc("set", "--manufacturing-orders", "none", "--json")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["manufacturingOrders"] == []
