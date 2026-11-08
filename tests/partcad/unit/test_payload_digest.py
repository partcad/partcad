#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What names a BREP payload, and why it is the same name on every machine.

A payload is carried zstd-compressed, and two compressors need not write the
same frame for the same bytes: Python 3.14 compresses with the standard
library's zstd, earlier ones with 'backports.zstd', and either may sit on
another libzstd. What is keyed by a payload's name - each shape's
tessellation, and every request a wrapper is keyed on by content - is shared
between machines, so the name ('payload_digest', one copy on each side of the
pipe) is a digest of the BREP and never of the frame. These hold the two
copies to that and to each other, the core's compressor to the sandbox's, and
the one producer of BREP in the core ('basic_shapes') to bytes no platform
can change.
"""

import ast
import hashlib
import inspect
import math
import os
import sys
import textwrap

import pytest

import partcad as pc
from partcad import basic_shapes, brep_ascii, cache_artifacts, shape_envelope

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import mass_properties  # noqa: E402
import ocp_serialize  # noqa: E402

try:
    from compression.zstd import compress as _compress
except ImportError:  # pragma: no cover - exercised on the other interpreter
    from backports.zstd import compress as _compress

# A plain payload that compresses no better than geometry does.
PLAIN = b"".join(hashlib.sha256(b"geometry %d" % i).digest() for i in range(4096))
# One that compresses as an ASCII BREP does, so that two levels write two frames.
TEXT = b" ".join(b"%d.%d" % (i * i % 9973, i % 97) for i in range(40000))


def _leaf(payload):
    return {"name": "//pkg:part", "label": "part", shape_envelope.KEY_BREP: payload}


# --------------------------------------------------------------------------- #
# The name of a payload                                                       #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("level", [1, 3, 9, 19])
def test_a_payload_is_named_by_its_brep_whatever_frame_carries_it(level):
    frame = _compress(PLAIN, level)
    expected = hashlib.sha256(PLAIN).hexdigest()

    assert shape_envelope.payload_digest(frame) == expected
    assert shape_envelope.payload_digest(shape_envelope.brep_base64(frame)) == expected
    assert ocp_serialize.payload_digest(frame) == expected


def test_a_payload_carried_uncompressed_has_the_name_of_its_compressed_twin():
    assert shape_envelope.payload_digest(PLAIN) == shape_envelope.payload_digest(_compress(PLAIN, 3))
    assert ocp_serialize.payload_digest(PLAIN) == shape_envelope.payload_digest(PLAIN)


@pytest.mark.parametrize("size", [0, 1, (1 << 20) - 1, 1 << 20, (1 << 20) + 1, 3 * (1 << 20) + 5])
def test_both_sides_agree_at_every_size_the_core_digests_in_chunks(size):
    """The core streams a frame through the digest a megabyte at a time; the sandbox decompresses it whole."""
    plain = (PLAIN * (size // len(PLAIN) + 1))[:size]
    frame = _compress(plain, 3)

    assert shape_envelope.payload_digest(frame) == ocp_serialize.payload_digest(frame)
    assert shape_envelope.payload_digest(frame) == hashlib.sha256(plain).hexdigest()


def test_different_geometry_is_a_different_name():
    assert shape_envelope.payload_digest(_compress(PLAIN, 3)) != shape_envelope.payload_digest(
        _compress(PLAIN + b"!", 3)
    )


def test_a_frame_cut_short_is_refused_rather_than_named():
    with pytest.raises(ValueError, match="ended before"):
        shape_envelope.payload_digest(_compress(PLAIN, 3)[:-16])


def test_a_frame_that_expands_past_the_bound_is_refused_rather_than_named():
    """Bounded exactly as 'brep_plain()' is: what the core digests may come from a cache it does not trust."""
    bomb = _compress(b"\0" * (64 << 20), 3)
    with pytest.raises(ValueError, match="refusing to read it"):
        shape_envelope.payload_digest(bomb)


# --------------------------------------------------------------------------- #
# What is keyed by it                                                         #
# --------------------------------------------------------------------------- #


def test_a_request_is_the_same_key_whatever_frame_carries_its_geometry():
    """'request_key' names each payload by its digest, so another compressor asks the same question."""
    fast = {"wrapped": _leaf(_compress(TEXT, 1)), "options": {"a": 1}}
    small = {"options": {"a": 1}, "wrapped": _leaf(_compress(TEXT, 19))}

    assert fast["wrapped"][shape_envelope.KEY_BREP] != small["wrapped"][shape_envelope.KEY_BREP]
    assert cache_artifacts.request_key(fast) == cache_artifacts.request_key(small)


def test_a_request_about_other_geometry_is_another_key():
    one = {"wrapped": _leaf(_compress(PLAIN, 3))}
    other = {"wrapped": _leaf(_compress(PLAIN + b"!", 3))}

    assert cache_artifacts.request_key(one) != cache_artifacts.request_key(other)


# --------------------------------------------------------------------------- #
# The two compressors                                                         #
# --------------------------------------------------------------------------- #


def test_the_core_compresses_as_the_sandbox_does():
    """One frame format and one level on both sides of the pipe: the copies cannot import each other."""
    assert shape_envelope.ZSTD_LEVEL == ocp_serialize.ZSTD_LEVEL
    assert shape_envelope.ZSTD_MAGIC == ocp_serialize.ZSTD_MAGIC


def test_a_frame_the_core_writes_is_the_frame_the_sandbox_writes():
    """Not what the digest relies on - it reads past the frame - but what keeps a cache from holding two copies."""
    assert shape_envelope.brep_compressed(PLAIN) == ocp_serialize._compress(PLAIN)


# --------------------------------------------------------------------------- #
# The BREP the core writes                                                    #
# --------------------------------------------------------------------------- #

# What answers differently in the last bit on another platform or another
# Python: the C library's trigonometry, 'sum()' of floats (compensated from
# Python 3.12), and 'math.dist' (whose algorithm has changed across releases).
_PLATFORM_DEPENDENT = {"sin", "cos", "tan", "radians", "dist"}


@pytest.mark.parametrize(
    "source",
    # The two modules, and the one function of a wrapper's they borrow: what
    # turns a basic part's inertia tensor with the part.
    [brep_ascii, basic_shapes, mass_properties.turned],
    ids=["brep_ascii", "basic_shapes", "mass_properties.turned"],
)
def test_the_brep_writer_reaches_for_nothing_a_platform_rounds_its_own_way(source):
    tree = ast.parse(textwrap.dedent(inspect.getsource(source)))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "math":
            if node.attr in _PLATFORM_DEPENDENT:
                found.append("math.%s (line %d)" % (node.attr, node.lineno))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "sum":
            found.append("sum() (line %d)" % node.lineno)
    assert not found, "%s: %s" % (source.__name__, ", ".join(found))


@pytest.mark.parametrize(
    "degrees, expected",
    [
        (0, (1.0, 0.0)),
        (90, (0.0, 1.0)),
        (180, (-1.0, 0.0)),
        (270, (0.0, -1.0)),
        (-90, (0.0, -1.0)),
        (450, (0.0, 1.0)),
        (30, (0.8660254037844386, 0.5)),
        (60, (0.5, 0.8660254037844386)),
        (45, (0.7071067811865476, 0.7071067811865476)),
        (-30, (0.8660254037844386, -0.5)),
    ],
)
def test_an_angle_is_turned_exactly_where_the_exact_value_is_a_double(degrees, expected):
    """A quarter turn is 0 and 1, not 6e-17, and the rest is the double nearest the true value."""
    assert basic_shapes.cos_sin(degrees) == expected


def test_an_angle_is_turned_to_within_an_ulp_of_the_c_library_where_that_rounds_well():
    for degrees in [i * 0.37 for i in range(-500, 500)]:
        cos, sin = basic_shapes.cos_sin(degrees)
        radians = math.radians(degrees)
        assert cos == pytest.approx(math.cos(radians), abs=4e-16)
        assert sin == pytest.approx(math.sin(radians), abs=4e-16)


def test_an_angle_that_is_not_one_is_refused():
    for degrees in (math.inf, -math.inf, math.nan):
        with pytest.raises(ValueError):
            basic_shapes.cos_sin(degrees)
    with pytest.raises(ValueError, match="too large"):
        basic_shapes.cos_sin(1e300)


def test_a_turned_basic_part_is_the_same_bytes_every_time():
    """What a cache shared between machines needs of it, short of having two machines."""
    finish = {"validate": {"solidify": True}, "offset": [[1.5, -2, 3], [0.3, -0.7, 0.2], 37.25], "scale": 1.75}
    first = basic_shapes.part({"cylinder": {"radius": 3, "height": 7}}, finish)[0]
    again = basic_shapes.part({"cylinder": {"radius": 3, "height": 7}}, finish)[0]

    assert first == again
    assert shape_envelope.payload_digest(shape_envelope.brep_compressed(first)) == hashlib.sha256(first).hexdigest()


@pytest.mark.parametrize("degrees", [0, 30, 37.25, 90, 123.4, -71])
def test_a_turned_inertia_tensor_is_exactly_symmetric(degrees):
    """Not to within an ulp: an exporter writing both halves of it would write two numbers for one."""
    finish = {"validate": {"solidify": True}, "offset": [[0, 0, 0], [0.3, -0.7, 0.2], degrees]}
    tensor = basic_shapes.part({"cuboid": [10, 20, 30]}, finish)[1]["unitInertia"]

    for row in range(3):
        for col in range(3):
            assert tensor[row][col] == tensor[col][row]


def test_turning_a_tensor_keeps_it_symmetric_whatever_the_rotation():
    tensor = [[3.0, 0.5, -0.25], [0.5, 7.0, 1.125], [-0.25, 1.125, 11.0]]
    for step in range(200):
        angle = step * 0.0317
        axis = [math.sin(step), math.cos(step * 1.3), 0.5]
        norm = math.sqrt(sum(v * v for v in axis))
        x, y, z = (v / norm for v in axis)
        c, s, t = math.cos(angle), math.sin(angle), 1 - math.cos(angle)
        matrix = [
            [t * x * x + c, t * x * y - s * z, t * x * z + s * y],
            [t * x * y + s * z, t * y * y + c, t * y * z - s * x],
            [t * x * z - s * y, t * y * z + s * x, t * z * z + c],
        ]
        turned = mass_properties.turned(tensor, matrix)
        assert all(turned[r][k] == turned[k][r] for r in range(3) for k in range(3))
        # Still the same tensor: its trace does not change with the frame.
        assert math.fsum(turned[i][i] for i in range(3)) == pytest.approx(21.0, rel=1e-12)
