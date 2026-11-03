#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""End to end: walls and rooms, built through PartCAD in a sandbox.

A wall is a 'type: wall' part - a one-sided surface drawn to lay out a space -
and a room is a 'type: walls' scene, the walls standing on the outline of a
sketch. PartCAD ships one of each in '//builtin/building'. What is held here is
what PartCAD does with them rather than the geometry, which 'test_wall_geometry.py'
asks of the sandbox's own functions directly:

  * a wall is a surface by its type - an alias of one too - and is passed over by
    the checks that ask whether a part is a body, never validated into a solid,
    and drawn one-sided ('surface.py');
  * a wall has to say it is not manufacturable, and nothing manufacturable can be
    made with one in it;
  * a room is one wall per edge of its sketch, placed along it, and a sketch that
    is not one closed loop of lines and arcs is refused with the reason.

The package declares no requirements of its own, so it renders in the CAD
sandbox the other part tests provision rather than building one.
"""

import asyncio
import math
import os
import sys
import textwrap
import threading
import types

import pytest

import partcad as pc
from partcad import cmf, output, surface
from partcad.scene_factory_walls import SceneFactoryWalls
from partcad.test.degenerate import DegenerateTest
from partcad.test.manufacturability import ManufacturabilityTest
from partcad.test.shell import ShellTest
from partcad.test.solidity import SolidityTest
from partcad.test.test import Test
from partcad.test.validity import ValidityTest

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
    source: "//builtin/building:wall;length=3141.592654,radius=-1000"

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
    wall, _envelope = _built(context, "//builtin/building:wall;length=2000")
    assert wall.errors == []
    assert wall._shape_properties() == {"color": "#9C9284", "oneSided": True}
    box = asyncio.run(wall.get_bounding_box_async(context))
    assert box == pytest.approx((0.0, 0.0, 0.0, 2000.0, 0.0, 2700.0), abs=1e-6)


def test_an_alias_of_a_wall_is_a_wall(context):
    """It states no properties and no type of its own, and is one-sided and a surface all the same."""
    alias, envelope = _built(context, "curved")
    assert envelope is not None and alias.errors == []
    assert surface.surface_type(alias) == "wall"
    assert alias._shape_properties() == {"oneSided": True}


@pytest.mark.parametrize("check", [ShellTest, DegenerateTest, SolidityTest, ValidityTest])
@pytest.mark.parametrize("name", ["north", "curved"])
def test_the_checks_that_ask_for_a_body_pass_a_wall_over_and_say_why(context, check, name):
    wall = context.get_part(name)
    test = check()

    reason = test.inapplicable(wall)
    assert reason is not None and "surface by its type ('wall')" in reason
    assert asyncio.run(test.test([], context, wall, {})) == Test.TEST_PASSED


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
    assert verdict == Test.TEST_FAILED


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
        assert properties["oneSided"] is True
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


def test_the_builtin_wall_is_drawn_in_a_colour_it_declares_and_does_not_claim(package):
    """Its grey is a CMF colour of '//builtin/building', display-only: a wall is never made.

    In a context of its own. Asking for the wall itself, with no parameters,
    records its grey in the declaration every instance of it is copied from, and
    an instance named with another colour then keeps the grey (a CMF issue of
    its own, reported on the pull request that brought this test); the module's
    context goes on to paint rooms with such instances.
    """
    context = pc.Context(str(package))
    wall = context.get_part("//builtin/building:wall")
    assert cmf.own_parameters(wall, context) == {"color": "//builtin/building:wall"}
    colors = context.get_project(output.BUILTIN_BUILDING_PACKAGE).config_obj["colors"]
    assert colors["wall"]["display"] == "#9C9284"
    assert colors["wall"]["manufacturable"] is False


def test_a_painted_room_paints_every_wall(context):
    """A room's own colour is every wall's, over the grey the wall it is built of states."""
    walls = _walls(context, "painted")

    assert len(walls) == 4
    for _label, name, _location, properties in walls:
        assert "color=//:sage" in name
        assert properties["color"] == "#7D8F69"
        assert properties["oneSided"] is True

    # And a room nobody painted is the walls' own grey.
    for _label, _name, _location, properties in _walls(context, "living"):
        assert properties["color"] == "#9C9284"


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
