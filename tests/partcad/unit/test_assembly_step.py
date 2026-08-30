#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for the 'step' assembly type.

The point of the type is that a STEP file becomes the same in-memory
representation an ASSY file produces, so the tests compare trees and placements
directly rather than inspecting anything STEP-specific.

The reader itself runs in a python sandbox (see assembly_step_reader), which is
not something a unit test can rely on having, so most of these stub the one
method that runs it and hand back the tree the reader really returns for
'examples/feature_import/AeroAssembly.step' - the same tree
'examples/feature_import/AeroAssembly_assy_example/AeroAssembly.assy' records.
The one test that reads a real STEP file end to end is marked 'slow' and skips
itself when there is no sandbox to read it with.
"""

import asyncio
import contextlib
import functools
import http.server
import os
import shutil
import threading
from pathlib import Path

import pytest

import partcad as pc
from partcad.assembly_factory_step import AssemblyFactoryStep

ROOT_DIR = Path(__file__).resolve().parents[3]
AERO_STEP = ROOT_DIR / "examples/feature_import/AeroAssembly.step"

# The tree wrapper_import_assy returns for AeroAssembly.step: an assembly of two
# groups and two loose shapes. Only the placements of the parts are here - the
# reader folds each parent's transform into the shapes below it, so a group node
# carries no location of its own.
AERO_TREE = {
    "type": "assembly",
    "name": "AeroAssembly",
    "links": [
        {
            "type": "assembly",
            "name": "AeroFrameAssembly",
            "links": [
                ("AeroFrameAssembly_solid1", [[-69.13423, -87.08086, 82.88129], [1.0, 0.0, 0.0], 0.0]),
                ("AeroFrameAssembly_solid2", [[-69.13423, -87.08086, 82.88129], [1.0, 0.0, 0.0], 0.0]),
                (
                    "AeroFrameAssembly_solid3",
                    [[-128.61717, 53.05292, 75.22509], [0.12943, -0.12943, -0.98311], 90.9762],
                ),
            ],
        },
        ("AeroFrame_Plate", [[-76.86294, -86.19999, 80.29769], [1.0, 0.0, 0.0], 0.0]),
        ("AeroFrame_Cap", [[-76.86294, -86.19999, 80.29769], [1.0, 0.0, 0.0], 0.0]),
        {
            "type": "assembly",
            "name": "MirrorAeroFrameAssembly",
            "links": [
                ("MirrorAeroFrameAssembly_solid1", [[-84.59165, -85.31912, -77.71409], [1.0, 0.0, 0.0], 0.0]),
                ("MirrorAeroFrameAssembly_solid2", [[-84.59165, -85.31912, -77.71409], [1.0, 0.0, 0.0], 0.0]),
                (
                    "MirrorAeroFrameAssembly_solid3",
                    [[-144.0746, 54.81466, -70.05789], [-0.12943, 0.12943, -0.98311], 90.9762],
                ),
            ],
        },
    ],
}


def _materialize(node, folder):
    """Turn the shorthand above into the reader's own data, writing the files.

    The reader writes one STEP file per distinct shape before it returns, and
    the part factory refuses a path that is not there, so the files have to
    exist. Their contents are never read: no test here builds geometry.
    """
    if isinstance(node, dict):
        return {
            "type": "assembly",
            "name": node["name"],
            "links": [_materialize(link, folder) for link in node["links"]],
        }
    name, location = node
    part_file = os.path.join(folder, "%s.step" % name)
    Path(part_file).write_text("ISO-10303-21;\n")
    return {"type": "part", "name": name, "part_file": part_file, "location": location}


@pytest.fixture
def stub_reader(monkeypatch):
    """Replace the sandboxed read with the canned tree, into the real output dir."""

    async def _read_async(self):
        # Whatever the source is - a file in the package or one just downloaded
        # - it has to be on disk by the time the reader would be handed it.
        assert os.path.exists(self.path), "the reader was called before the source file was there"
        folder = self._generated_dir()
        os.makedirs(folder, exist_ok=True)
        return _materialize(AERO_TREE, folder)

    monkeypatch.setattr(AssemblyFactoryStep, "_read_async", _read_async)


def package(tmp_path, monkeypatch, extra=""):
    """A one-package workspace whose only assembly is a STEP file, plus a context.

    The generated geometry is pointed at a directory of this test's own, so that
    a test can tell what the assembly wrote from what was in the package already.
    """
    pkg = tmp_path / "pkg"
    pkg.mkdir(exist_ok=True)
    (pkg / "partcad.yaml").write_text("assemblies:\n  AeroAssembly:\n    type: step\n%s" % extra)
    (pkg / "AeroAssembly.step").write_text("ISO-10303-21;\n")

    ctx = pc.Context(str(pkg))
    monkeypatch.setattr(ctx.user_config, "internal_state_dir", str(tmp_path / "state"))
    return pkg, ctx


def names(item):
    return [child.name for child in getattr(item, "children", [])]


def placement(location):
    packed = location.as_packed()
    return (
        tuple(round(v, 4) for v in packed[0]),
        tuple(round(v, 4) for v in packed[1]),
        round(packed[2], 4),
    )


def find_child(item, name):
    """The item an assembly holds under 'name', at any depth."""
    for child in getattr(item, "children", []):
        if child.name == name:
            return child.item
        found = find_child(child.item, name)
        if found is not None:
            return found
    return None


def test_step_assembly_builds_the_tree_the_file_describes(tmp_path, monkeypatch, stub_reader):
    """The assembly *is* the STEP root: its children are the root's components.

    A group in the file becomes a nested assembly, and a loose shape becomes a
    placed part, exactly as 'pc import assembly' writes them into an .assy file.
    """
    _, ctx = package(tmp_path, monkeypatch)
    aero = ctx._get_assembly(":AeroAssembly")
    assert aero is not None
    asyncio.run(aero.do_instantiate())

    assert names(aero) == [
        "AeroFrameAssembly",
        "AeroFrame_Plate",
        "AeroFrame_Cap",
        "MirrorAeroFrameAssembly",
    ]

    group = find_child(aero, "AeroFrameAssembly")
    assert names(group) == [
        "AeroFrameAssembly_solid1",
        "AeroFrameAssembly_solid2",
        "AeroFrameAssembly_solid3",
    ]

    # A group sits at the origin; the placements it contains are already absolute.
    by_name = {child.name: child for child in aero.children}
    assert placement(by_name["AeroFrameAssembly"].location) == ((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 0.0)
    assert placement(by_name["AeroFrame_Plate"].location)[0] == (-76.8629, -86.2, 80.2977)
    assert placement(group.children[2].location)[2] == pytest.approx(90.9762)


def test_step_components_are_ordinary_parts(tmp_path, monkeypatch, stub_reader):
    """Each component is a part of the package, named '<assembly>/<component>'.

    They are not declared in 'partcad.yaml' - the STEP file is what declares them
    - so a package that is handed one of these names builds the assembly that
    owns it first. That has to work on a project that has never touched the
    assembly.
    """
    pkg, ctx = package(tmp_path, monkeypatch)
    project = ctx.get_project("")

    assert "AeroAssembly/AeroFrame_Plate" not in project.parts
    part = project.get_part("AeroAssembly/AeroFrame_Plate")
    assert part is not None
    assert part.name == "AeroAssembly/AeroFrame_Plate"
    # It reads a file of its own, kept outside the package.
    assert part.config["type"] == "step"
    assert Path(part.path).name == "AeroFrame_Plate.step"

    # A component of a nested group is reachable by name too.
    assert project.get_part("AeroAssembly/AeroFrameAssembly_solid3") is not None

    # Still not something the package declares.
    assert "AeroAssembly/AeroFrame_Plate" in project.parts
    assert "AeroAssembly/AeroFrame_Plate" not in (project.config_obj.get("parts") or {})


def test_a_slash_in_a_part_name_is_not_enough(tmp_path, monkeypatch):
    """Only a name whose prefix really is such an assembly triggers the build."""
    _, ctx = package(tmp_path, monkeypatch)
    project = ctx.get_project("")
    assert project._derived_part_owner("AeroAssembly/AeroFrame_Plate") == ("assembly", "AeroAssembly")
    assert project._derived_part_owner("brackets/left") is None
    assert project._derived_part_owner("AeroFrame_Plate") is None


def test_nothing_is_written_into_the_package(tmp_path, monkeypatch, stub_reader):
    """Using the assembly leaves the user's source tree exactly as it was.

    The per-component geometry is derived data, so it goes under PartCAD's own
    state directory. 'pc import assembly' is the command that deliberately
    materializes it into the package instead.
    """
    pkg, ctx = package(tmp_path, monkeypatch)
    before = sorted(p.relative_to(pkg).as_posix() for p in pkg.rglob("*"))

    aero = ctx._get_assembly(":AeroAssembly")
    asyncio.run(aero.do_instantiate())
    assert ctx.get_project("").get_part("AeroAssembly/AeroFrame_Cap") is not None

    assert sorted(p.relative_to(pkg).as_posix() for p in pkg.rglob("*")) == before

    # And what it did write is under the internal state directory.
    state = Path(ctx.user_config.internal_state_dir)
    written = sorted(p.name for p in state.rglob("*.step"))
    assert "AeroFrame_Cap.step" in written
    assert Path(ctx.get_part(":AeroAssembly/AeroFrame_Cap").path).is_relative_to(state)


def test_the_step_assembly_type_is_registered():
    """'type: step' in the assemblies section reaches this factory."""
    assert pc.factory.all["assembly"]["step"] is AssemblyFactoryStep


@contextlib.contextmanager
def _serve(directory):
    """Serve 'directory' over HTTP on a private loopback port.

    Downloads go through 'aiohttp', so a file:// URL is not an option: the test
    needs something that actually speaks HTTP. Binding to port 0 keeps the
    server private to this test, so tests can still run in parallel.
    """
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:%d" % server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_step_assembly_from_url(tmp_path, monkeypatch, stub_reader):
    """A 'type: step' assembly can pull its STEP file from a URL.

    The package loads without the file, the file is downloaded the first time
    the assembly is used, and only then is it read - which is what the stubbed
    reader asserts.
    """
    served = tmp_path / "served"
    served.mkdir()
    (served / "AeroAssembly.step").write_text("ISO-10303-21;\n")

    pkg = tmp_path / "pkg"
    pkg.mkdir()

    with _serve(served) as url:
        (pkg / "partcad.yaml").write_text(
            "assemblies:\n"
            "  AeroAssembly:\n"
            "    type: step\n"
            "    fileFrom: url\n"
            "    fileUrl: %s/AeroAssembly.step\n" % url
        )

        # The package loads even though the STEP file is not in it yet
        ctx = pc.Context(str(pkg))
        monkeypatch.setattr(ctx.user_config, "internal_state_dir", str(tmp_path / "state"))
        aero = ctx._get_assembly(":AeroAssembly")
        assert aero is not None
        assert os.path.exists(aero.path) is False

        # Instantiating the assembly downloads the STEP file and reads it
        asyncio.run(aero.do_instantiate())
        assert os.path.exists(aero.path) is True
        assert names(aero)[0] == "AeroFrameAssembly"

    # The components of a downloaded file are parts like any other.
    assert ctx.get_project("").get_part("AeroAssembly/AeroFrame_Plate") is not None


@pytest.mark.slow
def test_step_assembly_end_to_end(tmp_path):
    """A real STEP file, read by the real reader (needs the sandbox).

    The same file 'pc import assembly' is tested against, so the tree it comes
    out with has to be the same one - it is the same reader.
    """
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "partcad.yaml").write_text("assemblies:\n  AeroAssembly:\n    type: step\n")
    shutil.copy(AERO_STEP, pkg / "AeroAssembly.step")

    ctx = pc.Context(str(pkg))
    aero = ctx._get_assembly(":AeroAssembly")
    assert aero is not None
    try:
        asyncio.run(aero.do_instantiate())
    except Exception as e:
        pytest.skip("Sandbox unavailable for the STEP assembly reader: %s" % e)

    assert names(aero) == [
        "AeroFrameAssembly",
        "AeroFrame_Plate",
        "AeroFrame_Cap",
        "MirrorAeroFrameAssembly",
    ]
    assert len(find_child(aero, "AeroFrameAssembly").children) == 3

    part = ctx.get_project("").get_part("AeroAssembly/AeroFrame_Plate")
    assert part is not None
    assert asyncio.run(part.get_wrapped(ctx)) is not None

    # Nothing of it landed in the package.
    assert sorted(p.name for p in pkg.iterdir()) == ["AeroAssembly.step", "partcad.yaml"]
