#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'threadsMax' is never lower than four, however it is set.

There are five ways in -- the configuration file, PC_THREADS_MAX, the command
line (which assigns the attribute), the configuration a client hands the daemon
with every request, and nothing at all, which leaves it to the machine -- and the
floor has to hold on every one of them, or it is not a floor: a value that gets
past it on one route is the configuration PartCAD runs with for whoever takes
that route. Each is pinned here, with what the user is told: that the minimum is
four, once. (What the floor is for is said beside 'THREADS_MAX_MINIMUM'; it is
no longer what keeps 'pc render -r' from deadlocking, which nested objects can
no longer do on a pool of any size -- see 'test_sync_threads.py'.)
"""

import logging

import pytest

from partcad_utils import logging as pc_logging
from partcad_utils import user_config as user_config_module
from partcad_utils.user_config import THREADS_MAX_MINIMUM, UserConfig, default_threads_max


@pytest.fixture
def heard(partcad_warnings):
    """What the user is told (see 'partcad_warnings' in tests/conftest.py)."""
    return partcad_warnings


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A HOME of the test's own, with no 'threadsMax' anywhere around it."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("PC_THREADS_MAX", raising=False)
    (tmp_path / ".partcad").mkdir()
    return tmp_path


def write_config(home, text):
    path = home / ".partcad" / "config.yaml"
    path.write_text(text)
    return path


def below(value, origin=None):
    where = " (from %s)" % origin if origin else ""
    return "threadsMax %d%s is below the minimum of 4; using 4 instead" % (value, where)


def test_the_minimum_is_four():
    assert THREADS_MAX_MINIMUM == 4


# ---- the configuration file ------------------------------------------------------


def test_a_low_value_in_the_configuration_file_is_raised(home, heard):
    path = write_config(home, "threadsMax: 2\n")

    assert UserConfig().threads_max == 4
    assert heard == [below(2, str(path))]


@pytest.mark.parametrize("value", [4, 9])
def test_a_value_at_or_above_the_minimum_is_kept(home, heard, value):
    write_config(home, "threadsMax: %d\n" % value)

    assert UserConfig().threads_max == value
    assert heard == []


def test_nothing_set_is_left_for_the_machine_to_decide(home, heard):
    """None, not a number: what the machine gets is 'default_threads_max()'."""
    assert UserConfig().threads_max is None
    assert "threadsMax" not in UserConfig().to_dict()
    assert heard == []


# ---- PC_THREADS_MAX --------------------------------------------------------------


def test_a_low_value_in_the_environment_is_raised(home, heard, monkeypatch):
    monkeypatch.setenv("PC_THREADS_MAX", "2")

    assert UserConfig().threads_max == 4
    assert heard == [below(2, "PC_THREADS_MAX")]


def test_the_environment_is_read_as_a_number(home, heard, monkeypatch):
    monkeypatch.setenv("PC_THREADS_MAX", "6")
    assert UserConfig().threads_max == 6
    assert heard == []


def test_the_environment_outranks_the_file_and_is_what_gets_raised(home, heard, monkeypatch):
    write_config(home, "threadsMax: 9\n")
    monkeypatch.setenv("PC_THREADS_MAX", "1")

    assert UserConfig().threads_max == 4
    assert heard == [below(1, "PC_THREADS_MAX")]


def test_a_value_that_is_not_a_number_is_ignored_rather_than_fatal(home, heard, monkeypatch):
    """It used to raise ValueError while 'partcad_utils' was being imported."""
    monkeypatch.setenv("PC_THREADS_MAX", "lots")

    config = UserConfig()

    assert config.threads_max is None
    assert "threadsMax" not in config.to_dict()
    assert heard == ["threadsMax 'lots' (from PC_THREADS_MAX) is not a whole number, and is ignored"]


# ---- the command line: '--threads-max' assigns the attribute ---------------------


def test_assigning_a_low_value_raises_it(home, heard):
    config = UserConfig()

    config.threads_max = 1

    assert config.threads_max == 4
    assert heard == [below(1)]


def test_an_assigned_value_travels_to_the_daemon(home, heard):
    """'--threads-max' set the attribute alone, which 'to_dict' never read."""
    config = UserConfig()

    config.threads_max = 8

    assert config.to_dict()["threadsMax"] == 8
    assert UserConfig.from_dict(config.to_dict()).threads_max == 8


# ---- the configuration a client hands the daemon ---------------------------------


def test_a_low_value_a_caller_sends_is_raised(home, heard):
    """A client that did not raise it itself -- an older one, or not PartCAD's."""
    assert UserConfig.from_dict({"threadsMax": 2}).threads_max == 4
    assert heard == [below(2, "the caller's configuration")]


def test_what_is_sent_is_what_stands(home, heard, monkeypatch):
    """Raised by the client, so the daemon has nothing to raise and nothing to say.

    The user is told once, by the process that read the setting -- not again by
    the daemon, on every command.
    """
    monkeypatch.setenv("PC_THREADS_MAX", "2")
    sent = UserConfig().to_dict()

    assert sent["threadsMax"] == 4
    assert UserConfig.from_dict(sent).threads_max == 4
    assert heard == [below(2, "PC_THREADS_MAX")]


def test_the_caller_s_value_wins_over_the_daemon_s_own_environment(home, heard, monkeypatch):
    """The daemon's own PC_THREADS_MAX is whatever started it, possibly days ago."""
    monkeypatch.setenv("PC_THREADS_MAX", "2")

    assert UserConfig.from_dict({"threadsMax": 6}).threads_max == 6
    # Nothing about the daemon's own 2: it is not what this request runs under.
    assert heard == []


# ---- said once -------------------------------------------------------------------


def test_the_same_low_value_is_reported_once_per_process(home, heard, monkeypatch):
    """The CLI resolves its configuration more than once per command, and a
    daemon is handed one with every request."""
    monkeypatch.setenv("PC_THREADS_MAX", "3")

    UserConfig()
    UserConfig()
    config = UserConfig()
    config.threads_max = 3

    assert heard == [below(3, "PC_THREADS_MAX")]


def test_a_warning_nobody_can_hear_yet_is_held_until_somebody_can(monkeypatch):
    """The CLI resolves its configuration while it is imported, before its
    renderer exists; the daemon, before its log is connected to the client."""
    monkeypatch.setattr(pc_logging, "_said_once", set())
    monkeypatch.setattr(pc_logging, "_held", {})
    logger = logging.getLogger("partcad")
    monkeypatch.setattr(logger, "handlers", [])

    pc_logging.warning_once("key", "said once")

    messages = []

    class Collect(logging.Handler):
        def emit(self, record):
            messages.append(record.getMessage())

    logger.addHandler(Collect(level=logging.WARNING))
    assert messages == []

    pc_logging.release_held_warnings()
    pc_logging.release_held_warnings()
    pc_logging.warning_once("key", "said once")

    assert messages == ["said once"]


# ---- nothing set: the machine decides ----------------------------------------------


def test_two_cores_still_get_the_minimum_and_are_told_once(heard, monkeypatch):
    monkeypatch.setattr(user_config_module.os, "cpu_count", lambda: 2)

    assert default_threads_max() == 4
    assert default_threads_max() == 4

    assert heard == ["PartCAD needs at least 4 CPU cores for optimal performance, and found 2"]


def test_eight_cores_get_eight_and_nothing_is_said(heard, monkeypatch):
    monkeypatch.setattr(user_config_module.os, "cpu_count", lambda: 8)

    assert default_threads_max() == 8
    assert heard == []


def test_a_core_count_python_cannot_tell_is_one(heard, monkeypatch):
    """'os.cpu_count()' answers None when it cannot tell."""
    monkeypatch.setattr(user_config_module.os, "cpu_count", lambda: None)

    assert default_threads_max() == 4
    assert heard == ["PartCAD needs at least 4 CPU cores for optimal performance, and found 1"]
