#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The CMF section a payload carries after its BREP (docs/design/cmf.md, section 6).

Pinned here: the section round-trips; a payload without one is a BREP and
nothing else; OCCT reads a payload with one as the same geometry it would read
without it; and the rules a part's own CMF completes or replaces what its source
stated by.
"""

import os
import sys

import pytest

import partcad as pc

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import cmf_section  # noqa: E402
from cmf_section import NONE, CmfSet, Section  # noqa: E402

RED = CmfSet(color="//v:red", rgba=(201, 26, 9, 1.0), origin="source:step")
GREY = CmfSet(color="//v:grey", rgba=(150, 150, 150, 1.0), material="//m:abs", origin="source:step")
DECLARED = CmfSet(
    color="//v:blue", rgba=(0, 0, 255, 1.0), material="//m:pc", finish="//f:satin", roughness=0.6, origin="declared"
)


def _section():
    # Two solids - the first in grey ABS, the second in nothing - and six
    # faces: two red, two grey, two in nothing.
    return Section([RED, GREY], NONE, solids=[1, NONE], faces=[0, 0, 1, NONE, NONE, 1])


def test_a_section_round_trips():
    payload = cmf_section.join(b"BREP", _section())
    assert cmf_section.split(payload) == (b"BREP", _section())


def test_a_payload_without_one_is_its_brep():
    assert cmf_section.split(b"just a brep") == (b"just a brep", None)
    assert cmf_section.join(b"just a brep", Section()) == b"just a brep"
    assert cmf_section.join(b"just a brep", None) == b"just a brep"


def test_strings_are_utf8_and_shared():
    named = CmfSet(color="//pub/universe/lego:Medium Stone Grey", rgba=(150, 150, 150, 0.5))
    section = Section([named, CmfSet(color=named.color, material="//m:µ-alloy")], 0)
    assert cmf_section.split(cmf_section.join(b"B", section))[1] == Section(
        [CmfSet(color=named.color, rgba=(150, 150, 150, 128 / 255.0)), section.sets[1]], 0
    )


def test_what_is_unspecified_is_counted():
    summary = _section().summary()
    assert summary["unspecified"] == {"color": 2, "material": 1}


def test_the_part_s_own_cmf_completes_what_the_source_leaves_unset():
    completed = _section().completed(DECLARED)
    assert completed.summary()["unspecified"] == {}
    # A face the source coloured keeps its colour, and takes the part's material
    # and finish; a face it left alone is the part's own.
    assert completed.face_set(0).color == "//v:red"
    assert completed.face_set(0).finish == "//f:satin"
    assert completed.face_set(3).color == "//v:blue"
    # A solid the source made of something keeps it.
    assert completed.solid_set(0).material == "//m:abs"
    assert completed.solid_set(1).material == "//m:pc"


def test_dropping_a_component_lets_the_part_s_own_replace_it():
    replaced = _section().without(["color"]).completed(DECLARED)
    assert {replaced.face_set(i).color for i in range(6)} == {"//v:blue"}
    assert replaced.solid_set(0).material == "//m:abs"


def test_dropping_everything_leaves_only_the_part_s_own():
    replaced = _section().without(cmf_section.COMPONENTS).completed(DECLARED)
    assert {replaced.face_set(i).key() for i in range(6)} == {DECLARED.key()}


def test_a_part_with_no_source_cmf_is_its_own_everywhere():
    section = Section().completed(DECLARED)
    assert section.summary() == {
        "sets": [{**DECLARED.as_dict(), "faces": "all", "solids": "all"}],
        "unspecified": {},
    }
    assert Section().summary()["unspecified"] == {"color": "all", "material": "all"}


def test_sets_nothing_uses_are_dropped():
    section = Section([RED, GREY, DECLARED], 2, faces=[0, 0]).compacted()
    assert section.sets == [RED, DECLARED]
    assert section.faces == [0, 0] and section.default == 1


def test_a_truncated_section_is_refused():
    data = cmf_section.encode(_section())
    with pytest.raises(Exception):
        cmf_section.decode(data[:-3])


def test_occt_reads_the_same_geometry_with_a_section_after_it():
    pytest.importorskip("build123d")
    import build123d as bd
    import ocp_serialize
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape

    shape = (bd.Box(10, 10, 10) - bd.Cylinder(3, 20)).wrapped
    brep = ocp_serialize.shape_to_brep(shape)
    with_section = cmf_section.join(brep, _section())
    assert with_section != brep

    def faces(data):
        found = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(ocp_serialize.shape_from_brep(data), TopAbs_FACE, found)
        return found.Extent()

    assert faces(with_section) == faces(brep) == 7
