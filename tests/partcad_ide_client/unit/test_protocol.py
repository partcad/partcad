#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import json
import struct

import pytest

from partcad_ide_client import protocol


def test_frame_roundtrip():
    message = {"type": protocol.MSG_SHOW, "id": "abc", "objects": []}
    frame = protocol.encode_frame(message)

    header, payload = frame[: protocol.HEADER_LENGTH], frame[protocol.HEADER_LENGTH :]
    assert protocol.decode_header(header) == len(payload)
    assert protocol.decode_payload(payload) == message


def test_frame_header_is_self_describing():
    frame = protocol.encode_frame({"type": protocol.MSG_PING})
    magic, version, kind, length = struct.unpack(protocol.HEADER_FORMAT, frame[: protocol.HEADER_LENGTH])

    assert magic == protocol.MAGIC
    assert version == protocol.VERSION
    assert kind == protocol.KIND_JSON
    assert length == len(frame) - protocol.HEADER_LENGTH


def test_gltf_roundtrip_and_compression():
    # Highly compressible, like a real tessellation's index/vertex buffers.
    glb = b"glTF\x02\x00\x00\x00" + b"\x00" * 100000
    payload = protocol.encode_gltf(glb)

    assert protocol.decode_gltf(payload) == glb
    # Base64 inflates by 4/3, so a payload smaller than the input proves the
    # compression happened and not just the encoding.
    assert len(payload) < len(glb)


def test_gltf_rejects_non_bytes():
    with pytest.raises(TypeError):
        protocol.encode_gltf("not bytes")


def test_make_object_and_is_object():
    obj = protocol.make_object(b"glTF", name="//pkg:part", label="part")

    assert protocol.is_object(obj)
    assert obj[protocol.KEY_NAME] == "//pkg:part"
    assert obj[protocol.KEY_LABEL] == "part"
    assert protocol.decode_gltf(obj[protocol.KEY_GLTF]) == b"glTF"

    assert not protocol.is_object({"name": "//pkg:part"})
    assert not protocol.is_object("//pkg:part")


def test_decode_header_rejects_bad_magic():
    header = struct.pack(protocol.HEADER_FORMAT, b"NOPE", protocol.VERSION, protocol.KIND_JSON, 0)
    with pytest.raises(protocol.ProtocolError, match="magic"):
        protocol.decode_header(header)


def test_decode_header_rejects_other_versions():
    header = struct.pack(protocol.HEADER_FORMAT, protocol.MAGIC, protocol.VERSION + 1, protocol.KIND_JSON, 0)
    with pytest.raises(protocol.ProtocolError, match="version"):
        protocol.decode_header(header)


def test_decode_header_rejects_unknown_kind():
    header = struct.pack(protocol.HEADER_FORMAT, protocol.MAGIC, protocol.VERSION, 99, 0)
    with pytest.raises(protocol.ProtocolError, match="kind"):
        protocol.decode_header(header)


def test_decode_header_rejects_oversized_frame():
    header = struct.pack(
        protocol.HEADER_FORMAT, protocol.MAGIC, protocol.VERSION, protocol.KIND_JSON, protocol.MAX_FRAME_LENGTH + 1
    )
    with pytest.raises(protocol.ProtocolError, match="exceeds"):
        protocol.decode_header(header)


def test_decode_header_rejects_short_header():
    with pytest.raises(protocol.ProtocolError, match="header"):
        protocol.decode_header(protocol.MAGIC)


def test_decode_payload_rejects_non_object():
    with pytest.raises(protocol.ProtocolError, match="JSON object"):
        protocol.decode_payload(json.dumps([1, 2, 3]).encode("utf-8"))


def test_decode_payload_rejects_garbage():
    with pytest.raises(protocol.ProtocolError, match="valid JSON"):
        protocol.decode_payload(b"\xff\xfe not json")
