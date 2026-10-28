#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A cross-section: what is kept of an object cut by a box, and where.

The cut is done in each node's own frame, with the box taken there through every
placement above it, so the thing worth pinning is that the *placed* geometry is
what the box keeps: a part moved 100 mm along X and cut at x = 105 keeps five
millimetres of itself, not none. The rest is the bookkeeping that makes a cut
tree the same tree - the nodes, their names and placements, and what each says
about its size - and that skips the boolean wherever the box does not cross a
node at all.
"""

import asyncio
import os
import sys

import pytest
from OCP.BRepGProp import BRepGProp
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.GProp import GProp_GProps

import partcad as pc
from partcad import runtime, shape_envelope, shape_gltf, shape_section
from partcad.geom import Location

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import ocp_serialize  # noqa: E402
import wrapper_gltf  # noqa: E402
import wrapper_section  # noqa: E402


def box(dx=10.0, dy=10.0, dz=10.0):
    return BRepPrimAPI_MakeBox(dx, dy, dz).Shape()


def node(shape, location=None, children=None, **extra):
    """A BREP-form node, as the core hands one to a wrapper."""
    entry = dict(extra)
    if shape is not None:
        entry[ocp_serialize.KEY_BREP] = ocp_serialize.compressed_brep(shape)
    if location is not None:
        entry[ocp_serialize.KEY_LOCATION] = location.as_packed()
    if children is not None:
        entry[ocp_serialize.KEY_ASSEMBLY] = list(children)
    return entry


def volume(entry) -> float:
    """The volume of a node's own geometry, in its own frame."""
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(ocp_serialize.shape_from_payload(entry[ocp_serialize.KEY_BREP]), props)
    return props.Mass()


def cut(tree, section, keep_empty=True):
    errors = []
    result = wrapper_section.section_tree(tree, section, errors, keep_empty=keep_empty)
    assert errors == []
    return result


class TestNormalize:
    def test_nothing_is_no_section(self):
        assert shape_section.normalize(None) is None
        assert shape_section.normalize({}) is None
        assert shape_section.normalize({"x": None, "y": None, "z": None}) is None

    def test_only_the_axes_that_cut_are_kept_as_floats(self):
        assert shape_section.normalize({"x": [0, 25], "y": None, "z": (1, 2.5)}) == {
            "x": [0.0, 25.0],
            "z": [1.0, 2.5],
        }

    @pytest.mark.parametrize(
        "section",
        [
            [0, 1],
            {"w": [0, 1]},
            {"x": "12"},
            {"x": [1]},
            {"x": [0, 1, 2]},
            {"x": ["a", 1]},
            {"x": [0, float("inf")]},
            {"x": [5, 5]},
            {"x": [6, 5]},
        ],
    )
    def test_what_is_not_a_section_is_refused(self, section):
        with pytest.raises(ValueError):
            shape_section.normalize(section)

    def test_describe(self):
        assert shape_section.describe(None) == "nothing cut"
        assert shape_section.describe({"z": [0.0, 12.5], "x": [0.0, 25.0]}) == "x 0..25, z 0..12.5"


class TestClassify:
    def test_a_node_the_box_does_not_reach_is_outside(self):
        assert wrapper_section.classify((0, 0, 0), (10, 10, 10), [(20, 30), None, None]) == "outside"

    def test_a_node_inside_on_every_cut_axis_is_inside(self):
        assert wrapper_section.classify((0, 0, 0), (10, 10, 10), [(-1, 11), None, (-5, 50)]) == "inside"

    def test_a_node_the_boundary_crosses_is_cut(self):
        assert wrapper_section.classify((0, 0, 0), (10, 10, 10), [None, (2, 50), None]) == "cut"

    def test_the_cutter_reaches_past_the_node_where_nothing_is_cut(self):
        low, high = wrapper_section.cutter((0, 0, 0), (10, 10, 10), [(2, 5), None, None])
        assert low[0] == 2 and high[0] == 5
        assert low[1] < 0 and high[1] > 10
        assert low[2] < 0 and high[2] > 10


class TestSectionTree:
    def test_a_section_that_cuts_nothing_hands_the_tree_back(self):
        tree = node(box())
        assert wrapper_section.section_tree(tree, None, []) is tree
        assert wrapper_section.section_tree(tree, {}, []) is tree

    def test_a_part_is_cut_to_the_slab_it_keeps(self):
        result = cut(node(box(), name="pkg:cube"), {"x": [2.0, 5.0]})
        assert result["name"] == "pkg:cube"
        assert volume(result) == pytest.approx(3 * 10 * 10, rel=1e-6)

    def test_the_box_is_in_the_frame_of_the_root_not_of_the_node(self):
        # A cube from 100 to 110 along X once placed: a cut at 105..200 keeps
        # half of it, and the half is still in the node's own frame (5..10),
        # with the node's placement going on placing it.
        placed = Location([[100, 0, 0], [0, 0, 1], 0])
        tree = node(None, children=[node(box(), location=placed, label="cube")])
        result = cut(tree, {"x": [105.0, 200.0]})
        child = result[ocp_serialize.KEY_ASSEMBLY][0]
        assert child[ocp_serialize.KEY_LOCATION] == placed.as_packed()
        assert volume(child) == pytest.approx(5 * 10 * 10, rel=1e-6)
        low, high = wrapper_section._bounds(ocp_serialize.shape_from_payload(child[ocp_serialize.KEY_BREP]))
        assert low[0] == pytest.approx(5.0, abs=1e-3)
        assert high[0] == pytest.approx(10.0, abs=1e-3)

    def test_a_rotation_above_the_node_is_composed_too(self):
        # Turned a quarter about Z, the cube's own X runs along the root's Y:
        # cutting the root's Y to 0..4 keeps four tenths of the cube.
        turned = Location([[0, 0, 0], [0, 0, 1], 90])
        tree = node(None, location=turned, children=[node(box(), label="cube")])
        result = cut(tree, {"y": [0.0, 4.0]})
        assert volume(result[ocp_serialize.KEY_ASSEMBLY][0]) == pytest.approx(4 * 10 * 10, rel=1e-6)

    def test_a_node_wholly_inside_is_not_touched(self):
        tree = node(None, children=[node(box(), label="a")])
        payload = tree[ocp_serialize.KEY_ASSEMBLY][0][ocp_serialize.KEY_BREP]
        result = cut(tree, {"z": [-5.0, 50.0]})
        assert result[ocp_serialize.KEY_ASSEMBLY][0][ocp_serialize.KEY_BREP] is payload

    def test_a_node_wholly_outside_keeps_its_place_with_nothing_in_it(self):
        far = Location([[500, 0, 0], [0, 0, 1], 0])
        tree = node(None, children=[node(box(), label="near"), node(box(), location=far, label="far")])
        result = cut(tree, {"x": [0.0, 20.0]})
        near, gone = result[ocp_serialize.KEY_ASSEMBLY]
        assert near["label"] == "near" and gone["label"] == "far"
        assert wrapper_section._is_empty(ocp_serialize.shape_from_payload(gone[ocp_serialize.KEY_BREP]))
        assert gone[ocp_serialize.KEY_LOCATION] == far.as_packed()

        dropped = cut(tree, {"x": [0.0, 20.0]}, keep_empty=False)
        assert ocp_serialize.KEY_BREP not in dropped[ocp_serialize.KEY_ASSEMBLY][1]

    def test_what_a_node_says_about_itself_is_left_as_it_was(self):
        metadata = {"measurements": {"bbox": [0, 0, 0, 10, 10, 10]}}
        result = cut(node(box(), metadata=metadata, properties={"color": "#ff0000"}), {"x": [0.0, 5.0]})
        assert result["metadata"] == metadata
        assert result["properties"] == {"color": "#ff0000"}

    def test_the_sketches_beside_the_nodes_are_not_cut(self):
        sketches = {"//pkg:hole": node(box(1, 1, 1))}
        tree = node(box(), **{shape_envelope.KEY_SKETCHES: sketches})
        result = cut(tree, {"x": [50.0, 60.0]})
        assert result[shape_envelope.KEY_SKETCHES] is sketches

    def test_a_node_that_will_not_cut_is_left_whole_and_said(self):
        errors = []
        tree = {"label": "broken", ocp_serialize.KEY_BREP: "not a payload"}
        result = wrapper_section.section_tree(tree, {"x": [0.0, 1.0]}, errors)
        assert result[ocp_serialize.KEY_BREP] == "not a payload"
        assert len(errors) == 1 and errors[0].startswith("broken: ")

    def test_a_node_with_nothing_in_it_is_left_as_it_is(self):
        empty = node(ocp_serialize.compound_of([]), label="empty")
        result = cut(node(None, children=[empty]), {"x": [0.0, 5.0]})
        assert result[ocp_serialize.KEY_ASSEMBLY][0][ocp_serialize.KEY_BREP] == empty[ocp_serialize.KEY_BREP]

    def test_what_is_not_a_node_among_the_children_is_passed_through(self):
        result = cut(node(None, children=[node(box()), "not a node"]), {"x": [0.0, 5.0]})
        assert result[ocp_serialize.KEY_ASSEMBLY][1] == "not a node"

    def test_the_wrapper_answers_with_the_cut_tree_and_what_would_not_cut(self):
        answer = wrapper_section.process({"tree": node(box()), "section": {"x": [0.0, 5.0]}})
        assert answer["success"] is True and answer["errors"] == []
        assert volume(answer["tree"]) == pytest.approx(500.0)
        with pytest.raises(Exception, match="No shape tree to cut"):
            wrapper_section.process({"section": {"x": [0.0, 5.0]}})


class TestGltf:
    def test_the_gltf_wrapper_cuts_before_it_tessellates(self):
        far = Location([[500, 0, 0], [0, 0, 1], 0])
        tree = node(None, children=[node(box(), label="near"), node(box(), location=far, label="far")])
        whole = wrapper_gltf.process({"tree": tree, "tolerance": 0.1})
        assert len(whole["tree"][ocp_serialize.KEY_GEOMETRY]) == 1
        assert all(ocp_serialize.KEY_GLTF_REF in child for child in whole["tree"][ocp_serialize.KEY_ASSEMBLY])

        cut_tree = wrapper_gltf.process({"tree": tree, "tolerance": 0.1, "section": {"x": [0.0, 5.0]}})
        assert cut_tree["section"] == {"x": [0.0, 5.0]}
        assert cut_tree["errors"] == []
        near, gone = cut_tree["tree"][ocp_serialize.KEY_ASSEMBLY]
        # Half the near cube is a different shape from the whole one, and the
        # far one has nothing left to draw - and is not reported as a failure.
        assert ocp_serialize.KEY_GLTF_REF in near
        assert ocp_serialize.KEY_GLTF_REF not in gone
        assert near[ocp_serialize.KEY_GLTF_REF] not in whole["tree"][ocp_serialize.KEY_GEOMETRY]


class InProcessSandbox:
    """A Python runtime that runs the wrapper it is asked for here, in this process.

    On the request as it would travel - serialized, payload table and all, and
    read back as the wrapper reads it - and answering as the wrapper answers, so
    what is under test is everything on the core's side of the pipe.
    'answer', when given, is what the sandbox says instead: an exit code, what
    it wrote and what it complained of.
    """

    WRAPPERS = {"wrapper_section.py": wrapper_section, "wrapper_gltf.py": wrapper_gltf}

    def __init__(self, answer=None):
        self.answer = answer
        self.ensured = []
        self.requests = []

    async def ensure_async(self, requirement):
        self.ensured.append(requirement)

    async def run_async(self, argv, stdin):
        name = os.path.basename(argv[0])
        request = ocp_serialize.deserialize_raw(runtime.stdin_bytes(stdin).decode("utf-8"))
        self.requests.append((name, request))
        if self.answer is not None:
            return self.answer
        return 0, ocp_serialize.serialize(self.WRAPPERS[name].process(request), share=True), ""


class SandboxContext:
    """The little of a context the core asks for to cut a tree: a runtime, and no cache."""

    cache_artifacts = None

    def __init__(self, sandbox):
        self.sandbox = sandbox

    def get_python_runtime(self, version=None):
        return self.sandbox


class TestSectionAsync:
    def test_the_tree_is_cut_in_the_sandbox_and_handed_back_in_the_cores_form(self):
        sandbox = InProcessSandbox()
        tree = node(None, children=[node(box(), label="cube")], name="pkg:assy")
        result = asyncio.run(shape_section.section_async(SandboxContext(sandbox), tree, {"x": [0, 5]}))
        assert sandbox.ensured == list(shape_section._DEPENDENCIES)
        [(wrapper_name, request)] = sandbox.requests
        assert wrapper_name == "wrapper_section.py"
        assert request["section"] == {"x": [0.0, 5.0]}
        assert result["name"] == "pkg:assy"
        assert volume(result[ocp_serialize.KEY_ASSEMBLY][0]) == pytest.approx(500.0)

    def test_nothing_to_cut_starts_no_sandbox(self):
        sandbox = InProcessSandbox()
        tree = node(box())
        assert asyncio.run(shape_section.section_async(SandboxContext(sandbox), tree, None)) is tree
        assert asyncio.run(shape_section.section_async(SandboxContext(sandbox), None, {"x": [0, 5]})) is None
        assert sandbox.requests == []

    def test_a_context_and_a_tree_are_required(self):
        with pytest.raises(ValueError, match="context is required"):
            asyncio.run(shape_section.section_async(None, node(box()), {"x": [0, 5]}))
        with pytest.raises(ValueError, match="Not a shape tree"):
            asyncio.run(shape_section.section_async(SandboxContext(InProcessSandbox()), {"a": 1}, {"x": [0, 5]}))

    @pytest.mark.parametrize(
        "answer, message",
        [
            ((1, "", ""), "Failed to cut the shape tree"),
            ((0, "", "Traceback: it broke"), "it broke"),
            ((0, ocp_serialize.serialize({"success": False, "exception": "no kernel"}), ""), "no kernel"),
            ((0, ocp_serialize.serialize({"success": True, "tree": None}), ""), "produced no shape tree"),
        ],
    )
    def test_a_sandbox_that_did_not_cut_is_a_failure(self, answer, message):
        with pytest.raises(Exception, match=message):
            asyncio.run(
                shape_section.section_async(SandboxContext(InProcessSandbox(answer)), node(box()), {"x": [0, 5]})
            )

    def test_a_node_that_would_not_cut_is_warned_about_and_shown_whole(self, monkeypatch):
        warnings = []
        monkeypatch.setattr(shape_section.pc_logging, "warning", warnings.append)
        tree = node(None, children=[{"label": "broken", ocp_serialize.KEY_BREP: b"not a payload"}])
        result = asyncio.run(shape_section.section_async(SandboxContext(InProcessSandbox()), tree, {"x": [0, 5]}))
        assert result[ocp_serialize.KEY_ASSEMBLY][0]["label"] == "broken"
        assert len(warnings) == 1 and "x 0..5" in warnings[0] and "broken: " in warnings[0]

    def test_a_tree_asked_for_in_either_form_is_cut_first(self):
        sandbox = InProcessSandbox()
        context = SandboxContext(sandbox)
        tree = node(box(), label="cube")
        brep = asyncio.run(shape_gltf.in_form_async(context, tree, shape_envelope.FORM_BREP, section={"z": [0, 5]}))
        assert volume(brep) == pytest.approx(500.0)
        assert asyncio.run(shape_gltf.in_form_async(context, tree, shape_envelope.FORM_BREP)) is tree

        gltf = asyncio.run(shape_gltf.in_form_async(context, tree, shape_envelope.FORM_GLTF, section={"z": [0, 5]}))
        # One sandbox cuts and tessellates: the section goes with the tree.
        assert [name for name, _ in sandbox.requests] == ["wrapper_section.py", "wrapper_gltf.py"]
        assert sandbox.requests[-1][1]["section"] == {"z": [0.0, 5.0]}
        assert ocp_serialize.KEY_GLTF_REF in gltf
