#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""How much tessellation a preview gets, and how little of it is sent twice.

Two decisions live in 'wrapper_gltf', and neither is visible in what it produces:
how fine the mesh is, and whether one shape placed a hundred times is tessellated
and sent a hundred times. Both are silent when they go wrong -- a preview that is
merely slow, or merely large -- so they are pinned here.

The deflection is the one with a moving part underneath it. 'export_gltf' asks
OCCT for a *relative* deflection, a fraction of each edge rather than a distance,
so the wrapper meshes the shape itself first and hands the exporter a value that
tells it to leave that mesh alone. If a build123d release ever meshed regardless,
every number here would go on being produced and the tessellation would stop
answering to the budget, which is why one of these tests tessellates a real
cylinder and counts the triangles rather than trusting the arrangement.
"""

import json
import os
import struct
import sys

import pytest
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder

import partcad as pc
from partcad import shape_gltf
from partcad.geom import Location

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import ocp_serialize  # noqa: E402
import wrapper_gltf  # noqa: E402


def box(dx=10.0, dy=10.0, dz=10.0):
    return BRepPrimAPI_MakeBox(dx, dy, dz).Shape()


def node(shape, location=None, children=None, **extra):
    """A BREP-form node, as the core hands one to the wrapper."""
    entry = dict(extra)
    entry[ocp_serialize.KEY_BREP] = ocp_serialize.compressed_brep(shape)
    if location is not None:
        entry[ocp_serialize.KEY_LOCATION] = location.as_packed()
    if children is not None:
        entry[ocp_serialize.KEY_ASSEMBLY] = list(children)
    return entry


def triangles(glb: bytes) -> int:
    """How many triangles a binary glTF holds, read off its accessors."""
    length = struct.unpack("<I", glb[12:16])[0]
    meta = json.loads(glb[20 : 20 + length])
    accessors = meta.get("accessors", [])
    total = 0
    for mesh in meta.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            if "indices" in primitive:
                total += accessors[primitive["indices"]]["count"] // 3
    return total


class TestBudget:
    """What deflection the tessellation runs at, in mm."""

    def test_it_is_a_fraction_of_the_size_of_what_is_shown(self):
        """Which is the whole point: a preview is looked at as a whole.

        A part 10 mm across and an assembly 10 m across want the same answer to
        "is this smooth enough" and deflections a thousand apart to get it.
        """
        request = {"screenDivisor": 2000.0, "minTolerance": 0.001, "maxTolerance": 10.0}
        assert wrapper_gltf._budget(400.0, request) == pytest.approx(0.2)
        assert wrapper_gltf._budget(4000.0, request) == pytest.approx(2.0)

    def test_a_caller_that_says_what_it_wants_is_not_second_guessed(self):
        request = {"tolerance": 0.05, "screenDivisor": 2000.0}
        assert wrapper_gltf._budget(400.0, request) == pytest.approx(0.05)

    def test_it_is_clamped_at_both_ends(self):
        """The floor is for a tiny object, the ceiling for a bogus bounding box.

        Without the floor a 1 mm part would be tessellated to half a micron for a
        gain no screen can show; without the ceiling one stray node a kilometre
        from the origin would flatten everything else into facets.
        """
        request = {"screenDivisor": 2000.0, "minTolerance": 0.01, "maxTolerance": 1.0}
        assert wrapper_gltf._budget(1.0, request) == pytest.approx(0.01)
        assert wrapper_gltf._budget(1000000.0, request) == pytest.approx(1.0)

    def test_a_tree_with_nothing_to_measure_gets_the_floor(self):
        """An interface whose ports carry no boundary has no size at all."""
        request = {"screenDivisor": 2000.0, "minTolerance": 0.02, "maxTolerance": 1.0}
        assert wrapper_gltf._budget(None, request) == pytest.approx(0.02)

    def test_the_core_and_the_sandbox_agree_on_the_policy(self):
        """The numbers are the core's; the sandbox is where the size is known.

        Stated in 'shape_gltf' and applied in the wrapper, so this is the test that
        notices if the sandbox's fallbacks and the core's constants drift apart.
        """
        assert shape_gltf.SCREEN_DIVISOR == shape_gltf.SCREEN_PIXELS / shape_gltf.PIXEL_BUDGET
        request = {
            "screenDivisor": shape_gltf.SCREEN_DIVISOR,
            "minTolerance": shape_gltf.MIN_TOLERANCE,
            "maxTolerance": shape_gltf.MAX_TOLERANCE,
        }
        assert wrapper_gltf._budget(2000.0, request) == pytest.approx(2000.0 / shape_gltf.SCREEN_DIVISOR)


class TestSize:
    """What the budget is a fraction *of*: the whole tree, where it sits."""

    def test_a_single_shape_is_measured_as_itself(self):
        size = wrapper_gltf._size(node(box(10, 10, 10)), {}, [])
        assert size == pytest.approx(3**0.5 * 10, rel=1e-3)

    def test_the_placements_are_composed_down_the_tree(self):
        """Eight parts 10 mm across are 10 mm stacked and metres apart spread out.

        The same geometry, the same nodes, and a deflection that has to differ by
        that factor - so a walk that ignored the placements would size a large
        assembly as if it were one of its parts.
        """
        together = wrapper_gltf._size(
            {ocp_serialize.KEY_ASSEMBLY: [node(box(10, 10, 10)), node(box(10, 10, 10))]},
            {},
            [],
        )
        apart = wrapper_gltf._size(
            {
                ocp_serialize.KEY_ASSEMBLY: [
                    node(box(10, 10, 10)),
                    node(box(10, 10, 10), location=Location([[1000, 0, 0], [0, 0, 1], 0])),
                ]
            },
            {},
            [],
        )
        assert together == pytest.approx(3**0.5 * 10, rel=1e-3)
        assert apart > 1000

    def test_a_placement_on_a_parent_reaches_its_children(self):
        """Composed placement first then the node's own, as 'placed()' states it."""
        nested = wrapper_gltf._size(
            {
                ocp_serialize.KEY_LOCATION: Location([[500, 0, 0], [0, 0, 1], 0]).as_packed(),
                ocp_serialize.KEY_ASSEMBLY: [
                    node(box(10, 10, 10)),
                    node(box(10, 10, 10), location=Location([[500, 0, 0], [0, 0, 1], 0])),
                ],
            },
            {},
            [],
        )
        # The two boxes end up 500 mm apart wherever the parent puts the pair.
        assert nested == pytest.approx(
            wrapper_gltf._size(
                {
                    ocp_serialize.KEY_ASSEMBLY: [
                        node(box(10, 10, 10)),
                        node(box(10, 10, 10), location=Location([[500, 0, 0], [0, 0, 1], 0])),
                    ]
                },
                {},
                [],
            ),
            rel=1e-6,
        )

    def test_a_tree_with_no_geometry_has_no_size(self):
        assert wrapper_gltf._size({ocp_serialize.KEY_ASSEMBLY: []}, {}, []) is None

    def test_a_shape_is_decoded_once_however_often_it_appears(self):
        """The cache the two passes share: measuring must not cost a second decode."""
        shape = box(10, 10, 10)
        payload = ocp_serialize.compressed_brep(shape)
        shapes = {}
        wrapper_gltf._size(
            {
                ocp_serialize.KEY_ASSEMBLY: [
                    {ocp_serialize.KEY_BREP: payload},
                    {ocp_serialize.KEY_BREP: payload},
                    {ocp_serialize.KEY_BREP: payload},
                ]
            },
            shapes,
            [],
        )
        assert len(shapes) == 1


class TestSharing:
    """One entry per distinct geometry, however many nodes are made of it."""

    @staticmethod
    def convert(tree, monkeypatch, tolerance=0.1, angular=0.4):
        """'_convert' with the tessellation stubbed: the sharing is what is under test.

        The stub returns the BREP's own bytes, so an entry can be matched back to
        the shape it came from without a CAD kernel in the loop.
        """
        monkeypatch.setattr(wrapper_gltf, "_to_glb", lambda shape, *_: ocp_serialize.shape_to_brep(shape))
        errors, geometry = [], {}
        converted = wrapper_gltf._convert(tree, tolerance, angular, errors, {}, geometry, set())
        return converted, geometry, errors

    def test_one_shape_placed_many_times_is_one_entry(self, monkeypatch):
        payload = ocp_serialize.compressed_brep(box(10, 10, 10))
        tree = {
            ocp_serialize.KEY_ASSEMBLY: [
                {ocp_serialize.KEY_BREP: payload, "name": "bolt-%d" % index} for index in range(100)
            ]
        }
        converted, geometry, errors = self.convert(tree, monkeypatch)

        assert errors == []
        assert len(geometry) == 1
        children = converted[ocp_serialize.KEY_ASSEMBLY]
        assert len(children) == 100
        # Every node names that one entry, and none of them carries a copy.
        assert {child[ocp_serialize.KEY_GLTF_REF] for child in children} == set(geometry)
        assert all(ocp_serialize.KEY_GLTF not in child for child in children)
        assert all(ocp_serialize.KEY_BREP not in child for child in children)
        # The names are the nodes' own: what is shared is geometry, not identity.
        assert [child["name"] for child in children][:2] == ["bolt-0", "bolt-1"]

    def test_different_shapes_are_different_entries(self, monkeypatch):
        tree = {
            ocp_serialize.KEY_ASSEMBLY: [
                node(box(10, 10, 10)),
                node(box(20, 10, 10)),
                node(box(10, 10, 10)),
            ]
        }
        converted, geometry, _ = self.convert(tree, monkeypatch)

        refs = [child[ocp_serialize.KEY_GLTF_REF] for child in converted[ocp_serialize.KEY_ASSEMBLY]]
        assert len(geometry) == 2
        assert refs[0] == refs[2] != refs[1]

    def test_a_placement_does_not_make_a_shape_a_different_shape(self, monkeypatch):
        """Which is what makes the sharing possible: placements are not in geometry."""
        payload = ocp_serialize.compressed_brep(box(10, 10, 10))
        tree = {
            ocp_serialize.KEY_ASSEMBLY: [
                {ocp_serialize.KEY_BREP: payload},
                {
                    ocp_serialize.KEY_BREP: payload,
                    ocp_serialize.KEY_LOCATION: Location([[50, 0, 0], [0, 0, 1], 0]).as_packed(),
                },
            ]
        }
        converted, geometry, _ = self.convert(tree, monkeypatch)

        assert len(geometry) == 1
        first, second = converted[ocp_serialize.KEY_ASSEMBLY]
        assert first[ocp_serialize.KEY_GLTF_REF] == second[ocp_serialize.KEY_GLTF_REF]
        # And the one that was placed still says where it sits.
        assert ocp_serialize.KEY_LOCATION not in first
        assert second[ocp_serialize.KEY_LOCATION][0] == [50, 0, 0]

    def test_geometry_anywhere_in_the_structure_is_converted(self, monkeypatch):
        """Including the sketches a port is drawn with, which are not nodes.

        The walk is of the whole structure rather than of the places geometry is
        known to sit, so that the day the core adds another it is not left handing
        a browser BREP.
        """
        tree = {
            ocp_serialize.KEY_BREP: ocp_serialize.compressed_brep(box(10, 10, 10)),
            "sketches": {"//pkg:m3": node(box(3, 3, 0.1))},
        }
        converted, geometry, _ = self.convert(tree, monkeypatch)

        assert len(geometry) == 2
        assert ocp_serialize.KEY_GLTF_REF in converted
        assert ocp_serialize.KEY_GLTF_REF in converted["sketches"]["//pkg:m3"]
        assert ocp_serialize.KEY_BREP not in converted["sketches"]["//pkg:m3"]

    def test_a_shape_that_will_not_tessellate_is_reported_once(self, monkeypatch):
        """Once per distinct shape, not once per node that names it.

        A hundred instances of one unmeshable part are one thing wrong, and a
        hundred lines about it would bury whatever else the show had to say.
        """
        payload = ocp_serialize.compressed_brep(box(10, 10, 10))

        def boom(*_):
            raise Exception("no triangles here")

        monkeypatch.setattr(wrapper_gltf, "_to_glb", boom)
        errors, geometry = [], {}
        failed = set()
        tree = {ocp_serialize.KEY_ASSEMBLY: [{ocp_serialize.KEY_BREP: payload, "name": "a"} for _ in range(5)]}
        converted = wrapper_gltf._convert(tree, 0.1, 0.4, errors, {}, geometry, failed)

        assert len(errors) == 1
        assert geometry == {}
        # Every node keeps its place and simply has nothing to draw.
        for child in converted[ocp_serialize.KEY_ASSEMBLY]:
            assert ocp_serialize.KEY_GLTF_REF not in child
            assert child["name"] == "a"

    def test_the_table_is_on_the_root_of_what_comes_back(self, monkeypatch):
        monkeypatch.setattr(wrapper_gltf, "_to_glb", lambda shape, *_: b"glTF-stub")
        result = wrapper_gltf.process({"tree": node(box(10, 10, 10)), "screenDivisor": 2000.0})

        assert result["success"] is True
        assert list(result["tree"][ocp_serialize.KEY_GEOMETRY]) == [result["tree"][ocp_serialize.KEY_GLTF_REF]]
        # And it says what it chose, which is the number that decides all of this.
        assert result["tolerance"] == pytest.approx(result["size"] / 2000.0)
        assert result["angularTolerance"] == 0.4


class TestDigest:
    """What names an entry of that table."""

    def test_the_same_geometry_is_the_same_name(self):
        """Content and not identity: nodes arrive as separately parsed dicts.

        Two nodes built from one cached shape are two dicts holding equal bytes,
        never one object, so anything keyed on identity would share nothing.
        """
        payload = ocp_serialize.compressed_brep(box(10, 10, 10))
        assert ocp_serialize.payload_digest(payload) == ocp_serialize.payload_digest(bytes(payload))

    def test_different_geometry_is_a_different_name(self):
        assert ocp_serialize.payload_digest(
            ocp_serialize.compressed_brep(box(10, 10, 10))
        ) != ocp_serialize.payload_digest(ocp_serialize.compressed_brep(box(20, 10, 10)))


class TestDeflectionTakesEffect:
    """The arrangement the absolute deflection rests on, checked against OCCT.

    'export_gltf' meshes what it is given unless a fine enough triangulation is
    already there, and passes OCCT a *relative* deflection when it does. The
    wrapper therefore meshes first, absolutely, and tells the exporter to leave it
    alone -- so the test of that is whether the triangle count still answers to the
    tolerance. Nothing else would notice it stopping: the preview would simply be
    coarse, or enormous, at every setting.
    """

    def cylinder_triangles(self, tolerance):
        shape = BRepPrimAPI_MakeCylinder(10.0, 20.0).Shape()
        return triangles(wrapper_gltf._to_glb(shape, tolerance, 1.0))

    def test_a_finer_tolerance_is_a_finer_mesh(self):
        # A loose angular cap, so that what is measured is the linear budget: it is
        # the term that scales with the object, and the one meshed here by hand.
        coarse = self.cylinder_triangles(2.0)
        fine = self.cylinder_triangles(0.02)
        assert coarse > 0
        assert fine > coarse * 2

    def test_the_tolerance_is_a_distance_and_not_a_fraction(self):
        """Absolute mm, which is what makes the budget mean a fraction of a pixel.

        Asked both ways of the same number, which is the only way to tell which
        meaning survived: 0.02 as a fraction of each edge of a cylinder of radius 10
        is coarser than 0.02 mm by orders of magnitude, so if 'export_gltf' had
        re-meshed relatively the two readings would be the other way round.
        """
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.BRepTools import BRepTools

        shape = BRepPrimAPI_MakeCylinder(10.0, 20.0).Shape()

        # 0.02 read as a fraction of each edge, produced by hand and exported as it
        # is - which is also what proves '_export' meshes nothing of its own.
        BRepTools.Clean_s(shape)
        BRepMesh_IncrementalMesh(shape, 0.02, True, 1.0, True)
        as_fraction = triangles(wrapper_gltf._export(shape, 1.0))

        # The same number through the wrapper, where it is millimetres.
        as_distance = triangles(wrapper_gltf._to_glb(shape, 0.02, 1.0))

        assert as_fraction > 0
        assert as_distance > as_fraction * 2
