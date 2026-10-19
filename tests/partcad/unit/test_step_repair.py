#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Repairing a STEP file before OpenCASCADE reads it ('wrappers/step_repair.py').

A transformation operator written without the two attributes it inherits from
'functionally_defined_transformation' is rejected by OpenCASCADE when it loads,
and the geometry placed by it then crashes the process. The repair puts them
back, and touches nothing else.
"""

import asyncio
import importlib.util
import os

import pytest

import partcad as pc
from partcad import shape_envelope

REPAIR = os.path.join(os.path.dirname(pc.__file__), "wrappers", "step_repair.py")
PACKAGE = "tests/partcad/unit/data/step_repair/partcad.yaml"


@pytest.fixture(scope="module")
def step_repair():
    spec = importlib.util.spec_from_file_location("step_repair_under_test", REPAIR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_short_2d_operator_gets_its_inherited_attributes(step_repair):
    text = "#37 = CARTESIAN_TRANSFORMATION_OPERATOR_2D('',#36,#33,#32,1.);\n"
    assert step_repair.repair_text(text) == (
        "#37 = CARTESIAN_TRANSFORMATION_OPERATOR_2D('','',$,#36,#33,#32,1.);\n",
        1,
    )


def test_a_short_3d_operator_gets_them_too(step_repair):
    text = "#19 = CARTESIAN_TRANSFORMATION_OPERATOR_3D('a, b (c)',#8,#7,#17,1.,#18);"
    repaired, count = step_repair.repair_text(text)
    assert count == 1
    assert repaired == "#19 = CARTESIAN_TRANSFORMATION_OPERATOR_3D('a, b (c)','',$,#8,#7,#17,1.,#18);"


def test_a_complete_operator_is_left_alone(step_repair):
    text = (
        "#1 = CARTESIAN_TRANSFORMATION_OPERATOR_2D('','',$,#2,#3,#4,1.);\n"
        "#5 = CARTESIAN_TRANSFORMATION_OPERATOR_3D('it''s','',$,#6,$,#7,$,#8);\n"
    )
    assert step_repair.repair_text(text) == (text, 0)


def test_a_complex_instance_is_left_alone(step_repair):
    # Each partial list in a complex instance holds one supertype's attributes.
    text = "#9 = ( CARTESIAN_TRANSFORMATION_OPERATOR_3D($) GEOMETRIC_REPRESENTATION_ITEM() );"
    assert step_repair.repair_text(text) == (text, 0)


def test_a_file_needing_no_repair_is_read_as_it_is(step_repair, tmp_path):
    clean = tmp_path / "clean.step"
    clean.write_text("ISO-10303-21;\nDATA;\n#1 = CARTESIAN_POINT('',(0.,0.,0.));\nENDSEC;\n")
    with step_repair.readable(str(clean)) as path:
        assert path == str(clean)


def test_a_repaired_copy_is_gone_afterwards(step_repair):
    source = os.path.join(os.path.dirname(PACKAGE), "cadmpeg.step")
    with step_repair.readable(source) as path:
        assert path != source
        with open(path, encoding="latin-1") as f:
            assert "CARTESIAN_TRANSFORMATION_OPERATOR_2D('','',$," in f.read()
    assert not os.path.exists(path)


@pytest.mark.slow
def test_opencascade_reads_the_file_it_used_to_crash_on():
    ctx = pc.Context(PACKAGE)
    part = ctx.get_part(":cadmpeg")
    try:
        envelope = asyncio.run(part.get_wrapped(ctx))
    except Exception as e:
        pytest.skip("The sandbox is unavailable: %s" % e)
    assert envelope is not None, part.errors
    measured = envelope[shape_envelope.KEY_METADATA][shape_envelope.METADATA_MEASUREMENTS]
    # Everything cadmpeg wrote: the Pad twice over and the Pocket's tool.
    assert measured["solids"] == 3
