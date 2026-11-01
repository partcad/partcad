#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The geometry of a wall, of the outline a room's walls follow, and of a one-sided drawing.

A wall is a one-sided surface: a face whose normal points to the side it is seen
from, with its doors and windows cut out of it by a sketch drawn as if the wall
were unrolled flat (see 'wrappers/wrapper_wall.py'). Everything about it that
matters is a number or a direction, so each is asked for here, directly of the
functions the sandbox runs - in this process, which has OCP: how much of the
wall is left once its openings are cut out (an arc keeps lengths along it, so
the same openings leave the same area on a curved wall as on a straight one),
which way every face of it looks, and the exact words a wall that cannot be
built is refused with.

The outline is read the same way ('wrappers/wrapper_outline.py'): one wall per
edge, clockwise whichever way the sketch was drawn, and a refusal with the
reason for anything that is not one closed loop of lines and arcs. And the
drawing ('wrappers/appearance.py'): a one-sided shape seen from behind is not
drawn, and a curved one is cut where it turns away.

The end-to-end half - a wall and a room built through PartCAD in a sandbox - is
'test_walls.py'.
"""

import importlib.util
import math
import os
import re
import sys

import pytest
from OCP.BRep import BRep_Builder
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_MakeEdge,
    BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_MakePolygon,
    BRepBuilderAPI_MakeWire,
)
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.GC import GC_MakeArcOfCircle
from OCP.Geom import Geom_BezierCurve
from OCP.gp import gp_Ax2, gp_Circ, gp_Dir, gp_Pnt
from OCP.GProp import GProp_GProps
from OCP.TColgp import TColgp_Array1OfPnt
from OCP.TopoDS import TopoDS_Compound

import partcad as pc
from partcad import output
from partcad.render import resolve_viewport

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import appearance  # noqa: E402
import ocp_serialize  # noqa: E402
import wrapper_export  # noqa: E402
import wrapper_outline  # noqa: E402
import wrapper_wall  # noqa: E402

LENGTH = 4000.0
HEIGHT = 2700.0
DOOR = (500.0, 0.0, 1400.0, 2100.0)
WINDOW = (2000.0, 900.0, 3200.0, 2000.0)
OPENED = LENGTH * HEIGHT - 900.0 * 2100.0 - 1200.0 * 1100.0


def _area(shape):
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, props)
    return props.Mass()


def _rectangle(x0, y0, x1, y1):
    polygon = BRepBuilderAPI_MakePolygon()
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        polygon.Add(gp_Pnt(x, y, 0.0))
    polygon.Close()
    return BRepBuilderAPI_MakeFace(polygon.Wire()).Face()


def _compound(*shapes):
    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    for shape in shapes:
        builder.Add(compound, shape)
    return compound


def _openings():
    return _compound(_rectangle(*DOOR), _rectangle(*WINDOW))


def _looks(shape):
    """'[(point, normal)]' of every face of 'shape', as plain tuples."""
    looks = []
    for face in wrapper_wall._explore(shape, "face"):
        point, normal = wrapper_wall.face_normal(face)
        looks.append(((point.X(), point.Y(), point.Z()), (normal.X(), normal.Y(), normal.Z())))
    return looks


def test_a_straight_wall_stands_on_the_x_axis_and_looks_along_minus_y():
    wall = wrapper_wall.build(LENGTH, HEIGHT)

    assert BRepCheck_Analyzer(wall).IsValid()
    assert _area(wall) == pytest.approx(LENGTH * HEIGHT)
    x_min, y_min, z_min, x_max, y_max, z_max = wrapper_wall._bounds(wall)
    assert (x_min, x_max, z_min, z_max) == pytest.approx((0.0, LENGTH, 0.0, HEIGHT), abs=1e-6)
    assert (y_min, y_max) == pytest.approx((0.0, 0.0), abs=1e-6)
    # Its front is where 'pc render --view front' looks from.
    [(_point, normal)] = _looks(wall)
    assert normal == pytest.approx((0.0, -1.0, 0.0), abs=1e-9)


def test_openings_are_cut_out_where_the_unrolled_drawing_puts_them():
    wall = wrapper_wall.build(LENGTH, HEIGHT, 0.0, _openings())

    assert BRepCheck_Analyzer(wall).IsValid()
    assert _area(wall) == pytest.approx(OPENED)
    # Still one face, looking the same way: a door stands on the floor and
    # leaves the wall in one piece.
    [(_point, normal)] = _looks(wall)
    assert normal == pytest.approx((0.0, -1.0, 0.0), abs=1e-9)


def test_a_door_as_tall_as_the_wall_leaves_two_walls_both_looking_the_same_way():
    wall = wrapper_wall.build(LENGTH, HEIGHT, 0.0, _compound(_rectangle(1000.0, 0.0, 2000.0, HEIGHT)))

    looks = _looks(wall)
    assert len(looks) == 2
    assert _area(wall) == pytest.approx((LENGTH - 1000.0) * HEIGHT)
    for _point, normal in looks:
        assert normal == pytest.approx((0.0, -1.0, 0.0), abs=1e-9)


@pytest.mark.parametrize("radius", [1500.0, -1500.0])
@pytest.mark.parametrize("openings", [False, True])
def test_an_arc_wall_keeps_its_length_and_its_openings_and_looks_to_its_front(radius, openings):
    """Half a circle each way. Bent towards its front it looks towards its axis; bent away, away from it."""
    length = math.pi * abs(radius)
    wall = wrapper_wall.build(length, HEIGHT, radius, _openings() if openings else None)

    assert BRepCheck_Analyzer(wall).IsValid()
    expected = length * HEIGHT - (900.0 * 2100.0 + 1200.0 * 1100.0 if openings else 0.0)
    assert _area(wall) == pytest.approx(expected, rel=1e-6)

    # It starts at the origin, setting off along +X, and bends towards the side
    # its radius says - its front, -Y, for a positive one: its axis is at
    # (0, -radius).
    x_min, y_min, _z_min, x_max, y_max, _z_max = wrapper_wall._bounds(wall)
    assert (x_min, x_max) == pytest.approx((0.0, abs(radius)), abs=1e-3)
    if radius > 0:
        assert (y_min, y_max) == pytest.approx((-2.0 * radius, 0.0), abs=1e-3)
    else:
        assert (y_min, y_max) == pytest.approx((0.0, -2.0 * radius), abs=1e-3)

    for point, normal in _looks(wall):
        towards_axis = (-point[0], -radius - point[1])
        dot = normal[0] * towards_axis[0] + normal[1] * towards_axis[1]
        assert (dot > 0) == (radius > 0), (point, normal)
        assert normal[2] == pytest.approx(0.0, abs=1e-9)


def test_a_round_wall_goes_once_around_and_no_further():
    radius = 1000.0
    wall = wrapper_wall.build(2.0 * math.pi * radius, HEIGHT, radius)
    assert _area(wall) == pytest.approx(2.0 * math.pi * radius * HEIGHT)

    with pytest.raises(wrapper_wall.WallError, match="goes once around at most"):
        wrapper_wall.build(2.0 * math.pi * radius + 1.0, HEIGHT, radius)


@pytest.mark.parametrize(
    "opening, where",
    [
        ((3500.0, 0.0, 4100.0, 2000.0), "X from 3500 to 4100"),
        ((0.0, -10.0, 100.0, 2000.0), "Y from -10 to 2000"),
        ((100.0, 2000.0, 900.0, 2800.0), "Y from 2000 to 2800"),
    ],
)
def test_an_opening_beyond_the_wall_is_an_error_that_says_how_far(opening, where):
    with pytest.raises(wrapper_wall.WallError) as raised:
        wrapper_wall.build(LENGTH, HEIGHT, 0.0, _compound(_rectangle(*opening)), "the openings sketch '//p:o'")
    message = str(raised.value)
    assert message.startswith("the openings sketch '//p:o' reaches beyond the wall")
    assert where in message
    assert "4000 mm long and 2700 mm high" in message


def test_an_opening_that_meets_an_edge_is_on_the_wall():
    """A door stands on the floor, to within a thousandth of a millimetre."""
    wall = wrapper_wall.build(LENGTH, HEIGHT, 0.0, _compound(_rectangle(0.0, -1e-4, 900.0, 2100.0)))
    assert _area(wall) == pytest.approx(LENGTH * HEIGHT - 900.0 * 2100.0, rel=1e-6)


def test_an_opening_on_another_plane_or_open_is_refused():
    lifted = BRepBuilderAPI_MakePolygon()
    for x, y, z in ((0, 0, 0), (100, 0, 0), (100, 100, 5), (0, 100, 5)):
        lifted.Add(gp_Pnt(x, y, z))
    lifted.Close()
    with pytest.raises(wrapper_wall.WallError, match="not drawn on the XY plane"):
        wrapper_wall.build(LENGTH, HEIGHT, 0.0, BRepBuilderAPI_MakeFace(lifted.Wire(), False).Face())

    three_sides = BRepBuilderAPI_MakePolygon()
    for x, y in ((0, 0), (100, 0), (100, 100), (0, 100)):
        three_sides.Add(gp_Pnt(x, y, 0))
    with pytest.raises(wrapper_wall.WallError, match="open wire"):
        wrapper_wall.build(LENGTH, HEIGHT, 0.0, three_sides.Wire())


def test_a_wall_needs_a_size_and_something_left_of_it():
    with pytest.raises(wrapper_wall.WallError, match="'length' is 0.0"):
        wrapper_wall.build(0.0, HEIGHT)
    with pytest.raises(wrapper_wall.WallError, match="'height' is -1.0"):
        wrapper_wall.build(LENGTH, -1.0)
    with pytest.raises(wrapper_wall.WallError, match="leave nothing of the wall"):
        wrapper_wall.build(LENGTH, HEIGHT, 0.0, _compound(_rectangle(0.0, 0.0, LENGTH, HEIGHT)))


# --------------------------------------------------------------------------- #
# The outline a room's walls follow                                           #
# --------------------------------------------------------------------------- #


def _outline(shape):
    return [
        (
            segment["kind"],
            tuple(round(value, 6) for value in segment["start"]),
            round(segment["heading"], 6) % 360.0,
            round(segment["length"], 6),
            round(segment["radius"], 6),
        )
        for segment in wrapper_outline.outline(shape, "the plan")
    ]


# Clockwise from the corner at the origin: up the west side first, so that the
# inside of the room is on every wall's right, which is its front.
RECTANGLE = [
    ("line", (0.0, 0.0), 90.0, 3000.0, 0.0),
    ("line", (0.0, 3000.0), 0.0, 4000.0, 0.0),
    ("line", (4000.0, 3000.0), 270.0, 3000.0, 0.0),
    ("line", (4000.0, 0.0), 180.0, 4000.0, 0.0),
]


def test_a_rectangle_is_four_walls_clockwise_whichever_way_it_was_drawn():
    anticlockwise = _rectangle(0.0, 0.0, 4000.0, 3000.0)  # as a basic sketch draws one
    polygon = BRepBuilderAPI_MakePolygon()
    for x, y in ((0, 0), (0, 3000), (4000, 3000), (4000, 0)):
        polygon.Add(gp_Pnt(x, y, 0))
    polygon.Close()
    clockwise = BRepBuilderAPI_MakeFace(polygon.Wire()).Face()

    assert _outline(anticlockwise) == RECTANGLE
    assert _outline(clockwise) == RECTANGLE
    # A closed wire is the same outline as the face it bounds.
    assert _outline(polygon.Wire()) == RECTANGLE


def test_a_circle_is_one_wall_all_the_way_round_bending_into_the_room():
    edge = BRepBuilderAPI_MakeEdge(gp_Circ(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 2000.0)).Edge()
    [(kind, start, heading, length, radius)] = _outline(BRepBuilderAPI_MakeWire(edge).Wire())

    assert (kind, start, heading, radius) == ("arc", (2000.0, 0.0), 270.0, 2000.0)
    assert length == pytest.approx(2.0 * math.pi * 2000.0)


def _wire(*edges):
    maker = BRepBuilderAPI_MakeWire()
    for edge in edges:
        maker.Add(edge)
    return maker.Wire()


def _line(a, b):
    return BRepBuilderAPI_MakeEdge(gp_Pnt(*a, 0.0), gp_Pnt(*b, 0.0)).Edge()


def _arc(a, through, b):
    return BRepBuilderAPI_MakeEdge(
        GC_MakeArcOfCircle(gp_Pnt(*a, 0.0), gp_Pnt(*through, 0.0), gp_Pnt(*b, 0.0)).Value()
    ).Edge()


def test_an_arc_that_bulges_out_bends_towards_the_room_and_one_that_bulges_in_bends_away():
    """Clockwise, a rounded corner bends to the right, into the room it faces; a column bends away from it."""
    corner = math.sqrt(0.5) * 1000.0
    rounded = _wire(
        _line((0, 0), (4000, 0)),
        _arc((4000, 0), (4000 + corner, 1000 - corner), (5000, 1000)),
        _line((5000, 1000), (5000, 3000)),
        _line((5000, 3000), (0, 3000)),
        _line((0, 3000), (0, 0)),
    )
    walls = _outline(rounded)
    [arc] = [wall for wall in walls if wall[0] == "arc"]
    assert arc[4] == pytest.approx(1000.0)
    assert arc[3] == pytest.approx(math.pi * 500.0)

    column = _wire(
        _line((0, 0), (2000, 0)),
        _arc((2000, 0), (2500, 500), (3000, 0)),
        _line((3000, 0), (4000, 0)),
        _line((4000, 0), (4000, 3000)),
        _line((4000, 3000), (0, 3000)),
        _line((0, 3000), (0, 0)),
    )
    walls = _outline(column)
    [arc] = [wall for wall in walls if wall[0] == "arc"]
    assert arc == ("arc", (3000.0, 0.0), 90.0, pytest.approx(math.pi * 500.0), -500.0)


def test_loose_edges_that_close_are_joined_into_one_outline():
    edges = [_line((0, 0), (10, 0)), _line((10, 10), (0, 10)), _line((10, 0), (10, 10)), _line((0, 10), (0, 0))]
    assert len(_outline(_compound(*edges))) == 4


def test_anything_but_one_closed_loop_of_lines_and_arcs_is_refused_with_the_reason():
    room = _rectangle(0.0, 0.0, 4000.0, 3000.0)
    with pytest.raises(wrapper_outline.OutlineError, match="the plan has a hole in it"):
        wrapper_outline.outline(BRepAlgoAPI_Cut(room, _rectangle(1000, 1000, 2000, 2000)).Shape(), "the plan")
    with pytest.raises(wrapper_outline.OutlineError, match="the plan has 2 faces"):
        wrapper_outline.outline(_compound(room, _rectangle(5000, 0, 6000, 1000)), "the plan")
    with pytest.raises(wrapper_outline.OutlineError, match="the plan is an open outline"):
        wrapper_outline.outline(_line((0, 0), (1000, 0)), "the plan")

    points = TColgp_Array1OfPnt(1, 3)
    for index, (x, y) in enumerate(((0, 0), (500, 500), (1000, 0)), 1):
        points.SetValue(index, gp_Pnt(x, y, 0))
    spline = BRepBuilderAPI_MakeEdge(Geom_BezierCurve(points)).Edge()
    # Numbered in the order the walk meets the edges, which is the order the
    # walls would have been named in ('wall-<n>').
    with pytest.raises(wrapper_outline.OutlineError, match=r"edge \d of the plan is a Bezier curve"):
        wrapper_outline.outline(_wire(spline, _line((1000, 0), (0, 0))), "the plan")

    lifted = BRepBuilderAPI_MakePolygon()
    for x, y, z in ((0, 0, 0), (100, 0, 0), (100, 100, 5), (0, 100, 5)):
        lifted.Add(gp_Pnt(x, y, z))
    lifted.Close()
    with pytest.raises(wrapper_outline.OutlineError, match="not drawn on the XY plane"):
        wrapper_outline.outline(lifted.Wire(), "the plan")


# --------------------------------------------------------------------------- #
# A one-sided shape, drawn                                                    #
# --------------------------------------------------------------------------- #


def test_a_one_sided_face_seen_from_behind_is_not_drawn():
    wall = wrapper_wall.build(LENGTH, HEIGHT)
    # It looks along -Y: seen from -Y it is there, from +Y it is not, and from
    # straight above - edge-on - it is the line a plan draws it as.
    assert _area(appearance.without_backs(wall, (0, -100, 0))) == pytest.approx(LENGTH * HEIGHT)
    assert _area(appearance.without_backs(wall, (100, -100, 100))) == pytest.approx(LENGTH * HEIGHT)
    assert appearance._faces(appearance.without_backs(wall, (0, 100, 0))) == []
    assert appearance._faces(appearance.without_backs(wall, (100, 100, 100))) == []
    assert _area(appearance.without_backs(wall, (0, 0, 100))) == pytest.approx(LENGTH * HEIGHT)


def test_a_round_wall_is_drawn_as_the_half_of_it_that_faces_the_camera():
    """Cut along its silhouette: the near half of a round room goes, the far half stays."""
    radius = 1000.0
    wall = wrapper_wall.build(2.0 * math.pi * radius, HEIGHT, radius)
    full = 2.0 * math.pi * radius * HEIGHT

    for origin in ((100, -100, 100), (0, -100, 0), (-30, 70, 10)):
        drawn = appearance.without_backs(wall, origin)
        assert _area(drawn) == pytest.approx(full / 2.0, rel=1e-6), origin
    # Looked at along its axis, every point of it is edge-on: all of it is the plan.
    assert _area(appearance.without_backs(wall, (0, 0, 100))) == pytest.approx(full, rel=1e-6)


def test_only_a_tree_that_says_so_is_drawn_one_sided():
    wall = wrapper_wall.build(LENGTH, HEIGHT)
    # A leaf as a decoded tree carries it: its payload, and the shape decoded from it.
    leaf = {ocp_serialize.KEY_BREP: "unused", ocp_serialize.KEY_SHAPE: wall}
    plain = {**leaf, "properties": {"color": "#E4DED4"}}
    one_sided = {**leaf, "properties": {appearance.ONE_SIDED_KEY: True}}
    room = {ocp_serialize.KEY_ASSEMBLY: [plain], "properties": {appearance.ONE_SIDED_KEY: True}}
    undone = {ocp_serialize.KEY_ASSEMBLY: [{**one_sided, "properties": {appearance.ONE_SIDED_KEY: False}}]}

    assert not appearance.has_one_sided(plain)
    assert appearance.has_one_sided(one_sided)
    # Inherited the way a colour is, and stated off the way one is stated over.
    assert appearance.has_one_sided(room)
    assert not appearance.has_one_sided(undone)

    # A tree with nothing one-sided in it is drawn exactly as it was: the very
    # shape it was handed, as its one group.
    whole, groups = appearance.split_for_view(plain, wall, (0, -100, 0))
    assert whole is wall and groups == [("#E4DED4", wall)]

    # One that has is drawn without the faces the camera sees from behind.
    whole, groups = appearance.split_for_view(one_sided, wall, (0, -100, 0))
    assert _area(whole) == pytest.approx(LENGTH * HEIGHT)
    assert [color for color, _shape in groups] == [appearance.DEFAULT_COLOR]

    # And a drawing of nothing but its back is refused, saying which way to look.
    with pytest.raises(ValueError, match="nothing faces the camera.*'--view front'"):
        appearance.split_for_view(one_sided, wall, (0, 100, 0))


# --------------------------------------------------------------------------- #
# A room, drawn by the real renderer                                          #
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def real_svg():
    """'render_svg.py' with the real kernel, as the sandbox runs it."""
    spec = importlib.util.spec_from_file_location(
        "partcad.builtin.render.render_svg",
        os.path.join(output.BUILTIN_PATHS[output.BUILTIN_PACKAGES[output.RENDER]], "render_svg.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _room(one_sided=True):
    """A 4 x 3 m room as the 'walls' scene places it, four walls looking in, as the tree a renderer is handed.

    Its second wall - the north one, from (0, 3000) to (4000, 3000) - has a
    window in the middle of it: 1000 mm wide and high, 1000 mm off the floor,
    which puts it between X = 1500 and 2500 seen from the front.
    """
    walls = []
    for index, (_kind, (x, y), heading, length, _radius) in enumerate(RECTANGLE):
        window = _compound(_rectangle(1500.0, 1000.0, 2500.0, 2000.0)) if index == 1 else None
        node = ocp_serialize.encode(wrapper_wall.build(length, HEIGHT, 0.0, window))
        node[ocp_serialize.KEY_LOCATION] = [[x, y, 0.0], [0.0, 0.0, 1.0], heading]
        if one_sided:
            node["properties"] = {appearance.ONE_SIDED_KEY: True}
        walls.append(node)
    return {"name": "room", ocp_serialize.KEY_ASSEMBLY: walls}


def _lines(real_svg, tmp_path, tree, view):
    path = str(tmp_path / "room.svg")
    request = {"wrapped": tree, "shape_kind": "scene", "reproducible": True}
    request.update(resolve_viewport(view))
    result = real_svg.process(path, wrapper_export.decode(request))
    assert result["success"], result
    with open(path, encoding="utf-8") as f:
        svg = f.read()
    return [
        tuple(float(value) for value in line)
        for line in re.findall(r'<line x1="([^"]+)" y1="([^"]+)" x2="([^"]+)" y2="([^"]+)"', svg)
    ]


def _verticals(lines, longer_than):
    """The X of every vertical line on the page longer than 'longer_than', relative to the leftmost, rounded."""
    xs = [x1 for x1, y1, x2, y2 in lines if abs(x1 - x2) < 1e-6 and abs(y2 - y1) > longer_than]
    return sorted({round(x - min(xs), 1) for x in xs}) if xs else []


def test_a_room_drawn_from_the_front_shows_the_window_in_its_far_wall(real_svg, tmp_path):
    """From the front the south wall turns its back on the camera, and is looked through.

    Two-sided, it is all there is to see: a 4000 x 2700 rectangle hiding the
    rest of the room, window and all. One-sided, the same rectangle is drawn -
    it is the north wall now, with the side walls seen edge-on at either end -
    and so is the window in the middle of it.
    """
    two_sided = _lines(real_svg, tmp_path, _room(one_sided=False), "front")
    one_sided = _lines(real_svg, tmp_path, _room(), "front")

    assert _verticals(two_sided, 900.0) == [0.0, 4000.0]
    assert _verticals(one_sided, 900.0) == [0.0, 1500.0, 2500.0, 4000.0]


def test_a_room_seen_from_above_is_its_plan(real_svg, tmp_path):
    """Every wall is edge-on from straight above, and kept: the drawing is the outline, all four sides of it.

    Nothing but the outline - a wall's top and bottom edges are both on it, one
    over the other - and all of it: the length drawn along each side is at least
    that side.
    """
    lines = _lines(real_svg, tmp_path, _room(), "top")
    x0 = min(min(x1, x2) for x1, _y1, x2, _y2 in lines)
    y0 = min(min(y1, y2) for _x1, y1, _x2, y2 in lines)
    sides = {"x=0": 0.0, "x=4000": 0.0, "y=0": 0.0, "y=3000": 0.0}
    for x1, y1, x2, y2 in lines:
        x1, x2, y1, y2 = x1 - x0, x2 - x0, y1 - y0, y2 - y0
        length = math.hypot(x2 - x1, y2 - y1)
        on = [
            name
            for name, (a, b, at) in {
                "x=0": (x1, x2, 0.0),
                "x=4000": (x1, x2, 4000.0),
                "y=0": (y1, y2, 0.0),
                "y=3000": (y1, y2, 3000.0),
            }.items()
            if abs(a - at) < 1e-3 and abs(b - at) < 1e-3
        ]
        assert on, "a line off the outline: %s" % ((x1, y1, x2, y2),)
        sides[on[0]] += length
    assert sides["x=0"] >= 3000.0 - 1e-3 and sides["x=4000"] >= 3000.0 - 1e-3, sides
    assert sides["y=0"] >= 4000.0 - 1e-3 and sides["y=3000"] >= 4000.0 - 1e-3, sides


def test_a_room_seen_from_a_corner_is_drawn_without_its_near_corner(real_svg, tmp_path):
    """From the front right, above: the north and west walls face the camera, the south and east do not.

    The room has no ceiling, so from above its far corner, at (0, 3000), shows
    over the near walls either way. What one-sidedness changes is the near
    corner, at (4000, 0), where the two walls that turn their backs on the
    camera meet: two-sided it is drawn floor to ceiling in front of everything,
    and one-sided it is not there at all. Across the page the camera's right is
    (1, 1, 0) / sqrt(2), so it is 4000 / sqrt(2) from the corner at (0, 0), and
    the far corner 3000 / sqrt(2).
    """
    two_sided = _verticals(_lines(real_svg, tmp_path, _room(one_sided=False), "iso"), 1500.0)
    one_sided = _verticals(_lines(real_svg, tmp_path, _room(), "iso"), 1500.0)

    near = round(4000.0 / math.sqrt(2.0), 1)
    far = round(3000.0 / math.sqrt(2.0), 1)
    assert near in two_sided
    assert near not in one_sided
    assert far in one_sided
