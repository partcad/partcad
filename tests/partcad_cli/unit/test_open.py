#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for `pc open`.

The command is a thin wrapper over `partcad_client.external`, and what is pinned
here is the wrapping: the options it hands over, and the two ways it reports
back. The JSON shape matters most -- the VS Code extension's "Open in..." menu
reads it, and on a failure the message it carries is the whole answer (which X
server to install, or how to let PartCAD use a container), so it has to survive
a non-zero exit rather than be replaced by one.

The one thing this command sends to the daemon is pinned here too, from both
sides: an application that reads meshes has to be handed one, and making a mesh
out of a solid is CAD work -- but *only* that. A `pc open` that needed no
conversion and connected anyway would start a daemon to open a file that was
already on disk, on a machine that may have neither a CAD environment nor any
use for one, and would fail where it used to work. Which method is sent, on
what, and that nothing is sent otherwise, is the whole contract; that a daemon
call is allowed here at all is `test_command_boundary.py`'s to say.

Which side of the command boundary this command is on is checked by
`test_command_boundary.py`; nothing here starts an application or a container.
"""

import json
from collections.abc import Iterator

import pytest
from click.testing import CliRunner
from partcad_cli.click.command import cli
from partcad_cli.click.commands import open as open_command
from partcad_client import external


@pytest.fixture
def opened(monkeypatch):
    """Record the call `pc open` makes, and answer it however a test wants."""

    class Recorder:
        def __init__(self):
            self.calls = []
            self.error = None
            self.result = external.OpenResult(
                tool="freecad",
                method="native",
                path="/w/cube.step",
                command=["/usr/bin/freecad", "/w/cube.step"],
                detail="FreeCAD is installed on this machine.",
            )

        def open_file(
            self, path, tool="freecad", use_docker=False, image=None, log=None, object_type=None, transcode=None
        ):
            self.calls.append(
                {
                    "path": path,
                    "tool": tool,
                    "use_docker": use_docker,
                    "image": image,
                    "log": log,
                    "object_type": object_type,
                    "transcode": transcode,
                }
            )
            if self.error:
                raise self.error
            return self.result

    recorder = Recorder()
    monkeypatch.setattr(external, "open_file", recorder.open_file)
    return recorder


def _invoke(click_runner, *args):
    return click_runner.invoke(cli, ["--no-ansi", "open", *args])


def test_the_options_reach_the_opener(click_runner: Iterator[CliRunner], opened) -> None:
    result = _invoke(
        click_runner, "--with", "freecad", "--use-docker", "--docker-image", "freecad/freecad:weekly", "x.step"
    )
    assert result.exit_code == 0, result.output
    assert opened.calls == [
        {
            "path": "x.step",
            "tool": "freecad",
            "use_docker": True,
            "image": "freecad/freecad:weekly",
            "log": opened.calls[0]["log"],
            "object_type": None,
            "transcode": opened.calls[0]["transcode"],
        }
    ]


def test_freecad_is_the_default_application(click_runner: Iterator[CliRunner], opened) -> None:
    _invoke(click_runner, "x.step")
    assert opened.calls[0]["tool"] == "freecad"
    assert opened.calls[0]["use_docker"] is False


def test_what_happened_is_reported(click_runner: Iterator[CliRunner], opened) -> None:
    result = _invoke(click_runner, "x.step")
    assert "FreeCAD is installed on this machine." in result.output


def test_json_reports_what_happened_in_full(click_runner: Iterator[CliRunner], opened) -> None:
    result = _invoke(click_runner, "--json", "x.step")
    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "ok": True,
        "tool": "freecad",
        "method": "native",
        "path": "/w/cube.step",
        "source": None,
        "command": ["/usr/bin/freecad", "/w/cube.step"],
        "detail": "FreeCAD is installed on this machine.",
    }


def test_json_stays_silent_about_progress(click_runner: Iterator[CliRunner], opened) -> None:
    # The caller parses stdout; progress lines would be in the way of the one
    # thing it is there to read.
    _invoke(click_runner, "--json", "x.step")
    assert opened.calls[0]["log"] is None


def test_a_failure_is_an_error_with_the_reason(click_runner: Iterator[CliRunner], opened) -> None:
    opened.error = external.ExternalToolError("FreeCAD was not found on this machine.")
    result = _invoke(click_runner, "x.step")
    assert result.exit_code != 0
    assert "FreeCAD was not found" in result.output


def test_a_failure_keeps_its_message_under_json(click_runner: Iterator[CliRunner], opened) -> None:
    opened.error = external.ExternalToolError("Install XQuartz (https://www.xquartz.org/)")
    result = _invoke(click_runner, "--json", "x.step")
    assert result.exit_code == 1
    reported = json.loads(result.output)
    assert reported["ok"] is False
    assert "XQuartz" in reported["error"]


def test_the_declared_type_is_handed_over(click_runner: Iterator[CliRunner], opened) -> None:
    """A '.py' is three different script types, and the tree knows which."""
    _invoke(click_runner, "--with", "blender", "--type", "cadquery", "cube.py")
    assert opened.calls[0]["object_type"] == "cadquery"
    assert opened.calls[0]["tool"] == "blender"


def test_a_conversion_is_the_daemon_s_adhoc_convert(click_runner: Iterator[CliRunner], opened, monkeypatch) -> None:
    """Making a mesh out of a solid is CAD work, so it crosses the wire.

    The opening does not: what `pc open` sends is the same file-in, file-out
    conversion `pc adhoc convert` sends, and nothing else.
    """
    sent = []
    monkeypatch.setattr(open_command, "run", lambda cli_ctx, method, params, **kw: sent.append((method, params, kw)))

    _invoke(click_runner, "--with", "blender", "/w/cube.step")
    opened.calls[0]["transcode"]("/w/cube.step", "step", "/state/cube-0123.stl", "stl")

    assert sent == [
        (
            "adhoc.convert",
            {
                "kind": "part",
                "input_type": "step",
                "output_type": "stl",
                "input_filename": "/w/cube.step",
                "output_filename": "/state/cube-0123.stl",
            },
            {"needs_context": False},
        )
    ]


def test_a_failed_conversion_is_reported_like_any_other_reason(
    click_runner: Iterator[CliRunner], opened, monkeypatch
) -> None:
    """A daemon error arrives as a ClickException, and it is a reason like the rest.

    Left to itself it would exit non-zero with the message on stderr, which is
    exactly what the JSON is there to prevent: the extension shows `error` and
    has nothing else.
    """
    import rich_click as click

    def explode(path, **kwargs):
        kwargs["transcode"]("/w/cube.step", "step", "/state/cube.stl", "stl")

    monkeypatch.setattr(
        open_command,
        "run",
        lambda *args, **kw: (_ for _ in ()).throw(click.ClickException("The daemon could not read cube.step")),
    )
    monkeypatch.setattr(external, "open_file", explode)

    result = _invoke(click_runner, "--json", "--with", "blender", "/w/cube.step")

    assert result.exit_code == 1
    reported = json.loads(result.output)
    assert reported["ok"] is False
    assert "could not read cube.step" in reported["error"]


def test_what_was_converted_is_said_as_well_as_what_was_opened(click_runner: Iterator[CliRunner], opened) -> None:
    """A user who asked for a STEP file has to be told a mesh is what Blender got."""
    opened.result = external.OpenResult(
        tool="blender",
        method="native",
        path="/state/cube-0123.stl",
        source="/w/cube.step",
        command=["/usr/bin/blender"],
        detail="Blender is installed on this machine.",
    )
    result = _invoke(click_runner, "--with", "blender", "/w/cube.step")
    assert "cube-0123.stl" in result.output
    assert "cube.step" in result.output


# ---------------------------------------------------------------------------
# Nothing to convert, nothing to connect to
# ---------------------------------------------------------------------------


@pytest.fixture
def no_daemon(monkeypatch):
    """Fail loudly if the command connects to the daemon at all.

    Both doors are shut, not just the one this command holds the key to:
    `service.run` is what `pc open` calls, and `client.connect` is what would
    answer if anything else in the invocation reached for a daemon.
    """
    import partcad_client.client

    def refuse(*_args, **_kwargs):
        raise AssertionError("pc open reached for the daemon when nothing needed converting")

    monkeypatch.setattr(open_command, "run", refuse)
    monkeypatch.setattr(partcad_client.client, "connect", refuse)


@pytest.fixture
def installed_blender(monkeypatch):
    """A machine with Blender on it, and nothing actually started."""
    started = []
    monkeypatch.setattr(external, "native_command", lambda _spec: ["/usr/bin/blender"])
    monkeypatch.setattr(external, "_spawn", lambda args: started.append(list(args)))
    return started


@pytest.fixture
def mesh(tmp_path):
    (tmp_path / "partcad.yaml").write_text("name: test\n")
    path = tmp_path / "cube.stl"
    path.write_text("solid cube\nendsolid cube\n")
    return path


@pytest.fixture(autouse=True)
def workspace_state(monkeypatch, tmp_path):
    """Put this workspace's own directory under the test's, not under `$HOME`.

    A converted mesh is written there (`external.transcode_path`), and a unit
    test has no business leaving one in the directory a real daemon serves.
    """
    monkeypatch.setattr(external, "socket_path", lambda _root: str(tmp_path / ".partcad" / "hash" / "socket"))


def test_a_mesh_is_opened_without_a_daemon(click_runner, no_daemon, installed_blender, mesh) -> None:
    """The whole point of `pc open` staying a client command, kept true.

    This one goes through the real `partcad_client.external`, not the recorder
    above: what is being checked is that no conversion is *decided on*, which
    the recorder would hide by never asking.
    """
    result = _invoke(click_runner, "--json", "--with", "blender", str(mesh))

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["path"] == str(mesh)
    assert installed_blender[0][0] == "/usr/bin/blender"


def test_the_declared_type_does_not_make_it_a_daemon_command(click_runner, no_daemon, installed_blender, mesh) -> None:
    """The extension passes `--type` for every object it opens, mesh or not."""
    result = _invoke(click_runner, "--json", "--with", "blender", "--type", "stl", str(mesh))
    assert result.exit_code == 0, result.output


def test_an_application_that_takes_what_it_is_given_never_connects(click_runner, no_daemon, monkeypatch, mesh) -> None:
    """FreeCAD, Gazebo and KiCad read what they are handed; there is nothing to ask."""
    started = []
    monkeypatch.setattr(external, "native_command", lambda _spec: ["/usr/bin/freecad"])
    monkeypatch.setattr(external, "_spawn", lambda args: started.append(list(args)))

    result = _invoke(click_runner, "--json", "--with", "freecad", str(mesh))

    assert result.exit_code == 0, result.output
    assert started == [["/usr/bin/freecad", str(mesh)]]


def test_a_failure_with_nothing_to_convert_does_not_connect_either(click_runner, no_daemon, monkeypatch, mesh) -> None:
    """A machine with no Blender is told so; it is not told to start a daemon first."""
    monkeypatch.setattr(external, "native_command", lambda _spec: None)

    result = _invoke(click_runner, "--json", "--with", "blender", str(mesh))

    assert result.exit_code == 1
    assert "--use-docker" in json.loads(result.output)["error"]


def test_a_solid_is_the_one_case_that_connects(click_runner, installed_blender, monkeypatch, tmp_path) -> None:
    """The other half of the contract: the conversion really does go to the daemon.

    Driven through the real `external`, so what is pinned is that the decision
    to convert is what reaches `service.run` -- not a callback a test invoked.
    """
    (tmp_path / "partcad.yaml").write_text("name: test\n")
    solid = tmp_path / "cube.step"
    solid.write_text("ISO-10303-21;\n")
    sent = []

    def convert(_cli_ctx, method, params, **kwargs):
        sent.append((method, params, kwargs))
        # The daemon's job, done here so that `external` finds the file it
        # asked for and the command carries on to the opening.
        open(params["output_filename"], "w").write("solid converted\nendsolid converted\n")

    monkeypatch.setattr(open_command, "run", convert)

    result = _invoke(click_runner, "--json", "--with", "blender", str(solid))

    assert result.exit_code == 0, result.output
    assert [method for method, _params, _kwargs in sent] == ["adhoc.convert"]
    assert sent[0][1]["input_type"] == "step"
    assert sent[0][1]["output_type"] == "stl"
    assert sent[0][2] == {"needs_context": False}
    reported = json.loads(result.output)
    assert reported["source"] == str(solid)
    assert reported["path"] == sent[0][1]["output_filename"]
