#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Where the user is: the country, language, currency and location options, and what a plugin is told of them.

Worked out on the client, from its locale, and handed to the daemon with the
rest of the configuration; never worked out on the daemon, which answers for
whoever typed the command. And a plugin is told the country, state and city,
never the address or the location.
"""

import pytest

from partcad_utils import config_report, user_locale
from partcad_utils.user_config import UserConfig

LOCALE_VARIABLES = ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE")
OPTION_VARIABLES = ("PC_COUNTRY", "PC_LANGUAGE", "PC_CURRENCY", "PC_LOCATION")


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A $HOME of its own, with no configuration file, and a process environment that says nothing."""
    monkeypatch.setenv("HOME", str(tmp_path))
    for name in LOCALE_VARIABLES + OPTION_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    # What Python itself thinks the locale is, which the variables above do not
    # always decide: a test states the whole locale it is about.
    monkeypatch.setattr(user_locale.locale, "getlocale", lambda *_: (None, None))
    # And what the operating system's settings say, which on Windows and macOS
    # is asked when the environment says nothing.
    monkeypatch.setattr(user_locale, "_os_locale_name", lambda: "")
    for name in ("PC_LOCATION_ACCESS", "PC_MANUFACTURING_ORDERS"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def _write_config(home, text):
    (home / ".partcad").mkdir(exist_ok=True)
    (home / ".partcad" / "config.yaml").write_text(text)


# ---- making sense of what was configured -------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [("nl", "NL"), (" US ", "US"), ("NLD", None), ("", None), (None, None), ("N1", None)],
)
def test_a_country_is_an_iso_3166_alpha_2_code(value, expected):
    assert user_locale.country_code(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [("EN", "en"), ("en-GB", "en"), ("en_GB.UTF-8", "en"), ("fr@euro", "fr"), ("eng", None), ("", None)],
)
def test_a_language_is_an_iso_639_1_code(value, expected):
    assert user_locale.language_code(value) == expected


@pytest.mark.parametrize("value, expected", [("eur", "EUR"), ("USD", "USD"), ("€", None), ("EURO", None)])
def test_a_currency_is_an_iso_4217_code(value, expected):
    assert user_locale.currency_code(value) == expected


@pytest.mark.parametrize(
    "country, expected",
    [("NL", "EUR"), ("de", "EUR"), ("US", "USD"), ("CA", "CAD"), ("GB", "GBP"), ("SE", "SEK"), ("ZZ", None)],
)
def test_a_country_s_currency_is_known_or_not_guessed(country, expected):
    assert user_locale.currency_of(country) == expected


@pytest.mark.parametrize(
    "value",
    [
        {"latitude": 52.37, "longitude": 4.89},
        {"lat": "52.37", "lng": "4.89"},
        [52.37, 4.89],
        "52.37,4.89",
    ],
)
def test_a_location_can_be_written_several_ways(value):
    assert user_locale.location(value) == {"latitude": 52.37, "longitude": 4.89}


@pytest.mark.parametrize("value", [None, "", "Amsterdam", "91,0", [1, 2, 3], {"latitude": 1}, "a,b"])
def test_anything_else_is_no_location_rather_than_an_error(value):
    assert user_locale.location(value) is None


@pytest.mark.parametrize(
    "environ, expected",
    [
        ({"LANG": "nl_NL.UTF-8"}, ("NL", "nl")),
        ({"LC_ALL": "fr_CA.UTF-8", "LANG": "en_US.UTF-8"}, ("CA", "fr")),
        ({"LANG": "C.UTF-8"}, (None, None)),
        ({"LANG": "POSIX"}, (None, None)),
        ({"LANGUAGE": "de:en"}, (None, "de")),
        ({"LANG": "C", "LANGUAGE": "sv_SE"}, ("SE", "sv")),
        ({}, (None, None)),
    ],
)
def test_the_locale_says_the_country_and_the_language(home, monkeypatch, environ, expected):
    for name, value in environ.items():
        monkeypatch.setenv(name, value)
    assert user_locale.detect() == expected


# ---- the client works them out, the daemon takes them ------------------------


def test_the_client_works_them_out_from_its_locale(home, monkeypatch):
    monkeypatch.setenv("LANG", "nl_NL.UTF-8")
    config = UserConfig()
    assert (config.country, config.language, config.currency) == ("NL", "nl", "EUR")
    assert config.location is None


def test_what_is_configured_wins_over_the_locale(home, monkeypatch):
    monkeypatch.setenv("LANG", "nl_NL.UTF-8")
    _write_config(home, "country: ca\nlanguage: fr\n")
    config = UserConfig()
    assert (config.country, config.language, config.currency) == ("CA", "fr", "CAD")


def test_the_environment_configures_them_too(home, monkeypatch):
    monkeypatch.setenv("LANG", "nl_NL.UTF-8")
    monkeypatch.setenv("PC_COUNTRY", "US")
    monkeypatch.setenv("PC_CURRENCY", "eur")
    monkeypatch.setenv("PC_LOCATION", "40.7,-74.0")
    config = UserConfig()
    assert (config.country, config.language, config.currency) == ("US", "nl", "EUR")
    assert config.location == {"latitude": 40.7, "longitude": -74.0}


def test_the_address_s_country_comes_before_the_locale_s(home, monkeypatch):
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    _write_config(home, "user:\n  countryCode: DE\n  location: '48.1,11.6'\n")
    config = UserConfig()
    assert (config.country, config.language, config.currency) == ("DE", "en", "EUR")
    assert config.location == {"latitude": 48.1, "longitude": 11.6}


def test_what_the_client_worked_out_is_handed_to_the_daemon(home, monkeypatch):
    monkeypatch.setenv("LANG", "sv_SE.UTF-8")
    monkeypatch.setenv("PC_LOCATION", "59.33,18.07")
    sent = UserConfig().to_dict()
    assert {key: sent[key] for key in ("country", "language", "currency")} == {
        "country": "SE",
        "language": "sv",
        "currency": "SEK",
    }

    # The daemon was started somewhere else, and answers for the client anyway.
    monkeypatch.setenv("LANG", "ja_JP.UTF-8")
    monkeypatch.setenv("PC_COUNTRY", "JP")
    monkeypatch.delenv("PC_LOCATION")
    daemon = UserConfig.from_dict(sent)
    assert (daemon.country, daemon.language, daemon.currency) == ("SE", "sv", "SEK")
    assert daemon.location == {"latitude": 59.33, "longitude": 18.07}


def test_the_daemon_works_out_nothing_of_its_own(home, monkeypatch):
    # A client in the 'C' locale, which says nothing: the daemon's locale,
    # environment and file are not where the user is either.
    monkeypatch.setenv("LANG", "C")
    sent = UserConfig().to_dict()
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    monkeypatch.setenv("PC_COUNTRY", "DE")
    monkeypatch.setenv("PC_LOCATION", "52.5,13.4")
    _write_config(home, "language: de\ncurrency: EUR\n")
    daemon = UserConfig.from_dict(sent)
    assert (daemon.country, daemon.language, daemon.currency, daemon.location) == (None, None, None, None)
    assert daemon.user_info() == {}


# ---- what a plugin is told ---------------------------------------------------

USER = """
user:
  firstName: Ann
  lastName: Example
  email: ann@example.com
  line1: Damrak 1
  zipCode: '1012'
  city: Amsterdam
  stateCode: NH
  countryCode: NL
  location: [52.37, 4.89]
"""


def test_a_plugin_is_told_the_country_state_and_city_and_nothing_finer(home, monkeypatch):
    monkeypatch.setenv("LANG", "en_GB.UTF-8")
    _write_config(home, USER)
    config = UserConfig()
    assert config.user_info() == {
        "country": "NL",
        "state": "NH",
        "city": "Amsterdam",
        "language": "en",
        "currency": "EUR",
    }
    # What PartCAD itself uses to choose a shop for a plugin, and keeps.
    assert config.address()["zipCode"] == "1012"
    assert config.location == {"latitude": 52.37, "longitude": 4.89}


def test_a_delivery_address_is_an_address_too(home):
    _write_config(home, "user:\n  shippingAddress:\n    city: Utrecht\n    stateCode: UT\n    countryCode: NL\n")
    info = UserConfig().user_info()
    assert (info["country"], info["state"], info["city"]) == ("NL", "UT", "Utrecht")


# ---- what a report says ------------------------------------------------------


def test_a_report_says_whether_a_location_is_set_and_not_where(home, monkeypatch):
    monkeypatch.setenv("PC_LOCATION", "52.37,4.89")
    monkeypatch.setenv("PC_COUNTRY", "NL")
    reported = dict(config_report.resolved_options(UserConfig()))
    assert reported["location"] == "<set>"
    assert reported["country"] == "NL"
    assert config_report.option_value("location", "") == "<not set>"

    environment = dict(config_report.environment({"PC_LOCATION": "52.37,4.89", "PC_COUNTRY": "NL"}))
    assert environment == {"PC_COUNTRY": "NL", "PC_LOCATION": config_report.SCRUBBED}


# ---- what the operating system says, when the environment does not -----------


def test_the_system_s_own_locale_is_asked_when_the_environment_says_nothing(home, monkeypatch):
    """A process started from the Dock or the Start menu has no LANG; the system's settings still say."""
    monkeypatch.setattr(user_locale, "_os_locale_name", lambda: "en_NL")
    assert user_locale.detect() == ("NL", "en")


def test_the_environment_comes_before_the_system_s_settings(home, monkeypatch):
    monkeypatch.setattr(user_locale, "_os_locale_name", lambda: "en_NL")
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    assert user_locale.detect() == ("DE", "de")


def test_the_system_fills_in_only_what_the_environment_left_unsaid(home, monkeypatch):
    """'LANGUAGE' names a language and no country; the region comes from the system."""
    monkeypatch.setattr(user_locale, "_os_locale_name", lambda: "en_NL")
    monkeypatch.setenv("LANGUAGE", "fr")
    assert user_locale.detect() == ("NL", "fr")


def test_a_script_subtag_is_not_taken_for_a_region(monkeypatch):
    monkeypatch.setattr(user_locale.sys, "platform", "win32")
    monkeypatch.setattr(user_locale, "_windows_locale_name", lambda: "zh-Hans_CN")
    assert user_locale._os_locale_name() == "zh_CN"


def test_a_system_that_will_not_say_says_nothing(monkeypatch):
    def broken():
        raise OSError("no such library")

    monkeypatch.setattr(user_locale.sys, "platform", "darwin")
    monkeypatch.setattr(user_locale, "_macos_locale_name", broken)
    assert user_locale._os_locale_name() == ""


def test_linux_has_no_settings_beside_its_environment(monkeypatch):
    monkeypatch.setattr(user_locale.sys, "platform", "linux")
    assert user_locale._os_locale_name() == ""


# ---- whether any of it is wanted: locationAccess and manufacturingOrders ------


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, None),
        ("", None),
        ([], []),
        ("none", []),
        (["place"], ["place"]),
        (["handle", "place"], ["place", "handle"]),
        ("place, handle", ["place", "handle"]),
        ("HANDLE", ["handle"]),
        (["place", "sell"], ["place"]),
        (42, None),
    ],
)
def test_what_the_user_uses_partcad_for(value, expected):
    assert user_locale.manufacturing_orders(value) == expected


@pytest.mark.parametrize("value, expected", [(None, False), ("", False), (True, True), ("on", True), ("0", False)])
def test_location_access_is_only_on_when_somebody_said_so(value, expected):
    assert user_locale.location_access(value) is expected


def test_a_location_asked_of_the_system_is_kept_to_about_a_kilometre():
    assert user_locale.rounded_location({"latitude": 52.373091, "longitude": 4.892341}) == {
        "latitude": 52.37,
        "longitude": 4.89,
    }
    assert user_locale.rounded_location("north") is None


def test_nobody_has_been_asked_and_nothing_is_allowed_by_default(home):
    config = UserConfig()
    assert config.location_access is False
    assert config.manufacturing_orders is None


def test_the_answers_are_read_from_the_file_and_the_environment(home, monkeypatch):
    _write_config(home, "locationAccess: true\nmanufacturingOrders: [handle]\n")
    config = UserConfig()
    assert (config.location_access, config.manufacturing_orders) == (True, ["handle"])

    monkeypatch.setenv("PC_LOCATION_ACCESS", "off")
    monkeypatch.setenv("PC_MANUFACTURING_ORDERS", "none")
    config = UserConfig()
    assert (config.location_access, config.manufacturing_orders) == (False, [])


def test_the_answers_travel_to_the_daemon_and_never_asked_stays_never_asked(home, monkeypatch):
    sent = UserConfig().to_dict()
    assert sent["locationAccess"] is False and sent["manufacturingOrders"] == ""

    # The daemon's own file says otherwise, and is not where the user is.
    _write_config(home, "locationAccess: true\nmanufacturingOrders: [place]\n")
    daemon = UserConfig.from_dict(sent)
    assert (daemon.location_access, daemon.manufacturing_orders) == (False, None)

    answered = UserConfig.from_dict({**sent, "manufacturingOrders": [], "locationAccess": True})
    assert (answered.location_access, answered.manufacturing_orders) == (True, [])


def test_save_options_writes_the_user_s_answers_and_leaves_the_rest_of_the_file(home):
    from partcad_utils.user_config import save_options

    _write_config(home, "# mine\nthreadsMax: 8  # keep\nuser:\n  firstName: Ann\n")
    path = save_options(
        {"country": "NL", "locationAccess": True, "manufacturingOrders": ["place"]},
        {"line1": "Damrak 1", "city": "Amsterdam"},
    )
    text = (home / ".partcad" / "config.yaml").read_text()
    assert path == str(home / ".partcad" / "config.yaml")
    assert "# mine" in text and "threadsMax: 8  # keep" in text
    config = UserConfig()
    assert (config.country, config.location_access, config.manufacturing_orders) == ("NL", True, ["place"])
    assert config.address() == {"line1": "Damrak 1", "city": "Amsterdam"}
    assert config.pii_config.firstName == "Ann"


def test_none_removes_an_option_and_an_emptied_user_section_goes_with_it(home):
    import yaml

    from partcad_utils.user_config import save_options

    save_options({"country": "NL", "currency": "EUR"}, {"city": "Amsterdam"})
    save_options({"country": None, "manufacturingOrders": []}, {"city": None, "zipCode": None})
    assert yaml.safe_load((home / ".partcad" / "config.yaml").read_text()) == {
        "currency": "EUR",
        "manufacturingOrders": [],
    }


def test_a_location_has_moved_only_when_it_is_further_than_the_service_can_be_off_by():
    amsterdam = {"latitude": 52.37, "longitude": 4.89}
    # GeoClue's answers for one unmoved computer, at neighbourhood accuracy:
    # 52.36, 52.39 and 52.40 were three of them, a few minutes apart.
    assert not user_locale.moved({"latitude": 52.36, "longitude": 4.89}, {"latitude": 52.40, "longitude": 4.89}, 3050)
    assert not user_locale.moved(amsterdam, {"latitude": 52.38, "longitude": 4.89})
    # Utrecht is 35 km away.
    assert user_locale.moved(amsterdam, {"latitude": 52.09, "longitude": 5.12}, 3050)
    # Nothing saved yet: anything found is somewhere.
    assert user_locale.moved(None, amsterdam)
    assert not user_locale.moved(amsterdam, None)


def test_the_distance_is_the_one_partcad_chooses_shops_by():
    from partcad import locality

    assert locality.distance_km is user_locale.distance_km
    assert user_locale.distance_km((52.37, 4.89), (53.22, 6.57)) == pytest.approx(146, abs=3)
