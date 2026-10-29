#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A part is finished by the wrapper that builds it, and the core does what is left.

Every part leaves its factory validated - a closed shell turned into the solid
it bounds, and the result judged - and then moved by its 'offset' and scaled by
its 'scale'. The core used to ask a sandbox of its own for each of those, which
is an interpreter importing OCP to parse the BREP back, three of them for a part
with both. Now the factory's request asks the wrapper that builds the part to do
it while the shape is live ('wrapper_common.finished'), the answer says how far
that went, and 'Shape.get_wrapped' does the rest as it always did.

Three halves are covered here. The sandbox half runs in-process, against the
very functions the old sandboxes ran, and is held to what those produced. The
core half is run with the factory stubbed: what a claim spares, what it does not,
and the claims it refuses. And the cache key, which a transform done in another
process must not change: a part and the same part moved never share an entry.
The last section runs the real thing, and counts the interpreters.
"""

import asyncio
import logging
import os
import sys

import pytest
from cache_config import CacheUserConfig
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.BRepTools import BRepTools
from OCP.TopAbs import TopAbs_SHELL, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer

import partcad as pc
from partcad import runtime_python, shape_envelope
from partcad import transform as pc_transform
from partcad.cache_shape import ShapeCache
from partcad.shape import Shape

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import ocp_serialize  # noqa: E402
import wrapper_common  # noqa: E402
import wrapper_solidity  # noqa: E402
import wrapper_transform  # noqa: E402

OFFSET = [[10, 0, 0], [0, 0, 1], 0]


def _box():
    return BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape()


def _shell():
    return TopExp_Explorer(_box(), TopAbs_SHELL).Current()


def _bbox(shape):
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box, True)
    return [round(value, 6) for value in box.Get()]


def _decoded(envelope):
    """What a wrapper's answer decodes to on the far side of the pipe: through the frame it crosses it in.

    A frame rather than a line of JSON, because that is what a Python wrapper
    answers PartCAD's own requests with, and because the envelope holds its
    payload as the bytes 'encode_shape' wrote, which stock JSON has no room for
    (see 'ocp_serialize.serialize').
    """
    return ocp_serialize.deserialize(ocp_serialize.serialize(envelope))


def _plain(envelope):
    """The BREP text an envelope carries, uncompressed: what two payloads are compared by."""
    return ocp_serialize._brep_payload(envelope[ocp_serialize.KEY_BREP])


@pytest.fixture
def asked(monkeypatch):
    """Set what the request asked, as 'handle_input' would have; put back afterwards."""

    def ask(finish, name="//test:thing", label="thing"):
        monkeypatch.setattr(wrapper_common, "_request_finish", finish)
        monkeypatch.setattr(wrapper_common, "_request_name", name)
        monkeypatch.setattr(wrapper_common, "_request_label", label)

    return ask


#
# The sandbox half
#


def test_the_two_ends_spell_the_protocol_alike():
    assert ocp_serialize.KEY_FINISH == shape_envelope.KEY_FINISH
    assert ocp_serialize.METADATA_FINISHED == shape_envelope.METADATA_FINISHED
    assert ocp_serialize.FINISHED_VALIDATED == shape_envelope.FINISHED_VALIDATED
    assert ocp_serialize.FINISHED_DECLINED == shape_envelope.FINISHED_DECLINED


def test_the_claim_is_taken_off_and_nothing_else_is():
    claim = {"validated": {"solidify": True, "problems": []}}
    sections = {"header": "kept"}
    with_more = {"brep": b"x", "metadata": {"finished": claim, "sections": sections}}
    assert shape_envelope.take_finished(with_more) == ({"brep": b"x", "metadata": {"sections": sections}}, claim)
    assert with_more["metadata"]["finished"] == claim, "the envelope it was taken from is left as it was"
    # A claim that was all the metadata held takes the metadata with it.
    assert shape_envelope.take_finished({"brep": b"x", "metadata": {"finished": claim}}) == ({"brep": b"x"}, claim)
    # Nothing to take, and something that is not a claim.
    plain = {"brep": b"x", "metadata": {"sections": sections}}
    assert shape_envelope.take_finished(plain) == (plain, {})
    assert shape_envelope.take_finished(None) == (None, {})
    assert shape_envelope.take_finished({"brep": b"x", "metadata": {"finished": "yes"}}) == ({"brep": b"x"}, {})


def test_the_request_is_taken_off_before_the_wrapper_sees_it(monkeypatch):
    """A partType wrapper hands its request on to the package's script, which has no business with it."""
    for name in ("_request_finish", "_request_name", "_request_label"):
        monkeypatch.setattr(wrapper_common, name, None)
    request = {"name": "//test:thing", "label": "thing", ocp_serialize.KEY_FINISH: {"validate": {"solidify": True}}}
    wrapper_common.remember_request(request)
    assert ocp_serialize.KEY_FINISH not in request
    assert wrapper_common._request_finish == {"validate": {"solidify": True}}
    assert wrapper_common._request_name == "//test:thing"

    wrapper_common.remember_request({"name": "other", ocp_serialize.KEY_FINISH: "not a request"})
    assert wrapper_common._request_finish is None
    # Not a request a part is built from at all: nothing is remembered of it.
    wrapper_common.remember_request(["not", "a", "dict"])
    assert wrapper_common._request_name == "other"


def test_a_request_that_asks_nothing_gets_its_shape_back_as_it_was(asked):
    """A sketch goes through the same script wrappers, and asks for none of this."""
    asked(None)
    box = _box()
    # For 'handle_output' to encode, as it always did.
    assert wrapper_common.finished(box) is box
    assert wrapper_common.finished(None) is None
    # And what a wrapper learnt about it is encoded with it, as the STEP
    # wrapper always encoded it.
    sections = {ocp_serialize.METADATA_SECTIONS: {"header": "kept"}}
    assert wrapper_common.finished(box, metadata=sections) == ocp_serialize.encode_shape(
        box, name="//test:thing", label="thing", metadata=sections
    )
    # Not a shape: left for 'handle_output' to encode or refuse, as it always was.
    asked({"validate": {"solidify": True}})
    assert wrapper_common.finished("not a shape") == "not a shape"


def test_a_closed_shell_leaves_as_the_solid_the_old_sandbox_made_of_it(asked):
    """Byte for byte: the same conversion, of the same shape, measured the same."""
    shell = _shell()
    # What the core used to do: the shell encoded, decoded in another sandbox,
    # solidified there and encoded again.
    old = wrapper_solidity.process(None, {"wrapped": _decoded(ocp_serialize.encode_shape(shell)), "solidify": True})
    expected = ocp_serialize.encode_shape(old["solidified"])

    asked({"validate": {"solidify": True}})
    finished = wrapper_common.finished(shell)
    claim = finished[ocp_serialize.KEY_METADATA].pop(ocp_serialize.METADATA_FINISHED)

    assert claim == {"validated": {"solidify": True, "problems": old["problems"]}}
    assert _decoded(finished).ShapeType() == TopAbs_SOLID
    assert _plain(finished) == _plain(expected)
    assert finished[ocp_serialize.KEY_METADATA] == expected[ocp_serialize.KEY_METADATA]


def test_a_part_read_from_a_file_is_judged_and_not_converted(asked):
    shell = _shell()
    old = wrapper_solidity.process(None, {"wrapped": shell, "solidify": False})
    asked({"validate": {"solidify": False}})
    finished = wrapper_common.finished(shell, metadata={ocp_serialize.METADATA_SECTIONS: {"header": "kept"}})
    claim = finished[ocp_serialize.KEY_METADATA].pop(ocp_serialize.METADATA_FINISHED)

    assert claim["validated"] == {"solidify": False, "problems": old["problems"]}
    assert "it holds no solid" in claim["validated"]["problems"]
    assert _plain(finished) == _plain(ocp_serialize.encode_shape(shell))
    # What the wrapper read from the file rides along as it always did.
    assert finished[ocp_serialize.KEY_METADATA][ocp_serialize.METADATA_SECTIONS] == {"header": "kept"}


def test_it_is_moved_and_scaled_after_it_is_validated_and_says_so(asked):
    asked({"validate": {"solidify": True}, "offset": OFFSET, "scale": 2})
    finished = wrapper_common.finished(_shell())
    claim = finished[ocp_serialize.KEY_METADATA].pop(ocp_serialize.METADATA_FINISHED)

    assert list(claim) == ["validated", "offset", "scale"]
    assert claim["offset"] == OFFSET and claim["scale"] == 2
    shape = _decoded(finished)
    assert shape.ShapeType() == TopAbs_SOLID
    # Moved 10 in X, then scaled about the origin.
    assert _bbox(shape) == [20.0, 0.0, 0.0, 40.0, 40.0, 60.0]
    # By the fallback's own functions, in the same order.
    expected = wrapper_transform.scale(wrapper_transform.relocate(wrapper_common.solidify(_shell()), OFFSET), 2)
    assert _plain(finished) == _plain(ocp_serialize.encode_shape(expected))
    # And measured as what came out.
    assert finished[ocp_serialize.KEY_METADATA]["measurements"]["bbox"] == pytest.approx(_bbox(shape))


def test_a_request_to_move_it_alone_moves_it_alone(asked):
    asked({"offset": OFFSET})
    finished = wrapper_common.finished(_box())
    assert finished[ocp_serialize.KEY_METADATA][ocp_serialize.METADATA_FINISHED] == {"offset": OFFSET}
    assert _bbox(_decoded(finished)) == [10.0, 0.0, 0.0, 20.0, 20.0, 30.0]


def test_a_step_that_fails_is_left_to_the_core_with_everything_after_it(asked, monkeypatch, capfd):
    def refuse(shape, factor):
        raise ValueError("no such factor")

    monkeypatch.setattr(wrapper_transform, "scale", refuse)
    asked({"validate": {"solidify": True}, "offset": OFFSET, "scale": "nonsense"})
    finished = wrapper_common.finished(_box())
    claim = finished[ocp_serialize.KEY_METADATA][ocp_serialize.METADATA_FINISHED]

    assert "scale" not in claim
    assert claim["offset"] == OFFSET
    assert "no such factor" in claim["declined"]
    assert _bbox(_decoded(finished)) == [10.0, 0.0, 0.0, 20.0, 20.0, 30.0]
    # Said nowhere a run's warnings are read: the core's own sandbox says
    # whatever there is to say, when it does the step itself.
    assert capfd.readouterr().err == ""


def test_a_validation_that_fails_claims_nothing_and_moves_nothing(asked, monkeypatch, capfd):
    """The core validates before it moves, and could not validate a part already moved."""

    def broken(shape):
        raise RuntimeError("the analyzer gave up")

    monkeypatch.setattr(wrapper_common, "solid_problems", broken)
    shell = _shell()
    asked({"validate": {"solidify": True}, "offset": OFFSET})
    finished = wrapper_common.finished(shell)
    claim = finished[ocp_serialize.KEY_METADATA][ocp_serialize.METADATA_FINISHED]

    assert list(claim) == ["declined"]
    assert _plain(finished) == _plain(ocp_serialize.encode_shape(shell))
    assert capfd.readouterr().err == ""


def test_several_shapes_leave_as_one_part(asked):
    """What 'transform.compound' did in a sandbox of its own, done before the part is finished."""
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS_Shape

    first = _box()
    second = BRepPrimAPI_MakeBox(5.0, 5.0, 5.0).Shape()
    asked({"validate": {"solidify": True}, "scale": 2})
    # Nothing, a null shape and a location a script showed are skipped, as the
    # sandbox that used to compound them skipped them.
    answer = wrapper_common.finished_shapes([first, None, TopoDS_Shape(), TopLoc_Location(), second])

    assert len(answer) == 1
    claim = answer[0][ocp_serialize.KEY_METADATA][ocp_serialize.METADATA_FINISHED]
    assert claim["validated"]["problems"] == [] and claim["scale"] == 2
    compound = _decoded(answer[0])
    solids = TopExp_Explorer(compound, TopAbs_SOLID)
    count = 0
    while solids.More():
        count += 1
        solids.Next()
    assert count == 2
    assert _bbox(compound) == [0.0, 0.0, 0.0, 20.0, 40.0, 60.0]


def test_a_list_it_cannot_make_one_part_of_is_answered_as_it_was(asked):
    shapes = [_box(), object()]
    asked({"validate": {"solidify": True}})
    assert wrapper_common.finished_shapes(shapes) is shapes
    # And one shape is the part itself, finished.
    single = wrapper_common.finished_shapes([_box()])
    assert ocp_serialize.METADATA_FINISHED in single[0][ocp_serialize.KEY_METADATA]
    # A request that asks nothing gets the list it handed in.
    asked(None)
    several = [_box(), _box()]
    assert wrapper_common.finished_shapes(several) is several


#
# The core half
#


class _Built(Shape):
    """A part as a factory hands it back: the envelope its wrapper wrote, with whatever that claimed."""

    def __init__(self, name="thing", config=None, claim=None, brep=b"geometry", annotations=None):
        super().__init__("//test", {"name": name, **(config or {})})
        self.name = name
        self.kind = "part"
        self._claim = claim
        self._brep = brep
        self._annotations = annotations
        self.builds = 0

    async def get_shape(self, ctx):
        self.builds += 1
        envelope = {"name": self.name, "label": self.name, "brep": self._brep}
        metadata = shape_envelope.make_metadata(
            measurements={"bbox": [0, 0, 0, 1, 1, 1]}, annotations=self._annotations
        )
        if self._claim is not None:
            metadata[shape_envelope.METADATA_FINISHED] = self._claim
        envelope[shape_envelope.KEY_METADATA] = metadata
        return envelope


class _Uncached(_Built):
    def get_cacheable(self):
        return False


@pytest.fixture
def sandboxes(monkeypatch):
    """Every sandbox the core could start in 'get_wrapped', recorded in the order it is asked for."""
    asked = []

    async def solidity(self, ctx, obj, solidify=False):
        asked.append(("solidity", solidify))
        return {"success": True, "solidified": None, "problems": ["it holds no solid"]}

    def move(operation):
        async def run(ctx, shape, value):
            asked.append((operation, value))
            moved = dict(shape)
            moved["brep"] = shape["brep"] + b"+" + operation.encode()
            moved[shape_envelope.KEY_METADATA] = {"measurements": {"bbox": [9, 9, 9, 9, 9, 9]}}
            return moved

        return run

    monkeypatch.setattr(Shape, "_ask_solidity", solidity)
    monkeypatch.setattr(pc_transform, "offset", move("offset"))
    monkeypatch.setattr(pc_transform, "scale", move("scale"))
    return asked


VALIDATED = {"validated": {"solidify": True, "problems": ["it holds no solid"]}}
BEND = [{"kind": "bend", "points": [[1.0, 0.0, 0.0]]}]


def test_what_is_asked_of_the_wrapper():
    assert _Built().finish_request() == {"validate": {"solidify": True}}
    moved = _Built(config={"type": "step", "offset": OFFSET, "scale": 2})
    assert moved.finish_request() == {"validate": {"solidify": False}, "offset": OFFSET, "scale": 2}
    sketch = _Built(config={"offset": OFFSET})
    sketch.kind = "sketch"
    assert sketch.finish_request() is None


def test_a_part_validated_by_its_wrapper_is_not_sent_to_another_sandbox(sandboxes, caplog):
    part = _Uncached(claim=VALIDATED)
    with caplog.at_level(logging.WARNING):
        envelope = asyncio.run(part.get_wrapped(object()))
    assert sandboxes == []
    # Reported in the very words the sandbox's answer is reported in.
    assert "//test:thing is not a solid: it holds no solid" in caplog.text
    # And the claim is gone before anything could store or report it.
    assert shape_envelope.METADATA_FINISHED not in envelope[shape_envelope.KEY_METADATA]
    assert shape_envelope.METADATA_FINISHED not in part._metadata


def test_a_part_whose_wrapper_claims_nothing_takes_the_way_it_always_did(sandboxes, caplog):
    part = _Uncached(config={"offset": OFFSET, "scale": 2})
    with caplog.at_level(logging.WARNING):
        envelope = asyncio.run(part.get_wrapped(object()))
    assert sandboxes == [("solidity", True), ("offset", OFFSET), ("scale", 2)]
    assert envelope["brep"] == b"geometry+offset+scale"
    assert "//test:thing is not a solid: it holds no solid" in caplog.text


def test_what_the_wrapper_moved_is_not_moved_again(sandboxes):
    claim = dict(VALIDATED, offset=OFFSET, scale=2)
    folded = _Uncached(config={"offset": OFFSET, "scale": 2}, claim=claim, annotations=BEND)
    envelope = asyncio.run(folded.get_wrapped(object()))
    assert sandboxes == []
    assert envelope["brep"] == b"geometry"

    # And what the source said about its elements went where they went, as it
    # does when a sandbox of the core's own moved the part.
    unfolded = _Uncached(config={"offset": OFFSET, "scale": 2}, annotations=BEND)
    asyncio.run(unfolded.get_wrapped(object()))
    assert folded._metadata["annotations"] == unfolded._metadata["annotations"]
    assert folded._metadata["annotations"][0]["points"] == [[22.0, 0.0, 0.0]]


def test_what_the_wrapper_could_not_do_is_done_here(sandboxes, caplog):
    claim = dict(VALIDATED, offset=OFFSET, declined="scale: no such factor")
    part = _Uncached(config={"offset": OFFSET, "scale": 2}, claim=claim)
    with caplog.at_level(logging.DEBUG):
        envelope = asyncio.run(part.get_wrapped(object()))
    assert sandboxes == [("scale", 2)]
    assert envelope["brep"] == b"geometry+scale"
    assert "no such factor" in caplog.text


@pytest.mark.parametrize(
    "config, claim",
    [
        # Moved by something it was not asked to move it by.
        ({"offset": OFFSET}, dict(VALIDATED, offset=[[1, 0, 0], [0, 0, 1], 0])),
        # Moved when nothing said to move it.
        ({}, dict(VALIDATED, scale=2)),
        # Scaled without having been moved first.
        ({"offset": OFFSET, "scale": 2}, dict(VALIDATED, scale=2)),
        # Moved without having been validated first.
        ({"offset": OFFSET}, {"offset": OFFSET}),
        # Converted when the file was the authority.
        ({"type": "step"}, VALIDATED),
    ],
)
def test_a_claim_nobody_can_account_for_is_refused(sandboxes, config, claim):
    with pytest.raises(Exception, match="was not asked to"):
        asyncio.run(_Uncached(config=config, claim=claim).get_wrapped(object()))


def test_only_a_part_is_finished_by_its_wrapper(sandboxes):
    """A sketch asks for nothing, so a claim on one is a claim nobody asked for."""
    sketch = _Uncached(config={"offset": OFFSET}, claim={"offset": OFFSET})
    sketch.kind = "sketch"
    with pytest.raises(Exception, match="was not asked to"):
        asyncio.run(sketch.get_wrapped(object()))


#
# The cache key
#

BREP = b"CASCADE Topology V3, (c) Open Cascade\n"
# One part, declared twice: alike in everything but the 'offset' (and the name,
# which is not part of what a shape is keyed on).
PLAIN = {"type": "stl", "path": "box.stl"}
MOVED = dict(PLAIN, offset=OFFSET)


@pytest.fixture
def ctx(tmp_path):
    """A context whose shape cache is this test's alone."""
    (tmp_path / "partcad.yaml").write_text("name: //test\n")
    context = pc.Context(str(tmp_path))
    context.cache_shapes = ShapeCache(user_config=CacheUserConfig(tmp_path / "cache"))
    return context


def _folded(name, config):
    """The part as a wrapper that finishes it builds it: moved there, and said so."""
    claim = dict(VALIDATED)
    if "offset" in config:
        claim["offset"] = config["offset"]
    return _Built(name, config, claim=claim, brep=BREP + (b"moved" if "offset" in config else b"plain"))


def test_a_part_moved_by_its_wrapper_keys_apart_from_the_same_part_unmoved(ctx, sandboxes):
    assert asyncio.run(_folded("a", PLAIN).get_cache_key_async()) != asyncio.run(
        _folded("b", MOVED).get_cache_key_async()
    )
    # And the name is not what tells them apart: the same part under two names
    # is one entry.
    assert asyncio.run(_folded("a", PLAIN).get_cache_key_async()) == asyncio.run(
        _folded("c", PLAIN).get_cache_key_async()
    )


@pytest.mark.parametrize("first", ["plain", "moved"])
def test_an_entry_is_never_served_as_the_other(ctx, sandboxes, first):
    """Whichever is built first, each gets its own geometry back, moved exactly once."""
    order = [("plain", PLAIN), ("moved", MOVED)]
    if first == "moved":
        order.reverse()
    for name, config in order:
        part = _folded(name, config)
        envelope = asyncio.run(part.get_wrapped(ctx))
        assert part.builds == 1, name
        assert envelope["brep"].endswith(name.encode()), name

    # Read back by parts that have not been built: each from its own entry,
    # untouched - a hit is not moved again, and carries no claim to act on.
    for name, config in order:
        part = _folded(name, config)
        envelope = asyncio.run(part.get_wrapped(ctx))
        assert part.builds == 0, name
        assert envelope["brep"] == BREP + name.encode()
        assert shape_envelope.METADATA_FINISHED not in (shape_envelope.metadata_of(envelope) or {})
    assert sandboxes == []


def test_an_entry_the_core_moved_is_the_entry_a_finishing_wrapper_would_have_written(ctx, sandboxes):
    """One key whichever process moved the part: an entry written before this change is still the moved part."""
    old = _Built("moved", MOVED, brep=BREP)
    asyncio.run(old.get_wrapped(ctx))
    assert ("offset", OFFSET) in sandboxes

    del sandboxes[:]
    new = _folded("moved", MOVED)
    envelope = asyncio.run(new.get_wrapped(ctx))
    assert new.builds == 0
    assert envelope["brep"] == BREP + b"+offset"
    assert sandboxes == []


#
# The real thing
#

PACKAGE = """
partTypes:
  many:
    kind: wrapper
    path: many.py

parts:
  moved:
    type: brep
    path: box.brep
    offset: [[10, 0, 0], [0, 0, 1], 0]
    scale: 2
  several:
    type: ":many"
    scale: 2
"""

MANY = """
if __name__ == "__partcad_part__":
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    output = {"shapes": [BRepPrimAPI_MakeBox(gp_Pnt(20.0 * i, 0, 0), 10, 10, 10).Shape() for i in range(3)]}
"""


@pytest.fixture
def package(tmp_path):
    (tmp_path / "partcad.yaml").write_text(PACKAGE)
    (tmp_path / "many.py").write_text(MANY)
    BRepTools.Write_s(_box(), str(tmp_path / "box.brep"))
    return tmp_path


@pytest.fixture
def interpreters(monkeypatch):
    """The wrapper every sandbox interpreter the run starts is started for, in order."""
    started = []
    original = runtime_python.PythonRuntime.run_async_onced

    async def counted(self, cmd, *args, **kwargs):
        started.append(os.path.basename(cmd[0]))
        return await original(self, cmd, *args, **kwargs)

    monkeypatch.setattr(runtime_python.PythonRuntime, "run_async_onced", counted)
    return started


def _built(package, name, cache):
    """'name' built afresh: a context of its own, with a shape cache nothing has written to."""
    context = pc.Context(str(package))
    context.cache_shapes = ShapeCache(user_config=CacheUserConfig(cache))
    part = context.get_part(name)
    envelope = asyncio.run(part.get_wrapped(context))
    assert part.errors == [], part.errors
    return envelope


@pytest.mark.slow
@pytest.mark.parametrize(
    "name, wrapper, bbox, volume",
    [
        ("moved", "wrapper_brep.py", [20.0, 0.0, 0.0, 40.0, 40.0, 60.0], 48000.0),
        ("several", "wrapper_part_type.py", [0.0, 0.0, 0.0, 100.0, 20.0, 20.0], 24000.0),
    ],
)
def test_a_part_is_built_finished_and_moved_in_one_interpreter(
    package, tmp_path, interpreters, monkeypatch, name, wrapper, bbox, volume
):
    """And it comes out as the part the old way made, in as many as four."""
    folded = _built(package, name, tmp_path / "folded")
    assert interpreters == [wrapper]
    measured = shape_envelope.metadata_of(folded)["measurements"]
    assert measured["bbox"] == pytest.approx(bbox, abs=1e-6)
    assert measured["volume"] == pytest.approx(volume)

    # The old way: a wrapper that is asked for nothing, and the core doing
    # every step in a sandbox of its own.
    del interpreters[:]
    monkeypatch.setattr(Shape, "finish_request", lambda self: None)
    unfolded = _built(package, name, tmp_path / "unfolded")
    assert interpreters[0] == wrapper and "wrapper_solidity.py" in interpreters and len(interpreters) >= 3
    old = shape_envelope.metadata_of(unfolded)["measurements"]
    assert old["bbox"] == pytest.approx(measured["bbox"], abs=1e-9)
    assert old["volume"] == pytest.approx(measured["volume"])
    assert old["solids"] == measured["solids"]
