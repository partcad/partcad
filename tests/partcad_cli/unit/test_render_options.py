#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What `pc render` and `pc adhoc render` send for the options they share.

Pinned here is the request: one parameter name and one meaning for each option,
whichever of the two commands it is given to, and the requests an ad-hoc render
refuses before anything is sent. What the daemon does with them is tested
beside the operations, and what they draw by the `render` and `adhoc render`
features.
"""

import importlib
import os

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
    monkeypatch.setattr(importlib.import_module("partcad_cli.click.commands." + module), "run", recorder.run)
    return recorder


def _invoke(*args):
    return CliRunner().invoke(cli, ["--no-ansi", *args])


@pytest.fixture
def script(tmp_path):
    path = tmp_path / "bracket.py"
    path.write_text("depth = 10\n", encoding="utf-8")
    return path


@pytest.mark.parametrize("given, sent", [(["--reproducible"], True), (["--no-reproducible"], False)])
def test_pc_render_sends_which_projection_was_asked_for(monkeypatch, given, sent):
    recorder = _record(monkeypatch, "render")

    result = _invoke("render", *given, "bracket")

    assert result.exit_code == 0, result.output
    assert recorder.calls[0][1]["reproducible"] is sent


def test_pc_render_sends_nothing_when_it_was_not_asked_so_the_file_type_decides(monkeypatch):
    recorder = _record(monkeypatch, "render")

    assert _invoke("render", "bracket").exit_code == 0
    assert "reproducible" not in recorder.calls[0][1]


@pytest.mark.parametrize("kind", ["part", "sketch"])
def test_pc_adhoc_render_sends_what_pc_render_would(monkeypatch, tmp_path, script, kind):
    recorder = _record(monkeypatch, "adhoc.render." + kind)
    out = tmp_path / "out"
    out.mkdir()

    result = _invoke(
        "adhoc",
        "render",
        kind,
        "--input",
        "build123d",
        "-t",
        "svg",
        "-O",
        str(out),
        "-p",
        "depth=12",
        "-p",
        "label=M4",
        "-e",
        "//pub/feature/render/draftwright",
        "--reproducible",
        "--view",
        "top",
        str(script),
    )

    assert result.exit_code == 0, result.output
    method, params = recorder.calls[0]
    assert method == "adhoc.render"
    assert params["kind"] == kind
    assert params["output_type"] == "svg"
    assert params["output_dir"] == str(out)
    assert params["output_filename"] is None
    assert params["params"] == ["depth=12", "label=M4"]
    assert params["options_package"] == "//pub/feature/render/draftwright"
    assert params["reproducible"] is True
    assert params["view"] == "top"


@pytest.mark.parametrize("kind", ["part", "sketch"])
def test_pc_adhoc_render_sends_the_picture_options_pc_render_sends(monkeypatch, script, kind):
    """A picture of a bare file is asked for in the same words as one of an object, and sent under the same names."""
    words = ["--style", "shaded", "--size", "square", "--background", "#102030", "--quality", "80", "--turn", "30"]
    adhoc = _record(monkeypatch, "adhoc.render." + kind)
    render = _record(monkeypatch, "render")

    result = _invoke("adhoc", "render", kind, *words, str(script), "bracket.png")
    assert result.exit_code == 0, result.output
    assert _invoke("render", *words, "bracket").exit_code == 0

    sent, expected = adhoc.calls[0][1], render.calls[0][1]
    for key in ("style", "size", "background", "quality", "turn"):
        assert sent[key] == expected[key], key
    assert sent["style"] == "shaded" and sent["turn"] == [0, 0, 30.0]


@pytest.mark.parametrize("option", ["--fps", "--duration", "--speed", "--preset"])
def test_pc_adhoc_render_takes_no_video_option(monkeypatch, script, option):
    """No video is rendered ad hoc, so a video's options are not offered there."""
    recorder = _record(monkeypatch, "adhoc.render.part")

    result = _invoke("adhoc", "render", "part", option, "1", str(script), "bracket.png")

    assert result.exit_code == 2
    assert recorder.calls == []


@pytest.mark.parametrize("spelling", ["--output", "-t", "--format"])
def test_the_file_type_has_pc_renders_spellings_too(monkeypatch, script, spelling):
    recorder = _record(monkeypatch, "adhoc.render.part")

    assert _invoke("adhoc", "render", "part", spelling, "png", str(script)).exit_code == 0
    assert recorder.calls[0][1]["output_type"] == "png"


def test_a_package_directory_is_sent_absolute(monkeypatch, tmp_path, script):
    """The daemon runs elsewhere, so a directory is resolved where the user is."""
    recorder = _record(monkeypatch, "adhoc.render.part")
    monkeypatch.chdir(tmp_path)

    assert _invoke("adhoc", "render", "part", "-e", "opts", "-t", "svg-thin", str(script)).exit_code == 0
    assert recorder.calls[0][1]["options_package"] == os.path.join(str(tmp_path), "opts")
    assert recorder.calls[0][1]["output_type"] == "svg-thin"


def test_a_file_type_no_projection_is_needs_a_package_to_come_from(monkeypatch, script):
    recorder = _record(monkeypatch, "adhoc.render.part")

    result = _invoke("adhoc", "render", "part", "-t", "tiff", str(script))

    assert result.exit_code == 2
    assert "-e" in result.output
    assert recorder.calls == []


def test_an_output_file_and_an_output_directory_are_one_too_many(monkeypatch, tmp_path, script):
    recorder = _record(monkeypatch, "adhoc.render.part")

    result = _invoke("adhoc", "render", "part", "-O", str(tmp_path), str(script), str(tmp_path / "out.svg"))

    assert result.exit_code == 2
    assert recorder.calls == []


def test_a_value_with_no_name_is_refused_before_anything_is_sent(monkeypatch, script):
    recorder = _record(monkeypatch, "adhoc.render.part")

    result = _invoke("adhoc", "render", "part", "-p", "12", str(script), "out.svg")

    assert result.exit_code == 2
    assert recorder.calls == []


def test_nothing_new_is_sent_when_nothing_new_was_asked(monkeypatch, script):
    """A plain ad-hoc render asks for exactly what it asked for before these options existed."""
    recorder = _record(monkeypatch, "adhoc.render.part")

    assert _invoke("adhoc", "render", "part", str(script), "out.svg").exit_code == 0
    params = recorder.calls[0][1]
    assert params["output_dir"] is None and params["options_package"] is None and params["params"] == []
    assert "reproducible" not in params
