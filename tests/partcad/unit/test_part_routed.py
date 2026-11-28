#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The routed part type (issue #975, tasks 3.2 and 3.4).

Two halves. The declaration and the factory - ports, validation, the route
parameter, the checks before the sweep - are tested on packages of their own,
built where they need geometry. The wrapper is run in this process on the
request the factory sends it, and its solid measured with OCP: volume, where the
end faces are and which way they face, and how a flat profile is turned at each
end.
"""

import asyncio
import math
import os
import sys
import textwrap

import pytest
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
from OCP.BRepGProp import BRepGProp
from OCP.GeomAbs import GeomAbs_SurfaceType
from OCP.gp import gp_Pnt
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_VERTEX
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS

import partcad as pc
from partcad.route_path import EndFrame, RoutePath, canonical_json, canonical_stops

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import wrapper_route  # noqa: E402

# -- The declaration and the factory --------------------------------------------

PACKAGE = """
sketches:
  strip:
    type: basic
    rectangle:
      side-x: 40
      side-y: 1
parts:
  tube:
    type: routed
    diameter: 6
    innerDiameter: 4
  sealed:
    type: routed
    diameter: 6
    ports:
      gland: [[0, 0, -12], [0, 0, 1], 0]
  ribbon:
    type: routed
    sketch: strip
"""


def _context(tmp_path, package=PACKAGE):
    (tmp_path / "partcad.yaml").write_text(textwrap.dedent(package))
    return pc.Context(str(tmp_path))


def _quarter_route(radius=50.0):
    stops = [
        EndFrame((radius, 0, 0), (0, 1, 0), (0, 0, 1)),
        (radius * math.cos(0.7), radius * math.sin(0.7), 0),
        EndFrame((0, radius, 0), (1, 0, 0), (0, 0, 1)),
    ]
    return stops, canonical_json(stops)


def test_a_plain_routed_part_has_no_ports(tmp_path):
    tube = _context(tmp_path).get_part(":tube")
    assert tube is not None
    assert dict(tube.with_ports.get_ports()) == {}


def test_declared_ports_appear_as_declared(tmp_path):
    sealed = _context(tmp_path).get_part(":sealed")
    (name,) = sealed.with_ports.get_ports()
    assert name.endswith("gland")


@pytest.mark.parametrize(
    "declaration, message",
    [
        ("diameter: 6\n    innerDiameter: 6", "'innerDiameter' (6) must be smaller than 'diameter' (6)"),
        ("diameter: 6\n    innerDiameter: 8", "'innerDiameter' (8) must be smaller than 'diameter' (6)"),
        ("diameter: 6\n    ports:\n      tip: ['%route%', [0, 0, 1], 0]", "cannot depend on it"),
        ("diameter: 6\n    implements:\n      'slab;length=%route%':", "cannot depend on it"),
    ],
    ids=["bore-equal", "bore-wider", "port-reads-route", "interface-reads-route"],
)
def test_a_declaration_the_part_cannot_use_is_refused(tmp_path, declaration, message, caplog):
    ctx = _context(tmp_path, "parts:\n  bad:\n    type: routed\n    %s\n" % declaration)
    with caplog.at_level("ERROR"):
        assert ctx.get_part(":bad") is None
    assert message in caplog.text


def test_a_route_is_a_parameter_of_its_own_and_keys_the_part(tmp_path):
    """No 'parameters:' declared, and each route a part with its own cache key."""
    ctx = _context(tmp_path)
    _, route = _quarter_route()
    _, other = _quarter_route(60.0)
    bare = ctx.get_part(":tube")
    one = ctx.get_part(":tube", {"route": route})
    again = ctx.get_part(":tube", {"route": route})
    two = ctx.get_part(":tube", {"route": other})
    assert one is not None and one is again

    def key(part):
        return asyncio.run(part.get_cache_key_async())

    assert len({key(bare), key(one), key(two)}) == 3


def test_a_routed_part_without_a_route_says_where_one_comes_from(tmp_path):
    ctx = _context(tmp_path)
    tube = ctx.get_part(":tube")
    assert asyncio.run(tube.get_wrapped(ctx)) is None
    (error,) = tube.errors
    assert "built from the route an assembly places it by ('route:')" in error


def test_a_sketch_too_wide_for_the_bend_is_refused_before_the_sweep(tmp_path):
    """A 40 by 1 mm strip through a 10 mm hairpin: its outer radius, the half-diagonal of its box, is 20.006 mm."""
    ctx = _context(tmp_path)
    stops = [EndFrame((0, 0, 0), (1, 0, 0), (0, 1, 0), lead=50), EndFrame((0, 10, 0), (1, 0, 0), (0, 1, 0), lead=50)]
    ribbon = ctx.get_part(":ribbon", {"route": canonical_json(stops)})
    assert asyncio.run(ribbon.get_wrapped(ctx)) is None
    assert any("tighter than the profile's radius of 20.006 mm" in error for error in ribbon.errors), ribbon.errors


def test_a_tube_is_built_through_the_sandbox(tmp_path):
    ctx = _context(tmp_path)
    _, route = _quarter_route()
    tube = ctx.get_part(":tube", {"route": route})
    assert asyncio.run(tube.get_wrapped(ctx)) is not None
    assert tube.errors == []


# -- The wrapper -----------------------------------------------------------------


def _faces(shape):
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        yield TopoDS.Face_s(explorer.Current())
        explorer.Next()


def _planar_faces(shape):
    """Each planar face as (centroid, unit normal, face)."""
    for face in _faces(shape):
        surface = BRepAdaptor_Surface(face)
        if surface.GetType() != GeomAbs_SurfaceType.GeomAbs_Plane:
            continue
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, props)
        centre = props.CentreOfMass()
        normal = surface.Plane().Axis().Direction()
        yield (centre.X(), centre.Y(), centre.Z()), (normal.X(), normal.Y(), normal.Z()), face


def _end_face(shape, origin):
    return min(_planar_faces(shape), key=lambda f: math.dist(f[0], origin))


def _longest_edge_direction(face):
    best, direction = 0.0, None
    explorer = TopExp_Explorer(face, TopAbs_EDGE)
    while explorer.More():
        edge = TopoDS.Edge_s(explorer.Current())
        vertices = []
        vexp = TopExp_Explorer(edge, TopAbs_VERTEX)
        while vexp.More():
            p = BRep_Tool.Pnt_s(TopoDS.Vertex_s(vexp.Current()))
            vertices.append((p.X(), p.Y(), p.Z()))
            vexp.Next()
        if len(vertices) == 2:
            length = math.dist(*vertices)
            if length > best:
                best = length
                direction = tuple((b - a) / length for a, b in zip(*vertices))
        explorer.Next()
    return direction


def _rect(width, height):
    poly = BRepBuilderAPI_MakePolygon(
        gp_Pnt(-width / 2, -height / 2, 0),
        gp_Pnt(width / 2, -height / 2, 0),
        gp_Pnt(width / 2, height / 2, 0),
        gp_Pnt(-width / 2, height / 2, 0),
        True,
    )
    return BRepBuilderAPI_MakeFace(poly.Wire()).Face()


def _volume(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def test_a_tube_on_an_arc_has_the_volume_of_its_section_times_its_length():
    stops, route = _quarter_route()
    length = RoutePath(canonical_stops(stops)).length
    shape = wrapper_route.process({"route": route, "diameter": 6, "innerDiameter": 4})
    assert _volume(shape) == pytest.approx(math.pi * (3**2 - 2**2) * length, rel=0.01)


def test_the_end_faces_sit_on_the_end_origins_square_to_their_axes():
    stops, route = _quarter_route()
    shape = wrapper_route.process({"route": route, "diameter": 6, "innerDiameter": 4})
    for end in (stops[0], stops[-1]):
        centre, normal, _ = _end_face(shape, end.origin)
        assert centre == pytest.approx(end.origin, abs=1e-6)
        # Square to the end's axis: the normal is +Z or -Z of the end frame.
        assert abs(sum(n * z for n, z in zip(normal, end.z))) == pytest.approx(1.0, abs=1e-6)


def test_a_flat_profile_meets_each_end_turned_as_its_x_axis():
    """The second end's X is turned 90 degrees from the first's: the strip rolls to meet it."""
    first = EndFrame((0, 0, 0), (0, 0, 1), (1, 0, 0))
    second = EndFrame((0, 0, 100), (0, 0, -1), (0, 1, 0))
    stops = [first, (20, 0, 50), second]
    shape = wrapper_route.process({"route": canonical_json(stops), "sketch": _rect(8, 2)})
    for end in (first, second):
        _, _, face = _end_face(shape, end.origin)
        long_side = _longest_edge_direction(face)
        alignment = abs(sum(a * b for a, b in zip(long_side, end.x)))
        assert math.acos(min(1.0, alignment)) == pytest.approx(0.0, abs=1e-6)


def test_a_request_without_a_route_is_refused():
    with pytest.raises(wrapper_route.RouteBuildError, match="no route"):
        wrapper_route.process({"route": "", "diameter": 6})


def test_a_solid_that_is_not_one_valid_solid_is_refused():
    """The check after the sweep, on shapes made to fail it."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.TopoDS import TopoDS_Builder, TopoDS_Compound

    builder, compound = TopoDS_Builder(), TopoDS_Compound()
    builder.MakeCompound(compound)
    builder.Add(compound, BRepPrimAPI_MakeBox(1, 1, 1).Shape())
    builder.Add(compound, BRepPrimAPI_MakeBox(gp_Pnt(5, 0, 0), 1, 1, 1).Shape())
    assert wrapper_route._defects(compound) == "the sweep made 2 solids, not one"
    assert wrapper_route._defects(BRepPrimAPI_MakeBox(1, 1, 1).Shape()) is None


def _section(shape, origin, normal):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
    from OCP.gp import gp_Dir, gp_Pln

    return BRepAlgoAPI_Section(shape, gp_Pln(gp_Pnt(*origin), gp_Dir(*normal))).Shape()


_C, _S = math.cos(0.7), math.sin(0.7)


def _half_turn_at(distance):
    return (
        EndFrame((0, 0, 0), (0, 0, 1), (1, 0, 0)),
        EndFrame((0, 0, distance), (0, 0, 1), (-0.999, 0.0447, 0)),
        EndFrame((0, 0, 200), (0, 0, -1), (1, 0, 0)),
    )


@pytest.mark.parametrize(
    "first, grommet, second, tolerance",
    [
        (*_half_turn_at(50), 1e-5),
        (*_half_turn_at(25), 1e-5),
        (*_half_turn_at(5), 1e-3),
        (
            EndFrame((50, 0, 0), (0, 1, 0), (0, 0, 1)),
            EndFrame((50 * _C, 50 * _S, 0), (-_S, _C, 0), (0.0447 * _C, 0.0447 * _S, -0.999)),
            EndFrame((0, 50, 0), (1, 0, 0), (0, 0, 1)),
            1e-5,
        ),
    ],
    ids=["half-turn-over-50mm", "half-turn-over-25mm", "half-turn-over-5mm", "arc"],
)
def test_a_flat_profile_meets_a_through_entry_turned_as_its_x_axis(first, grommet, second, tolerance):
    """The bound D6 states at a 'through' entry: 1e-5 rad for a roll of up to half
    a turn over 25 mm or more, straight or on an arc, and 1e-3 rad down to 5 mm."""
    shape = wrapper_route.process({"route": canonical_json([first, grommet, second]), "sketch": _rect(8, 2)})
    long_side = _longest_edge_direction(_section(shape, grommet.origin, grommet.z))
    x = grommet.x
    norm = math.sqrt(sum(c * c for c in x))
    alignment = abs(sum(a * b / norm for a, b in zip(long_side, x)))
    assert math.acos(min(1.0, alignment)) == pytest.approx(0.0, abs=tolerance)


def test_a_registered_route_names_the_part_by_its_digest(tmp_path):
    """D5: 'tube;route=<16 hex digits>', not tens of kilobytes of JSON."""
    ctx = _context(tmp_path)
    _, route = _quarter_route()
    _, other = _quarter_route(60.0)
    digest = ctx.register_route(route)
    assert ctx.register_route(route) == digest
    assert ctx.register_route(other) != digest
    tube = ctx.get_part(":tube", {"route": digest})
    assert tube.name == "tube;route=" + digest
    assert len(digest) == 16
    assert len(route) > 10000


def test_a_route_by_digest_is_built_as_the_route_itself(tmp_path):
    ctx = _context(tmp_path)
    _, route = _quarter_route()
    tube = ctx.get_part(":tube", {"route": ctx.register_route(route)})
    assert asyncio.run(tube.get_wrapped(ctx)) is not None
    assert tube.errors == []


def test_a_digest_this_build_has_not_registered_says_where_the_route_comes_from(tmp_path):
    ctx = _context(tmp_path)
    tube = ctx.get_part(":tube", {"route": "0123456789abcdef"})
    assert asyncio.run(tube.get_wrapped(ctx)) is None
    (error,) = tube.errors
    assert "route 0123456789abcdef is known only to the build of the assembly that places this part" in error
