#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The wrapper pipe is a frame: JSON with the payloads raw behind it.

PartCAD and its Python wrappers used to exchange one line of JSON in each
direction, with every BREP payload base64 inside it: compressed bytes, base64,
JSON, UTF-8 and back again on the other side, which at 50 MB of geometry was
seconds of the daemon's time spent holding the GIL. Now a request and its answer
are the frame the daemon and its clients exchange ('partcad_utils.framing'),
and a payload is an attachment: the bytes it is, once per distinct payload.

These hold the round trip in both directions, what the frame does with repeats,
that an answer is found past whatever was printed before it, that the JSON form
- what a container and a JavaScript runtime are sent, and what a wrapper asked
in it answers - is still read, and that every layer between the two ends keeps
the bytes as bytes.
"""

import asyncio
import base64
import os
import pathlib
import sys
import textwrap
import types

import pytest

import partcad as pc
from partcad import cache_artifacts, process_output, runtime, shape_envelope
from partcad_utils import framing

WRAPPERS = os.path.join(os.path.dirname(pc.__file__), "wrappers")
sys.path.append(WRAPPERS)
import ocp_serialize  # noqa: E402

BRICK = b"\x28\xb5\x2f\xfd" + os.urandom(4096)
CONE = b"\x28\xb5\x2f\xfd" + os.urandom(4096)


def _leaf(payload, label, **extra):
    return dict({"name": "//pkg:%s" % label, "label": label, shape_envelope.KEY_BREP: payload}, **extra)


def _castle(placements=12):
    """Many placements of two parts, one bytes object per part, as a tree is built in the daemon."""
    children = [
        _leaf(BRICK if i % 4 else CONE, "b%d" % i, location=[[i, 0, 0], [0, 0, 1], 0]) for i in range(placements)
    ]
    return {"name": "//pkg:castle", "label": "castle", shape_envelope.KEY_ASSEMBLY: children}


def _leaves(tree):
    if shape_envelope.KEY_BREP in tree:
        yield tree
    for child in tree.get(shape_envelope.KEY_ASSEMBLY) or []:
        yield from _leaves(child)


def _attachments(frame):
    """The lengths of the attachments a frame carries, as its header says."""
    return framing.attachment_lengths(framing.parse_headers(frame.split(b"\r\n\r\n", 1)[0]))


# --------------------------------------------------------------------------- #
# One format                                                                   #
# --------------------------------------------------------------------------- #


def test_the_sandbox_copy_of_the_framing_is_the_framing():
    """One implementation of the frame, in two places, because a sandbox cannot import 'partcad_utils'."""
    copy = pathlib.Path(WRAPPERS) / "partcad_framing.py"
    assert copy.read_bytes() == pathlib.Path(framing.__file__).read_bytes(), (
        "copy src/partcad_utils/framing.py over %s" % copy
    )


def test_a_request_is_the_frame_the_daemon_and_its_clients_exchange():
    frame = shape_envelope.serialize({"wrapped": _leaf(BRICK, "brick"), "width": 512})

    assert frame.startswith(b"Content-Length: ")
    assert _attachments(frame) == [len(BRICK)]
    # Raw, and not base64 anywhere.
    assert BRICK in frame
    assert base64.b64encode(BRICK) not in frame


# --------------------------------------------------------------------------- #
# The core to a wrapper                                                        #
# --------------------------------------------------------------------------- #


def test_a_wrapper_reads_the_request_the_core_writes():
    request = {"wrapped": _castle(), "width": 512, "blob": b"\x00\xff\n", "empty": b""}

    for read in (
        ocp_serialize.deserialize_raw(shape_envelope.serialize(request)),
        ocp_serialize.deserialize_raw(b"what printed first\n" + shape_envelope.serialize(request)),
    ):
        assert read["width"] == 512
        assert read["blob"] == b"\x00\xff\n"
        assert read["empty"] == b""
        assert [leaf["label"] for leaf in _leaves(read["wrapped"])] == [
            leaf["label"] for leaf in _leaves(request["wrapped"])
        ]
        assert all(
            leaf[ocp_serialize.KEY_BREP] == (BRICK if i % 4 else CONE)
            for i, leaf in enumerate(_leaves(read["wrapped"]))
        )


def test_a_frame_is_told_from_json():
    """Which is what decides the form a wrapper answers in."""
    request = {"wrapped": _leaf(BRICK, "brick")}

    assert ocp_serialize.is_frame(shape_envelope.serialize(request)) is True
    assert ocp_serialize.is_frame(shape_envelope.dumps(request).encode()) is False
    assert ocp_serialize.is_frame(shape_envelope.dumps(request)) is False
    assert ocp_serialize.is_frame(shape_envelope.serialize(request)[:-1]) is False


def test_bytes_read_raw_go_back_as_they_came():
    """A wrapper reading its request raw hands back what it holds of it, and the bytes in it stay bytes."""
    raw = ocp_serialize.deserialize_raw(shape_envelope.serialize({"blob": b"\x00", "nested": [{"more": b"\xff"}]}))

    assert raw == {"blob": b"\x00", "nested": [{"more": b"\xff"}]}
    for form in (ocp_serialize.serialize(raw), ocp_serialize.dumps(raw)):
        assert shape_envelope.deserialize(form) == raw


def test_each_distinct_payload_is_attached_once_and_held_once():
    """A repeat costs a reference, whether it is one object or two with the same bytes."""
    tree = _castle()
    # A sub-assembly read back from the cache holds a copy of the bytes one just built holds.
    tree[shape_envelope.KEY_ASSEMBLY].append(_leaf(bytes(bytearray(BRICK)), "copy"))
    frame = shape_envelope.serialize({"wrapped": tree})

    assert sorted(_attachments(frame)) == sorted([len(BRICK), len(CONE)])
    read = ocp_serialize.deserialize_raw(frame)
    assert len({id(leaf[ocp_serialize.KEY_BREP]) for leaf in _leaves(read["wrapped"])}) == 2
    # And no table: a frame needs none.
    assert shape_envelope.KEY_BREPS.encode() not in frame


def test_payloads_of_one_length_and_other_bytes_are_not_confused():
    other = BRICK[:-1] + bytes([BRICK[-1] ^ 1])
    frame = shape_envelope.serialize(
        {"wrapped": {"name": "x", shape_envelope.KEY_ASSEMBLY: [_leaf(BRICK, "a"), _leaf(other, "b")]}}
    )

    read = ocp_serialize.deserialize_raw(frame)
    assert [leaf[ocp_serialize.KEY_BREP] for leaf in _leaves(read["wrapped"])] == [BRICK, other]


def test_an_empty_payload_is_an_attachment_like_any_other():
    """Nothing, attached: what a wrapper that built nothing hands back, in both directions."""
    tree = {"name": "x", shape_envelope.KEY_ASSEMBLY: [_leaf(b"", "a"), _leaf(b"", "b"), _leaf(BRICK, "c")]}

    frame = shape_envelope.serialize({"wrapped": tree})

    assert sorted(_attachments(frame)) == [0, len(BRICK)]
    read = ocp_serialize.deserialize_raw(frame)
    assert [leaf[ocp_serialize.KEY_BREP] for leaf in _leaves(read["wrapped"])] == [b"", b"", BRICK]
    back = shape_envelope.deserialize(ocp_serialize.serialize({"tree": read["wrapped"]}))
    assert [leaf[shape_envelope.KEY_BREP] for leaf in _leaves(back["tree"])] == [b"", b"", BRICK]


def test_a_part_finish_request_travels_as_data():
    """What a part factory asks the wrapper building it to do (see 'Shape.finish_request')."""
    finish = {"validate": {"solidify": True}, "offset": [[1, 2, 3], [0, 0, 1], 0]}
    read = ocp_serialize.deserialize_raw(shape_envelope.serialize({"name": "p", "finish": finish}))

    assert read["finish"] == finish


# --------------------------------------------------------------------------- #
# A wrapper to the core                                                        #
# --------------------------------------------------------------------------- #


def test_the_core_reads_the_answer_a_wrapper_writes():
    raw = ocp_serialize.deserialize_raw(shape_envelope.serialize({"wrapped": _castle()}))
    answer = {"success": True, "tree": raw["wrapped"], "files": [b"\x89PNG", b""], "nested": {"deep": [b"x"]}}

    read = shape_envelope.deserialize(ocp_serialize.serialize(answer, name="//pkg:castle", label="castle"))

    assert read["success"] is True
    assert read["files"] == [b"\x89PNG", b""]
    assert read["nested"] == {"deep": [b"x"]}
    leaves = list(_leaves(read["tree"]))
    assert [leaf[shape_envelope.KEY_BREP] for leaf in leaves] == [
        leaf[ocp_serialize.KEY_BREP] for leaf in _leaves(raw["wrapped"])
    ]
    # Every node naming one attachment holds the one bytes object.
    assert len({id(leaf[shape_envelope.KEY_BREP]) for leaf in leaves}) == 2


def test_the_parts_of_an_answer_encoded_one_by_one_are_one_attachment():
    """The parts of a STEP assembly are encoded a node at a time, into equal bytes."""
    answer = {
        "shape": {"name": "x", ocp_serialize.KEY_ASSEMBLY: [_leaf(bytes(bytearray(BRICK)), str(i)) for i in range(5)]}
    }

    frame = ocp_serialize.serialize(answer)

    assert _attachments(frame) == [len(BRICK)]


def test_a_tessellation_table_travels_as_attachments():
    """The glTF of a tree, keyed by geometry: bytes like any other, so raw like any other.

    Read back by the core through 'decode()' of the table on the tree's root,
    which turns its '__bytes__' objects into bytes, base64 or attached.
    """
    glb = b"glTF" + os.urandom(64)
    answer = {
        "success": True,
        "tree": {"name": "x", "label": "x", shape_envelope.KEY_GEOMETRY: {"d1": glb}, shape_envelope.KEY_ASSEMBLY: []},
    }

    frame = ocp_serialize.serialize(answer)

    assert len(glb) in _attachments(frame)
    assert base64.b64encode(glb) not in frame
    table = shape_envelope.loads(frame)["tree"][shape_envelope.KEY_GEOMETRY]
    assert shape_envelope.decode(table) == {"d1": glb}


def test_an_answer_is_found_past_what_was_printed_in_front_of_it():
    """What printed before the wrapper took its channel away (see 'wrapper_common.protect_response_channel')."""
    frame = ocp_serialize.serialize({"success": True, "shape": _leaf(BRICK, "brick")})
    noise = b"Content-Length: 12 is what a library printed\nprogress 50%\r\n\r\n"

    for data in (noise + frame, frame + b"\nlate noise\n", b"\xff\xfe binary noise\n" + frame):
        assert shape_envelope.deserialize(data)["shape"][shape_envelope.KEY_BREP] == BRICK


def test_of_several_frames_the_last_is_the_answer():
    first = ocp_serialize.serialize({"n": 1})
    second = ocp_serialize.serialize({"n": 2, "blob": b"\x00"})

    assert shape_envelope.deserialize(first + second) == {"n": 2, "blob": b"\x00"}


def test_an_answer_in_json_is_still_read():
    """A wrapper asked in JSON - in a container - answers in JSON, table and progress lines included."""
    tree = ocp_serialize.deserialize_raw(shape_envelope.serialize({"wrapped": _castle()}))["wrapped"]
    line = ocp_serialize.dumps({"success": True, "tree": tree}, share=True)
    assert ocp_serialize.KEY_BREPS in line

    for data in (line, line.encode(), "progress\n" + line + "\n", ("progress\n" + line).encode()):
        read = shape_envelope.deserialize(data)
        assert [leaf[shape_envelope.KEY_BREP] for leaf in _leaves(read["tree"])] == [
            leaf[ocp_serialize.KEY_BREP] for leaf in _leaves(tree)
        ]


@pytest.mark.parametrize("form", ["frame", "json"])
def test_an_error_answer_is_read_in_either_form(form):
    answer = {"success": False, "exception": "the script raised"}
    data = ocp_serialize.serialize(answer) if form == "frame" else ocp_serialize.dumps(answer)

    assert shape_envelope.deserialize(data) == answer


def test_a_frame_cut_off_says_so():
    frame = ocp_serialize.serialize({"shape": _leaf(BRICK, "brick")})

    with pytest.raises(ValueError, match="did not arrive whole"):
        shape_envelope.deserialize(frame[:-100])


def test_no_answer_at_all_says_so():
    with pytest.raises(ValueError, match="no output"):
        shape_envelope.deserialize(b"")


# --------------------------------------------------------------------------- #
# What carries it                                                             #
# --------------------------------------------------------------------------- #


def test_a_frame_comes_off_a_process_as_bytes_and_anything_else_as_text():
    frame = ocp_serialize.serialize({"blob": b"\xff\x00"})

    assert process_output.answer(frame) == frame
    assert process_output.answer(b"progress\n" + frame) == b"progress\n" + frame
    assert process_output.answer(b'{"success": true}') == '{"success": true}'
    # Text that mentions the header is text, and so is a frame that did not arrive whole.
    assert process_output.answer(b"Content-Length: 5\r\n\r\nab") == "Content-Length: 5\r\n\r\nab"
    assert isinstance(process_output.answer(frame[:-1]), str)
    assert process_output.answer(b"") == ""
    assert process_output.loggable(frame) == "a framed answer of %d bytes" % len(frame)


def _ctx(tmp_path):
    return types.SimpleNamespace(user_config=types.SimpleNamespace(internal_state_dir=str(tmp_path)))


@pytest.fixture
def python_runtime(tmp_path):
    """A 'PythonRuntime' that runs this interpreter and provisions nothing."""
    from partcad import runtime_python

    made = runtime_python.PythonRuntime(_ctx(tmp_path), "test", "3.11")
    made.exec_path = sys.executable
    made.provisioned = True
    return made


# A wrapper as PartCAD's own are written: what it was asked, handed back.
ECHO = textwrap.dedent("""
    import sys

    sys.path.insert(0, sys.argv[3])
    import wrapper_common

    path, request = wrapper_common.handle_input(decode=False)
    print("progress, which is not the answer")
    wrapper_common.handle_output({"success": True, "echo": request})
    """)


@pytest.mark.parametrize("asynchronous", [False, True], ids=["run", "run_async"])
def test_a_wrapper_answers_through_the_python_runtime_in_a_frame(python_runtime, tmp_path, asynchronous):
    """Every launch point of the Python sandbox: bytes in, bytes out, and the payloads intact."""
    script = tmp_path / "echo.py"
    script.write_text(ECHO)
    command = [str(script), str(tmp_path / "out"), str(tmp_path), WRAPPERS]
    request = {"wrapped": _castle(), "blob": b"\x00\xff"}

    if asynchronous:
        exitcode, stdout, stderr = asyncio.run(
            python_runtime.run_async_onced(command, stdin=lambda: shape_envelope.serialize(request))
        )
    else:
        exitcode, stdout, stderr = python_runtime.run_onced(command, stdin=shape_envelope.serialize(request))

    assert exitcode == 0, stderr
    assert isinstance(stdout, bytes)
    echo = shape_envelope.deserialize(stdout)["echo"]
    assert echo["blob"] == b"\x00\xff"
    assert [leaf[shape_envelope.KEY_BREP] for leaf in _leaves(echo["wrapped"])] == [
        leaf[shape_envelope.KEY_BREP] for leaf in _leaves(request["wrapped"])
    ]


def test_a_wrapper_asked_in_json_answers_text_through_the_python_runtime(python_runtime, tmp_path):
    script = tmp_path / "echo.py"
    script.write_text(ECHO)
    command = [str(script), str(tmp_path / "out"), str(tmp_path), WRAPPERS]

    exitcode, stdout, stderr = python_runtime.run_onced(command, stdin=shape_envelope.dumps({"width": 3}))

    assert exitcode == 0, stderr
    assert isinstance(stdout, str)
    assert shape_envelope.deserialize(stdout)["echo"] == {"width": 3}


def test_a_framed_answer_from_a_service_stays_bytes(tmp_path):
    """The JSON dialect of a container service carries standard output as base64 (see '_rpc_result')."""
    frame = ocp_serialize.serialize({"success": True, "blob": b"\xff"})
    made = runtime.Runtime(_ctx(tmp_path), "service")

    stdout, stderr, returncode = made._rpc_result(
        {"result": {"stdout": base64.b64encode(frame).decode(), "stderr": "", "exit_code": 0}}, []
    )

    assert returncode == 0 and stderr == ""
    assert stdout == frame
    assert shape_envelope.deserialize(stdout) == {"success": True, "blob": b"\xff"}


def test_a_framed_answer_is_remembered_as_the_line_it_says(monkeypatch):
    """A cached wrapper answer is a line of JSON, which a frame's bytes cannot be (see 'cache_artifacts')."""
    stored = {}

    async def store_async(cache, hash, result, files=None, directory=None):
        stored.update(result)
        return True

    monkeypatch.setattr(cache_artifacts, "store_async", store_async)
    answer = {"success": True, "tree": _leaf(BRICK, "brick"), "glb": b"glTF"}
    frame = ocp_serialize.serialize(answer)

    assert asyncio.run(cache_artifacts.store_response_async(None, None, frame))

    line = stored["response"]
    assert isinstance(line, str) and "\n" not in line
    assert shape_envelope.deserialize(line) == shape_envelope.deserialize(frame)


def test_a_framed_answer_written_a_little_at_a_time_arrives_whole(monkeypatch):
    """'os.write' may take less than it is handed: each piece of the frame is written on from a view of itself."""
    import wrapper_common

    received = []
    handed = []

    def write(fd, data):
        handed.append(type(data))
        taken = bytes(data[:4096])
        received.append(taken)
        return len(taken)

    monkeypatch.setattr(wrapper_common, "_response_fd", 99)
    monkeypatch.setattr(wrapper_common, "_answer_framed", True)
    monkeypatch.setattr(wrapper_common, "os", types.SimpleNamespace(write=write))
    answer = {"success": True, "shape": _leaf(os.urandom(1 << 20), "big"), "blob": b"\x00" * 5000}

    wrapper_common.handle_output(answer)

    assert len(received) > 250
    assert set(handed) == {memoryview}
    assert shape_envelope.deserialize(b"".join(received)) == answer
