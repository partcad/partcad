#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'basic' sketches and parts, whose BREP the core writes itself ('basic_shapes', 'brep_ascii').

Nothing in the core can check a shape it wrote - that is the point of writing
it without a kernel - so these read every one back with OCCT and hold it to the
shape OCCT builds from the same numbers: for a sketch, the face the retired
'wrapper_sketch_basic' built, whose construction is kept below as the
reference; for a part, the solid 'BRepPrimAPI' builds, moved and scaled by
'wrapper_transform'. "The same" is validity, area or volume, box, centroid and
inertia, and - for a sketch, where a tool path reads it - which way every edge
runs, in which order, and which way the face points.
"""

import asyncio
import math
import os
import sys

import jsonschema
import pytest

import partcad as pc
from partcad import basic_shapes, brep_ascii, shape_envelope
from partcad.lint.all import get_partcad_schema
from partcad.part_factory_basic import PartFactoryBasic
from partcad.sketch_factory_basic import SketchFactoryBasic
from partcad.user_config import UserConfig

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import ocp_serialize  # noqa: E402
import shape_measure  # noqa: E402
import wrapper_common  # noqa: E402
import wrapper_transform  # noqa: E402

# --------------------------------------------------------------------------- #
# The references                                                              #
# --------------------------------------------------------------------------- #


def _reference_outline(kind, config):
    """The wire 'wrapper_sketch_basic' built for one outline, with the OCCT calls it made, or None."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeWire
    from OCP.GC import GC_MakeArcOfCircle
    from OCP.gp import gp_Ax2, gp_Circ, gp_Dir, gp_Pnt

    if kind == "circle":
        x, y, radius = 0.0, 0.0, config
        if isinstance(config, dict):
            x, y, radius = config.get("x", 0.0), config.get("y", 0.0), config["radius"]
        edge = BRepBuilderAPI_MakeEdge(gp_Circ(gp_Ax2(gp_Pnt(x, y, 0), gp_Dir(0.0, 0.0, 1.0)), radius))
        return BRepBuilderAPI_MakeWire(edge.Edge()).Wire()
    if kind in ("square", "rectangle"):
        if kind == "square":
            x, y, sx = 0.0, 0.0, config
            if isinstance(config, dict):
                x, y, sx = config.get("x", 0.0), config.get("y", 0.0), config["side"]
            sy = sx
        else:
            x, y = config.get("x", 0.0), config.get("y", 0.0)
            sx, sy = config["side-x"], config["side-y"]
        hx, hy = sx / 2.0, sy / 2.0
        polygon = BRepBuilderAPI_MakePolygon(
            gp_Pnt(x + hx, y + hy, 0.0),
            gp_Pnt(x + hx, y - hy, 0.0),
            gp_Pnt(x - hx, y - hy, 0.0),
            gp_Pnt(x - hx, y + hy, 0.0),
            True,
        )
        return polygon.Wire()
    # A slot.
    x, y, angle = config.get("x", 0.0), config.get("y", 0.0), config.get("angle", 0.0)
    radius, reach = config["width"] / 2.0, config["length"] - config["width"]
    cos, sin = math.cos(math.radians(angle)), math.sin(math.radians(angle))

    def point(px, py):
        return gp_Pnt(x + px * cos - py * sin, y + px * sin + py * cos, 0.0)

    top_left, top_right = point(0.0, radius), point(reach, radius)
    bottom_right, bottom_left = point(reach, -radius), point(0.0, -radius)
    builder = BRepBuilderAPI_MakeWire()
    if reach > 0.0:
        builder.Add(BRepBuilderAPI_MakeEdge(top_left, top_right).Edge())
    builder.Add(
        BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(top_right, point(reach + radius, 0.0), bottom_right).Value()).Edge()
    )
    if reach > 0.0:
        builder.Add(BRepBuilderAPI_MakeEdge(bottom_right, bottom_left).Edge())
    builder.Add(BRepBuilderAPI_MakeEdge(GC_MakeArcOfCircle(bottom_left, point(-radius, 0.0), top_left).Value()).Edge())
    return builder.Wire()


def _reference_sketch(config):
    """The face 'wrapper_sketch_basic.process' built: the outer wire, the holes, and 'ShapeFix_Face'."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.ShapeFix import ShapeFix_Face

    kind = next(key for key in ("circle", "square", "rectangle", "slot") if key in config)
    builder = BRepBuilderAPI_MakeFace(_reference_outline(kind, config[kind]), True)
    inner = config.get("inner", {})
    for single, several in (("circle", "circles"), ("square", "squares"), ("rectangle", "rectangles")):
        for item in ([inner[single]] if single in inner else []) + list(inner.get(several, [])):
            builder.Add(_reference_outline(single, item))
    for item in ([inner["slot"]] if "slot" in inner else []) + list(inner.get("slots", [])):
        builder.Add(_reference_outline("slot", item))
    builder.Build()
    fixer = ShapeFix_Face(builder.Face())
    fixer.FixOrientation()
    fixer.Perform()
    return fixer.Result()


def _reference_part(config, finish):
    """The same solid from 'BRepPrimAPI', centred as a basic part is, then moved and scaled as a wrapper would."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    if "cuboid" in config:
        cuboid = config["cuboid"]
        sx, sy, sz = cuboid if isinstance(cuboid, list) else [cuboid] * 3
        x = y = z = 0.0
        shape = BRepPrimAPI_MakeBox(gp_Pnt(x - sx / 2.0, y - sy / 2.0, z - sz / 2.0), sx, sy, sz).Shape()
    else:
        cylinder = config["cylinder"]
        radius, height = cylinder["radius"], cylinder["height"]
        x = y = z = 0.0
        axis = gp_Ax2(gp_Pnt(x, y, z - height / 2.0), gp_Dir(0.0, 0.0, 1.0))
        shape = BRepPrimAPI_MakeCylinder(axis, radius, height).Shape()
    if "offset" in finish:
        shape = wrapper_transform.relocate(shape, finish["offset"])
    if "scale" in finish:
        shape = wrapper_transform.scale(shape, finish["scale"])
    return shape


# --------------------------------------------------------------------------- #
# Reading a shape back                                                        #
# --------------------------------------------------------------------------- #


def _read(payload):
    return ocp_serialize.shape_from_brep(payload)


def _valid(shape) -> bool:
    from OCP.BRepCheck import BRepCheck_Analyzer

    return BRepCheck_Analyzer(shape).IsValid()


def _area(shape) -> float:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    properties = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, properties)
    return properties.Mass()


def _faces(shape):
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        yield TopoDS.Face_s(explorer.Current())
        explorer.Next()


def _facing(face):
    """Which way a planar face points, as the face holds its plane."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.TopAbs import TopAbs_REVERSED

    direction = BRepAdaptor_Surface(face).Plane().Axis().Direction()
    sign = -1.0 if face.Orientation() == TopAbs_REVERSED else 1.0
    return tuple(round(sign * value, 9) + 0.0 for value in (direction.X(), direction.Y(), direction.Z()))


def _runs(face):
    """Every edge of every wire of 'face', in order, as the points it runs from and to."""
    from OCP.BRep import BRep_Tool
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS, TopoDS_Iterator

    def at(vertex):
        point = BRep_Tool.Pnt_s(vertex)
        return tuple(round(value, 9) + 0.0 for value in (point.X(), point.Y(), point.Z()))

    wires = []
    over_wires = TopoDS_Iterator(face)
    while over_wires.More():
        edges = []
        over_edges = TopoDS_Iterator(over_wires.Value())
        while over_edges.More():
            edge = TopoDS.Edge_s(over_edges.Value())
            edges.append((at(TopExp.FirstVertex_s(edge, True)), at(TopExp.LastVertex_s(edge, True))))
            over_edges.Next()
        wires.append(edges)
        over_wires.Next()
    return wires


def _close(a, b, tolerance=1e-9):
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(_close(x, y, tolerance) for x, y in zip(a, b))
    return abs(a - b) <= tolerance * max(1.0, abs(b))


# --------------------------------------------------------------------------- #
# Sketches                                                                    #
# --------------------------------------------------------------------------- #

SKETCHES = {
    "circle": {"circle": 5},
    "circle-placed": {"circle": {"x": 2, "y": -3, "radius": 2}},
    "circle-with-square": {"circle": 5, "inner": {"square": 2}},
    "circle-with-circle": {"circle": 5, "inner": {"circle": 3}},
    "square": {"square": 5},
    "square-placed-with-holes": {
        "square": {"side": 20, "x": 3, "y": -1},
        "inner": {"circles": [{"radius": 1, "x": 5}, {"radius": 2, "x": -2, "y": 4}], "squares": [{"side": 2, "x": 8}]},
    },
    "rectangle": {"rectangle": {"side-x": 5, "side-y": 3}},
    "rectangle-with-circle": {"rectangle": {"side-x": 6, "side-y": 4}, "inner": {"circle": 1}},
    "rectangle-with-rectangle": {
        "rectangle": {"side-x": 6, "side-y": 4},
        "inner": {"rectangle": {"side-x": 1, "side-y": 2, "x": 1}},
    },
    "slot": {"slot": {"length": 30, "width": 4}},
    "slot-turned-with-slot": {
        "slot": {"length": 30, "width": 8, "angle": 30, "x": 1, "y": 2},
        "inner": {"slot": {"length": 10, "width": 2, "x": 5, "y": 5, "angle": 30}},
    },
    "circle-with-round-slot": {
        "circle": 9,
        "inner": {"slots": [{"length": 2, "width": 2}], "circles": [{"radius": 1, "x": 4}]},
    },
}


@pytest.mark.parametrize("name", sorted(SKETCHES))
def test_a_basic_sketch_is_the_face_occt_built(name):
    config = SKETCHES[name]
    payload, measurements = basic_shapes.sketch(config)
    mine = _read(payload)
    reference = _reference_sketch(config)

    assert _valid(mine)
    assert _area(mine) == pytest.approx(_area(reference), rel=1e-12)
    [face] = list(_faces(mine))
    [reference_face] = list(_faces(reference))
    assert _facing(face) == _facing(reference_face)
    assert _runs(face) == _runs(reference_face)
    assert _close(measurements["bbox"], shape_measure.measurements(reference)["bbox"], 1e-9)
    assert measurements["volume"] is None
    assert measurements["solids"] == 0
    assert measurements["freeShells"] == 0


@pytest.mark.parametrize(
    "config, facing",
    [
        ({"circle": 1}, (0.0, 0.0, 1.0)),
        ({"square": 1}, (0.0, 0.0, -1.0)),
        ({"slot": {"length": 3, "width": 1}}, (0.0, 0.0, -1.0)),
    ],
)
def test_a_sketch_faces_the_way_its_outline_runs(config, facing):
    """A circle runs counter-clockwise and the rest clockwise, and the face follows, as OCCT's did."""
    [face] = list(_faces(_read(basic_shapes.sketch(config)[0])))
    assert _facing(face) == facing


@pytest.mark.parametrize(
    "config, message",
    [
        ({}, "names no supported outer shape"),
        ({"circle": 0}, "encloses nothing"),
        ({"circle": -1}, "negative radius"),
        ({"slot": {"length": 3, "width": 0}}, "width greater than zero"),
        ({"slot": {"length": 3, "width": 4}}, "cannot be 4 wide"),
        ({"circle": "five"}, "has to be a number"),
        ({"rectangle": 4}, "'side-x' and 'side-y'"),
    ],
)
def test_a_sketch_that_cannot_be_built_says_why(config, message):
    with pytest.raises(ValueError, match=message):
        basic_shapes.sketch(config)


def test_a_hole_that_encloses_nothing_is_left_out():
    """As the wrapper left out a wire OCCT could not build."""
    payload, _measurements = basic_shapes.sketch({"circle": 5, "inner": {"circle": 0, "square": 0}})
    [face] = list(_faces(_read(payload)))
    assert len(_runs(face)) == 1


# --------------------------------------------------------------------------- #
# Parts                                                                       #
# --------------------------------------------------------------------------- #

PARTS = [
    ({"cuboid": 10}, {}),
    ({"cuboid": [2, 4, 6]}, {"offset": [[1, -2, 3], [0, 0, 1], 0]}),
    ({"cuboid": [2, 4, 6]}, {"offset": [[5, 6, 7], [1, 2, 3], 37]}),
    ({"cuboid": [2, 4, 6]}, {"offset": [[5, 6, 7], [0, 0, 1], 90], "scale": 2.5}),
    ({"cylinder": {"radius": 2, "height": 5}}, {}),
    ({"cylinder": {"radius": 3, "height": 7}}, {"offset": [[1, 0, 0], [1, 1, 0], 45]}),
    ({"cylinder": {"radius": 3, "height": 7}}, {"offset": [[1, 2, 3], [0.2, -0.7, 0.3], 123], "scale": 0.3}),
    ({"cylinder": {"radius": 3, "height": 7}}, {"scale": 4}),
]


@pytest.mark.parametrize("config, finish", PARTS)
def test_a_basic_part_is_the_solid_occt_builds(config, finish):
    request = {"validate": {"solidify": True}, **finish}
    payload, measurements, claim = basic_shapes.part(config, request)
    mine = _read(payload)
    reference = shape_measure.measurements(_reference_part(config, finish))

    assert _valid(mine)
    assert wrapper_common.solid_problems(mine) == []
    # What OCCT integrates out of the solid written...
    integrated = shape_measure.measurements(mine)
    assert integrated["solids"] == 1
    assert integrated["freeShells"] == 0
    assert integrated["volume"] == pytest.approx(reference["volume"], rel=1e-9)
    # ...and what was worked out without it, against the reference.
    assert measurements["solids"] == 1
    assert measurements["freeShells"] == 0
    assert measurements["volume"] == pytest.approx(reference["volume"], rel=1e-9)
    assert _close(measurements["bbox"], reference["bbox"], 1e-7)
    assert _close(measurements["centroid"], reference["centroid"], 1e-9)
    assert _close(measurements["unitInertia"], reference["unitInertia"], 1e-7)
    # And it says it did all of what it was asked, in the words a wrapper would.
    assert claim == {"validated": {"solidify": True, "problems": []}, **finish}


@pytest.mark.parametrize("config, finish", PARTS[2:4] + PARTS[5:7])
def test_a_basic_part_takes_part_in_a_boolean(config, finish):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    payload, measurements, _claim = basic_shapes.part(config, finish)
    corner = [value - 0.5 for value in measurements["centroid"]]
    cut = BRepAlgoAPI_Cut(_read(payload), BRepPrimAPI_MakeBox(gp_Pnt(*corner), 1.0, 1.0, 1.0).Shape()).Shape()
    assert _valid(cut)
    assert shape_measure.measurements(cut)["volume"] == pytest.approx(measurements["volume"] - 1.0, rel=1e-6)


@pytest.mark.parametrize(
    "finish, claimed, declined",
    [
        ({"offset": "somewhere"}, {}, "offset: not a '[[x, y, z], [ax, ay, az], angle]' location"),
        ({"offset": [[0, 0, 0], [0, 0, 0], 10]}, {}, "offset: a direction needs a length"),
        ({"scale": -1}, {}, "scale: only a number greater than zero"),
        ({"scale": [1, 2, 3]}, {}, "scale: only a number greater than zero"),
        ({"offset": [[1, 0, 0], [0, 0, 1], 0], "scale": 0}, {"offset": [[1, 0, 0], [0, 0, 1], 0]}, "scale: "),
    ],
)
def test_what_a_part_cannot_apply_itself_is_left_to_the_core(finish, claimed, declined):
    """Claimed up to the step it stops at, with why, as 'wrapper_common._finish' claims."""
    payload, measurements, claim = basic_shapes.part({"cuboid": 2}, {"validate": {"solidify": True}, **finish})
    assert claim.pop("declined").startswith(declined)
    assert claim == {"validated": {"solidify": True, "problems": []}, **claimed}
    # Built where it would have been without what was declined.
    offset = claimed.get("offset", [[0, 0, 0], [0, 0, 1], 0])[0]
    assert measurements["centroid"] == pytest.approx(offset)
    assert _valid(_read(payload))


@pytest.mark.parametrize(
    "config, message",
    [
        ({}, "names neither"),
        ({"cuboid": 1, "cylinder": {"radius": 1, "height": 1}}, "names cuboid and cylinder"),
        ({"cuboid": 0}, "'cuboid' has to be greater than zero"),
        ({"cuboid": [1, 2]}, "three sizes along X, Y and Z"),
        ({"cuboid": [1, 0, 2]}, r"'cuboid\[1\]' has to be greater than zero"),
        ({"cuboid": {"side-x": 1, "side-y": 1, "side-z": 1}}, "placed by the part's 'offset'"),
        ({"cylinder": {"radius": 1}}, "needs its 'height'"),
        ({"cylinder": {"radius": -1, "height": 1}}, "'cylinder.radius' has to be greater than zero"),
        ({"cylinder": {"radius": 1, "height": 1, "z": 2}}, "not 'z'; it is placed by the part's 'offset'"),
        ({"cylinder": 3}, "'radius' and 'height'"),
        ({"cuboid": True}, "has to be a number"),
    ],
)
def test_a_part_that_cannot_be_built_says_why(config, message):
    with pytest.raises(ValueError, match=message):
        basic_shapes.part(config)


# --------------------------------------------------------------------------- #
# The format                                                                  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("value", [0.1, 1.0 / 3.0, math.pi, 2.0 * math.pi, 1e-7, -2.5e300, 5e-324, 12345678.9])
def test_a_number_is_written_so_that_it_reads_back_as_itself(value):
    assert float(brep_ascii.real(value)) == value


def test_a_number_a_brep_cannot_hold_is_refused():
    for value in (math.inf, -math.inf, math.nan):
        with pytest.raises(ValueError):
            brep_ascii.real(value)
    assert brep_ascii.real(-0.0) == "0"
    assert brep_ascii.real(5.0) == "5"


def test_a_payload_is_version_1_ascii_that_reads_as_ascii():
    payload, _measurements = basic_shapes.sketch({"circle": 1})
    assert payload.startswith(b"\n" + brep_ascii.HEADER.encode() + b"\n")
    assert not ocp_serialize.is_binary_brep(payload)
    # The shape written last is the one the file is of, and it is numbered 1.
    assert payload.rstrip().endswith(b"+1 0")


def test_a_shape_held_twice_is_written_once():
    """A seam is in its wire twice, and a vertex in every edge it bounds, and each is one shape."""
    payload, _measurements, _claim = basic_shapes.part({"cylinder": {"radius": 1, "height": 1}})
    assert b"TShapes 13\n" in payload
    # The free shells the core counts off an ASCII payload when nothing was recorded agree.
    from partcad import brep_inspect

    assert brep_inspect.payload_free_shells(basic_shapes.envelope(payload, {})) == 0


# --------------------------------------------------------------------------- #
# Through a package                                                           #
# --------------------------------------------------------------------------- #

PACKAGE = """
sketches:
  ring:
    type: basic
    cache: false
    circle: 5
    inner:
      circle: 3
parts:
  block:
    type: basic
    cache: false
    cuboid: [10, 20, 5]
    offset: [[1, 2, 3], [0, 0, 1], 30]
  rod:
    type: basic
    cache: false
    parameters:
      length:
        type: float
        default: 20
    cylinder:
      radius: 2
      height: "%length%"
    scale: 2
  spacer:
    type: basic
    cache: false
    parameters:
      length:
        type: float
        default: 10
    cylinder:
      radius: 4
      height: "%length%"
    offset: [[0, 0, "%length / 2%"], [0, 0, 1], 0]
  both:
    type: basic
    cache: false
    cuboid: 1
    cylinder: {radius: 1, height: 1}
"""


@pytest.fixture
def package(tmp_path, monkeypatch):
    (tmp_path / "partcad.yaml").write_text(PACKAGE)
    user_config = UserConfig()
    user_config.python_sandbox = "none"
    ctx = pc.Context(str(tmp_path), user_config=user_config)

    def no_sandbox(*args, **kwargs):
        raise AssertionError("a basic shape asked for a sandbox")

    monkeypatch.setattr(ctx, "get_python_runtime", no_sandbox)
    return ctx


def _built(ctx, shape):
    return asyncio.run(shape.get_wrapped(ctx))


def test_a_basic_sketch_is_built_without_a_sandbox(package):
    ctx = package
    sketch = ctx.get_sketch("ring")
    envelope = _built(ctx, sketch)

    assert envelope["name"] == "//:ring" and envelope["label"] == "ring"
    assert shape_envelope.brep_bytes(envelope["brep"]).startswith(shape_envelope.ZSTD_MAGIC)
    assert _area(_read(shape_envelope.brep_plain(envelope["brep"]))) == pytest.approx(math.pi * (25 - 9))
    assert asyncio.run(sketch.get_measurements_async(ctx))["bbox"] == [-5.0, -5.0, 0.0, 5.0, 5.0, 0.0]
    assert sketch.environment_cache_key is None


def test_a_basic_part_is_built_moved_and_scaled_without_a_sandbox(package):
    """Its offset and scale are claimed, so 'get_wrapped' has nothing left to hand to 'transform.py'."""
    ctx = package
    block = _built(ctx, ctx.get_part("block"))
    rod = _built(ctx, ctx.get_part("rod"))

    # The claim is taken off before anything is recorded.
    assert shape_envelope.METADATA_FINISHED not in block[shape_envelope.KEY_METADATA]
    measured = block[shape_envelope.KEY_METADATA][shape_envelope.METADATA_MEASUREMENTS]
    assert measured["centroid"] == pytest.approx([1.0, 2.0, 3.0])
    assert measured["volume"] == pytest.approx(1000.0)
    # Turned by 30 degrees about Z, so wider in X than its 10 mm.
    assert measured["bbox"][3] - measured["bbox"][0] == pytest.approx(10 * math.cos(math.radians(30)) + 20 * 0.5)

    measured = rod[shape_envelope.KEY_METADATA][shape_envelope.METADATA_MEASUREMENTS]
    assert measured["bbox"] == pytest.approx([-4.0, -4.0, -20.0, 4.0, 4.0, 20.0])


def test_a_basic_part_is_parametric(package):
    ctx = package
    rod = ctx.get_part("rod;length=8")
    measured = _built(ctx, rod)[shape_envelope.KEY_METADATA][shape_envelope.METADATA_MEASUREMENTS]
    assert measured["bbox"] == pytest.approx([-4.0, -4.0, -8.0, 4.0, 4.0, 8.0])
    assert rod.info()["primitive"] == {"cylinder": {"radius": 2, "height": 8}}


def test_a_basic_part_is_placed_by_an_offset_written_in_its_parameters(package):
    """Standing on the XY plane whatever its length: the offset is resolved for each instance."""
    ctx = package
    for name, length in (("spacer", 10.0), ("spacer;length=25", 25.0)):
        part = ctx.get_part(name)
        measured = _built(ctx, part)[shape_envelope.KEY_METADATA][shape_envelope.METADATA_MEASUREMENTS]
        assert measured["bbox"] == pytest.approx([-4.0, -4.0, 0.0, 4.0, 4.0, length])
    # The declaration keeps the expression for the next instance to resolve.
    assert ctx.get_part("spacer").config["offset"][0][2] == "%length / 2%"


def test_two_sizes_of_a_basic_part_are_two_cache_entries(tmp_path):
    (tmp_path / "partcad.yaml").write_text(
        "parts:\n  spacer:\n    type: basic\n    parameters:\n      length:\n        type: float\n"
        '        default: 10\n    cylinder:\n      radius: 4\n      height: "%length%"\n'
    )
    ctx = pc.Context(str(tmp_path))
    short, long = (ctx.get_part(name).hash.get() for name in ("spacer;length=10", "spacer;length=25"))
    assert short is not None and long is not None
    assert short != long


def test_a_basic_part_that_names_two_solids_is_an_error(package):
    ctx = package
    assert _built(ctx, ctx.get_part("both")) is None
    assert pc.logging.had_errors


@pytest.mark.parametrize("cls", [SketchFactoryBasic, PartFactoryBasic])
def test_a_basic_shape_is_keyed_on_the_code_that_writes_it(cls):
    factory = cls.__new__(cls)
    factory.config = {}
    factory.project = type("Project", (), {"name": "//pkg"})()
    assert factory.code_versions() == "%s@%d" % (basic_shapes.CODE_NAME, basic_shapes.CACHE_VERSION)
    assert factory.environment_cache_key() is None
    assert cls.WRAPPERS == ()


# --------------------------------------------------------------------------- #
# The schema                                                                  #
# --------------------------------------------------------------------------- #


def _validate(part):
    jsonschema.validate(instance={"parts": {"thing": part}}, schema=get_partcad_schema())


@pytest.mark.parametrize(
    "part",
    [
        {"type": "basic", "cuboid": 10},
        {"type": "basic", "cuboid": [1, 2, "%z%"]},
        {"type": "basic", "cylinder": {"radius": 1, "height": "%length%"}},
        {"type": "basic", "cylinder": {"radius": 1, "height": 2}, "offset": [[0, 0, 0], [0, 1, 0], 90]},
    ],
)
def test_the_schema_takes_a_basic_part(part):
    _validate(part)


@pytest.mark.parametrize(
    "part",
    [
        {"type": "basic", "cuboid": 0},
        {"type": "basic", "cuboid": [1, 2]},
        {"type": "basic", "cuboid": [1, 2, 0]},
        {"type": "basic", "cuboid": {"side-x": 1, "side-y": 2, "side-z": 3}},
        {"type": "basic", "cylinder": {"radius": 1, "height": 2, "z": 1}},
        {"type": "basic", "cylinder": {"radius": 1}},
        {"type": "basic", "cylinder": {"radius": 1, "height": 2, "depth": 3}},
        {"type": "basic", "cylinder": 4},
    ],
)
def test_the_schema_refuses_a_basic_part_it_cannot_build(part):
    with pytest.raises(jsonschema.exceptions.ValidationError):
        _validate(part)
