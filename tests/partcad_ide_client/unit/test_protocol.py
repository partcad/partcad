#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import json
import os
import re
import struct

import pytest

from partcad_ide_client import protocol


def test_frame_roundtrip():
    message = {"type": protocol.MSG_SHOW, "id": "abc", protocol.KEY_OBJECT: None}
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


def test_make_node_and_is_node():
    node = protocol.make_node(b"glTF", name="//pkg:part", label="part")

    assert protocol.is_node(node)
    assert node[protocol.KEY_NAME] == "//pkg:part"
    assert node[protocol.KEY_LABEL] == "part"
    assert protocol.decode_gltf(node[protocol.KEY_GLTF]) == b"glTF"
    # A part is a tree one node deep: nothing inside it, and no key saying so.
    assert protocol.KEY_ASSEMBLY not in node

    # A node that holds others rather than geometry is a node too - an assembly's
    # own node is exactly that.
    assert protocol.is_node(protocol.make_node(name="//pkg:mount", children=[]))

    assert not protocol.is_node({"name": "//pkg:part"})
    assert not protocol.is_node("//pkg:part")


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


# ---- the viewer's tabs -----------------------------------------------------

_MESSAGES_TS = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "ide", "vscode", "src", "webview", "messages.ts"
)


def _ts_tab_groups() -> dict:
    """'TAB_GROUPS' as 'messages.ts' writes it, read off the source."""
    with open(_MESSAGES_TS, encoding="utf-8") as f:
        source = f.read()
    block = re.search(r"export const TAB_GROUPS[^=]*= \{(.*?)\n\};", source, re.S)
    assert block, "TAB_GROUPS is not where this test looks for it in %s" % _MESSAGES_TS
    constants = {
        name: re.findall(r"'([^']+)'", body)
        for name, body in re.findall(r"export const (\w+): TabId\[\] = \[([^\]]*)\]", source)
    }
    groups = {}
    for group, value in re.findall(r"^\s*(\w+): (.+?),$", block.group(1), re.M):
        groups[group] = constants[value] if value in constants else re.findall(r"'([^']+)'", value)
    return groups


def test_the_viewer_tabs_are_the_ones_the_extension_has():
    """A tab 'pc ide view' can name and the viewer cannot open is a flag that does nothing."""
    assert _ts_tab_groups() == {group: list(tabs) for group, tabs in protocol.VIEWER_TABS.items()}


def test_every_tab_is_a_tab_id_of_the_extension():
    with open(_MESSAGES_TS, encoding="utf-8") as f:
        union = re.search(r"export type TabId =(.*?);", f.read(), re.S).group(1)
    ids = set(re.findall(r"'([^']+)'", union))
    assert set(protocol.viewer_tab_ids()) <= ids
    assert set(protocol.VIEWER_TABS) <= ids


def test_the_tab_ids_are_listed_group_by_group():
    assert protocol.viewer_tab_ids()[:3] == ("3d", "2d", "draft")
    assert len(set(protocol.viewer_tab_ids())) == len(protocol.viewer_tab_ids())
