#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The paths a request names, reaching a sandbox that is sent files rather than sharing them.

A sandbox in upload mode -- the ``remote`` one, ``docker`` with
``useDockerRemote`` -- is sent the directories the command line names, unpacks
them where it likes and rewrites the arguments naming them. The request on
standard input it cannot rewrite, so a reader whose source file, search paths
and script travel there failed with "No such file or directory" naming a file
that exists, and so did a partType's part and a sketch's drawing.

Two layers, as in 'test_container_execute.py'. The two halves of the mechanism
in process -- 'partcad.request_paths' building the command and
'wrapper_common' adopting what the sandbox made of it -- and then real wrappers
run by the real service function the way a container runs them, with the
caller's files deleted before the run: whatever the wrapper reads, it is not
where PartCAD keeps it.
"""

import asyncio
import base64
import importlib.util
import io
import json
import os
import sys
import types

import pytest

import partcad as pc
from partcad import request_paths
from partcad import runtime as pc_runtime
from partcad import runtime_python_remote, shape_envelope
from partcad import wrapper as pc_wrapper
from partcad_utils import container_service

WRAPPERS = os.path.dirname(pc_wrapper.get("import.py"))

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
sys.path.append(os.path.join(os.path.dirname(pc.__file__), "builtin", "import"))
import import_urdf  # noqa: E402
import ocp_serialize  # noqa: E402
import wrapper_common  # noqa: E402
import wrapper_import  # noqa: E402

KEYS = ("source_file", "base_dir", "output_folder", "search_paths", wrapper_import.SCRIPT_KEY)


@pytest.fixture
def carried(monkeypatch):
    """'wrapper_common's record of what it adopted, this test's own: it is module state."""
    pairs = []
    monkeypatch.setattr(wrapper_common, "_carried", pairs)
    return pairs


class _Exchanging:
    """A runtime that is sent files rather than sharing them, as far as 'written' asks."""

    EXCHANGES_FILES = True


# --------------------------------------------------------------------------- #
# What PartCAD sends                                                           #
# --------------------------------------------------------------------------- #


def test_the_core_and_the_wrapper_spell_the_mechanism_alike():
    """Twins: a wrapper runs in a sandbox and cannot import 'partcad'."""
    assert request_paths.KEY == wrapper_common.PATHS_KEY
    assert request_paths.ARGUMENT == wrapper_common.PATHS_ARGUMENT
    from partcad import output

    assert output.SCRIPT_KEY == wrapper_import.SCRIPT_KEY


def test_the_paths_follow_the_command_and_the_request_says_where_from(tmp_path):
    request = {
        "path": str(tmp_path / "a.dxf"),
        "roots": [str(tmp_path / "one"), None, str(tmp_path / "two")],
        "tolerance": 0.1,
    }
    command = request_paths.carry(["wrapper.py", "first"], request, ("path", "roots", "tolerance", "absent"))

    assert command == [
        "wrapper.py",
        "first",
        request_paths.ARGUMENT,
        str(tmp_path / "a.dxf"),
        str(tmp_path / "one"),
        str(tmp_path / "two"),
    ]
    # A list keeps its positions, the one that is no path included.
    assert request[request_paths.KEY] == [["path", None], ["roots", 0], ["roots", 2]]
    assert request["roots"][1] is None
    assert request["tolerance"] == 0.1


def test_a_relative_path_is_carried_absolute_in_both_places(tmp_path, monkeypatch):
    """A sandbox rewrites an argument by the directory it is in, and a relative one is in none."""
    monkeypatch.chdir(tmp_path)
    request = {"path": os.path.join("sub", "..", "a.svg")}
    command = request_paths.carry(["wrapper.py"], request, ("path",))
    assert command[-1] == str(tmp_path / "a.svg")
    assert request["path"] == str(tmp_path / "a.svg")


def test_a_request_that_names_no_path_is_left_as_it_was():
    request = {"path": None, "empty": "", "kind": 3}
    command = ["wrapper.py", "x"]
    assert request_paths.carry(command, request, ("path", "empty", "kind")) == ["wrapper.py", "x"]
    assert request == {"path": None, "empty": "", "kind": 3}


def test_a_runtime_sharing_the_files_is_told_nothing_about_what_is_written(tmp_path):
    """Those override 'run_async' with a signature that takes no 'output_dirs' at all."""
    assert request_paths.written(object(), str(tmp_path)) == {}


def test_a_runtime_sent_the_files_is_told_where_they_are_written(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert request_paths.written(_Exchanging(), "out", None) == {"output_dirs": [str(tmp_path / "out")]}


# --------------------------------------------------------------------------- #
# What the wrapper makes of it                                                 #
# --------------------------------------------------------------------------- #


def test_the_paths_are_taken_off_the_end_of_the_command_line():
    argv = ["wrapper.py", "first", "second", wrapper_common.PATHS_ARGUMENT, "/here/a", "/here/b"]
    assert wrapper_common.take_paths_argument(argv) == ["/here/a", "/here/b"]
    # What a wrapper reads by position is where it always was.
    assert argv == ["wrapper.py", "first", "second"]

    argv = ["wrapper.py", "first"]
    assert wrapper_common.take_paths_argument(argv) is None
    assert argv == ["wrapper.py", "first"]


def test_the_request_is_pointed_at_where_the_paths_are_here(carried):
    request = {
        "path": "/there/pkg/a.dxf",
        "roots": ["/there/pkg", "/there/lib"],
        wrapper_common.PATHS_KEY: [["path", None], ["roots", 0], ["roots", 1]],
    }
    here = ["/here/1/a.dxf", "/here/1", "/there/lib"]

    request = wrapper_common.adopt_paths(request, here)

    assert request == {"path": "/here/1/a.dxf", "roots": ["/here/1", "/there/lib"]}
    # Only what moved is remembered: '/there/lib' was not sent, and is where it was.
    assert carried == [("/here/1/a.dxf", "/there/pkg/a.dxf"), ("/here/1", "/there/pkg")]
    assert wrapper_common.files_were_sent()


def test_a_request_and_a_command_line_that_disagree_leave_the_request_as_it_came(carried, capsys):
    request = {"path": "/there/a.dxf", wrapper_common.PATHS_KEY: [["path", None]]}
    assert wrapper_common.adopt_paths(request, ["/here/a.dxf", "/here/b.dxf"]) == {"path": "/there/a.dxf"}
    assert "the request's are used as they are" in capsys.readouterr().err
    assert carried == []
    assert not wrapper_common.files_were_sent()


def test_a_place_the_request_no_longer_holds_is_passed_over(carried):
    request = {
        "path": 3,
        "roots": ["/there/a"],
        wrapper_common.PATHS_KEY: [["path", None], ["roots", 5], "nonsense", ["roots", 0]],
    }
    request = wrapper_common.adopt_paths(request, ["/here/x", "/here/y", "/here/z", "/here/a"])
    assert request == {"path": 3, "roots": ["/here/a"]}
    assert carried == [("/here/a", "/there/a"), ("/here", "/there")]


def test_a_file_that_kept_its_name_brings_its_directory(carried):
    """What is beside a file is beside it over there: the sandbox unpacked its directory whole."""
    request = {
        "stage": "D:\\work\\pkg\\stage.usd",
        "renamed": "/there/other/model.step",
        wrapper_common.PATHS_KEY: [["stage", None], ["renamed", None]],
    }
    here = os.path.join(os.sep, "here", "1")
    # The second was sent on its own, under a name of the sandbox's choosing:
    # where it is says nothing about where its siblings are.
    wrapper_common.adopt_paths(request, [os.path.join(here, "stage.usd"), "/exchange/3.step"])

    assert (here, "D:\\work\\pkg") in carried
    assert ("/exchange", "/there/other") not in carried
    assert wrapper_common.to_host(os.path.join(here, "layers", "a.usd")) == "D:\\work\\pkg\\layers\\a.usd"


def test_a_request_with_no_paths_is_not_touched(carried):
    request = {"kind": "assembly"}
    assert wrapper_common.adopt_paths(request, None) is request
    assert request == {"kind": "assembly"}


def test_an_answer_names_the_files_where_partcad_keeps_them(carried):
    here = os.path.join(os.sep, "here", "1")
    out = os.path.join(os.sep, "here", "2")
    carried.extend([(here, "/there/pkg"), (out, "/state/out")])
    answer = {
        "root": {
            "links": [
                {"part_file": os.path.join(here, "meshes", "arm.stl")},
                {"part_file": os.path.join(out, "box.step")},
                {"part_file": here},
                # A sibling whose name merely starts with a carried one is not in it.
                {"part_file": here + "0" + os.sep + "x.stl"},
            ]
        },
        "count": 3,
        "warnings": ["Mesh file not found: %s" % os.path.join(here, "x.stl")],
    }
    links = answer["root"]["links"]

    assert wrapper_common.to_host(answer) is answer
    assert [link["part_file"] for link in links] == [
        "/there/pkg/meshes/arm.stl",
        "/state/out/box.step",
        "/there/pkg",
        here + "0" + os.sep + "x.stl",
    ]
    # A message that mentions a path keeps the spelling it was written with.
    assert answer["warnings"] == ["Mesh file not found: %s" % os.path.join(here, "x.stl")]
    assert answer["count"] == 3


def test_a_windows_callers_paths_come_back_in_its_own_spelling(carried):
    here = os.path.join(os.sep, "here", "1")
    carried.extend([(here, "D:\\work\\pkg"), (here + "s", "\\\\server\\share\\lib")])
    assert wrapper_common.to_host(os.path.join(here, "meshes", "arm.stl")) == "D:\\work\\pkg\\meshes\\arm.stl"
    assert wrapper_common.to_host(os.path.join(here + "s", "a.stl")) == "\\\\server\\share\\lib\\a.stl"


def test_nothing_is_rewritten_where_nothing_was_sent(carried):
    answer = {"part_file": "/anywhere/a.stl"}
    assert wrapper_common.to_host(answer) == {"part_file": "/anywhere/a.stl"}


def test_handle_input_and_handle_output_do_both_halves(carried, monkeypatch, tmp_path):
    """The two ends every wrapper goes through, in process: nothing is left changed but these globals."""
    for name in ("_request_name", "_request_label", "_request_finish", "_answer_framed", "_response_fd"):
        monkeypatch.setattr(wrapper_common, name, getattr(wrapper_common, name))
    # Neither is this test's to do to the process it shares: point descriptor 1
    # at standard error, and set the locale.
    monkeypatch.setattr(wrapper_common, "protect_response_channel", lambda: None)
    monkeypatch.setattr(wrapper_common.locale, "setlocale", lambda *args: None)

    here, there = str(tmp_path / "here"), str(tmp_path / "there")
    request = {"path": os.path.join(there, "a.dxf"), "name": "pkg:a"}
    command = request_paths.carry(["wrapper.py", here], request, ("path",))
    # As a sandbox that was sent 'there' leaves the command line.
    monkeypatch.setattr(sys, "argv", [part.replace(there, here) for part in command])
    monkeypatch.setattr(sys, "stdin", types.SimpleNamespace(buffer=io.BytesIO(ocp_serialize.serialize(request))))

    path, adopted = wrapper_common.handle_input(decode=False)

    assert path == os.path.normpath(here)
    assert adopted == {"path": os.path.join(here, "a.dxf"), "name": "pkg:a"}

    answer = tmp_path / "answer"
    with open(answer, "wb") as f:
        monkeypatch.setattr(wrapper_common, "_response_fd", f.fileno())
        monkeypatch.setattr(wrapper_common, "_answer_framed", False)
        wrapper_common.handle_output({"read": os.path.join(here, "a.dxf")})
    assert json.loads(answer.read_text())["read"] == os.path.join(there, "a.dxf")


def test_the_urdf_reader_says_what_to_declare_when_it_was_sent_files(carried):
    """A 'package://' reference is looked for above the URDF, and nothing above it was sent."""
    assert import_urdf.sent_note("package://arm/meshes/a.stl") == ""
    carried.append(("/here/1", "/there/pkg"))
    note = import_urdf.sent_note("package://arm/meshes/a.stl")
    assert "'arm'" in note and "'searchPaths'" in note
    # A plain path is relative to the URDF, whose directory was sent.
    assert import_urdf.sent_note("meshes/a.stl") == ""


# --------------------------------------------------------------------------- #
# Through the container's service                                              #
# --------------------------------------------------------------------------- #


@pytest.fixture
def server(monkeypatch, tmp_path):
    """The container's service, loaded from its file without a container (see 'test_container_execute')."""
    monkeypatch.setenv("PC_CONTAINER_ALLOWED_COMMANDS", json.dumps({"python": sys.executable}))
    monkeypatch.setenv("PC_CONTAINER_SANDBOX_ROOT", str(tmp_path / "pc-sandbox"))
    monkeypatch.setenv("PC_CONTAINER_STORE", str(tmp_path / "pc-store"))
    spec = importlib.util.spec_from_file_location("pc_container_json_rpc", container_service.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sent_and_run(server, command, request, written, deleted):
    """Run 'command' as the 'remote' sandbox runs it, with 'deleted' gone from here first.

    The directories sent are the ones 'runtime_python_remote' works out from
    the command, and the request goes as a container is sent it: JSON.
    """
    command = ["python"] + command
    input_dirs, output_files, output_dirs = runtime_python_remote.RemotePythonRuntime._exchanged(
        command, None, None, None, request_paths.written(_Exchanging(), *written).get("output_dirs")
    )
    packed = {directory: pc_runtime.pack_directory(directory) for directory in input_dirs}
    for directory in deleted:
        for root, _, files in os.walk(directory):
            for name in files:
                os.remove(os.path.join(root, name))

    result = server.handle_execute_command(
        command=command,
        stdin=base64.b64encode(ocp_serialize.dumps(request).encode("utf-8")).decode("utf-8"),
        output_files=output_files,
        input_dirs=packed,
        output_dirs=output_dirs,
    )
    assert result["exit_code"] == 0, base64.b64decode(result["stderr"]).decode("utf-8", "replace")
    # What came back, written where it was asked for, as the client does.
    for name, archive in (result.get("output_dirs") or {}).items():
        os.makedirs(name, exist_ok=True)
        container_service.unpack_directory(archive, name)
    return shape_envelope.deserialize(base64.b64decode(result["stdout"]))


READER = """
import os
import sys

sys.path.append(os.path.dirname(__file__))
import helper


def process(path, request):
    with open(request["source_file"]) as f:
        mesh = os.path.join(request["base_dir"], "meshes", f.read().strip())
    found = [os.path.join(root, "lib.stl") for root in request["search_paths"]]
    found = [candidate for candidate in found if os.path.isfile(candidate)]
    os.makedirs(request["output_folder"], exist_ok=True)
    made = os.path.join(request["output_folder"], "box.step")
    with open(made, "w") as f:
        f.write(helper.BOX)
    return {
        "root": {
            "type": "assembly",
            "name": "robot",
            "links": [
                {"type": "part", "name": "arm", "part_file": mesh, "seen": os.path.isfile(mesh)},
                {"type": "part", "name": "lib", "part_file": found[0]},
                {"type": "part", "name": "box", "part_file": made},
            ],
        }
    }
"""


def test_an_import_reader_reads_what_its_request_names_and_answers_in_partcads_paths(server, tmp_path):
    """The URDF reader's failure, with a reader of this test's own: everything it reads is in the request."""
    reader = tmp_path / "reader"
    reader.mkdir()
    (reader / "read_it.py").write_text(READER)
    (reader / "helper.py").write_text("BOX = 'a box'\n")
    package = tmp_path / "pkg"
    (package / "meshes").mkdir(parents=True)
    (package / "robot.txt").write_text("arm.stl\n")
    (package / "meshes" / "arm.stl").write_text("solid arm\n")
    library = tmp_path / "lib"
    library.mkdir()
    (library / "lib.stl").write_text("solid lib\n")
    output_folder = tmp_path / "state" / "urdf" / "0123"

    request = {
        "source_file": str(package / "robot.txt"),
        "base_dir": str(package),
        "output_folder": str(output_folder),
        "search_paths": [str(package), str(library)],
        wrapper_import.SCRIPT_KEY: str(reader / "read_it.py"),
    }
    command = request_paths.carry([os.path.join(WRAPPERS, "wrapper_import.py"), str(package)], request, KEYS)

    answer = _sent_and_run(server, command, request, [str(output_folder)], [reader, package, library])

    assert answer["success"] is True, answer.get("exception")
    links = {link["name"]: link for link in answer["root"]["links"]}
    assert links["arm"]["seen"] is True
    assert links["arm"]["part_file"] == str(package / "meshes" / "arm.stl")
    assert links["lib"]["part_file"] == str(library / "lib.stl")
    # Written over there, sent back, and named where it now is.
    assert links["box"]["part_file"] == str(output_folder / "box.step")
    assert (output_folder / "box.step").read_text() == "a box"


PART_TYPE = """
import os

with open(request["path"]) as f:
    layer = os.path.join(os.path.dirname(request["path"]), f.read().strip())
with open(layer) as f:
    f.read()
output = {"shapes": [], "dependencies": [layer, "relative.png"]}
"""


def test_a_part_type_reads_its_file_and_reports_what_else_it_read_in_partcads_paths(server, tmp_path):
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    (plugin / "part_layered.py").write_text(PART_TYPE)
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "stage.txt").write_text("layer.txt\n")
    (package / "layer.txt").write_text("geometry\n")

    request = {"path": str(package / "stage.txt"), "name": "pkg:stage", "label": "stage"}
    command = request_paths.carry(
        [os.path.join(WRAPPERS, "wrapper_part_type.py"), str(plugin / "part_layered.py"), str(plugin)],
        request,
        ("path",),
    )

    answer = _sent_and_run(server, command, request, [], [plugin, package])

    assert answer["success"] is True, answer.get("exception")
    assert answer["dependencies"] == [str(package / "layer.txt"), "relative.png"]


def test_the_step_assembly_reader_sends_the_file_and_has_the_parts_come_back(tmp_path):
    """'pc import assembly' and the 'step' assembly type, told what an upload-mode runtime is told."""
    from partcad import assembly_step_reader

    calls = []

    class Runtime(_Exchanging):
        async def ensure_async(self, *args, **kwargs):
            pass

        async def run_async(self, command, stdin, **kwargs):
            calls.append((command, shape_envelope.deserialize(stdin), kwargs))
            return 0, shape_envelope.serialize({"success": True, "root": {"type": "assembly"}}), ""

    runtime = Runtime()
    ctx = types.SimpleNamespace(get_python_runtime=lambda version=None: runtime)
    source = tmp_path / "pkg" / "robot.step"
    folder = tmp_path / "parts"

    root = asyncio.run(assembly_step_reader.read_assembly_tree(ctx, str(source), str(folder)))

    assert root == {"type": "assembly"}
    command, request, kwargs = calls[0]
    assert command[-3:] == [request_paths.ARGUMENT, str(source), str(folder)]
    assert request[request_paths.KEY] == [["assembly_file", None], ["output_folder", None]]
    assert kwargs == {"output_dirs": [str(folder)]}
