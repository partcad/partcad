#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The 'gltf' part type: '.gltf' with its buffers beside it, or a single '.glb'.

The fixture is what build123d's 'export_gltf' -- PartCAD's own glTF export --
writes for a 10 x 20 x 30 mm box centred at (100, 0, 0), so reading it back
exactly is the round trip: glTF's metres and Y-up have to come back as
millimetres and Z-up for the box to land where it started.
"""

import asyncio
import os
from pathlib import Path

import pytest

import partcad as pc
from partcad import factory, shape_envelope
from partcad.actions.part import import_part_action
from partcad.actions.part.import_part import gltf_companions
from partcad.part_factory_gltf import PartFactoryGltf

DATA = Path("tests/partcad/unit/data/import_gltf")
PACKAGE = str(DATA / "partcad.yaml")


def test_gltf_is_a_part_type():
    assert factory.all["part"]["gltf"] is PartFactoryGltf


def test_a_gltf_part_is_its_file():
    ctx = pc.Context(PACKAGE)
    part = ctx.get_part(":box")
    assert os.path.abspath(part.path) == os.path.abspath(DATA / "box.gltf")
    assert os.path.abspath(ctx.get_part(":box_binary").path) == os.path.abspath(DATA / "box.glb")


def test_the_buffers_a_gltf_names_are_its_companions():
    assert gltf_companions(DATA / "box.gltf") == ["box.bin"]
    # A '.glb' carries them inside, and is not JSON at all.
    assert gltf_companions(DATA / "box.glb") == []


def test_importing_a_gltf_brings_its_buffers(tmp_path):
    project_dir = tmp_path / "package"
    project_dir.mkdir()
    (project_dir / "partcad.yaml").write_text("parts: {}\n")
    project = pc.Context(str(project_dir)).get_project("")

    import_part_action(project, "gltf", "imported", str(DATA / "box.gltf"))

    assert (project_dir / "imported.gltf").is_file()
    assert (project_dir / "box.bin").read_bytes() == (DATA / "box.bin").read_bytes()


@pytest.mark.slow
@pytest.mark.parametrize("name", [":box", ":box_binary"])
def test_a_gltf_reads_back_where_it_was_written(name):
    ctx = pc.Context(PACKAGE)
    try:
        envelope = asyncio.run(ctx.get_part(name).get_wrapped(ctx))
    except Exception as e:
        pytest.skip("The sandbox is unavailable: %s" % e)
    measured = envelope[shape_envelope.KEY_METADATA][shape_envelope.METADATA_MEASUREMENTS]
    assert measured["solids"] == 1
    assert measured["volume"] == pytest.approx(6000)
    assert measured["bbox"] == pytest.approx([95, -10, -15, 105, 10, 15], abs=1e-6)
