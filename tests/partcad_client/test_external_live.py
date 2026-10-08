#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc ide open` in a real container, in both transfer modes.

`test_external.py` pins the deciding against a fake endpoint; this pins that an
edit made inside a real container really comes back -- shared through a mount,
or sent there and back with `useDockerRemote` -- and really reaches the object's
source when it had to be converted to be opened.

The "application" is `sh` editing the file it is handed, in a small public image
with a python3 for the service: what is under test is the round trip, not a
window. The display is stubbed for the same reason; forwarding one is pinned in
`test_external.py`. Skipped where no daemon answers.
"""

import os
import shutil
import sys
import uuid

import pytest

docker = pytest.importorskip("docker")

from partcad_client import external  # noqa: E402
from partcad_utils import containers  # noqa: E402

IMAGE = os.environ.get("PC_TEST_CONTAINER_IMAGE", "python:3.12-slim")
SESSION = uuid.uuid4().hex[:8]

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Linux containers on a Windows runner")

# Appends to the file it is handed, as an application saving an edit would.
EDIT = 'printf " edited" >> "$1"'
# Saves beside what it opened, as KiCad does with a project.
EDIT_BESIDE = 'printf " edited" >> "$1"; printf saved > "$(dirname "$1")/saved.txt"'


@pytest.fixture(scope="module")
def client():
    try:
        client = docker.from_env()
        client.ping()
        if str(client.info().get("OSType", "")).lower() not in ("", "linux"):
            pytest.skip("this daemon does not run Linux containers")
    except Exception as e:
        pytest.skip("no Docker daemon answers here: %s" % e)
    try:
        containers.resolve_image(client, IMAGE)
    except Exception as e:
        pytest.skip("cannot get %s: %s" % (IMAGE, e))
    yield client
    for container in client.containers.list(all=True, filters={"label": containers.LABEL_CONTAINER}):
        if container.labels.get(containers.LABEL_ROLE, "").startswith("open-live-" + SESSION):
            container.remove(force=True)
    for volume in client.volumes.list():
        if volume.name.startswith("partcad-open-live-" + SESSION):
            volume.remove(force=True)


@pytest.fixture
def in_container(monkeypatch, client):
    """`pc ide open` with no local application and a display that is never looked at."""
    monkeypatch.setattr(external, "native_command", lambda _spec: None)
    monkeypatch.setattr(external, "_x11_forwarding", lambda _spec: ({"DISPLAY": ":99"}, {}, {}, ""))


def _tool(name, script, formats, companions=()):
    """An application that is `sh` running ``script`` on the file."""
    tool = external.tool_from_declaration(
        "live-%s-%s" % (SESSION, name),
        {
            "displayName": "Live " + name,
            "container": {"image": IMAGE},
            "binaries": ["sh"],
            "args": ["-c", script, "app"],
            "formats": list(formats),
            "companions": list(companions),
        },
    )
    external.TOOLS[tool.name] = tool
    return tool


@pytest.fixture
def tools():
    before = dict(external.TOOLS)
    yield
    external.TOOLS.clear()
    external.TOOLS.update(before)


def _copy(source, _source_type, target, _target_type, _kind):
    """A conversion that changes nothing but the name: enough to see which file went where."""
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.copyfile(source, target)


MODES = [containers.MOUNT, containers.UPLOAD]


@pytest.mark.parametrize("mode", MODES)
def test_an_edit_to_a_file_opened_as_it_is_lands_in_it(mode, tmp_path, in_container, tools):
    tool = _tool("asis-" + mode, EDIT, ["stl"])
    part = tmp_path / "cube.stl"
    part.write_text("solid cube")

    result = external.open_file(str(part), tool.name, use_docker=True, mode=mode)

    assert result.method == "docker"
    assert part.read_text() == "solid cube edited"
    assert result.changed
    assert result.written_back == str(part)


@pytest.mark.parametrize("mode", MODES)
def test_a_converted_edit_is_converted_back_over_the_source(mode, tmp_path, in_container, tools):
    """The application reads OBJ only, so the STL goes over as OBJ and comes back as STL."""
    tool = _tool("convert-" + mode, EDIT, ["obj"])
    part = tmp_path / "cube.stl"
    part.write_text("solid cube")
    calls = []

    def transcode(source, source_type, target, target_type, kind):
        calls.append((source_type, target_type))
        _copy(source, source_type, target, target_type, kind)

    result = external.open_file(str(part), tool.name, use_docker=True, mode=mode, transcode=transcode)

    assert calls == [("stl", "obj"), ("obj", "stl")]
    assert result.path.endswith(".obj")
    assert part.read_text() == "solid cube edited"
    assert result.written_back == str(part)


@pytest.mark.parametrize("mode", MODES)
def test_nothing_done_is_nothing_brought_back(mode, tmp_path, in_container, tools):
    tool = _tool("noop-" + mode, "true", ["obj"])
    part = tmp_path / "cube.stl"
    part.write_text("solid cube")
    calls = []

    def transcode(*args):
        calls.append(args[1::2][:2])
        _copy(*args)

    result = external.open_file(str(part), tool.name, use_docker=True, mode=mode, transcode=transcode)

    assert not result.changed
    assert result.written_back is None
    assert len(calls) == 1  # there, and not back
    assert part.read_text() == "solid cube"


@pytest.mark.parametrize("mode", MODES)
def test_a_script_is_not_overwritten_by_its_edited_output(mode, tmp_path, in_container, tools):
    tool = _tool("script-" + mode, EDIT, ["step"])
    script = tmp_path / "cube.py"
    script.write_text("import cadquery as cq\n")

    result = external.open_file(
        str(script), tool.name, use_docker=True, mode=mode, object_type="cadquery", transcode=_copy
    )

    assert script.read_text() == "import cadquery as cq\n"
    assert result.written_back is None
    assert result.edited and open(result.edited).read().endswith(" edited")


@pytest.mark.parametrize("mode", MODES)
def test_an_application_saving_beside_its_project_brings_the_directory_back(mode, tmp_path, in_container, tools):
    """KiCad's shape: handed the project beside the part, saving into its directory."""
    tool = _tool("beside-" + mode, EDIT_BESIDE, ["proj"], companions=[".proj"])
    (tmp_path / "board.step").write_text("step")
    project = tmp_path / "board.proj"
    project.write_text("project")

    result = external.open_file(str(tmp_path / "board.step"), tool.name, use_docker=True, mode=mode)

    assert project.read_text() == "project edited"
    assert (tmp_path / "saved.txt").read_text() == "saved"
    assert result.changed


def test_upload_mode_mounts_nothing_of_this_machine(tmp_path, in_container, tools, client):
    tool = _tool("nomount", EDIT, ["stl"])
    part = tmp_path / "cube.stl"
    part.write_text("solid cube")

    external.open_file(str(part), tool.name, use_docker=True, mode=containers.UPLOAD)

    (container,) = client.containers.list(all=True, filters={"label": "%s=%s" % (containers.LABEL_ROLE, tool.role)})
    binds = [m for m in container.attrs["Mounts"] if m["Type"] == "bind"]
    assert binds == []
    # The application's settings still have a home that outlives the container.
    assert any(m["Type"] == "volume" and m["Destination"] == external.CONTAINER_HOME for m in container.attrs["Mounts"])


def test_the_container_is_reused_and_prunable(tmp_path, in_container, tools, client):
    tool = _tool("reuse", EDIT, ["stl"])
    part = tmp_path / "cube.stl"
    part.write_text("solid cube")

    external.open_file(str(part), tool.name, use_docker=True, mode=containers.UPLOAD)
    external.open_file(str(part), tool.name, use_docker=True, mode=containers.UPLOAD)

    found = client.containers.list(all=True, filters={"label": "%s=%s" % (containers.LABEL_ROLE, tool.role)})
    assert len(found) == 1
    assert found[0].name.startswith("partcad-" + tool.role + "-")
    assert part.read_text() == "solid cube edited edited"
