#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc --extra-param`: any object name, every override kept, and a refusal that says what was wrong."""

import re

from partcad_cli.click.command import cli
from partcad_utils.user_config import user_config


def _run(click_runner, tmp_path, *overrides):
    path = tmp_path / "notes.txt"
    path.write_text("nothing to check\n")
    arguments = ["--no-ansi"]
    for override in overrides:
        arguments += ["--extra-param", override]
    # A command that runs here and quickly: '--file' on a file nothing checks.
    return click_runner.invoke(cli, arguments + ["lint", "--file", str(path)])


def test_every_override_of_one_object_stands(click_runner, tmp_path):
    try:
        result = _run(click_runner, tmp_path, "//test:desk.length=60", "//test:desk.width=30")
        assert result.exit_code == 0, result.output
        assert user_config.parameter_config["//test:desk"] == {"length": "60", "width": "30"}
    finally:
        del user_config.parameter_config["//test:desk"]


def test_an_object_name_may_have_dots(click_runner, tmp_path):
    try:
        result = _run(click_runner, tmp_path, "//test/v1.2:bracket.v2.length=60.5")
        assert result.exit_code == 0, result.output
        assert user_config.parameter_config["//test/v1.2:bracket.v2"] == {"length": "60.5"}
    finally:
        del user_config.parameter_config["//test/v1.2:bracket.v2"]


def test_an_override_that_names_no_parameter_is_refused(click_runner, tmp_path):
    result = _run(click_runner, tmp_path, "length=60")
    assert result.exit_code == 2
    # The usage box wraps, colours and frames the message.
    text = " ".join(re.sub(r"[│╭╮╰╯─]", " ", re.sub(r"\x1b\[[0-9;]*m", "", result.output)).split())
    assert "Invalid value for '--extra-param': 'length=60' is not '<object>.<parameter>=<value>'" in text
