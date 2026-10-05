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
from partcad import shape_envelope, shape_gltf
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


def vertices(glb: bytes) -> int:
    """How many vertices a binary glTF holds, read off its POSITION accessors."""
    length = struct.unpack("<I", glb[12:16])[0]
    meta = json.loads(glb[20 : 20 + length])
    accessors = meta.get("accessors", [])
    return sum(
        accessors[primitive["attributes"]["POSITION"]]["count"]
        for mesh in meta.get("meshes", [])
        for primitive in mesh.get("primitives", [])
        if "POSITION" in primitive.get("attributes", {})
    )


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


def measured(bbox, location=None, children=None, **extra):
    """A node carrying the box it recorded when it was built, and nothing else.

    Which is all 'size_of' reads: no geometry, no kernel. Every shape a wrapper
    returned carries this (see 'ocp_serialize.encode_shape').
    """
    entry = dict(extra)
    if bbox is not None:
        entry[shape_envelope.KEY_METADATA] = {
            shape_envelope.METADATA_MEASUREMENTS: {shape_envelope.METADATA_BBOX: list(bbox)}
        }
    if location is not None:
        entry[shape_envelope.KEY_LOCATION] = location.as_packed()
    if children is not None:
        entry[shape_envelope.KEY_ASSEMBLY] = list(children)
    return entry


class TestSize:
    """What the budget is a fraction *of*: the whole tree, where it sits.

    Read from what each shape recorded as it was built rather than measured again,
    so none of this needs a CAD kernel - which is the point. Two answers to "how big
    is it" is what a second measurement would be.
    """

    def test_a_single_shape_is_measured_as_itself(self):
        assert shape_gltf.size_of(measured([0, 0, 0, 10, 10, 10])) == pytest.approx(3**0.5 * 10)

    def test_the_placements_are_composed_down_the_tree(self):
        """Eight parts 10 mm across are 10 mm stacked and metres apart spread out.

        The same geometry, the same nodes, and a deflection that has to differ by
        that factor - so a walk that ignored the placements would size a large
        assembly as if it were one of its parts.
        """
        together = shape_gltf.size_of(
            {
                shape_envelope.KEY_ASSEMBLY: [
                    measured([0, 0, 0, 10, 10, 10]),
                    measured([0, 0, 0, 10, 10, 10]),
                ]
            }
        )
        apart = shape_gltf.size_of(
            {
                shape_envelope.KEY_ASSEMBLY: [
                    measured([0, 0, 0, 10, 10, 10]),
                    measured([0, 0, 0, 10, 10, 10], location=Location([[1000, 0, 0], [0, 0, 1], 0])),
                ]
            }
        )
        assert together == pytest.approx(3**0.5 * 10)
        assert apart == pytest.approx((1010.0**2 + 10**2 + 10**2) ** 0.5)

    def test_a_placement_on_a_parent_reaches_its_children(self):
        """Composed placement first then the node's own, as 'placed()' states it."""
        spread = [
            measured([0, 0, 0, 10, 10, 10]),
            measured([0, 0, 0, 10, 10, 10], location=Location([[500, 0, 0], [0, 0, 1], 0])),
        ]
        moved = shape_gltf.size_of(
            {
                shape_envelope.KEY_LOCATION: Location([[70, 0, 0], [0, 0, 1], 0]).as_packed(),
                shape_envelope.KEY_ASSEMBLY: spread,
            }
        )
        # Wherever the parent puts the pair, the pair is the same size.
        assert moved == pytest.approx(shape_gltf.size_of({shape_envelope.KEY_ASSEMBLY: spread}))

    def test_a_rotated_box_is_re_bounded_rather_than_moved(self):
        """Its eight corners are placed, because its two extremes are not its extent.

        A 10 mm cube turned 45 degrees about Z spans 10*sqrt(2) across X and Y, and
        moving only (min, max) would report it as still 10 - under-stating the size
        and so over-tessellating everything in the tree.
        """
        turned = shape_gltf.size_of(measured([0, 0, 0, 10, 10, 10], location=Location([[0, 0, 0], [0, 0, 1], 45])))
        assert turned == pytest.approx(((10 * 2**0.5) ** 2 + (10 * 2**0.5) ** 2 + 100) ** 0.5)
        # Over-stated rather than under-stated, which is the safe direction.
        assert turned > shape_gltf.size_of(measured([0, 0, 0, 10, 10, 10]))

    def test_a_tree_that_recorded_nothing_has_no_size(self):
        assert shape_gltf.size_of({shape_envelope.KEY_ASSEMBLY: []}) is None
        assert shape_gltf.size_of(measured(None)) is None

    def test_a_node_that_recorded_nothing_is_passed_over(self):
        """One stripped node does not cost the tree the sizes the others recorded."""
        size = shape_gltf.size_of(
            {
                shape_envelope.KEY_ASSEMBLY: [
                    measured(None, location=Location([[9000, 0, 0], [0, 0, 1], 0])),
                    measured([0, 0, 0, 10, 10, 10]),
                ]
            }
        )
        assert size == pytest.approx(3**0.5 * 10)


class TestTolerance:
    """The budget, applied: what deflection a tree is tessellated at, in mm."""

    def test_it_is_a_fraction_of_the_size_of_what_is_shown(self):
        """Which is the whole point: a preview is looked at as a whole.

        A part 10 mm across and an assembly 10 m across want the same answer to
        "is this smooth enough" and deflections a thousand apart to get it.
        """
        small = shape_gltf.tolerance_for(measured([0, 0, 0, 10, 10, 10]))
        large = shape_gltf.tolerance_for(measured([0, 0, 0, 10000, 10000, 10000]))
        assert large == pytest.approx(small * 1000)
        assert small == pytest.approx(3**0.5 * 10 / shape_gltf.SCREEN_DIVISOR)

    def test_it_is_clamped_at_both_ends(self):
        """The floor is for a tiny object, the ceiling for a bogus bounding box.

        Without the floor a speck would be tessellated to a nanometre for a gain no
        screen can show; without the ceiling one stray node a kilometre from the
        origin would flatten everything else into facets.
        """
        assert shape_gltf.tolerance_for(measured([0, 0, 0, 0.0001, 0.0001, 0.0001])) == pytest.approx(
            shape_gltf.MIN_TOLERANCE
        )
        assert shape_gltf.tolerance_for(measured([0, 0, 0, 1e9, 1e9, 1e9])) == pytest.approx(shape_gltf.MAX_TOLERANCE)

    def test_a_tree_of_unknown_size_gets_the_nominal_one(self):
        """Not the floor: the finest setting there is, for the least known tree.

        A tree records no size when it has no geometry - an interface whose ports
        carry no boundary, where the tolerance decides nothing - or when its
        metadata was stripped, where guessing palm-sized beats guessing microscopic.
        """
        assert shape_gltf.tolerance_for({shape_envelope.KEY_ASSEMBLY: []}) == pytest.approx(
            shape_gltf.NOMINAL_SIZE / shape_gltf.SCREEN_DIVISOR
        )

    def test_the_budget_is_half_a_pixel_of_a_thousand(self):
        """The two numbers the divisor is made of, so it cannot drift from them."""
        assert shape_gltf.SCREEN_DIVISOR == shape_gltf.SCREEN_PIXELS / shape_gltf.PIXEL_BUDGET


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
        result = wrapper_gltf.process({"tree": node(box(10, 10, 10)), "tolerance": 0.2})

        assert result["success"] is True
        assert list(result["tree"][ocp_serialize.KEY_GEOMETRY]) == [result["tree"][ocp_serialize.KEY_GLTF_REF]]


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


def line_primitives(glb: bytes) -> list:
    """The 'LINES' primitives of a binary glTF, each as its list of (x, y, z) positions."""
    meta, binary = wrapper_gltf._read_glb(glb)
    accessors, views = meta.get("accessors", []), meta.get("bufferViews", [])
    found = []
    for mesh in meta.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            if primitive.get("mode") != 1:
                continue
            accessor = accessors[primitive["attributes"]["POSITION"]]
            view = views[accessor["bufferView"]]
            start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
            values = struct.unpack_from("<%df" % (accessor["count"] * 3), binary, start)
            found.append([tuple(values[i : i + 3]) for i in range(0, len(values), 3)])
    return found


def edge(start, end):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    from OCP.gp import gp_Pnt

    return BRepBuilderAPI_MakeEdge(gp_Pnt(*start), gp_Pnt(*end)).Edge()


class TestEdges:
    """What becomes of the edges that bound no face.

    A sketch of open lines - the bend lines of a sheet metal drawing - has no face,
    so it has no triangles, and export_gltf writes nothing for it. It is drawn all
    the same, as glTF line segments, or the viewer shows nothing where the drawing
    has something to say.
    """

    def test_a_sketch_of_lines_alone_is_drawn_as_lines(self):
        shape = ocp_serialize.compound_of([edge((30, 0, 0), (30, 40, 0)), edge((80, 0, 0), (80, 40, 0))])
        glb = wrapper_gltf._to_glb(shape, 0.1, 0.4)

        assert triangles(glb) == 0
        (segments,) = line_primitives(glb)
        # Two straight edges are two segments, which is four positions.
        assert len(segments) == 4

    def test_the_lines_are_in_the_frame_the_triangles_are_in(self):
        """Metres, and Y up: what export_gltf does to a face, done to a line.

        PartCAD's (30, 40, 0) mm is glTF's (0.03, 0, -0.04) m. The viewer converts
        neither, so a line left in millimetres would be drawn a thousand times too
        big and lying on its side beside a face that is not.
        """
        glb = wrapper_gltf._to_glb(edge((0, 0, 0), (30, 40, 0)), 0.1, 0.4)
        (segments,) = line_primitives(glb)
        assert segments[0] == pytest.approx((0.0, 0.0, 0.0))
        assert segments[1] == pytest.approx((0.03, 0.0, -0.04))

    def test_a_curve_is_drawn_to_the_tolerance(self):
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
        from OCP.gp import gp_Ax2, gp_Circ, gp_Dir, gp_Pnt

        circle = BRepBuilderAPI_MakeEdge(gp_Circ(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 10.0)).Edge()
        coarse = line_primitives(wrapper_gltf._to_glb(circle, 1.0, 1.0))[0]
        fine = line_primitives(wrapper_gltf._to_glb(circle, 0.01, 1.0))[0]
        assert len(coarse) >= 6
        assert len(fine) > len(coarse) * 2

    def test_a_solid_is_not_drawn_as_a_wireframe(self):
        """The edges of a face are the face's outline, and are not added again."""
        assert line_primitives(wrapper_gltf._to_glb(box(), 0.1, 0.4)) == []

    def test_lines_beside_a_face_are_drawn_once(self):
        """The exporter draws free edges beside a face itself; they are not added twice."""
        shape = ocp_serialize.compound_of([box(), edge((0, 0, 20), (10, 0, 20))])
        glb = wrapper_gltf._to_glb(shape, 0.1, 0.4)

        assert triangles(glb) > 0
        assert sum(len(segments) for segments in line_primitives(glb)) == 2

    def test_a_node_of_lines_alone_gets_its_geometry(self):
        errors, geometry = [], {}
        tree = node(ocp_serialize.compound_of([edge((0, 0, 0), (10, 0, 0))]), name="bends")
        converted = wrapper_gltf._convert(tree, 0.1, 0.4, errors, {}, geometry, set())

        assert errors == []
        assert list(geometry) == [converted[ocp_serialize.KEY_GLTF_REF]]

    def test_what_the_drawing_says_about_its_lines_goes_with_them(self):
        """The metadata is not geometry, so it is carried through untouched.

        It is what the viewer pins to the lines - the angle and direction of each
        bend - so a tessellation that dropped it would leave the lines unlabelled.
        """
        annotations = [{"points": [[0.0, 0.0, 0.0], [10.0, 0.0, 0.0]], "metadata": {"angle": "90"}}]
        tree = node(
            ocp_serialize.compound_of([edge((0, 0, 0), (10, 0, 0))]),
            metadata=ocp_serialize.make_metadata(annotations=annotations),
        )
        converted = wrapper_gltf._convert(tree, 0.1, 0.4, [], {}, {}, set())

        assert converted[ocp_serialize.KEY_METADATA][ocp_serialize.METADATA_ANNOTATIONS] == annotations


def primitives(glb: bytes) -> int:
    """How many primitives a binary glTF holds - which is how many draw calls it is.

    A glTF loader makes one mesh per primitive and a mesh is a draw call, so this is
    the number that decides whether an assembly can be orbited.
    """
    length = struct.unpack("<I", glb[12:16])[0]
    meta = json.loads(glb[20 : 20 + length])
    return sum(len(mesh.get("primitives", [])) for mesh in meta.get("meshes", []))


class TestOnePrimitivePerShape:
    """What makes a large assembly drawable: a draw call per shape, not per face.

    OCCT writes a primitive per face unless asked otherwise, and asking means
    driving its writer directly rather than through 'build123d.export_gltf' - which
    reaches for a private helper of build123d's. These are the tests that fail if
    that helper moves, loudly, instead of leaving a preview that is merely slow.
    """

    def drilled(self):
        """A plate with four holes: faces enough that per-face is visibly different."""
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
        from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

        solid = BRepPrimAPI_MakeBox(60.0, 40.0, 5.0).Shape()
        for x, y in ((10, 10), (50, 10), (10, 30), (50, 30)):
            hole = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(x, y, -1.0), gp_Dir(0, 0, 1)), 3.0, 7.0).Shape()
            solid = BRepAlgoAPI_Cut(solid, hole).Shape()
        return solid

    def test_a_shape_of_many_faces_is_one_primitive(self):
        glb = wrapper_gltf._to_glb(self.drilled(), 0.05, 0.4)
        assert primitives(glb) == 1

    def test_the_merge_loses_no_geometry(self):
        """Concatenated, not welded: the same triangles over the same vertices.

        Welding would smooth the hard edges of every part in the viewer, which is a
        change nobody asked for and one that no triangle count would reveal - hence
        the vertices here as well as the triangles.
        """
        shape = self.drilled()
        wrapper_gltf._mesh(shape, 0.05, 0.4)
        merged = wrapper_gltf._export(shape, 0.4)

        # Meshed again, because '_export' frees the triangulation it wrote out -
        # which is also why it documents that it meshes nothing itself.
        wrapper_gltf._mesh(shape, 0.05, 0.4)
        monkey = wrapper_gltf._create_xde
        try:
            wrapper_gltf._create_xde = None
            per_face = wrapper_gltf._export(shape, 0.4)
        finally:
            wrapper_gltf._create_xde = monkey

        assert primitives(per_face) > 1, "export_gltf is expected to write a primitive per face"
        assert primitives(merged) == 1
        assert triangles(merged) == triangles(per_face)
        assert vertices(merged) == vertices(per_face)

    def test_without_the_builder_it_still_draws(self):
        """A preview that is slow to orbit beats no preview at all.

        'export_gltf' is the fallback, so a build123d that moved its document
        builder costs draw calls rather than the 3D view.
        """
        shape = self.drilled()
        monkey = wrapper_gltf._create_xde
        try:
            wrapper_gltf._create_xde = None
            glb = wrapper_gltf._to_glb(shape, 0.05, 0.4)
        finally:
            wrapper_gltf._create_xde = monkey
        assert triangles(glb) > 0
        assert primitives(glb) > 1

    def test_the_lines_of_an_open_sketch_survive_the_merge(self):
        """Faces merge into one primitive; the edges that bound none stay their own.

        They have to: a line segment is a different draw mode from a triangle, so
        merging the two would be drawing one as the other. This is the test that
        notices if 'SetMergeFaces' ever swallowed them (see '_with_lines').
        """
        from OCP.BRep import BRep_Builder
        from OCP.TopoDS import TopoDS_Compound

        compound = TopoDS_Compound()
        builder = BRep_Builder()
        builder.MakeCompound(compound)
        builder.Add(compound, BRepPrimAPI_MakeBox(10.0, 10.0, 10.0).Shape())
        builder.Add(compound, edge((0, 0, 20), (10, 10, 20)))

        glb = wrapper_gltf._to_glb(compound, 0.05, 0.4)
        assert primitives(glb) == 2
        assert len(line_primitives(glb)) == 1
        assert triangles(glb) == 12


class TestTheSandboxDoesNotDecideTheBudget:
    """It is handed millimetres, because the core already knows the size."""

    def test_a_request_with_no_tolerance_is_refused(self):
        with pytest.raises(Exception, match="tolerance"):
            wrapper_gltf.process({"tree": node(box(10, 10, 10))})

    def test_what_it_was_given_is_what_it_reports(self, monkeypatch):
        monkeypatch.setattr(wrapper_gltf, "_to_glb", lambda shape, *_: b"glTF-stub")
        result = wrapper_gltf.process({"tree": node(box(10, 10, 10)), "tolerance": 0.25})
        assert result["tolerance"] == pytest.approx(0.25)
        assert result["angularTolerance"] == pytest.approx(0.4)
