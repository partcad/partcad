#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'-p'/'--param' on every command that names an object.

What is pinned here is what reaches the daemon: one spelling, one parameter
name, on every command that offers it, and a value with no '=' refused before
anything is sent. What the daemon does with the values -- write them into the
object's name -- is tested beside the operations.
"""

import importlib

import click
import pytest
from click.testing import CliRunner

from partcad_cli.click.command import cli


class _Recorder:
    def __init__(self):
        self.calls = []

    def run(self, cli_ctx, method, params, needs_context=False, **kwargs):
        self.calls.append((method, params))
        return None


def _record(monkeypatch, module):
    recorder = _Recorder()
    monkeypatch.setattr(importlib.import_module("partcad_cli.click." + module), "run", recorder.run)
    return recorder


def _invoke(*args):
    return CliRunner().invoke(cli, ["--no-ansi", *args])


# Every command that names one object, with the module that sends its request.
# 'pc cae' sends from 'analysis', which its four analyses share.
COMMANDS = [
    ("commands.render", "render.objects", ["render"]),
    ("commands.export", "render.objects", ["export"]),
    ("commands.test", "test.run", ["test"]),
    ("commands.sim", "simulate.run", ["sim"]),
    ("commands.cam", "cam.route", ["cam"]),
    ("commands.instructions", "assembly.guide", ["instructions"]),
    ("commands.info", "info.object", ["info"]),
    ("commands.bom", "bom", ["bom"]),
    ("commands.ide.view", "inspect.object", ["ide", "view"]),
    ("analysis", "cae.analyze", ["cae", "fea"]),
    ("analysis", "cae.analyze", ["cae", "cfd"]),
    ("analysis", "cae.analyze", ["cae", "thermal"]),
    ("analysis", "cae.analyze", ["cae", "dynamic"]),
]


@pytest.mark.parametrize("module, method, command", COMMANDS)
def test_every_value_reaches_the_daemon_as_written(monkeypatch, module, method, command):
    recorder = _record(monkeypatch, module)

    result = _invoke(*command, "bolt", "-p", "length=10", "--param", "include=BEND_UP,BEND_DOWN")

    # Not 'exit_code == 0': what a command does with the answer is its own
    # business ('pc sim' fails a run that simulated nothing, which this fake
    # answer is). A usage error, though, would be the option not parsing.
    assert result.exit_code != 2, result.output
    ((called, params),) = recorder.calls
    assert called == method
    assert params["object"] == "bolt"
    assert params["params"] == ["length=10", "include=BEND_UP,BEND_DOWN"]


@pytest.mark.parametrize("module, method, command", COMMANDS)
def test_a_value_without_a_name_is_refused_before_anything_is_sent(monkeypatch, module, method, command):
    recorder = _record(monkeypatch, module)

    result = _invoke(*command, "bolt", "-p", "length")

    assert result.exit_code == 2
    # A fragment: the rest of the message is styled, and boxed to the width of
    # the terminal.
    assert "'length' is not" in result.output
    assert recorder.calls == []


@pytest.mark.parametrize("module, method, command", COMMANDS)
def test_no_value_is_an_empty_list(monkeypatch, module, method, command):
    recorder = _record(monkeypatch, module)

    result = _invoke(*command, "bolt")

    assert result.exit_code != 2, result.output
    ((_, params),) = recorder.calls
    assert params["params"] == []


@pytest.mark.parametrize("module, method, command", COMMANDS)
def test_dash_p_is_the_parameter_on_every_one_of_them(module, method, command):
    """Click lets the last of two options claiming one short flag win, silently.

    So a command that came to own '-p' for something else as well would read
    'pc render bolt -p length=10' as that something else, and render the bolt
    with its default length. This is the check that it has not.
    """
    found = cli
    for name in command:
        # The groups load their commands on demand, so they are asked rather
        # than read off '.commands'.
        found = found.get_command(click.Context(found), name)
    claims = [option.name for option in found.params if "-p" in getattr(option, "opts", [])]
    assert claims == ["params"]
