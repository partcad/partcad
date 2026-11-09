#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""PartCAD's decoder of meshoptimizer's codecs ('wrappers/meshopt_decode.py'), against meshoptimizer itself.

The vectors in 'data/import_gltf/meshopt_vectors.json' are streams meshoptimizer's
own encoder wrote and what its own decoder read them as (see 'make_fixtures.py'
there): attributes in version 0 and in version 1, where the encoder chose 2-byte
and rotated XOR deltas as well as byte deltas, every filter, and triangles and
index sequences. A filter's result is specified to one unit in the last place,
and the reference rounds in single precision, so a filtered component may differ
from it by one.
"""

import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest

import partcad as pc

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import meshopt_decode  # noqa: E402

VECTORS = json.loads((Path("tests/partcad/unit/data/import_gltf/meshopt_vectors.json")).read_text())

# The type each filter's output is in, by its element's size.
_FILTERED = {
    "OCTAHEDRAL": {4: "i1", 8: "<i2"},
    "QUATERNION": {8: "<i2"},
    "EXPONENTIAL": {12: "<f4"},
    "COLOR": {4: "u1", 8: "<u2"},
}


def _name(vector):
    return "%s-%s-%d-%s" % (vector["mode"], vector["filter"], vector["stride"], vector["encoded"][:2])


@pytest.mark.parametrize("vector", VECTORS, ids=[_name(v) for v in VECTORS])
def test_what_meshoptimizer_wrote_decodes_as_it_reads_it(vector):
    decoded = meshopt_decode.decode(
        bytes.fromhex(vector["encoded"]),
        vector["count"],
        vector["stride"],
        vector["mode"],
        vector["filter"],
        khr=vector["khr"],
    )
    expected = bytes.fromhex(vector["decoded"])
    if vector["filter"] == "NONE":
        assert decoded == expected
    else:
        dtype = _FILTERED[vector["filter"]][vector["stride"]]
        ours = np.frombuffer(decoded, dtype).astype(np.float64)
        theirs = np.frombuffer(expected, dtype).astype(np.float64)
        assert np.abs(ours - theirs).max() <= 1


def test_the_vectors_cover_every_mode_filter_and_version():
    seen = {(v["mode"], v["filter"]) for v in VECTORS}
    assert {("TRIANGLES", "NONE"), ("INDICES", "NONE"), ("ATTRIBUTES", "NONE")} <= seen
    assert {("ATTRIBUTES", name) for name in ("OCTAHEDRAL", "QUATERNION", "EXPONENTIAL", "COLOR")} <= seen
    versions = {bytes.fromhex(v["encoded"])[0] for v in VECTORS if v["mode"] == "ATTRIBUTES"}
    assert {0xA0, 0xA1} <= versions
    # Version 1's channel modes, read from each stream's tail: byte deltas (0),
    # 2-byte deltas (1) and XOR deltas (2), the last with a rotation.
    modes = set()
    for vector in VECTORS:
        data = bytes.fromhex(vector["encoded"])
        if vector["mode"] == "ATTRIBUTES" and data[0] == 0xA1:
            stride = vector["stride"]
            modes.update(data[len(data) - stride // 4 :])
    assert {mode & 0x0F for mode in modes} == {0, 1, 2}
    assert any(mode >> 4 for mode in modes)


def test_the_specification_s_own_example_of_a_4_bit_group():
    """EXT_meshopt_compression, Appendix A: ten bytes, sixteen deltas, two of them stored whole."""
    data = bytes([0x17, 0x5F, 0xF0, 0xBC, 0x77, 0xA9, 0x21, 0x00, 0x34, 0xB5])
    row = []
    assert meshopt_decode._group(data, 0, 4, row) == len(data)
    deltas = [(value >> 1) ^ -(value & 1) for value in row]
    assert deltas == [-1, -4, -3, 26, -91, 0, -6, 6, -4, -4, 5, -5, 1, -1, 0, 0]


@pytest.mark.parametrize(
    "data, value",
    [
        (b"\x7f", 0x7F),
        (b"\x81\x04", 0x201),
        # The specification's third example says 0x1fd005, which is not what
        # unsigned LEB128 - its own definition, and meshoptimizer's decoder -
        # makes of these bytes: 0x7f, then 0x20 << 7, then 0x05 << 14.
        (b"\xff\xa0\x05", 0x1507F),
    ],
)
def test_leb128_as_the_specification_defines_it(data, value):
    assert meshopt_decode._leb128(data, 0) == (value, len(data))


@pytest.mark.parametrize(
    "mode, header, message",
    [
        ("ATTRIBUTES", 0x55, "not a meshopt attribute stream"),
        ("ATTRIBUTES", 0xA2, "newer than PartCAD reads"),
        ("TRIANGLES", 0xE0, "not a meshopt triangle stream"),
        ("INDICES", 0xD0, "not a meshopt index stream"),
    ],
)
def test_a_stream_of_another_kind_or_version_is_refused(mode, header, message):
    with pytest.raises(ValueError, match=message):
        meshopt_decode.decode(bytes([header]) + bytes(64), 3, 4, mode)


def _first(mode, filter_name="NONE"):
    return next(v for v in VECTORS if v["mode"] == mode and v["filter"] == filter_name)


@pytest.mark.parametrize("mode", ["ATTRIBUTES", "TRIANGLES", "INDICES"])
def test_a_stream_cut_short_or_with_bytes_over_is_refused(mode):
    vector = _first(mode)
    data = bytes.fromhex(vector["encoded"])
    with pytest.raises(ValueError):
        meshopt_decode.decode(data[: len(data) // 2], vector["count"], vector["stride"], mode)
    with pytest.raises(ValueError):
        # One more byte before the tail is a byte nothing uses.
        tail = 16 if mode == "TRIANGLES" else (4 if mode == "INDICES" else 32)
        meshopt_decode.decode(data[:-tail] + b"\0" + data[-tail:], vector["count"], vector["stride"], mode)


def test_what_the_extension_does_not_allow_is_refused():
    vector = _first("ATTRIBUTES", "COLOR")
    with pytest.raises(ValueError, match="unknown meshopt filter 'COLOR'"):
        # COLOR is KHR_meshopt_compression's, not EXT_meshopt_compression's.
        meshopt_decode.decode(
            bytes.fromhex(vector["encoded"]), vector["count"], vector["stride"], "ATTRIBUTES", "COLOR"
        )
    with pytest.raises(ValueError, match="unknown meshopt compression mode"):
        meshopt_decode.decode(b"", 0, 4, "POINTS")
    with pytest.raises(ValueError, match="takes no filter"):
        meshopt_decode.decode(b"", 3, 4, "TRIANGLES", "OCTAHEDRAL")
    with pytest.raises(ValueError, match="multiple of 4"):
        meshopt_decode.decode_vertex_buffer(b"\xa0" + bytes(40), 1, 6)
