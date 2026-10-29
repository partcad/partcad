#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A payload carried by several nodes is written once, in a table on the document.

An assembly is mostly repeats of a few parts, and a document written a node at a
time carried each part as often as it was placed: the LEGO castle's render
request was 33 MB of JSON for 4.6 MB of geometry. 'shape_envelope.dumps(share=
True)' writes each payload once ('KEY_BREPS') and has every node name its entry
('KEY_BREP_REF'); 'loads()' puts the payloads back. These hold that the table is
invisible to everything that reads a tree, that it is written only when it saves
something, and that each side of the pipe reads what the other writes.

The table is the JSON form's: what a container is sent, and what a wrapper asked
in JSON answers. A frame ('serialize()') attaches each distinct payload once
instead, which 'test_wrapper_frames.py' holds.
"""

import json
import os
import sys

import pytest

import partcad as pc
from partcad import shape_envelope

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import ocp_serialize  # noqa: E402

# A part's payload is kilobytes; a table of payloads shorter than their digests
# would be larger than the document it replaces, and is not written.
BRICK = b"\x28\xb5\x2f\xfd" + b"brick geometry " * 200
CONE = b"\x28\xb5\x2f\xfd" + b"cone geometry " * 200


def _leaf(payload, label):
    return {"name": "//pkg:%s" % label, "label": label, shape_envelope.KEY_BREP: payload}


def _castle(placements=20):
    """A tree of many placements of two parts, as it is built in the daemon: one bytes object per part."""
    children = [
        dict(_leaf(BRICK if i % 4 else CONE, "brick"), label="b%d" % i, location=[[i, 0, 0], [0, 0, 1], 0])
        for i in range(placements)
    ]
    return {"name": "//pkg:castle", "label": "castle", shape_envelope.KEY_ASSEMBLY: children}


def _leaves(tree):
    if shape_envelope.KEY_BREP in tree:
        yield tree
    for child in tree.get(shape_envelope.KEY_ASSEMBLY) or []:
        yield from _leaves(child)


def test_a_repeated_payload_is_written_once():
    text = shape_envelope.dumps({"wrapped": _castle()}, share=True)
    document = json.loads(text)

    assert sorted(document[shape_envelope.KEY_BREPS]) == sorted(
        shape_envelope.payload_digest(payload) for payload in (BRICK, CONE)
    )
    assert '"%s":' % shape_envelope.KEY_BREP not in text
    assert len(text) < len(shape_envelope.dumps({"wrapped": _castle()}))


def test_the_table_is_taken_back_out_and_every_node_has_its_payload():
    request = {"wrapped": _castle(), "width": 512}

    read = shape_envelope.loads(shape_envelope.dumps(request, share=True))

    assert shape_envelope.KEY_BREPS not in read
    assert read == shape_envelope.loads(shape_envelope.dumps(request))


def test_nodes_naming_one_entry_hold_one_bytes_object():
    """So a tree read back holds each payload once, which is what 'total_size' then counts."""
    read = shape_envelope.loads(shape_envelope.dumps({"wrapped": _castle()}, share=True))

    bricks = [
        leaf[shape_envelope.KEY_BREP] for leaf in _leaves(read["wrapped"]) if leaf[shape_envelope.KEY_BREP] == BRICK
    ]
    assert len(bricks) > 1
    assert all(payload is bricks[0] for payload in bricks)


def test_nothing_repeated_is_the_document_it_always_was():
    request = {"wrapped": _leaf(BRICK, "brick"), "width": 512}

    assert shape_envelope.dumps(request, share=True) == shape_envelope.dumps(request)


def test_a_table_larger_than_what_it_replaces_is_not_written():
    """Payloads shorter than their digests: naming them would cost more than carrying them."""
    tiny = b"\x28\xb5\x2f\xfd tiny"
    tree = {"name": "x", shape_envelope.KEY_ASSEMBLY: [_leaf(tiny, "a"), _leaf(tiny, "b")]}

    assert shape_envelope.dumps({"wrapped": tree}, share=True) == shape_envelope.dumps({"wrapped": tree})


def test_without_share_nothing_changes():
    """Every JSON document nobody asked to share, as it always was."""
    text = shape_envelope.dumps({"wrapped": _castle()})

    assert shape_envelope.KEY_BREPS not in text
    assert shape_envelope.KEY_BREP_REF not in text


def test_equal_payloads_in_different_objects_are_still_one_entry():
    """A sub-assembly read back from the cache holds a copy of the bytes the one just built holds."""
    tree = _castle(4)
    tree[shape_envelope.KEY_ASSEMBLY].append(_leaf(bytes(bytearray(BRICK)), "copy"))

    document = json.loads(shape_envelope.dumps({"wrapped": tree}, share=True))

    assert len(document[shape_envelope.KEY_BREPS]) == 2


def test_a_reference_to_nothing_is_refused():
    document = {"wrapped": {"name": "x", shape_envelope.KEY_BREP_REF: "missing"}, shape_envelope.KEY_BREPS: {}}

    with pytest.raises(ValueError, match="missing"):
        shape_envelope.loads(json.dumps(document))


# --------------------------------------------------------------------------- #
# Across the pipe                                                             #
# --------------------------------------------------------------------------- #


def test_the_sandbox_reads_the_table_the_core_writes():
    """'deserialize_raw' - what wrapper_gltf and every tree-walking wrapper reads - sees no table."""
    request = {"wrapped": _castle(), "width": 512}

    shared = ocp_serialize.deserialize_raw(shape_envelope.dumps(request, share=True))
    plain = ocp_serialize.deserialize_raw(shape_envelope.dumps(request))

    assert shared == plain


def test_the_sandbox_holds_each_payload_it_was_sent_once():
    shared = ocp_serialize.deserialize_raw(shape_envelope.dumps({"wrapped": _castle()}, share=True))

    payloads = [leaf[ocp_serialize.KEY_BREP] for leaf in _leaves(shared["wrapped"])]
    distinct = {id(payload) for payload in payloads}
    assert len(distinct) == 2


def test_the_core_reads_the_table_the_sandbox_writes():
    """A wrapper's answer: the same tree, encoded leaf by leaf, then shared on the way out."""
    encoded = json.loads(shape_envelope.dumps({"shape": _castle()}))

    text = ocp_serialize.dumps(encoded, share=True)

    assert ocp_serialize.KEY_BREPS in json.loads(text)
    assert shape_envelope.deserialize(text) == shape_envelope.loads(json.dumps(encoded))


def test_a_sandbox_answer_with_nothing_repeated_is_unchanged():
    encoded = json.loads(shape_envelope.dumps({"shape": _leaf(BRICK, "brick")}))

    assert ocp_serialize.dumps(encoded, share=True) == ocp_serialize.dumps(encoded)


def test_both_ends_name_a_payload_the_same_way():
    assert ocp_serialize.payload_digest(shape_envelope.brep_base64(BRICK)) == shape_envelope.payload_digest(BRICK)
