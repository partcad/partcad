#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The native CAD formats PartCAD reads through cadmpeg, as the commands that are handed a file see them.

'pc import part' names a part's type from its file's extension, and 'pc adhoc
convert' and 'pc adhoc render' do when they are not told: those types are
declarations in '//builtin/import' rather than factories, so their extensions
come from the client's one table of them ('partcad_client.object_types'). What
is pinned here is what reaches the daemon.
"""

import importlib

import pytest
from click.testing import CliRunner

from partcad_cli.click.command import cli


class _Recorder:
    def __init__(self):
        self.calls = []

    def run(self, cli_ctx, method, params, **_kwargs):
        self.calls.append((method, params))
        return None


def _record(monkeypatch, module):
    recorder = _Recorder()
    monkeypatch.setattr(importlib.import_module("partcad_cli.click.commands." + module), "run", recorder.run)
    return recorder


@pytest.mark.parametrize(
    "file_name, part_type",
    [
        ("design.FCStd", "fcstd"),
        ("design.fcstd", "fcstd"),
        ("bracket.igs", "iges"),
        ("bracket.iges", "iges"),
        ("enclosure.f3d", "f3d"),
        ("housing.SLDPRT", "sldprt"),
        ("shaft.ipt", "ipt"),
        ("cover.CATPart", "catpart"),
        ("body.sab", "sat"),
        ("package.pvz", "pvz"),
        ("plate.step", "step"),
    ],
)
def test_import_part_names_the_type_from_the_extension(monkeypatch, tmp_path, file_name, part_type):
    recorder = _record(monkeypatch, "import.part")
    source = tmp_path / file_name
    source.write_bytes(b"")

    result = CliRunner().invoke(cli, ["--no-ansi", "import", "part", str(source)])

    assert result.exit_code == 0, result.output
    assert [(method, params["part_type"]) for method, params in recorder.calls] == [("import.object", part_type)]


@pytest.mark.parametrize("command", ["convert", "render"])
def test_adhoc_names_a_native_document_s_type_the_daemon_cannot_infer(monkeypatch, tmp_path, command):
    recorder = _record(monkeypatch, "adhoc.%s.part" % command)
    source = tmp_path / "housing.SLDPRT"
    source.write_bytes(b"")
    args = ["--no-ansi", "adhoc", command, "part", str(source), str(tmp_path / "out.step")]
    if command == "render":
        args[-1] = str(tmp_path / "out.png")

    result = CliRunner().invoke(cli, args)

    assert result.exit_code == 0, result.output
    assert [params["input_type"] for _method, params in recorder.calls] == ["sldprt"]


def test_adhoc_leaves_the_rest_to_the_daemon(monkeypatch, tmp_path):
    """A type the daemon infers itself is not second-guessed: it is sent as nothing, as before."""
    recorder = _record(monkeypatch, "adhoc.convert.part")
    source = tmp_path / "plate.stl"
    source.write_bytes(b"")

    CliRunner().invoke(cli, ["--no-ansi", "adhoc", "convert", "part", str(source), str(tmp_path / "out.step")])

    assert [params["input_type"] for _method, params in recorder.calls] == [None]


def test_a_native_document_is_an_input_and_not_an_output_of_a_conversion():
    convert = importlib.import_module("partcad_cli.click.commands.adhoc.convert.part")
    assert {"fcstd", "sldprt", "f3d"} <= set(convert.PART_TYPES)
    assert not {"fcstd", "sldprt", "f3d"} & set(convert.OUTPUT_PART_TYPES)
    # IGES PartCAD writes as well as reads.
    assert "iges" in convert.OUTPUT_PART_TYPES
