#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""End to end: walls and rooms, built through PartCAD in a sandbox.

A wall is a 'type: wall' part - with no thickness a one-sided surface drawn to
lay out a space, with one the solid behind that surface - and a room is a 'type:
walls' scene, the walls standing on the outline of a sketch. PartCAD ships one of
each in '//builtin/building', and its wall is a solid drawn as its private
surface. What is held here is what PartCAD does with them rather than the
geometry, which 'test_wall_geometry.py' asks of the sandbox's own functions
directly:

  * a wall with no thickness is a surface by its type - an alias of one too - and
    is passed over by the checks that ask whether a part is a body, never
    validated into a solid, and drawn one-sided ('surface.py'); one with a
    thickness is a solid held to being one;
  * a wall has to say it is not manufacturable, and nothing manufacturable can be
    made with one in it;
  * a room is one wall per edge of its sketch, placed along it, and a sketch that
    is not one closed loop of lines and arcs is refused with the reason;
  * PartCAD's own wall is a solid whose 'visual:' is its surface, private to
    '//builtin/building': a picture draws the surface, everything else the solid,
    and no other package can build a room of the surface.

The package declares no requirements of its own, so it renders in the CAD
sandbox the other part tests provision rather than building one.
"""

import asyncio
import math
import os
import re
import sys
import textwrap
import threading
import types

import pytest

import partcad as pc
from partcad import cmf, output, surface
from partcad.qual.basic.degenerate import DegenerateTest
from partcad.qual.basic.manufacturability import ManufacturabilityTest
from partcad.qual.basic.shell import ShellTest
from partcad.qual.basic.solidity import SolidityTest
from partcad.qual.basic.validity import ValidityTest
from partcad.qual.qualification import Qualification
from partcad.scene_factory_walls import SceneFactoryWalls

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import ocp_serialize  # noqa: E402

CONFIG = """
manufacturable: false

colors:
  sage:
    display: "#7D8F69"
    manufacturable: false

sketches:
  plan:
    type: basic
    rectangle: {x: 2000, y: 1500, side-x: 4000, side-y: 3000}
  round:
    type: basic
    circle: 2000
  holed:
    type: basic
    rectangle: {x: 2000, y: 1500, side-x: 4000, side-y: 3000}
    inner:
      circle: {x: 2000, y: 1500, radius: 200}
  door:
    type: basic
    rectangle: {x: 1450, y: 1050, side-x: 900, side-y: 2100}
  too-wide:
    type: basic
    rectangle: {x: 3900, y: 1050, side-x: 900, side-y: 2100}
  kept-door:
    type: basic
    private: true
    rectangle: {x: 1450, y: 1050, side-x: 900, side-y: 2100}
  ell:
    type: build123d
    path: ell.py
  bayed:
    type: build123d
    path: bayed.py

parts:
  north:
    type: wall
    length: 4000
    height: 2700
    openings: door
  broken-window:
    type: wall
    length: 4000
    height: 2700
    openings: too-wide
  curved:
    type: alias
    source: "//builtin/building:wall;length=3141.592654,radius=-1000,thickness=0"
  thick-north:
    type: wall
    length: 4000
    height: 2700
    openings: door
    thickness: 200
  thick-curved:
    type: alias
    source: "//builtin/building:wall;length=3141.592654,radius=-1000"
  too-thick:
    type: wall
    length: 3000
    height: 2700
    radius: -150
    thickness: 200
  surface-alias:
    type: alias
    source: //builtin/building:wall-surface
  own-kept-door:
    type: wall
    length: 4000
    height: 2700
    openings: kept-door
  builtin-kept-door:
    type: enrich
    source: //builtin/building:wall
    with:
      length: 4000
      height: 2700
      openings: //:kept-door

scenes:
  living:
    type: walls
    sketch: plan
    height: 2500
  rotunda:
    type: enrich
    source: //builtin/building:room
    with:
      sketch: //:round
      height: 3000
  courtyard:
    type: walls
    sketch: holed
    height: 2500
  painted:
    type: enrich
    source: //builtin/building:room
    with:
      sketch: //:plan
      color: //:sage
  thick-living:
    type: walls
    sketch: plan
    height: 2500
    thickness: 250
  of-surfaces:
    type: walls
    sketch: plan
    height: 2500
    wall: //builtin/building:wall-surface
  ell-room:
    type: walls
    sketch: ell
    height: 2500
  bayed-room:
    type: walls
    sketch: bayed
    height: 2500
"""

# An L from above: five outside corners and one inside one.
ELL = """
import build123d as bd

with bd.BuildSketch() as ell:
    with bd.BuildLine():
        bd.Polyline((0, 0), (4000, 0), (4000, 2000), (2000, 2000), (2000, 4000), (0, 4000), close=True)
    bd.make_face()

if "show_object" in locals():
    show_object(ell.sketch)
"""

# A room with a bay bulging out of its east wall and a column cut into its south
# one: four corners where an arc meets a straight wall at a right angle.
BAYED = """
import build123d as bd

with bd.BuildSketch() as bayed:
    with bd.BuildLine():
        bd.Line((0, 0), (2000, 0))
        bd.ThreePointArc((2000, 0), (2300, 300), (2600, 0))
        bd.Line((2600, 0), (4000, 0))
        bd.Line((4000, 0), (4000, 1000))
        bd.ThreePointArc((4000, 1000), (5000, 2000), (4000, 3000))
        bd.Line((4000, 3000), (4000, 4000))
        bd.Line((4000, 4000), (0, 4000))
        bd.Line((0, 4000), (0, 0))
    bd.make_face()

if "show_object" in locals():
    show_object(bayed.sketch)
"""

# A package that is manufacturable, as a package is unless it says otherwise.
MADE = """
parts:
  north:
    type: wall
    length: 4000
    height: 2700
  wall-said-so:
    type: wall
    manufacturable: false
    length: 4000
    height: 2700
"""


@pytest.fixture(scope="module")
def package(tmp_path_factory):
    root = tmp_path_factory.mktemp("walls_package")
    (root / "partcad.yaml").write_text(textwrap.dedent(CONFIG).lstrip())
    (root / "ell.py").write_text(textwrap.dedent(ELL).lstrip())
    (root / "bayed.py").write_text(textwrap.dedent(BAYED).lstrip())
    return root


@pytest.fixture(scope="module")
def context(package):
    return pc.Context(str(package))


def _built(context, name, kind="part"):
    shape = context.get_scene(name) if kind == "scene" else context.get_part(name)
    assert shape is not None, name
    envelope = asyncio.run(shape.get_wrapped(context))
    return shape, envelope


def test_a_wall_is_built_one_sided_with_its_openings_cut_out(context):
    wall, envelope = _built(context, "north")
    assert wall.errors == [], wall.errors

    assert surface.is_surface(wall)
    assert wall._shape_properties() == {"oneSided": True}
    shape = ocp_serialize.decode_shape(envelope)
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, props)
    assert props.Mass() == pytest.approx(4000.0 * 2700.0 - 900.0 * 2100.0)


def test_a_wall_is_never_asked_to_become_a_solid(context):
    wall = context.get_part("north")
    assert "validate" not in wall.finish_request()
    assert not wall._validates()


def test_an_opening_beyond_the_wall_is_an_error_naming_the_sketch_and_the_overhang(context):
    wall, envelope = _built(context, "broken-window")
    assert envelope is None
    [error] = wall.errors
    assert "the openings sketch '//:too-wide' reaches beyond the wall" in error
    assert "X from 3450 to 4350" in error


def test_the_builtin_wall_is_a_parametric_wall_in_its_own_colour(context):
    """A solid, 4.5 in (114.3 mm) thick behind its face, which is on the XZ plane: what a room is walled with."""
    wall, _envelope = _built(context, "//builtin/building:wall;length=2000")
    assert wall.errors == []
    assert wall._shape_properties() == {"color": "#9C9284"}
    assert not surface.is_surface(wall)
    box = asyncio.run(wall.get_bounding_box_async(context))
    assert box == pytest.approx((0.0, 0.0, 0.0, 2000.0, 114.3, 2700.0), abs=1e-6)


def _volume(envelope):
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(ocp_serialize.decode_shape(envelope), props)
    return props.Mass()


def test_a_thick_wall_is_its_elevation_extruded_back_through_its_thickness(context):
    """The face where a surface wall would be, the openings through it, and the thickness behind it."""
    wall, envelope = _built(context, "thick-north")
    assert wall.errors == [], wall.errors
    assert not surface.is_surface(wall)
    assert wall._shape_properties() is None
    # A body, so held to being one as it leaves the wrapper.
    assert wall._validates() and "validate" in wall.finish_request()
    assert _volume(envelope) == pytest.approx((4000.0 * 2700.0 - 900.0 * 2100.0) * 200.0, rel=1e-6)
    box = asyncio.run(wall.get_bounding_box_async(context))
    assert box == pytest.approx((0.0, 0.0, 0.0, 4000.0, 200.0, 2700.0), abs=1e-6)
    for check in (ShellTest, DegenerateTest, SolidityTest, ValidityTest):
        assert check().inapplicable(wall) is None, check


def test_a_thick_arc_wall_is_extruded_along_its_radius(context):
    """Bending away from its face, an arc wall's thickness is towards its axis: a ring sector, 114.3 thick."""
    wall, envelope = _built(context, "thick-curved")
    assert wall.errors == [], wall.errors
    assert not surface.is_surface(wall)
    # Half a turn of a ring between radii 885.7 and 1000, 2700 high.
    assert _volume(envelope) == pytest.approx(math.pi * (1000.0**2 - 885.7**2) / 2.0 * 2700.0, rel=1e-4)


def test_an_arc_wall_thicker_than_its_radius_behind_its_face_is_refused(context):
    wall, envelope = _built(context, "too-thick")
    assert envelope is None
    [error] = wall.errors
    assert "thinner than that: 'thickness' is 200 mm" in error


def test_an_alias_of_a_wall_is_a_wall(context):
    """It states no properties and no type of its own, and is one-sided and a surface all the same.

    Of PartCAD's own wall with no thickness: a surface, whatever it is drawn as.
    And it is in the colour of the wall it is another name for: a reference
    reports what its source turned out to be.
    """
    alias, envelope = _built(context, "curved")
    assert envelope is not None and alias.errors == []
    assert surface.surface_type(alias) == "wall"
    source = context.get_part(alias.config["source_resolved"])
    assert alias._shape_properties() == {"oneSided": True, "color": source._shape_properties()["color"]}


@pytest.mark.parametrize("check", [ShellTest, DegenerateTest, SolidityTest, ValidityTest])
@pytest.mark.parametrize("name", ["north", "curved"])
def test_the_checks_that_ask_for_a_body_pass_a_wall_over_and_say_why(context, check, name):
    wall = context.get_part(name)
    test = check()

    reason = test.inapplicable(wall)
    assert reason is not None and "surface by its type ('wall')" in reason
    assert asyncio.run(test.test([], context, wall, {})) == Qualification.TEST_PASSED


def test_a_wall_has_to_say_it_is_not_manufacturable(tmp_path):
    (tmp_path / "partcad.yaml").write_text(textwrap.dedent(MADE).lstrip())
    pc.logging.reset_errors()
    project = pc.Context(str(tmp_path)).get_project("//")

    assert project.get_part("north") is None
    reason = project.get_broken_object_reason("part", "north")
    assert "add 'manufacturable: false' to it, or to its package" in reason
    assert pc.logging.had_errors is True

    # Said on the part, in a package that is otherwise manufacturable, it is.
    assert project.get_part("wall-said-so") is not None


def test_nothing_manufacturable_can_be_made_of_a_wall(context):
    """Asked for as part of something that is to be made, a wall fails rather than passing over."""
    wall = context.get_part("north")
    test = ManufacturabilityTest()
    assert test.inapplicable(wall) is not None
    verdict = asyncio.run(test.test([], context, wall, {"force_manufacturing": True}))
    assert verdict == Qualification.TEST_FAILED


def _walls(context, name):
    scene, envelope = _built(context, name, kind="scene")
    assert scene.errors == [], scene.errors
    assert envelope is not None
    return [
        (node["label"], node["name"], node.get("location"), node.get("properties"))
        for node in envelope[ocp_serialize.KEY_ASSEMBLY]
    ]


def test_a_room_is_a_wall_per_edge_of_its_sketch_each_looking_in(context):
    walls = _walls(context, "living")

    assert [label for label, _name, _location, _properties in walls] == ["wall-1", "wall-2", "wall-3", "wall-4"]
    lengths = []
    for _label, name, location, properties in walls:
        assert name.startswith("//builtin/building:wall;")
        assert "height=2500" in name
        assert "radius=0.0" in name
        # Asked for with no thickness: the wall's own, 114.3 mm, stands.
        assert "thickness" not in name
        # Solids: the surface is what a picture draws, and no part of the scene.
        assert "oneSided" not in properties
        lengths.append(float(name.split("length=")[1].split(",")[0]))
    assert sorted(lengths) == [3000.0, 3000.0, 4000.0, 4000.0]

    # Each stands where its edge starts, and the four corners are the plan's.
    corners = sorted((round(location[0][0], 6), round(location[0][1], 6)) for _l, _n, location, _p in walls)
    assert corners == [(0.0, 0.0), (0.0, 3000.0), (4000.0, 0.0), (4000.0, 3000.0)]


def test_a_round_room_is_one_wall_once_around(context):
    [(label, name, location, _properties)] = _walls(context, "rotunda")

    assert label == "wall-1"
    assert "radius=2000.0" in name
    assert float(name.split("length=")[1].split(",")[0]) == pytest.approx(2.0 * math.pi * 2000.0, abs=1e-5)
    assert location[0][:2] == pytest.approx([2000.0, 0.0])


def test_a_sketch_with_a_hole_in_it_is_refused_with_the_reason(context):
    scene = context.get_scene("courtyard")
    with pytest.raises(Exception, match="has a hole in it; walls follow a single enclosed outline"):
        asyncio.run(scene.get_wrapped(context))


def test_the_builtin_room_says_it_needs_a_sketch(context):
    pc.logging.reset_errors()
    assert context.get_scene("//builtin/building:room") is None
    project = context.get_project(output.BUILTIN_BUILDING_PACKAGE)
    reason = project.get_broken_object_reason("scene", "room")
    assert "names none: give it a 'sketch', as 'room;sketch=//package:sketch'" in reason


def test_the_builtin_wall_is_drawn_in_a_colour_it_declares_and_does_not_claim(context):
    """Its grey is a CMF colour of '//builtin/building', display-only: a wall is never made."""
    wall = context.get_part("//builtin/building:wall")
    assert cmf.own_parameters(wall, context) == {"color": "//builtin/building:wall"}
    colors = context.get_project(output.BUILTIN_BUILDING_PACKAGE).config_obj["colors"]
    assert colors["wall"]["display"] == "#9C9284"
    assert colors["wall"]["manufacturable"] is False


def test_a_painted_room_paints_every_wall(context):
    """A room's own colour is every wall's, over the grey the wall it is built of states.

    With the wall itself asked for first, in the same context: making it records
    its grey in the declaration every wall of the room is copied from, and a
    room used to come out grey once it had been (see
    'Project._remember_declared_properties').
    """
    assert context.get_part("//builtin/building:wall")._shape_properties()["color"] == "#9C9284"

    walls = _walls(context, "painted")

    assert len(walls) == 4
    for _label, name, _location, properties in walls:
        assert "color=//:sage" in name
        assert properties["color"] == "#7D8F69"
        assert "oneSided" not in properties

    # And a room nobody painted is the walls' own grey.
    for _label, _name, _location, properties in _walls(context, "living"):
        assert properties["color"] == "#9C9284"


def test_a_room_that_states_a_thickness_passes_it_to_every_wall(context):
    walls = _walls(context, "thick-living")
    assert len(walls) == 4
    for _label, name, _location, _properties in walls:
        assert "thickness=250.0" in name


def test_a_room_is_drawn_as_the_surfaces_of_its_walls_and_is_walled_all_the_same(context):
    """The tree a picture draws: every wall the private surface, where the wall is; the scene itself, solids."""
    from partcad import visual

    scene, envelope = _built(context, "living", kind="scene")
    drawn = asyncio.run(visual.substitute_async(context, scene, envelope))
    nodes = drawn.tree[ocp_serialize.KEY_ASSEMBLY]
    assert len(nodes) == 4
    for before, after in zip(envelope[ocp_serialize.KEY_ASSEMBLY], nodes):
        # Where the wall is, under its own name and link: what the 3D view selects.
        assert after["label"] == before["label"]
        assert after["name"] == before["name"]
        assert after["location"] == before["location"]
        # Drawn as the surface, with the wall's own length and colour.
        assert after["visual"].startswith("//builtin/building:wall-surface;")
        assert "length=%s" % before["name"].split("length=")[1].split(",")[0] in after["visual"]
        assert after["properties"] == {"color": "#9C9284", "oneSided": True}
        assert "visual" not in before
    # The surfaces are what the picture is keyed on, besides the scene.
    assert drawn.keys and all(name.startswith("//builtin/building:wall-surface;") for name, _key in drawn.keys)
    assert drawn.cacheable
    # And the scene itself is still the solids it was.
    assert all("oneSided" not in node["properties"] for node in envelope[ocp_serialize.KEY_ASSEMBLY])


def test_the_surface_of_a_wall_is_private_to_the_building_package(context, caplog):
    """A room of surfaces, or an alias of one, in another package is refused, naming why; a command still reaches it."""
    refusal = (
        "A part '//builtin/building:wall-surface' is private to //builtin/building, "
        "and a reference written in // cannot name it"
    )
    scene = context.get_scene("of-surfaces")
    with pytest.raises(Exception):
        asyncio.run(scene.get_wrapped(context))
    # Each wall, as the instance the room asked for.
    assert re.search(
        r"A part '//builtin/building:wall-surface;height=2500\.0,length=\d+\.0,radius=0\.0' is private to "
        r"//builtin/building, and a reference written in // cannot name it",
        caplog.text,
    )

    caplog.clear()
    alias = context.get_part("surface-alias")
    with pytest.raises(Exception, match="The alias source //builtin/building:wall-surface is not found"):
        asyncio.run(alias.get_wrapped(context))
    assert refusal in caplog.text

    # A command names it to look at it, and is not a reference.
    assert context.get_part("//builtin/building:wall-surface") is not None
    assert context.get_part("//builtin/building:wall-surface", referrer=context.get_project("//").name) is None


def test_a_private_sketch_cuts_this_package_s_walls_and_no_other_package_s(context, caplog):
    """The openings of a 'type: wall' part of the sketch's own package, but not of an enrich of PartCAD's wall.

    That instance is '//builtin/building''s, which any package may ask for by
    name: the reference to the sketch is written there, and is refused.
    """
    own, envelope = _built(context, "own-kept-door")
    assert envelope is not None and own.errors == []
    caplog.clear()
    _borrowed, envelope = _built(context, "builtin-kept-door")
    assert envelope is None
    assert (
        "A sketch '//:kept-door' is private to //, and a reference written in //builtin/building cannot name it"
        in caplog.text
    )


def _corners_closed(context, name, thickness, height, ring):
    """The walls of 'name' fill the ring of 'ring' square millimetres around its plan exactly: no gap, no overlap."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common

    _scene, envelope = _built(context, name, kind="scene")
    solids = [ocp_serialize.decode_shape(node) for node in envelope[ocp_serialize.KEY_ASSEMBLY]]
    assert sum(_volume_of(solid) for solid in solids) == pytest.approx(ring * height, rel=1e-6)
    for i, first in enumerate(solids):
        for second in solids[i + 1 :]:
            assert _volume_of(BRepAlgoAPI_Common(first, second).Shape()) == pytest.approx(0.0, abs=1e-3)


def _volume_of(shape):
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def test_the_walls_of_a_rectangular_room_meet_at_its_corners_with_nothing_missing_and_nothing_in_both(context):
    """4000 x 3000, walls 250 thick outside it: the ring between it and the rectangle 250 bigger all round."""
    walls = _walls(context, "thick-living")
    for _label, name, _location, _properties in walls:
        assert "extendEnd=250.0" in name and "extendStart" not in name
    _corners_closed(context, "thick-living", 250.0, 2500.0, (4500.0 * 3500.0) - (4000.0 * 3000.0))


def test_the_walls_of_an_l_shaped_room_close_its_outside_corners_and_do_not_meet_twice_inside(context):
    """Five outside corners and an inside one, with PartCAD's own 114.3 mm: the outline grown by it, less the outline."""
    t = 114.3
    walls = _walls(context, "ell-room")
    assert sorted(name.split("extendEnd=")[1].split(",")[0] for _l, name, _p, _q in walls) == ["-114.3"] + ["114.3"] * 5
    perimeter = 2 * (4000.0 + 4000.0)
    _corners_closed(context, "ell-room", t, 2500.0, perimeter * t + (5 - 1) * t * t)


def test_where_a_bay_or_a_column_meets_a_wall_the_walls_neither_overlap_nor_leave_the_corner_open(context):
    """The arcs stay as they are and the straight walls beside them move: nothing in both, the column's corners filled.

    The bay's ends are inside corners, where its thickness and the straight
    wall's would fill one square; the column's are outside corners, where they
    would leave one open, below the south wall's line.
    """
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_IN

    t = 114.3
    _scene, envelope = _built(context, "bayed-room", kind="scene")
    solids = [ocp_serialize.decode_shape(node) for node in envelope[ocp_serialize.KEY_ASSEMBLY]]
    assert len(solids) == 8
    for i, first in enumerate(solids):
        for second in solids[i + 1 :]:
            assert _volume_of(BRepAlgoAPI_Common(first, second).Shape()) == pytest.approx(0.0, abs=1e-3)

    def filled(x, y):
        point = gp_Pnt(x, y, 1250.0)
        return any(BRepClass3d_SolidClassifier(solid, point, 1e-6).State() == TopAbs_IN for solid in solids)

    assert filled(2000.0 + t / 2, -t / 2) and filled(2600.0 - t / 2, -t / 2)
    # And the bay's corners are still walled, by the arc's thickness.
    assert filled(4000.0 + t / 2, 3000.0 + t / 4) and filled(4000.0 + t / 2, 1000.0 - t / 4)


def test_a_picture_of_a_room_draws_its_surfaces_on_the_outline_whatever_its_corners_did(context):
    """The extensions move the solids; the visual is asked for without them, the length of the edge it is on."""
    from partcad import visual

    scene, envelope = _built(context, "ell-room", kind="scene")
    drawn = asyncio.run(visual.substitute_async(context, scene, envelope))
    for node in drawn.tree[ocp_serialize.KEY_ASSEMBLY]:
        assert "extend" not in node["visual"]
        assert "length=%s" % node["name"].split("length=")[1].split(",")[0] in node["visual"]


def _reader_of(read):
    """What '_links_async' needs of a factory, around 'read', which stands in for reading the outline."""
    return types.SimpleNamespace(_links=None, _reader=None, _links_guard=threading.Lock(), _read_links_async=read)


def test_callers_that_arrive_together_read_the_outline_once():
    """From several threads and event loops at once, as a scene is prepared, staged and built: one read, one answer.

    Two reads would be the same sandbox run twice and two 'Outline' actions
    open under one name, which the progress display cannot tell apart.
    """
    reads = []

    async def read():
        reads.append(threading.get_ident())
        await asyncio.sleep(0.3)
        return ["wall-1", "wall-2"]

    factory = _reader_of(read)
    answers = []
    threads = [
        threading.Thread(target=lambda: answers.append(asyncio.run(SceneFactoryWalls._links_async(factory))))
        for _ in range(3)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)

    assert len(reads) == 1
    assert answers == [["wall-1", "wall-2"]] * 3
    assert factory._reader is None


def test_a_read_that_fails_leaves_the_next_caller_to_try_again():
    attempts = []

    async def read():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("the sandbox died")
        return ["wall-1"]

    factory = _reader_of(read)
    with pytest.raises(RuntimeError, match="the sandbox died"):
        asyncio.run(SceneFactoryWalls._links_async(factory))
    assert asyncio.run(SceneFactoryWalls._links_async(factory)) == ["wall-1"]
    assert len(attempts) == 2
