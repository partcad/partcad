#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A link of an ASSY file that says what colour it places its object in.

'color: "#RRGGBB"' on a link is the colour of that one placement: it is stamped
on the node the link places, as the 'color' of what the node reports about
itself, in place of whatever the object states - and the object is built once
however many colours it is placed in. Pinned here in three layers: what the
file may say (the schema an editor checks it against), what the factory reads
out of it (and refuses), and what the tree an assembly is built into says. That
a drawing draws the tree in those colours is 'test_render_colors.py''s.
"""

import asyncio
import logging
import textwrap

import pytest

import partcad as pc
from partcad import assembly_filter, shape_envelope
from partcad.assembly import Assembly, AssemblyChild
from partcad.geom import Location
from partcad.shape import Shape
from partcad_utils import assy_filter
from partcad_utils.assy_lint import ASSY_SCHEMA, CODE_SCHEMA, get_schema, validate_source

RED = "#C91A09"
BLUE = "#0055BF"
GREY = "#A0A5A9"

# --------------------------------------------------------------------------- #
# What the file may say                                                       #
# --------------------------------------------------------------------------- #


def _lint(text):
    return validate_source(textwrap.dedent(text).lstrip(), get_schema(ASSY_SCHEMA))


@pytest.mark.parametrize("color", ['"#C91A09"', '"#c91a09"', '"#C91A0980"'])
def test_the_schema_takes_a_colour_on_a_link(color):
    assert _lint("""
            links:
              - part: brick
                color: %s
              - links:
                  - part: brick
                color: %s
            """ % (color, color)) == []


@pytest.mark.parametrize("color", ['"red"', '"#C91A0"', '"C91A09"', "4"])
def test_the_schema_refuses_anything_else(color):
    findings = _lint("""
        links:
          - part: brick
            color: %s
        """ % color)
    assert [finding.code for finding in findings] == [CODE_SCHEMA]


# --------------------------------------------------------------------------- #
# What the factory reads                                                      #
# --------------------------------------------------------------------------- #

CONFIG = """
parts:
  brick:
    type: step
    path: brick.step
assemblies:
  wall:
    type: assy
"""


def _package(root, text):
    """A package of one brick and one assembly of it, 'text' being the assembly's file.

    The brick's file is there to be found and never read: nothing here builds it.
    """
    (root / "partcad.yaml").write_text(CONFIG)
    (root / "brick.step").write_text("ISO-10303-21;\nEND-ISO-10303-21;\n")
    (root / "wall.assy").write_text(textwrap.dedent(text).lstrip())
    return pc.Context(str(root))


def _wall(tmp_path, text):
    """The children of the assembly 'text' is the file of, as read: nothing is built."""
    ctx = _package(tmp_path, text)
    wall = ctx._get_assembly(":wall")
    asyncio.run(wall.do_instantiate())
    return wall


def test_a_link_s_colour_is_read_onto_the_child_it_places(tmp_path):
    wall = _wall(
        tmp_path,
        """
        links:
          - part: brick
            name: red
            color: "%s"
          - part: brick
            name: plain
          - links:
              - part: brick
                name: inner
            name: course
            color: "%s"
        """ % (RED, BLUE),
    )
    assert [(child.name, child.color) for child in wall.children] == [
        ("red", RED),
        ("plain", None),
        ("course", BLUE),
    ]
    # A container's colour is the container's, not handed down to its links
    # here: the tree hands it down, by the rule everything reading it follows.
    assert [(child.name, child.color) for child in wall.children[2].item.children] == [("inner", None)]


@pytest.mark.parametrize(
    "color, said",
    [
        ('"red"', "'color' must be"),
        ("4", "'color' must be"),
        # An unquoted '#' starts a comment, which leaves the field empty.
        ("#C91A09", "a '#' that is not quoted starts a YAML comment"),
    ],
)
def test_a_colour_that_is_not_one_is_reported_and_dropped(tmp_path, caplog, color, said):
    with caplog.at_level(logging.ERROR):
        wall = _wall(
            tmp_path,
            """
            links:
              - part: brick
                name: odd
                color: %s
            """ % color,
        )
    assert [(child.name, child.color) for child in wall.children] == [("odd", None)]
    assert any("'odd'" in record.getMessage() and said in record.getMessage() for record in caplog.records)


def test_the_root_node_has_no_link_to_be_coloured_by(tmp_path, caplog):
    with caplog.at_level(logging.ERROR):
        wall = _wall(
            tmp_path,
            """
            color: "%s"
            links:
              - part: brick
                name: plain
            """ % RED,
        )
    assert [(child.name, child.color) for child in wall.children] == [("plain", None)]
    assert any("root node" in record.getMessage() and "color" in record.getMessage() for record in caplog.records)


def test_nor_does_the_root_of_a_file_that_is_one_part(tmp_path, caplog):
    with caplog.at_level(logging.ERROR):
        wall = _wall(tmp_path, 'part: brick\ncolor: "%s"\n' % RED)
    assert [child.color for child in wall.children] == [None]
    assert any("root node" in record.getMessage() for record in caplog.records)


def test_a_colour_is_kept_through_a_filtered_view(tmp_path):
    wall = _wall(
        tmp_path,
        """
        links:
          - part: brick
            name: plain
          - part: brick
            name: red
            color: "%s"
        """ % RED,
    )
    view = asyncio.run(assembly_filter.filtered_async(wall, assy_filter.of({"red": None})))
    assert [(child.name, child.color) for child in view.children] == [("red", RED)]


def test_a_colour_moves_the_assembly_s_key_and_not_the_part_s(tmp_path):
    # The file is in the assembly's key, so recolouring a link rebuilds the
    # assembly; the part's key is its own, so it is built once for every colour.
    def keys(color):
        root = tmp_path / color.lstrip("#")
        root.mkdir()
        ctx = _package(root, 'links:\n  - part: brick\n    color: "%s"\n' % color)
        return ctx._get_assembly(":wall").get_cache_key(), ctx._get_part(":brick").get_cache_key()

    red_wall, red_brick = keys(RED)
    blue_wall, blue_brick = keys(BLUE)
    assert None not in (red_wall, red_brick)
    assert red_wall != blue_wall
    assert red_brick == blue_brick


# --------------------------------------------------------------------------- #
# What the tree says                                                          #
# --------------------------------------------------------------------------- #

BREP = b"CASCADE Topology V3, (c) Open Cascade\n\nLocations 0\n"


class _Ctx:
    cache_shapes = None


class _Part(Shape):
    """A part whose factory hands back an envelope, with no sandbox involved."""

    def __init__(self, name, color=None):
        config = {"name": name, "cache": False}
        if color is not None:
            config["properties"] = {"color": color, "material": "abs"}
        super().__init__("pkg", config)
        self.name = name
        self.kind = "part"
        self.cacheable = False

    async def get_shape(self, ctx):
        return {"name": None, "label": None, "brep": BREP}


class _Assembly(Assembly):
    """An assembly of the children it is handed, each an '(item, name, colour)'."""

    def __init__(self, name, children, color=None):
        config = {"name": name, "cache": False}
        if color is not None:
            config["properties"] = {"color": color}
        super().__init__("pkg", config)
        self.name = name
        self.cacheable = False
        self._placed = children

    def instantiate(self, _assembly):
        for item, name, color in self._placed:
            self.children.append(AssemblyChild(item, name, Location(), color=color))


def _tree(assembly):
    return asyncio.run(assembly.get_wrapped(_Ctx()))


def _properties(node):
    return node.get(shape_envelope.KEY_PROPERTIES)


def test_a_link_s_colour_is_the_colour_of_the_node_it_places():
    brick = _Part("brick")
    tree = _tree(_Assembly("wall", [(brick, "red", RED), (brick, "plain", None)]))

    red, plain = tree[shape_envelope.KEY_ASSEMBLY]
    assert _properties(red) == {"color": RED}
    assert _properties(plain) is None


def test_it_wins_over_the_object_s_own_and_leaves_the_rest_of_what_it_reports():
    brick = _Part("brick", color=GREY)
    tree = _tree(_Assembly("wall", [(brick, "red", RED), (brick, "grey", None)]))

    red, grey = tree[shape_envelope.KEY_ASSEMBLY]
    assert _properties(red) == {"color": RED, "material": "abs"}
    # The other placement of the very same object, and the object itself, are
    # untouched: the envelope is shared, and only the placed node is the link's.
    assert _properties(grey) == {"color": GREY, "material": "abs"}
    assert _properties(_tree(brick)) == {"color": GREY, "material": "abs"}


def test_an_assembly_placed_in_a_colour_carries_it_and_its_children_keep_theirs():
    wheel = _Assembly("wheel", [(_Part("rim"), "rim", None), (_Part("tyre"), "tyre", "#05131D")])
    tree = _tree(_Assembly("car", [(wheel, "front", GREY)]))

    (front,) = tree[shape_envelope.KEY_ASSEMBLY]
    assert _properties(front) == {"color": GREY}
    rim, tyre = front[shape_envelope.KEY_ASSEMBLY]
    # The rim states nothing and is drawn in the wheel's colour by inheritance;
    # the tyre states its own and keeps it.
    assert _properties(rim) is None
    assert _properties(tyre) == {"color": "#05131D"}
