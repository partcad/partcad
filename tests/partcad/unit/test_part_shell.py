#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""End to end: what reaches the core when a script hands back a shell.

A shell is a skin - faces joined along their edges, with nothing said about
which side of them is material - and a part that is one renders and measures
correctly while every boolean against it comes back with no solid in it. The
wrappers therefore state a *closed* shell as the solid it already bounds
('wrappers/wrapper_common.solidify'), and an open one is left alone because
there is no solid it bounds.

These run the real thing: a script in a sandbox, through the wrapper, into the
BREP envelope the core carries. The verdict is read with 'partcad.brep_inspect',
which is the core's own answer and needs no CAD kernel; OCCT is asked for the
volume as well, so that "it became a solid" is not the only thing checked.

The package declares no requirements of its own, so it renders in the CAD
sandbox the other part tests provision rather than building one.
"""

import asyncio
import os
import sys
import textwrap

import pytest

import partcad as pc
from partcad import brep_inspect
from partcad.test.shell import ShellTest

from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_SOLID

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import ocp_serialize  # noqa: E402

BOX_VOLUME = 10.0 * 20.0 * 30.0

# A part per way of handing back a shell. 'closed_*' is the shape a script means
# as a body and expresses as a skin; 'open_*' is a skin that is one.
SCRIPTS = {
    "closed_build123d.py": """
        import build123d as bd

        # The boundary of a box, on its own: closed, so it bounds exactly the
        # box it came from.
        show_object(bd.Box(10, 20, 30).shells()[0])
    """,
    "closed_cadquery.py": """
        import cadquery as cq

        show_object(cq.Workplane("XY").box(10, 20, 30).shells())
    """,
    "open_build123d.py": """
        import build123d as bd

        # One face in a shell: there is no volume for it to bound.
        show_object(bd.Shell(bd.Box(10, 20, 30).faces()[0]))
    """,
    "closed_part_type.py": """
        if __name__ == "__partcad_part__":
            import build123d as bd

            output = {"shape": bd.Box(10, 20, 30).shells()[0].wrapped}
    """,
    "compound_closed_build123d.py": """
        import build123d as bd

        # The same closed shell inside a compound, which is what a script that
        # groups whatever it produced hands back. The wrapper used to explode
        # this into the shell's faces, and a part takes no bare face, so the
        # part arrived with nothing in it.
        show_object(bd.Compound(children=[bd.Box(10, 20, 30).shells()[0]]))
    """,
    "compound_face_build123d.py": """
        import build123d as bd

        # A compound of one face: a surface where a body was meant, and nothing
        # solidify can do about it. It has to arrive and be reported.
        show_object(bd.Compound(children=[bd.Box(10, 20, 30).faces()[0]]))
    """,
}

CONFIG = """
partTypes:
  shell_box:
    kind: wrapper
    path: closed_part_type.py

parts:
  closed_build123d:
    type: build123d
  closed_cadquery:
    type: cadquery
  open_build123d:
    type: build123d
  # The same shape, with a section that is not an option PartCAD has.
  open_declares_a_skip:
    type: build123d
    path: open_build123d.py
    shell:
      skip: true
  closed_part_type:
    type: ":shell_box"
  compound_closed_build123d:
    type: build123d
  compound_face_build123d:
    type: build123d
"""


@pytest.fixture(scope="module")
def package(tmp_path_factory):
    root = tmp_path_factory.mktemp("shell_package")
    (root / "partcad.yaml").write_text(CONFIG)
    for name, script in SCRIPTS.items():
        (root / name).write_text(textwrap.dedent(script).lstrip())
    return root


@pytest.fixture(scope="module")
def context(package):
    return pc.Context(str(package))


def _envelope(context, name):
    part = context.get_part(name)
    assert part is not None
    envelope = asyncio.run(part.get_wrapped(context))
    assert part.errors == [], part.errors
    assert envelope is not None
    return part, envelope


def _volume(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


@pytest.mark.parametrize("name", ["closed_build123d", "closed_cadquery", "closed_part_type"])
def test_a_script_that_returns_a_closed_shell_produces_a_solid(context, name):
    """Whichever way it arrives: the two script types, and a partType wrapper."""
    part, envelope = _envelope(context, name)

    topology = brep_inspect.topology(envelope["brep"])
    assert topology is not None
    assert topology.free_shells == 0
    assert topology.count("solid") == 1

    # The same box, not a new one: the solid states what the shell already was.
    shape = ocp_serialize.decode_shape(envelope)
    assert _volume(shape) == pytest.approx(BOX_VOLUME)


@pytest.mark.parametrize("name", ["closed_build123d", "closed_cadquery", "closed_part_type"])
def test_the_shell_check_passes_it(context, name):
    part = context.get_part(name)

    assert asyncio.run(ShellTest().test([], context, part)) == ShellTest.TEST_PASSED


def test_a_solid_is_what_the_components_carry_too(context):
    """Not only the compound: 'components' is what an exploded view reads."""
    part, _ = _envelope(context, "closed_build123d")

    assert len(part.components) == 1
    component = ocp_serialize.decode_shape(part.components[0])
    assert component.ShapeType() == TopAbs_SOLID


def test_a_shell_that_does_not_close_stays_a_shell_and_is_reported(context):
    """There is no solid it bounds, so nothing invents one - and the core says so."""
    part, envelope = _envelope(context, "open_build123d")

    topology = brep_inspect.topology(envelope["brep"])
    assert topology is not None
    assert topology.count("shell") == 1
    assert topology.free_shells == 1
    assert topology.count("solid") == 0

    assert asyncio.run(ShellTest().test([], context, part)) == ShellTest.TEST_FAILED


def test_a_part_cannot_declare_its_way_out_of_the_check(context):
    """A 'shell: skip' in the declaration changes nothing; it is not an option.

    'pc lint' rejects the section outright (there is no such key in the schema),
    and the check would fail the part anyway - which is what this asserts,
    through the real configuration rather than by setting a flag on the object.
    """
    part, envelope = _envelope(context, "open_declares_a_skip")

    assert brep_inspect.topology(envelope["brep"]).free_shells == 1
    assert asyncio.run(ShellTest().test([], context, part)) == ShellTest.TEST_FAILED


# --- a compound is descended into, not exploded -------------------------------


def test_a_compound_holding_a_closed_shell_becomes_the_solid_it_bounds(context):
    """What used to arrive as an empty part is the body it meant.

    'get_downcasted_shape' knows nothing about shells, so a compound holding
    one and no solid came back as that shell's faces - which a part's compound
    does not take. The wrapper now asks what is in the compound first and hands
    this one over whole, so solidify gets to state it as a solid.
    """
    part, envelope = _envelope(context, "compound_closed_build123d")
    assert envelope is not None, "the part built nothing at all"

    topology = brep_inspect.topology(envelope["brep"])
    assert topology is not None
    assert topology.count("solid") == 1
    assert topology.free_shells == 0
    assert topology.free_count("face") == 0


def test_a_compound_holding_a_bare_face_is_reported_as_a_surface(context):
    """The half solidify cannot fix still has to arrive and be named.

    A face bounds no volume, so there is nothing to convert it into. What the
    change buys is that it reaches the core at all: before, the part was empty
    and 'degenerate' called it flat, which is a symptom rather than the cause.
    """
    part, envelope = _envelope(context, "compound_face_build123d")
    assert envelope is not None, "the surface did not reach the core"

    free, unread = brep_inspect.envelope_free_geometry(envelope)
    assert unread == 0
    assert free["face"] >= 1
    assert free["shell"] == 0
