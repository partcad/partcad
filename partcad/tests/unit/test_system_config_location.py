#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#
"""'pc system set ...' has to write the file PartCAD reads at startup.

That file is '$HOME/.partcad/config.yaml' -- UserConfig loads nothing else.
Deriving the destination from 'internalStateDir' instead made every
'pc system set' silently ineffective as soon as the state dir was moved: the
command reported success, wrote the value to '<internalStateDir>/config.yaml',
and the next run read the old value back from the untouched user config.
"""

import pytest

from partcad.actions.config import system_config_get, system_config_set
from partcad.user_config import UserConfig, user_config


def _set_telemetry_type(value: str) -> None:
    """Exactly what the 'pc system set telemetry type <value>' command does."""
    yaml, config = system_config_get()
    if "telemetry" not in config:
        config["telemetry"] = {}
    config["telemetry"]["type"] = value
    system_config_set(yaml, config)


@pytest.fixture
def relocated_dirs(tmp_path, monkeypatch):
    """A $HOME and an 'internalStateDir' that are deliberately not the same place.

    This is what '--internal-state-dir' / 'PC_INTERNAL_STATE_DIR' produces, and
    the only configuration in which the two paths could ever disagree.
    """
    home = tmp_path / "home"
    state = tmp_path / "state"
    home.mkdir()
    state.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(user_config, "internal_state_dir", str(state))
    # A PC_* override in the developer's own environment outranks the config
    # file, which would mask exactly the behaviour under test.
    monkeypatch.delenv("PC_TELEMETRY_TYPE", raising=False)
    monkeypatch.delenv("PC_INTERNAL_STATE_DIR", raising=False)
    return home, state


def test_setting_is_read_back_with_a_relocated_state_dir(relocated_dirs):
    _set_telemetry_type("none")

    assert UserConfig().telemetry_config.type == "none"


def test_setting_lands_in_the_user_config_dir(relocated_dirs):
    home, state = relocated_dirs

    _set_telemetry_type("none")

    assert (home / ".partcad" / "config.yaml").exists()
    assert not (state / "config.yaml").exists()


def test_unrelated_settings_survive_the_write(relocated_dirs):
    """The write edits the live config in place instead of replacing it."""
    home, _state = relocated_dirs
    (home / ".partcad").mkdir()
    (home / ".partcad" / "config.yaml").write_text("threadsMax: 3\n")

    _set_telemetry_type("none")

    config = UserConfig()
    assert config.telemetry_config.type == "none"
    assert config.get_int("threadsMax") == 3


def test_a_leftover_state_dir_config_is_neither_read_nor_touched(relocated_dirs):
    """A config.yaml an older PartCAD wrote under 'internalStateDir' is inert.

    It never fed into anything PartCAD loaded, so adopting it now would activate
    settings the user has no reason to expect. It is reported (see
    partcad.actions.config.system) and otherwise left exactly as it is.
    """
    home, state = relocated_dirs
    leftover = state / "config.yaml"
    leftover_content = 'telemetry:\n  sentryDsn: "leftover"\n'
    leftover.write_text(leftover_content)

    _set_telemetry_type("none")

    # It is not used as the base for the new write...
    assert "leftover" not in (home / ".partcad" / "config.yaml").read_text()
    # ...it does not reach the configuration PartCAD actually loads...
    assert UserConfig().telemetry_config.sentry_dsn != "leftover"
    # ...and it is not deleted or rewritten behind the user's back.
    assert leftover.read_text() == leftover_content


def test_default_layout_still_round_trips(tmp_path, monkeypatch):
    """The default, where the state dir and the config dir are one directory."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("PC_TELEMETRY_TYPE", raising=False)
    monkeypatch.delenv("PC_INTERNAL_STATE_DIR", raising=False)
    monkeypatch.setattr(user_config, "internal_state_dir", UserConfig.get_config_dir())

    _set_telemetry_type("none")

    assert UserConfig().telemetry_config.type == "none"
