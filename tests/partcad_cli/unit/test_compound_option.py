#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'--compound' on the commands that take an assembly in and can hand a part out.

What is pinned here is what reaches the daemon: one parameter, 'compound', sent
only when it is asked for, on 'pc export', 'pc import assembly' and 'pc adhoc
convert part'. What the daemon does with it is tested beside
'partcad.assembly_compound' and the operations.
"""

import importlib

import pytest
from click.testing import CliRunner

from partcad_cli.click.command import cli


class _Recorder:
    def __init__(self):
        self.calls = []

    def run(self, cli_ctx, method, params, needs_context=False, span_name=None):
        self.calls.append((method, params))
        return {"name": "robot"}


def _record(monkeypatch, module):
    recorder = _Recorder()
    monkeypatch.setattr(importlib.import_module("partcad_cli.click.commands." + module), "run", recorder.run)
    return recorder


def _invoke(*args):
    return CliRunner().invoke(cli, ["--no-ansi", *args])


def _commands(tmp_path):
    source = tmp_path / "robot.step"
    source.write_bytes(b"")
    return [
        ("export", "render.objects", ["export", "-t", "step", "-a", "robot"]),
        ("import.assembly", "import.object", ["import", "assembly", str(source)]),
        ("adhoc.convert.part", "adhoc.convert", ["adhoc", "convert", "part", str(source), str(tmp_path / "out.stl")]),
    ]


@pytest.mark.parametrize("index", range(3))
def test_compound_reaches_the_daemon(monkeypatch, tmp_path, index):
    module, method, args = _commands(tmp_path)[index]
    recorder = _record(monkeypatch, module)

    result = _invoke(*args, "--compound")

    assert result.exit_code == 0, result.output
    ((called, params),) = recorder.calls
    assert called == method
    assert params["compound"] is True


@pytest.mark.parametrize("index", range(3))
def test_no_compound_is_not_sent(monkeypatch, tmp_path, index):
    """Left out rather than sent as false: a request that does not ask is the request it always was."""
    module, _method, args = _commands(tmp_path)[index]
    recorder = _record(monkeypatch, module)

    result = _invoke(*args)

    assert result.exit_code == 0, result.output
    ((_called, params),) = recorder.calls
    assert "compound" not in params


def test_a_compound_import_says_which_part_it_made(monkeypatch, tmp_path):
    _record(monkeypatch, "import.assembly")
    source = tmp_path / "robot.urdf"
    source.write_text("<robot name='robot'/>")

    result = _invoke("import", "assembly", str(source), "--compound")

    assert result.exit_code == 0, result.output
    assert "imported successfully as the part 'robot'" in result.output
