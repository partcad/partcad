#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Reading a shape's topology off its BREP payload, and what the check does with it.

The point of 'partcad.brep_inspect' is that the core can answer "is this part a
body or a skin?" from the bytes it already holds - no CAD kernel, no sandbox, no
full parse of the payload. So this file imports no CAD library, and the fixtures
it reads are real 'BRepTools::Write' output checked in beside it (see
'data/brep/README.md').
"""

import asyncio
import os
import subprocess
import sys

import pytest

from partcad import brep_inspect, shape_envelope
from partcad.test.shell import ShellTest

try:
    from compression.zstd import compress as zstd_compress
except ImportError:  # pragma: no cover - taken on Python below 3.14
    from backports.zstd import compress as zstd_compress


DATA = os.path.join(os.path.dirname(__file__), "data", "brep")


def payload(name):
    with open(os.path.join(DATA, name), "rb") as f:
        return f.read()


# What each fixture is, as OCCT reports it: (root type, free shells, shells).
FIXTURES = {
    "solid.brep": ("solid", 0, 1),
    "shell_closed.brep": ("shell", 1, 1),
    "shell_open.brep": ("shell", 1, 1),
    "face.brep": ("face", 0, 0),
    "compound_solid_and_shell.brep": ("compound", 1, 2),
    "compound_two_solids.brep": ("compound", 0, 2),
    "compound_nested_shell.brep": ("compound", 1, 2),
    "compsolid.brep": ("compsolid", 0, 2),
}


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_the_topology_of_every_fixture(name):
    root, free, shells = FIXTURES[name]
    topology = brep_inspect.topology(payload(name))
    assert topology is not None, "the fixture did not read at all"
    assert topology.root == root
    assert topology.count("shell") == shells
    assert topology.free_shells == free


def test_a_solid_has_a_shell_and_owns_it():
    """The distinction the whole module exists for.

    Every solid is bounded by a shell, so "the payload contains a shell" is true
    of a box and says nothing. What is asked is whether a shell bounds anything.
    """
    topology = brep_inspect.topology(payload("solid.brep"))
    assert topology.count("shell") == 1
    assert topology.count("solid") == 1
    assert topology.free_shells == 0


def test_a_compound_of_two_solids_owns_both_its_shells():
    """Counted, not sensed: two owners, two owned shells, nothing left over."""
    topology = brep_inspect.topology(payload("compound_two_solids.brep"))
    assert topology.count("shell") == 2
    assert topology.count("solid") == 2
    assert topology.free_shells == 0


def test_a_compound_that_holds_a_shell_beside_a_solid():
    """The case that needs the care: one shell is a boundary, the other is not."""
    topology = brep_inspect.topology(payload("compound_solid_and_shell.brep"))
    assert topology.count("shell") == 2
    assert topology.count("solid") == 1
    assert topology.free_shells == 1


def test_a_compsolids_references_are_not_mistaken_for_shells():
    """A compsolid is made of solids. Both of its shells still bound a solid."""
    topology = brep_inspect.topology(payload("compsolid.brep"))
    assert topology.count("shell") == 2
    assert topology.free_shells == 0


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_the_payload_reads_the_same_however_it_is_carried(name):
    """Compressed bytes, base64 of them, or plain BREP - one answer."""
    plain = payload(name)
    compressed = zstd_compress(plain, 3)
    assert compressed.startswith(shape_envelope.ZSTD_MAGIC)
    expected = brep_inspect.free_shells(plain)
    assert brep_inspect.free_shells(compressed) == expected
    assert brep_inspect.free_shells(shape_envelope.brep_base64(compressed)) == expected


def test_a_payload_that_cannot_be_read_is_not_an_answer():
    """None, never zero: "no shell found" and "nothing read" are not the same."""
    assert brep_inspect.topology(b"") is None
    assert brep_inspect.topology(b"not a brep at all") is None
    assert brep_inspect.free_shells(b"\x00\x01\x02\x03") is None
    # Plausible up to the point where it is not: the header is there, the
    # section is not.
    assert brep_inspect.topology(b"CASCADE Topology V3, (c) Open Cascade\nLocations 0\n") is None
    # ...and a payload that stops in the middle of the records it declared.
    truncated = payload("solid.brep")
    assert brep_inspect.topology(truncated[: truncated.index(b"TShapes") + 40]) is None


def test_a_record_that_is_not_a_shape_type_stops_the_scan():
    """A format this no longer understands reads as unread, not as "no shell"."""
    broken = payload("shell_closed.brep").replace(b"\nSh\n", b"\nXx\n", 1)
    assert brep_inspect.topology(broken) is None


def test_the_declared_record_count_is_what_is_read():
    """The scan follows the count in the header rather than running to the end."""
    data = payload("solid.brep")
    header = data.index(b"TShapes 34")
    # One fewer record declared: the solid, written last, is not read, so the
    # shell it bounds is nobody's.
    fewer = data[:header] + data[header:].replace(b"TShapes 34", b"TShapes 33", 1)
    topology = brep_inspect.topology(fewer)
    assert topology.root == "shell"
    assert topology.free_shells == 1


def test_uncompressed_and_compressed_payloads_are_told_apart_by_the_frame():
    """'brep_plain' sniffs the zstd header; nothing in the envelope declares it."""
    plain = payload("face.brep")
    assert shape_envelope.brep_plain(plain) == plain
    assert shape_envelope.brep_plain(zstd_compress(plain, 3)) == plain
    assert shape_envelope.brep_plain(shape_envelope.brep_base64(zstd_compress(plain, 3))) == plain


def test_an_envelope_is_walked_and_an_assembly_with_it():
    """A shell anywhere in an assembly is a shell in the shape."""
    solid = {"name": "a", "label": "a", "brep": payload("solid.brep")}
    shell = {"name": "b", "label": "b", "brep": payload("shell_open.brep")}

    assert brep_inspect.envelope_free_shells(solid) == (0, 0)
    assert brep_inspect.envelope_free_shells(shell) == (1, 0)
    assert brep_inspect.envelope_free_shells({"name": "c", "assembly": [solid, solid]}) == (0, 0)
    assert brep_inspect.envelope_free_shells({"name": "c", "assembly": [solid, shell]}) == (1, 0)
    # Nested one level deeper, and beside a payload nothing can read.
    nested = {"assembly": [solid, {"assembly": [shell, {"brep": b"junk"}]}]}
    assert brep_inspect.envelope_free_shells(nested) == (1, 1)
    # Anything that is not an envelope contributes nothing rather than raising.
    assert brep_inspect.envelope_free_shells({"shape": None}) == (0, 0)
    assert brep_inspect.envelope_free_shells(None) == (0, 0)


class _Shape:
    """The little of a Shape that the 'shell' check touches."""

    def __init__(self, envelope, config=None, raises=None):
        self.config = config or {}
        self.project_name = "pkg"
        self.name = "thing"
        self._envelope = envelope
        self._raises = raises

    async def get_wrapped(self, ctx):
        if self._raises:
            raise self._raises
        return self._envelope


def verdict(shape, test_ctx=None):
    test_ctx = {} if test_ctx is None else test_ctx
    return asyncio.run(ShellTest().test([], None, shape, test_ctx))


def envelope(name):
    return {"name": "pkg:thing", "label": "thing", "brep": payload(name)}


def test_the_check_passes_a_solid_and_fails_a_free_shell():
    assert verdict(_Shape(envelope("solid.brep"))) == ShellTest.TEST_PASSED
    assert verdict(_Shape(envelope("shell_open.brep"))) == ShellTest.TEST_FAILED
    assert verdict(_Shape(envelope("compound_solid_and_shell.brep"))) == ShellTest.TEST_FAILED
    assert verdict(_Shape(envelope("compound_two_solids.brep"))) == ShellTest.TEST_PASSED


def test_a_part_that_is_meant_to_be_a_surface_says_so():
    shape = _Shape(envelope("shell_open.brep"), config={"shell": {"skip": True}})
    assert verdict(shape) == ShellTest.TEST_PASSED


def test_the_skip_setting_reaches_the_cache_key():
    """Or turning it off hands back the answer from before it was turned off."""
    test = ShellTest()
    plain = test.cache_key_suffix(None, _Shape(None))
    skipped = test.cache_key_suffix(None, _Shape(None, config={"shell": {"skip": True}}))
    assert plain != skipped


def test_a_shape_that_did_not_build_is_the_cad_checks_to_report():
    """Not a second failure naming a cause that is not the cause."""
    test_ctx = {}
    assert verdict(_Shape(None), test_ctx) == ShellTest.TEST_PASSED
    assert test_ctx[ShellTest.NOT_CACHEABLE]

    test_ctx = {}
    assert verdict(_Shape(None, raises=Exception("boom")), test_ctx) == ShellTest.TEST_PASSED
    assert test_ctx[ShellTest.NOT_CACHEABLE]


def test_a_payload_nothing_could_read_is_not_remembered_as_a_pass():
    test_ctx = {}
    shape = _Shape({"name": "pkg:thing", "label": "thing", "brep": b"not a brep"})
    assert verdict(shape, test_ctx) == ShellTest.TEST_PASSED
    assert test_ctx[ShellTest.NOT_CACHEABLE]


def test_no_cad_kernel_is_loaded_to_answer_the_question():
    """The constraint this module exists for, asserted rather than assumed.

    In a subprocess, because the suite as a whole may have imported OCP for
    another reason and this process's 'sys.modules' would then say nothing about
    whether answering the question needed it.
    """
    program = (
        "import sys\n"
        "from partcad import brep_inspect\n"
        "with open(sys.argv[1], 'rb') as f:\n"
        "    topology = brep_inspect.topology(f.read())\n"
        "assert topology is not None and topology.free_shells == 1, topology\n"
        "loaded = sorted(m for m in sys.modules if m.split('.')[0] in ('OCP', 'cadquery', 'build123d'))\n"
        "assert not loaded, loaded\n"
        "print('clean')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", program, os.path.join(DATA, "shell_open.brep")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "clean" in result.stdout
