#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The clusters the "Materials" callout writes one name per ('wrappers/material_clusters.py').

A cluster is the faces of one material, of one part or of several, each of which
touches another of them or is closer to it than the configured distance. What
is under test is which faces end up together, what they are called, where the
callout is pinned and which nodes of the tree it is pinned to - with the real
kernel and real CMF sections, decoded the way a sandbox decodes a tree.
"""

import os
import sys

import pytest

import partcad as pc

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
from cmf_section import CmfSet  # noqa: E402

ABS = CmfSet(material="//src:abs", origin="declared")
STEEL = CmfSet(material="//src:steel%2C 1.4301", origin="declared")
PAINT = CmfSet(color="//src:red", origin="declared", rgba=(201, 26, 9, 1.0))


def _kernel():
    pytest.importorskip("build123d")
    import build123d as bd

    return bd


def _box(size=10, material=ABS, name="//src:block", label=None, at=None, **extra):
    """A cube of 'size' in 'material' (None for none), as a node of a tree."""
    bd = _kernel()
    import ocp_serialize

    solid = bd.Box(size, size, size)
    section = None
    if material is not None:
        section = ocp_serialize.cmf_section_for(solid.wrapped, solids={solid.solid().wrapped: material})
    node = ocp_serialize.encode_shape(solid.wrapped, name=name, label=label, cmf=section)
    if at is not None:
        node[ocp_serialize.KEY_LOCATION] = [list(at), [0, 0, 1], 0]
    node.update(extra)
    return node


def _assembly(*children):
    return {"name": "//src:top", "label": None, "assembly": list(children)}


def _clusters(tree, distance=10):
    import material_clusters
    import ocp_serialize

    _whole, decoded = ocp_serialize.decode_tree(tree)
    return material_clusters.clusters(decoded, distance)


def _summary(found):
    return [(cluster["name"], cluster["nodes"]) for cluster in found]


def test_parts_of_one_material_closer_than_the_distance_are_one_cluster():
    # Two 10 mm cubes of ABS with a 5 mm gap between them, and a steel one far off.
    tree = _assembly(
        _box(label="left"),
        _box(label="right", at=(15, 0, 0)),
        _box(material=STEEL, label="far", at=(200, 0, 0)),
    )

    found = _clusters(tree, distance=10)

    assert _summary(found) == [("abs", [[0], [1]]), ("steel, 1.4301", [[2]])]
    assert found[0]["material"] == "//src:abs"
    # Every face of both cubes.
    assert found[0]["faces"] == 12


def test_parts_farther_apart_than_the_distance_are_two_clusters():
    tree = _assembly(_box(label="left"), _box(label="right", at=(15, 0, 0)))

    assert _summary(_clusters(tree, distance=4)) == [("abs", [[0]]), ("abs", [[1]])]


def test_parts_that_touch_are_one_cluster_at_any_distance():
    tree = _assembly(_box(label="left"), _box(label="right", at=(10, 0, 0)))

    assert _summary(_clusters(tree, distance=0)) == [("abs", [[0], [1]])]


def test_two_materials_are_never_one_cluster_however_close():
    tree = _assembly(_box(label="left"), _box(material=STEEL, label="right", at=(10, 0, 0)))

    assert _summary(_clusters(tree)) == [("abs", [[0]]), ("steel, 1.4301", [[1]])]


def test_a_part_of_two_materials_is_in_two_clusters():
    bd = _kernel()
    import ocp_serialize

    first, second = bd.Box(10, 10, 10), bd.Pos(10, 0, 0) * bd.Box(10, 10, 10)
    shape = ocp_serialize.compound_of([first.wrapped, second.wrapped])
    section = ocp_serialize.cmf_section_for(shape, solids={first.solid().wrapped: ABS, second.solid().wrapped: STEEL})
    tree = ocp_serialize.encode_shape(shape, name="//src:pair", label=None, cmf=section)

    found = _clusters(tree)

    assert _summary(found) == [("abs", [[]]), ("steel, 1.4301", [[]])]
    assert [cluster["faces"] for cluster in found] == [6, 6]


def test_a_surface_with_no_solid_is_of_what_its_faces_say():
    """A wall is a sheet of faces: its material is its faces' own set's."""
    bd = _kernel()
    import ocp_serialize

    sheet = bd.Face.make_rect(100, 50)
    section = ocp_serialize.cmf_section_for(sheet.wrapped, faces={sheet.wrapped: ABS})
    tree = ocp_serialize.encode_shape(sheet.wrapped, name="//src:wall", label=None, cmf=section)

    assert _summary(_clusters(tree)) == [("abs", [[]])]


def test_what_states_no_material_has_no_cluster():
    """A colour is not a material, and "unspecified" is not one either."""
    tree = _assembly(_box(material=None, label="bare"), _box(material=PAINT, label="painted", at=(20, 0, 0)))

    assert _clusters(tree) == []


def test_a_material_a_part_named_before_cmf_is_read_from_its_properties():
    """Relative to the package of the part that named it, as a part's 'material' always was."""
    tree = _box(material=None, name="//pkg:bracket", properties={"material": ":steel"})

    (found,) = _clusters(tree)

    assert found["material"] == "//pkg:steel"
    assert found["name"] == "steel"


def test_the_package_of_a_part_with_parameters_is_the_one_before_them():
    """A parameter's value can be a reference, with a ':' of its own."""
    tree = _box(material=None, name="//pkg:room;medium=//pub/std:air", properties={"material": "steel"})

    (found,) = _clusters(tree)

    assert found["material"] == "//pkg:steel"


def test_the_callout_is_pinned_on_the_material_near_the_middle_of_the_cluster():
    bd = _kernel()

    tree = _assembly(_box(label="left"), _box(label="right", at=(15, 0, 0)))
    (found,) = _clusters(tree)

    # The middle of the two cubes is in the gap between them, which is no
    # material; the point pinned is on a face of one of them, as near as that.
    # The two facing faces are as near as each other, so either will do.
    point = bd.Vertex(*found["at"])
    faces = [bd.Box(10, 10, 10), bd.Pos(15, 0, 0) * bd.Box(10, 10, 10)]
    assert min(point.distance_to(cube) for cube in faces) == pytest.approx(0, abs=1e-6)
    assert min(abs(found["at"][0] - 5), abs(found["at"][0] - 10)) == pytest.approx(0, abs=1e-6)


def test_one_geometry_placed_many_times_is_read_once(monkeypatch):
    import material_clusters

    calls = []
    joined = material_clusters._joined

    def counting(shape, materials):
        calls.append(len(materials))
        return joined(shape, materials)

    monkeypatch.setattr(material_clusters, "_joined", counting)
    tree = _assembly(*[_box(label="b%d" % index, at=(index * 12, 0, 0)) for index in range(5)])

    found = _clusters(tree)

    assert calls == [6]
    # Every gap is 2 mm: one chain of five.
    assert _summary(found) == [("abs", [[0], [1], [2], [3], [4]])]


def test_the_answer_is_the_same_every_time():
    tree = _assembly(
        _box(material=STEEL, label="c", at=(100, 0, 0)),
        _box(label="a"),
        _box(label="b", at=(50, 0, 0)),
    )

    assert _clusters(tree) == _clusters(tree)
    assert [cluster["name"] for cluster in _clusters(tree)] == ["abs", "abs", "steel, 1.4301"]


def test_the_wrapper_answers_from_the_tree_as_it_travelled():
    """What 'cmf.clusters' asks a sandbox: the tree undecoded, so that its nodes are still there to name."""
    import wrapper_materials

    tree = _assembly(_box(label="left"), _box(label="right", at=(15, 0, 0)))

    found = wrapper_materials.process({"operation": "clusters", "shape": tree, "distance": 10})

    assert _summary(found) == [("abs", [[0], [1]])]
    with pytest.raises(ValueError):
        wrapper_materials.process({"operation": "measure", "shape": tree})
