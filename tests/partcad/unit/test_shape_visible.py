#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What of a print can be seen: 'wrappers/wrapper_visible.py', and 'shape_visible' in front of it.

On real deposits, made in this process by '//builtin/cam''s own 'cam_gcode' (as
'test_cam_materialize.py' makes them) from real build123d solids: a print is a
compound of prisms, a wall ring with the infill's space as its hole and the
infill's lines as islands in it, and what is pinned here is which of their faces
are kept - the outside of the print whole, what a cut opens when it is cut - and
that nothing that is not a print is touched.
"""

import asyncio
import importlib.util
import os
import sys

import build123d as b3d
import pytest
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Plane
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS

import partcad as pc
from partcad import runtime, shape_envelope, shape_gltf, shape_visible

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import ocp_serialize  # noqa: E402
import wrapper_section  # noqa: E402
import wrapper_visible  # noqa: E402

CAM_DIR = os.path.join(os.path.dirname(os.path.abspath(pc.__file__)), "builtin", "cam")
BOTTOM = (b3d.Align.CENTER, b3d.Align.CENTER, b3d.Align.MIN)


class _WrapperCommonStub:
    @staticmethod
    def exception_to_str(exc):
        return None if exc is None else str(exc)

    @staticmethod
    def handle_exception(exc, script=None):
        pass


@pytest.fixture(scope="module")
def gcode():
    """`builtin/cam/cam_gcode.py` as an importable module, its siblings importable beside it."""
    saved = sys.modules.get("wrapper_common")
    sys.modules["wrapper_common"] = _WrapperCommonStub
    saved_path = list(sys.path)
    sys.path.insert(0, CAM_DIR)
    try:
        spec = importlib.util.spec_from_file_location(
            "partcad.builtin.cam.cam_gcode_v", os.path.join(CAM_DIR, "cam_gcode.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.path[:] = saved_path
        if saved is None:
            del sys.modules["wrapper_common"]
        else:
            sys.modules["wrapper_common"] = saved


def _print(gcode, tmp_path, design, **job):
    """What a filament printer deposits printing 'design': a compound of prisms."""
    request = {"wrapped": design.wrapped, "machine": "fff", "materialize": True, "tolerance": 0.01}
    request.update(job)
    result = gcode.process(str(tmp_path / "print.nc"), request)
    assert result["success"], result.get("exception")
    return result["product"]


def _plate():
    """A 20 x 10 x 5 mm plate with a hole through it."""
    return b3d.Box(20, 10, 5, align=BOTTOM) - b3d.Cylinder(2, 5, align=BOTTOM)


def _faces(shape):
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        yield TopoDS.Face_s(explorer.Current())
        explorer.Next()


def _normals(shape):
    """The outward normal of every face of 'shape', each a tuple, rounded."""
    found = []
    for face in _faces(shape):
        surface = BRepAdaptor_Surface(face)
        assert surface.GetType() == GeomAbs_Plane
        direction = surface.Plane().Axis().Direction()
        sign = -1.0 if face.Orientation() == TopAbs_REVERSED else 1.0
        found.append(tuple(round(sign * value, 6) + 0.0 for value in (direction.X(), direction.Y(), direction.Z())))
    return found


def _count(shape) -> int:
    return sum(1 for _ in _faces(shape))


@pytest.fixture(scope="module")
def plate_print(gcode, tmp_path_factory):
    return _print(gcode, tmp_path_factory.mktemp("print"), _plate(), infill=0.2)


def test_a_print_is_read_as_its_prisms_and_nothing_else_is(plate_print):
    prisms = wrapper_visible.deposit_of(plate_print)
    assert prisms is not None and len(prisms) > 25
    # Every layer is 0.2 mm, and they stand on one another.
    assert {prism.z1 - prism.z0 for prism in prisms} == {2000}
    # One solid has nothing inside it to hide; a curved face is not a bead.
    assert wrapper_visible.deposit_of(b3d.Box(10, 10, 10).wrapped) is None
    assert wrapper_visible.deposit_of(b3d.Compound([b3d.Sphere(3), b3d.Pos(10, 0, 0) * b3d.Sphere(3)]).wrapped) is None


def test_a_whole_print_keeps_its_outside_only(plate_print):
    report = {}
    compound, kept, dropped = wrapper_visible.strip(plate_print, report)
    prisms = wrapper_visible.deposit_of(plate_print)
    layers = sorted({prism.layer for prism in prisms})
    top = [prism for prism in prisms if prism.layer == layers[-1]]
    bottom = [prism for prism in prisms if prism.layer == layers[0]]
    # The top of the last layer and the bottom of the first, every one of them,
    # and of every other layer's tops and bottoms - each lying on the next -
    # next to nothing: where a layer is wider than the one over it, at most.
    horizontal = sum(len(prism.top) + len(prism.bottom) for prism in prisms)
    assert report["top"] >= sum(len(prism.top) for prism in top)
    assert report["bottom"] >= sum(len(prism.bottom) for prism in bottom)
    assert report["top"] + report["bottom"] < horizontal / 5
    # And sides: the walls' outsides and the hole's, and nothing of the infill.
    assert kept == _count(compound) == report["top"] + report["bottom"] + report["side"] + report.get("other", 0)
    assert dropped > 4 * kept
    assert sum(1 for normal in _normals(compound) if abs(normal[2]) == 1) == report["top"] + report["bottom"]


def test_a_cut_opens_the_inside_and_draws_the_cut(plate_print):
    whole = wrapper_visible.strip(plate_print)[1]
    node = {
        "name": "//demo:print",
        "label": "print",
        ocp_serialize.KEY_BREP: ocp_serialize.compressed_brep(plate_print),
    }

    answer = wrapper_visible.process({"tree": node, "section": {"x": [-100.0, 0.3]}})

    assert answer["success"] and answer["errors"] == []
    cut = ocp_serialize.shape_from_payload(answer["tree"][ocp_serialize.KEY_BREP])
    # Half the print, and more of it drawn than of the whole print's outside:
    # the infill the cut exposes.
    assert answer["kept"] > whole
    assert answer["dropped"] > 0
    # The faces the cut leaves, on its plane, facing out of what is kept.
    assert sum(1 for normal in _normals(cut) if normal == (1.0, 0.0, 0.0)) > 25
    # What the node says about itself is the object's, not the cut's.
    assert answer["tree"]["name"] == "//demo:print"


def test_a_cut_across_the_layers_opens_the_infill_from_above(plate_print):
    node = {"name": "p", ocp_serialize.KEY_BREP: ocp_serialize.compressed_brep(plate_print)}
    whole = wrapper_visible.strip(plate_print)[1]

    answer = wrapper_visible.process({"tree": node, "section": {"z": [0.0, 2.55]}})

    assert answer["kept"] > whole / 2
    cut = ocp_serialize.shape_from_payload(answer["tree"][ocp_serialize.KEY_BREP])
    tops = [normal for normal in _normals(cut) if normal == (0.0, 0.0, 1.0)]
    # The top of what is left is the cut: every prism of the layer it cut through.
    assert len(tops) > 5


def test_more_infill_is_more_to_see_in_a_cut(gcode, tmp_path):
    sparse = _print(gcode, tmp_path, b3d.Box(12, 12, 4, align=BOTTOM), infill=0.15)
    dense = _print(gcode, tmp_path, b3d.Box(12, 12, 4, align=BOTTOM), infill=0.4)
    section = {"y": [-100.0, 0.5]}
    kept = []
    for product in (sparse, dense):
        node = {"name": "p", ocp_serialize.KEY_BREP: ocp_serialize.compressed_brep(product)}
        kept.append(wrapper_visible.process({"tree": node, "section": section})["kept"])
    assert kept[1] > kept[0]


def test_a_shape_that_is_not_a_print_is_cut_as_any_shape_is():
    box = b3d.Box(10, 10, 10, align=BOTTOM).wrapped
    node = {"name": "b", ocp_serialize.KEY_BREP: ocp_serialize.compressed_brep(box)}
    section = {"x": [-100.0, 1.0]}

    seen = wrapper_visible.process({"tree": node, "section": section})
    errors = []
    cut = wrapper_section.section_tree(node, section, errors, keep_empty=False)

    assert seen["kept"] == 0 and seen["dropped"] == 0 and errors == []
    assert ocp_serialize.payload_digest(seen["tree"][ocp_serialize.KEY_BREP]) == ocp_serialize.payload_digest(
        cut[ocp_serialize.KEY_BREP]
    )
    # Uncut, it is handed back as it came.
    whole = wrapper_visible.process({"tree": node, "section": None})
    assert whole["tree"][ocp_serialize.KEY_BREP] is node[ocp_serialize.KEY_BREP]


def test_a_node_the_box_misses_is_left_with_no_geometry(plate_print):
    node = {"name": "p", ocp_serialize.KEY_BREP: ocp_serialize.compressed_brep(plate_print)}
    answer = wrapper_visible.process({"tree": {"name": "a", "assembly": [node]}, "section": {"x": [100.0, 200.0]}})
    assert ocp_serialize.KEY_BREP not in answer["tree"]["assembly"][0]


#
# The core's side: 'shape_visible.visible_async', and who asks it
#


class InProcessSandbox:
    """A Python runtime that runs the wrapper it is asked for here, on the request as it would travel."""

    def __init__(self):
        self.ensured = []
        self.requests = []

    async def ensure_async(self, requirement):
        self.ensured.append(requirement)

    async def run_async(self, argv, stdin):
        name = os.path.basename(argv[0])
        request = ocp_serialize.deserialize_raw(runtime.stdin_bytes(stdin))
        self.requests.append((name, request))
        assert name == "wrapper_visible.py"
        return 0, ocp_serialize.serialize(wrapper_visible.process(request), share=True), ""


class SandboxContext:
    cache_artifacts = None

    def __init__(self, sandbox):
        self.sandbox = sandbox

    def get_python_runtime(self, version=None):
        return self.sandbox


def test_the_core_asks_the_sandbox_with_the_section_normalized(plate_print):
    sandbox = InProcessSandbox()
    tree = {"name": "//demo:print", shape_envelope.KEY_BREP: ocp_serialize.compressed_brep(plate_print)}

    shown = asyncio.run(shape_visible.visible_async(SandboxContext(sandbox), tree, {"z": [0, 2.55], "x": None}))

    [(_, request)] = sandbox.requests
    assert request["section"] == {"z": [0.0, 2.55]}
    assert shown["name"] == "//demo:print"
    assert sandbox.ensured == list(shape_visible._DEPENDENCIES)


def test_a_tree_and_a_context_are_required():
    with pytest.raises(ValueError, match="context is required"):
        asyncio.run(shape_visible.visible_async(None, {"name": "x", "brep": b""}, None))
    with pytest.raises(ValueError, match="Not a shape tree"):
        asyncio.run(shape_visible.visible_async(SandboxContext(InProcessSandbox()), {"a": 1}, None))
    assert asyncio.run(shape_visible.visible_async(SandboxContext(InProcessSandbox()), None, None)) is None


def test_the_gltf_form_strips_instead_of_cutting_only_when_asked(monkeypatch):
    calls = []

    async def visible(ctx, tree, section=None, cacheable=True):
        calls.append(("visible", section))
        return tree

    async def section_async(ctx, tree, section, cacheable=True, keep_empty=True):
        calls.append(("section", section))
        return tree

    async def tessellate(ctx, tree, missing, tolerance, angular_tolerance):
        calls.append(("tessellate", tolerance, angular_tolerance))
        return {digest: b"glb" for digest in missing}, {}, {}

    monkeypatch.setattr(shape_visible, "visible_async", visible)
    monkeypatch.setattr(shape_gltf, "_tessellate_async", tessellate)
    from partcad import shape_section

    monkeypatch.setattr(shape_section, "section_async", section_async)
    box = ocp_serialize.compressed_brep(b3d.Box(10, 10, 10).wrapped)
    tree = {"name": "b", shape_envelope.KEY_BREP: box}

    asyncio.run(shape_gltf.convert_async(SandboxContext(None), dict(tree), section={"x": [0, 1]}, cacheable=False))
    asyncio.run(
        shape_gltf.convert_async(
            SandboxContext(None), dict(tree), section={"x": [0, 1]}, cacheable=False, hidden_stripped=True
        )
    )
    asyncio.run(shape_gltf.convert_async(SandboxContext(None), dict(tree), cacheable=False, hidden_stripped=True))

    assert [call[0] for call in calls] == ["section", "tessellate", "visible", "tessellate", "visible", "tessellate"]
    assert calls[2] == ("visible", {"x": [0, 1]}) and calls[4] == ("visible", None)
