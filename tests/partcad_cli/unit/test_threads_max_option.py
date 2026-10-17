#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc --threads-max`: never below four, and what a daemon is handed.

The option assigns the attribute after the configuration has been read, which
is how it used to slip past everything: the attribute was all it set, so no
floor applied to it and no daemon ever saw it -- 'to_dict', which is what
travels, reads the settings. Run through the real command line here, with
`pc config`, which prints the configuration in this process.
"""

import logging

import pytest
import rich_click as click

import partcad
from partcad_cli.click import command
from partcad_cli.click.command import cli
from partcad_utils.user_config import UserConfig


def test_the_option_is_global_and_read_from_pc_threads_max(monkeypatch):
    """Named by the group's 'auto_envvar_prefix' rather than on the option."""
    monkeypatch.setenv("PC_THREADS_MAX", "2")
    option = next(param for param in cli.params if param.name == "threads_max")

    assert "--threads-max" in option.opts
    assert option.resolve_envvar_value(click.Context(cli, **cli.context_settings)) == "2"


@pytest.fixture
def own_configuration(tmp_path, monkeypatch):
    """A configuration of the test's own in place of the process's.

    What the command line assigns lands on the process-wide configuration, and
    the rest of the session must not inherit a '--threads-max' from this test.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("PC_THREADS_MAX", raising=False)

    def install():
        config = UserConfig()
        monkeypatch.setattr(command, "pc_user_config", config)
        monkeypatch.setattr(partcad, "user_config", config)
        return config

    return install


@pytest.fixture
def printed():
    """What `pc config` prints, line by line, however the renderer is set up."""
    lines = []

    class Collect(logging.Handler):
        def emit(self, record):
            lines.append(record.getMessage())

    logger = logging.getLogger("partcad")
    handler = Collect(level=logging.INFO)
    logger.addHandler(handler)
    yield lines
    logger.removeHandler(handler)


def test_a_low_value_on_the_command_line_is_raised_with_a_warning(
    click_runner, own_configuration, partcad_warnings, printed
):
    config = own_configuration()

    result = click_runner.invoke(cli, ["--no-ansi", "--threads-max", "2", "config"])

    assert result.exit_code == 0, result.output
    assert "threads_max: 4" in printed
    assert partcad_warnings == ["threadsMax 2 is below the minimum of 4; using 4 instead"]
    # And it is what a daemon would be handed with the command's request.
    assert config.to_dict()["threadsMax"] == 4


def test_a_value_on_the_command_line_travels_to_the_daemon(click_runner, own_configuration, partcad_warnings, printed):
    config = own_configuration()

    result = click_runner.invoke(cli, ["--no-ansi", "--threads-max", "6", "config"])

    assert result.exit_code == 0, result.output
    assert "threads_max: 6" in printed
    assert config.to_dict()["threadsMax"] == 6
    assert partcad_warnings == []


def test_a_low_pc_threads_max_is_reported_once_however_often_it_is_read(
    click_runner, own_configuration, partcad_warnings, printed, monkeypatch
):
    """Read by the configuration as it is built, and again by click for the option."""
    monkeypatch.setenv("PC_THREADS_MAX", "2")
    own_configuration()

    result = click_runner.invoke(cli, ["--no-ansi", "config"])

    assert result.exit_code == 0, result.output
    assert "threads_max: 4" in printed
    assert partcad_warnings == ["threadsMax 2 (from PC_THREADS_MAX) is below the minimum of 4; using 4 instead"]
