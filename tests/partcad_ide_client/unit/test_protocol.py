#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import base64
import json
import math
import os
import re
import struct
import zlib

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


GLB = b"glTF\x02\x00\x00\x00" + bytes(range(256)) * 40


def test_a_gltf_payload_is_the_glb_itself():
    # Not compressed: on a loopback socket zlib cost more than the bytes it saved.
    payload = protocol.encode_gltf(bytearray(GLB))

    assert payload == GLB
    assert type(payload) is bytes
    assert protocol.decode_gltf(payload) == GLB


@pytest.mark.parametrize("level", [0, 1, 6, 9])
def test_every_spelling_an_older_partcad_wrote_is_still_read(level):
    """Base64 of zlib at any level, as text or as bytes: what a tessellation cached before may hold."""
    stream = zlib.compress(GLB, level)

    assert protocol.decode_gltf(base64.b64encode(stream).decode("ascii")) == GLB
    assert protocol.decode_gltf(stream) == GLB
    # And base64 of the GLB itself, which nothing wrote but which is no harder to read.
    assert protocol.decode_gltf(base64.b64encode(GLB).decode("ascii")) == GLB


def test_a_glb_is_never_taken_for_a_zlib_stream():
    assert not protocol.is_zlib(GLB)
    assert all(protocol.is_zlib(zlib.compress(GLB, level)) for level in range(10))


def test_gltf_rejects_non_bytes():
    with pytest.raises(TypeError):
        protocol.encode_gltf("not bytes")


def _show(geometry=None, **node):
    obj = {"name": "//pkg:assy", "label": None, "assembly": [{"name": "//pkg:bolt", "gltfRef": "bolt"}]}
    obj.update(node)
    if geometry is not None:
        obj[protocol.KEY_GEOMETRY] = geometry
    return {"type": protocol.MSG_SHOW, "id": "show", protocol.KEY_OBJECT: obj}


def _roundtrip(message, binary):
    frame = protocol.encode_frame(message, binary=binary)
    kind, length = protocol.read_header(frame[: protocol.HEADER_LENGTH])
    assert length == len(frame) - protocol.HEADER_LENGTH
    return kind, protocol.decode_payload(frame[protocol.HEADER_LENGTH :], kind)


def test_a_binary_frame_carries_the_glb_as_blobs_and_gives_it_back_where_it_was():
    sketch = {"name": "//pkg:circle", "gltf": b"glTF-sketch"}
    message = _show({"bolt": GLB, "nut": b"glTF-nut"}, gltf=b"glTF-own", sketches={"//pkg:circle": sketch})

    kind, decoded = _roundtrip(message, binary=True)

    assert kind == protocol.KIND_BINARY
    assert decoded == message


def test_a_binary_frame_is_laid_out_as_the_protocol_says():
    """The layout by hand, as the extension's reader reads it: no helper on either side to agree with."""
    message = _show({"bolt": GLB})
    frame = protocol.encode_frame(message, binary=True)
    payload = frame[protocol.HEADER_LENGTH :]

    (text_length,) = struct.unpack(">I", payload[:4])
    sent = json.loads(payload[4 : 4 + text_length])
    # The payload is the index of its blob, and nothing else of the message moved.
    assert sent[protocol.KEY_OBJECT][protocol.KEY_GEOMETRY] == {"bolt": 0}
    assert sent[protocol.KEY_OBJECT]["assembly"] == message[protocol.KEY_OBJECT]["assembly"]
    rest = payload[4 + text_length :]
    (count,) = struct.unpack(">I", rest[:4])
    (size,) = struct.unpack(">I", rest[4:8])
    assert (count, size) == (1, len(GLB))
    assert rest[8:] == GLB


def test_one_buffer_named_twice_is_one_blob():
    glb = b"glTF-shared"
    message = _show({"bolt": glb}, gltf=glb)

    frame = protocol.encode_frame(message, binary=True)

    assert frame.count(glb) == 1
    assert _roundtrip(message, binary=True)[1] == message


def test_only_payloads_are_blobs_whatever_else_a_node_says():
    """A package's metadata and properties are its own words, and an integer or a 'gltf' key in them is just that."""
    said = {"gltf": 0, "geometry": {"bolt": 0}, "count": 3}
    message = _show({"bolt": GLB}, metadata=said, properties={"gltf": "red"})

    _, decoded = _roundtrip(message, binary=True)

    assert decoded[protocol.KEY_OBJECT]["metadata"] == said
    assert decoded[protocol.KEY_OBJECT]["properties"] == {"gltf": "red"}


def test_encoding_leaves_the_tree_it_was_handed_alone():
    """The tree is the one PartCAD keeps; a frame of it must not turn its bytes into indices or text."""
    message = _show({"bolt": GLB}, gltf=b"glTF-own")
    before = json.dumps(message, default=lambda value: value.hex())

    protocol.encode_frame(message, binary=True)
    protocol.encode_frame(message)

    assert json.dumps(message, default=lambda value: value.hex()) == before


def test_a_json_frame_spells_the_glb_as_an_ide_from_before_binary_frames_reads_it():
    """Base64 of a zlib stream - stored, level 0: a copy, not a compression - which is all that IDE inflates."""
    kind, decoded = _roundtrip(_show({"bolt": GLB}), binary=False)

    assert kind == protocol.KIND_JSON
    payload = decoded[protocol.KEY_OBJECT][protocol.KEY_GEOMETRY]["bolt"]
    # What 'decodeGltf' in such an extension does: inflate(base64), and nothing else.
    assert zlib.decompress(base64.b64decode(payload)) == GLB
    assert len(base64.b64decode(payload)) > len(GLB)


def test_a_json_frame_too_large_stored_is_compressed_rather_than_refused(monkeypatch):
    # Everything that fitted a frame before binary frames still fits one.
    glb = b"glTF" + b"\x00" * 100000
    monkeypatch.setattr(protocol, "MAX_FRAME_LENGTH", 20000)

    _, decoded = _roundtrip(_show({"bolt": glb}), binary=False)

    payload = decoded[protocol.KEY_OBJECT][protocol.KEY_GEOMETRY]["bolt"]
    assert len(payload) < 20000
    assert protocol.decode_gltf(payload) == glb


def test_a_frame_that_cannot_fit_is_refused_before_anything_is_written(monkeypatch):
    monkeypatch.setattr(protocol, "MAX_FRAME_LENGTH", 1000)
    with pytest.raises(protocol.FrameTooLarge):
        protocol.frame_parts(_show({"bolt": os.urandom(5000)}), binary=True)


def test_text_spelled_payloads_go_into_a_binary_frame_as_the_glb():
    old = base64.b64encode(zlib.compress(GLB, 6)).decode("ascii")

    _, decoded = _roundtrip(_show({"bolt": old}), binary=True)

    assert decoded[protocol.KEY_OBJECT][protocol.KEY_GEOMETRY]["bolt"] == GLB


def test_a_held_entry_stays_null_in_either_kind():
    for binary in (True, False):
        _, decoded = _roundtrip(_show({"bolt": None}), binary=binary)
        assert decoded[protocol.KEY_OBJECT][protocol.KEY_GEOMETRY] == {"bolt": None}


def test_a_geometry_message_carries_its_table_as_blobs():
    message = {"type": protocol.MSG_GEOMETRY, "id": "g", protocol.KEY_GEOMETRY: {"bolt": GLB}}

    assert _roundtrip(message, binary=True)[1] == message


def _binary(text, blobs):
    body = text if isinstance(text, bytes) else json.dumps(text).encode("utf-8")
    parts = [struct.pack(">I", len(body)), body, struct.pack(">I", len(blobs))]
    for blob in blobs:
        parts += [struct.pack(">I", len(blob)), blob]
    return b"".join(parts)


@pytest.mark.parametrize(
    "payload, match",
    [
        (b"\x00\x00", "inside a length"),
        (struct.pack(">I", 1000) + b"{}", "inside its message"),
        (_binary(_show({"bolt": 1}), [b"glTF"]), "names blob 1 of 1"),
        (_binary(_show({"bolt": 0}), [b"glTF"])[:-2], "inside blob 0"),
        (_binary(_show({"bolt": 0}), [b"glTF"]) + b"!", "after its last blob"),
        (_binary(b"[1]", []), "JSON object"),
    ],
)
def test_a_binary_payload_that_does_not_add_up_is_refused(payload, match):
    with pytest.raises(protocol.ProtocolError, match=match):
        protocol.decode_payload(payload, protocol.KIND_BINARY)


def test_json_true_is_not_blob_one():
    decoded = protocol.decode_payload(_binary(_show({"bolt": True}), [b"a", b"b"]), protocol.KIND_BINARY)
    assert decoded[protocol.KEY_OBJECT][protocol.KEY_GEOMETRY]["bolt"] is True


def test_the_header_names_either_kind():
    for kind in protocol.KINDS:
        header = struct.pack(protocol.HEADER_FORMAT, protocol.MAGIC, protocol.VERSION, kind, 7)
        assert protocol.read_header(header) == (kind, 7)
        assert protocol.decode_header(header) == 7


def test_make_node_and_is_node():
    node = protocol.make_node(b"glTF", name="//pkg:part", label="part")

    assert protocol.is_node(node)
    assert node[protocol.KEY_NAME] == "//pkg:part"
    assert node[protocol.KEY_LABEL] == "part"
    assert node[protocol.KEY_GLTF] == b"glTF"
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


def test_the_tabs_a_scenario_is_selected_on_are_the_ones_the_extension_lists_them_on():
    """'pc ide view --scenario' is refused on any other tab, so the two lists have to agree."""
    with open(_MESSAGES_TS, encoding="utf-8") as f:
        source = f.read()
    body = re.search(r"export const SCENARIO_TABS: TabId\[\] = \[([^\]]*)\]", source).group(1)
    tabs = []
    for item in [part.strip() for part in body.split(",") if part.strip()]:
        # '...ANALYSIS_TABS' spreads the Analysis strip, which is VIEWER_TABS' own.
        tabs.extend(protocol.VIEWER_TABS["analysis"] if item == "...ANALYSIS_TABS" else re.findall(r"'([^']+)'", item))
    assert tuple(tabs) == protocol.SCENARIO_TABS


# ---- the extension's half --------------------------------------------------

_PROTOCOL_TS = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "ide", "vscode", "src", "viewer", "protocol.ts"
)


def _ts_constant(source, name):
    match = re.search(r"export const %s(?:: [^=]+)? = ([^;]+);" % name, source)
    assert match, "%s is not where this test looks for it in %s" % (name, _PROTOCOL_TS)
    return match.group(1).strip()


def test_the_extension_reads_the_kinds_and_says_the_capabilities_this_side_sends_and_asks_for():
    """Two independently released halves: a name that differs is a capability neither side ever sees."""
    with open(_PROTOCOL_TS, encoding="utf-8") as f:
        source = f.read()
    assert int(_ts_constant(source, "KIND_JSON")) == protocol.KIND_JSON
    assert int(_ts_constant(source, "KIND_BINARY")) == protocol.KIND_BINARY
    for name in (
        "CAP_BINARY",
        "CAP_OFFER",
        "MSG_OFFER",
        "MSG_GEOMETRY",
        "KEY_DIGESTS",
        "KEY_MISSING",
        "KEY_CAPABILITIES",
    ):
        assert _ts_constant(source, name) == "'%s'" % getattr(protocol, name), name
    # A product of integers there; the geometry that follows an offer is cut
    # into frames by this side's limit, and that side refuses one over its own.
    factors = [int(factor) for factor in _ts_constant(source, "MAX_FRAME_LENGTH").split("*")]
    assert math.prod(factors) == protocol.MAX_FRAME_LENGTH


def test_a_geometry_name_is_of_the_buffer_whatever_its_spelling():
    glb = b"glTF" + bytes(range(256)) * 4
    spelled = base64.b64encode(zlib.compress(glb, 6)).decode("ascii")

    assert protocol.geometry_name(glb) == protocol.geometry_name(spelled)
    assert protocol.geometry_name(glb) == protocol.geometry_name(memoryview(glb))
    assert protocol.geometry_name(glb) == protocol.geometry_name(bytearray(glb))
    assert protocol.geometry_name(glb) != protocol.geometry_name(glb + b"\x00")
