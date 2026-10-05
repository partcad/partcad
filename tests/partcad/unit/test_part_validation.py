#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Every part goes through one validation, whatever produced it.

Before it, a closed shell became the solid it bounds only when a cadquery or
build123d script or a partType plugin produced it; a STEP file, a mesh import
or an extrusion handed the same shell on as it was, and nothing at all judged
any part until somebody ran 'pc test'. Now the core asks the same question of
every part as it is built: the sandbox half ('wrapper_solidity') is asked here
in-process, and the core half - that every part reaches it, and what it does
with the answer - is asked with that answer stubbed.
"""

import asyncio
import logging
import os
import sys

from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.TopAbs import TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer

import partcad as pc
from partcad import shape_envelope
from partcad.shape import Shape

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import wrapper_solidity  # noqa: E402


def _box():
    return BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape()


def test_the_wrapper_turns_a_closed_shell_into_its_solid_and_sends_it_back():
    shell = TopExp_Explorer(_box(), TopAbs_SHELL).Current()
    answer = wrapper_solidity.process(None, {"wrapped": shell, "solidify": True})
    assert answer["success"]
    assert answer["problems"] == []
    assert answer["solidified"].ShapeType() == TopAbs_SOLID


def test_the_wrapper_sends_nothing_back_when_nothing_changed():
    answer = wrapper_solidity.process(None, {"wrapped": _box(), "solidify": True})
    assert answer["solidified"] is None
    assert answer["problems"] == []


def test_the_wrapper_says_what_is_wrong_with_a_part_that_is_not_a_solid():
    face = TopExp_Explorer(_box(), TopAbs_FACE).Current()
    answer = wrapper_solidity.process(None, {"wrapped": face, "solidify": True})
    assert answer["solidified"] is None
    assert "it holds no solid" in answer["problems"]


class _Part(Shape):
    """A part as any factory leaves it: an envelope, and nothing said about it."""

    def __init__(self, name):
        super().__init__("//test", {"name": name})
        self.name = name
        self.kind = "part"
        self.cache = False

    def get_cacheable(self):
        return False

    async def get_shape(self, ctx):
        return {"name": self.name, "label": self.name, "brep": b"shell"}


def test_every_part_is_validated_as_it_leaves_its_factory(monkeypatch, caplog):
    seen = []

    async def ask(self, ctx, obj, solidify=False):
        seen.append((obj, solidify))
        return {"success": True, "solidified": {"brep": b"solid"}, "problems": ["it has faces that belong to no solid"]}

    monkeypatch.setattr(Shape, "_ask_solidity", ask)
    part = _Part("thing")
    with caplog.at_level(logging.WARNING):
        envelope = asyncio.run(part.get_wrapped(object()))
    # Asked about the geometry alone, and asked to solidify it.
    assert seen == [({shape_envelope.KEY_BREP: b"shell"}, True)]
    # The geometry the sandbox sent back replaces the old; nothing else moves.
    assert envelope[shape_envelope.KEY_BREP] == b"solid"
    assert envelope["label"] == "thing"
    assert "is not a solid: it has faces that belong to no solid" in caplog.text


def test_a_sandbox_that_cannot_answer_leaves_the_part_as_it_was(monkeypatch, caplog):
    async def fail(self, ctx, obj, solidify=False):
        raise RuntimeError("no sandbox here")

    monkeypatch.setattr(Shape, "_ask_solidity", fail)
    with caplog.at_level(logging.WARNING):
        envelope = asyncio.run(_Part("other").get_wrapped(object()))
    assert envelope[shape_envelope.KEY_BREP] == b"shell"
    assert "could not be validated" in caplog.text


def test_an_assembly_is_not_a_part_and_is_not_asked(monkeypatch):
    async def ask(self, ctx, obj, solidify=False):
        raise AssertionError("an assembly was validated as a part")

    monkeypatch.setattr(Shape, "_ask_solidity", ask)
    part = _Part("asm")
    part.kind = "assembly"
    asyncio.run(part.get_wrapped(object()))


class _FilePart(_Part):
    """A part read from a file of the given type."""

    def __init__(self, name, part_type):
        super().__init__(name)
        self.config = {"name": name, "type": part_type}


def test_a_step_or_brep_part_is_judged_but_never_converted(monkeypatch, caplog):
    for part_type in ("step", "brep"):
        seen = []

        async def ask(self, ctx, obj, solidify=False):
            seen.append(solidify)
            return {"success": True, "solidified": None, "problems": ["it holds no solid"]}

        monkeypatch.setattr(Shape, "_ask_solidity", ask)
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            envelope = asyncio.run(_FilePart("file", part_type).get_wrapped(object()))
        assert seen == [False], part_type
        assert envelope[shape_envelope.KEY_BREP] == b"shell"
        assert "is not a solid: it holds no solid" in caplog.text


class _MeasuredPart(_Part):
    async def get_shape(self, ctx):
        return {
            "name": self.name,
            "brep": b"shell",
            shape_envelope.KEY_METADATA: shape_envelope.make_metadata(
                measurements={"volume": 0.0, "area": 2200.0},
                annotations=[{"kind": "bend"}],
                sections={"source": {"units": "mm"}},
            ),
        }


def test_a_solidified_part_is_measured_again_and_keeps_what_its_source_said(monkeypatch):
    async def ask(self, ctx, obj, solidify=False):
        solid = {
            "brep": b"solid",
            shape_envelope.KEY_METADATA: shape_envelope.make_metadata(measurements={"volume": 6000.0}),
        }
        return {"success": True, "solidified": solid, "problems": []}

    monkeypatch.setattr(Shape, "_ask_solidity", ask)
    envelope = asyncio.run(_MeasuredPart("measured").get_wrapped(object()))
    metadata = envelope[shape_envelope.KEY_METADATA]
    # The shell's numbers are gone, not merged under the solid's.
    assert metadata[shape_envelope.METADATA_MEASUREMENTS] == {"volume": 6000.0}
    assert metadata[shape_envelope.METADATA_ANNOTATIONS] == [{"kind": "bend"}]
    assert metadata[shape_envelope.METADATA_SECTIONS] == {"source": {"units": "mm"}}
