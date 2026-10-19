#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The built-in 'fcstd' part type: a FreeCAD document, read without FreeCAD.

It is a partType PartCAD ships in '//builtin/import', named by its bare name,
and it is what a file-backed partType is: the part's own file, resolved against
the part's package and depended on by its cache entry. Those parts are checked
without a sandbox. Reading the documents downloads cadmpeg and runs it, so
that part is marked slow and measured -- a PartDesign body is checked to come out as
its last feature's result rather than every feature stacked.
"""

import asyncio
import importlib.util
import os

import pytest

import partcad as pc
from partcad import factory, output, shape_envelope

PACKAGE = "tests/partcad/unit/data/import_fcstd/partcad.yaml"
SCRIPT = os.path.join(output.BUILTIN_PATHS[output.BUILTIN_PACKAGES[output.IMPORT]], "part_fcstd.py")


def _script():
    spec = importlib.util.spec_from_file_location("part_fcstd_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ctx():
    return pc.Context(PACKAGE)


def test_fcstd_is_a_builtin_part_type_not_a_factory(ctx):
    assert "fcstd" not in factory.all["part"]
    assert output.builtin_part_type(ctx, "fcstd") == "//builtin/import"
    # Nothing else is mistaken for one.
    assert output.builtin_part_type(ctx, "nope") is None
    assert output.builtin_part_type(ctx, "x:fcstd") is None


def test_the_part_is_its_file_in_its_own_package(ctx):
    part = ctx.get_part(":design_history")
    assert part is not None
    expected = os.path.abspath("tests/partcad/unit/data/import_fcstd/design_history.FCStd")
    assert os.path.abspath(part.path) == expected
    assert expected in [os.path.abspath(p) for p in part.cache_dependencies]
    # The declaration keeps saying what its author wrote.
    assert part.config["type"] == "fcstd"


def test_an_explicit_path_is_relative_to_the_part_s_package(ctx):
    part = ctx.get_part(":box")
    assert os.path.abspath(part.path) == os.path.abspath(
        "tests/partcad/unit/data/import_fcstd/techdraw_annotations.FCStd"
    )


def test_the_result_is_what_nothing_else_consumes():
    script = _script()
    model = {
        "features": [
            {"id": "f#Body", "ordinal": 1, "outputs": ["fcstd:model:body#Body:Shape:Body.Shape.brp:52"]},
            {
                "id": "f#Pad",
                "ordinal": 2,
                "dependencies": ["f#Body", "f#Sketch"],
                "source_properties": {"Visibility": "false"},
                "outputs": ["fcstd:model:body#Pad:AddSubShape:Pad.AddSubShape.brp:9", "x#Pad:Shape:Pad.Shape.brp:9"],
            },
            {"id": "f#Sketch", "ordinal": 3, "outputs": ["x#Sketch:Shape:Sketch.Shape.brp:3"]},
            {
                "id": "f#Fillet",
                "ordinal": 4,
                "dependencies": ["f#Pad", "f#Body"],
                "outputs": ["x#Fillet:Shape:Fillet.Shape.brp:47"],
            },
            {
                "id": "f#Hidden",
                "ordinal": 5,
                "source_properties": {"Visibility": "false"},
                "outputs": ["x#H:Shape:H.brp"],
            },
            {"id": "f#Off", "ordinal": 6, "suppressed": True, "outputs": ["x#O:Shape:O.Shape.brp:1"]},
            {"id": "f#Spreadsheet", "ordinal": 7},
        ]
    }
    assert script.result_entries(model) == ["Fillet.Shape.brp"]


def _measured(ctx, name):
    envelope = asyncio.run(ctx.get_part(name).get_wrapped(ctx))
    if envelope is None:
        return None
    return envelope[shape_envelope.KEY_METADATA][shape_envelope.METADATA_MEASUREMENTS]


@pytest.mark.slow
def test_documents_are_read_as_what_freecad_shows(ctx):
    box = _measured(ctx, ":box")
    assert box is not None, ctx.get_part(":box").errors
    assert box["solids"] == 1
    assert box["volume"] == pytest.approx(25 * 15 * 8)
    assert box["bbox"] == pytest.approx([0, 0, 0, 25, 15, 8], abs=1e-6)

    # Pad, Pocket and Fillet are three solids in the archive and one part.
    body = _measured(ctx, ":design_history")
    assert body["solids"] == 1
    assert body["volume"] == pytest.approx(3668.208, rel=1e-4)
    assert body["bbox"] == pytest.approx([0, 0, 0, 24, 16, 10], abs=1e-6)


@pytest.mark.slow
def test_a_document_with_no_solid_is_an_error(ctx):
    part = ctx.get_part(":sketches")
    envelope = asyncio.run(part.get_wrapped(ctx))
    assert envelope is None
    assert any("holds no solid" in str(error) for error in part.errors)
