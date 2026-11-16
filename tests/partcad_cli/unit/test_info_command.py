#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'pc info' on a colour, a material or a finish: what reaches the daemon.

The daemon decides what a name is (see
'tests/partcad_service_json_rpc/test_info_cmf.py'); what is pinned here is the
three flags that say it is a declaration, each sent as the boolean the object
kind flags are sent as, and nothing said when none is given -- which is what
leaves the name to be looked up.
"""

import importlib

import pytest
from click.testing import CliRunner

from partcad_cli.click.command import cli


class _Recorder:
    def __init__(self):
        self.calls = []

    def run(self, cli_ctx, method, params, needs_context=False, **kwargs):
        self.calls.append((method, params, needs_context))
        return None


@pytest.fixture
def recorder(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(importlib.import_module("partcad_cli.click.commands.info"), "run", recorder.run)
    return recorder


def _invoke(*args):
    return CliRunner().invoke(cli, ["--no-ansi", "info", *args])


def test_a_material_is_named_like_any_object_and_its_kind_is_left_to_the_daemon(recorder):
    result = _invoke("//pub/std/manufacturing/material/metal:steel-1018")

    assert result.exit_code == 0, result.output
    ((method, params, needs_context),) = recorder.calls
    assert method == "info.object"
    assert needs_context
    assert params["object"] == "//pub/std/manufacturing/material/metal:steel-1018"
    assert not any(params[kind] for kind in ("material", "color", "finish"))


@pytest.mark.parametrize(
    "flags, kind",
    [
        (["-m"], "material"),
        (["--material"], "material"),
        (["--color"], "color"),
        (["--finish"], "finish"),
    ],
)
def test_a_flag_says_the_name_is_a_declaration_of_that_kind(recorder, flags, kind):
    result = _invoke(*flags, ":Zinc-Plated")

    assert result.exit_code == 0, result.output
    ((_, params, _),) = recorder.calls
    assert params["object"] == ":Zinc-Plated"
    assert params[kind] is True
    assert [other for other in ("material", "color", "finish") if params[other]] == [kind]


def test_parameter_values_reach_the_daemon_for_a_material_too(recorder):
    result = _invoke("-m", "resin", "-p", "density=1250")

    assert result.exit_code == 0, result.output
    ((_, params, _),) = recorder.calls
    assert params["material"] is True
    assert params["params"] == ["density=1250"]


def test_the_help_says_a_material_can_be_named(recorder):
    result = _invoke("--help")

    assert result.exit_code == 0, result.output
    assert "--material" in result.output
    assert "--color" in result.output
    assert "--finish" in result.output
    assert recorder.calls == []
