#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The sandbox's answer, and everything else that wants the same descriptor.

A wrapper answers PartCAD on its standard output, so anything else printing
there corrupts the answer. That is not hypothetical: OCCT's STEP writer prints a
transfer summary on every `Write()`, gmsh prints unless told twice not to, and
`custom_cqgi.py` prints its own diagnostics -- and a native library writes to
file descriptor 1 directly, where neither `contextlib.redirect_stdout` nor
reassigning `sys.stdout` can reach it.

So `wrapper_common` takes the descriptor away and keeps the real one for
`handle_output()`. These run a wrapper as a real subprocess, because that is the
only way to have something write to descriptor 1 the way a shared library does.
"""

import json
import os
import subprocess
import sys
import textwrap
import types

import pytest

from partcad import wrapper as pc_wrapper

# Asked the way the core asks: 'partcad.wrappers' is a namespace package and has
# no '__file__', and in a frozen bundle the directory is not beside the source.
WRAPPERS = os.path.dirname(pc_wrapper.get("export.py"))

# argv[1] is the output path and argv[2] the working directory, which is what
# every wrapper is invoked with; argv[3] is this test telling it where the
# wrappers are, since it is not being run out of a sandbox.
SCRIPT = textwrap.dedent("""
    import os
    import subprocess
    import sys

    sys.path.insert(0, sys.argv[3])
    import wrapper_common

    path, request = wrapper_common.handle_input()

    # What a script of its own prints...
    print("a script talking to itself")
    # ...and what a native library prints, which goes to the descriptor and
    # never through 'sys.stdout' at all. The second has no newline on the end,
    # which is what a progress line looks like and what the "last line wins"
    # rule in 'ocp_serialize._payload_line()' cannot survive: without the
    # channel being moved, that fragment and the response become one line.
    os.write(1, b"OCCT: Transferring Shape, ShapeType = 2\\n")
    os.write(1, b"OCCT: writing... ")
    # ...and a process it starts, which inherits descriptor 1 and nothing else.
    subprocess.run([sys.executable, "-c", "print('a child talking')"], check=True)

    wrapper_common.handle_output({"success": True, "echo": request.get("echo"), "blob": b"\\x00\\xff\\n"})
    """)


def _ocp_serialize():
    sys.path.insert(0, WRAPPERS)
    try:
        import ocp_serialize
    finally:
        sys.path.remove(WRAPPERS)
    return ocp_serialize


def _run(tmp_path, framed=True):
    """Run the script above as a wrapper would be run, asked in a frame or in JSON, and return what it said."""
    ocp_serialize = _ocp_serialize()
    script = tmp_path / "wrapper.py"
    script.write_text(SCRIPT)
    request = {"echo": "hello"}
    finished = subprocess.run(
        [sys.executable, str(script), str(tmp_path / "out.bin"), str(tmp_path), WRAPPERS],
        input=ocp_serialize.serialize(request) if framed else ocp_serialize.dumps(request).encode("utf-8"),
        capture_output=True,
    )
    assert finished.returncode == 0, finished.stderr
    return ocp_serialize, finished


@pytest.mark.parametrize("framed", [True, False], ids=["frame", "json"])
def test_the_response_survives_everything_else_that_prints(tmp_path, framed):
    """The answer parses, and says what the wrapper meant it to say."""
    ocp_serialize, finished = _run(tmp_path, framed)

    response = ocp_serialize.deserialize(finished.stdout)
    assert response["success"] is True
    assert response["echo"] == "hello"
    assert response["blob"] == b"\x00\xff\n"


def test_a_frame_is_answered_with_a_frame_and_nothing_else(tmp_path):
    """The whole of standard output is the one frame: nothing is in front of it or after it.

    Which is what lets the core read it without looking for it, and what keeps
    its bytes raw: there is no text on the channel to be decoded as text.
    """
    ocp_serialize, finished = _run(tmp_path, framed=True)

    from partcad_utils import framing

    assert framing.find_message(finished.stdout) == 0
    message, end = framing.message_at(finished.stdout, 0)
    assert end == len(finished.stdout)
    assert message["blob"] == b"\x00\xff\n"


def test_json_is_answered_with_json(tmp_path):
    """What a wrapper in a container is sent, and what its caller reads back as text."""
    _ocp_serialize_module, finished = _run(tmp_path, framed=False)

    assert finished.stdout.startswith(b"{")
    assert json.loads(finished.stdout)["echo"] == "hello"


@pytest.mark.parametrize("framed", [True, False], ids=["frame", "json"])
def test_what_printed_is_not_lost_but_moved(tmp_path, framed):
    """Both kinds of noise still reach the log, which is where they are useful.

    Silencing them would be the other way to protect the channel and is the
    wrong one: "the mesher said nothing" is how a diagnosable failure becomes an
    undiagnosable one.
    """
    _ocp_serialize_module, finished = _run(tmp_path, framed)

    assert b"a script talking to itself" in finished.stderr
    assert b"OCCT: Transferring Shape" in finished.stderr
    assert b"OCCT: writing... " in finished.stderr
    assert b"a child talking" in finished.stderr
    # And none of it is on the channel.
    assert b"talking" not in finished.stdout
    assert b"OCCT" not in finished.stdout


def test_an_answer_written_a_little_at_a_time_arrives_whole(monkeypatch):
    """'os.write' may take less than it is handed; the rest is written from a view.

    In this process, with a descriptor that takes a few kilobytes per call, so
    that a multi-megabyte answer is written in hundreds of pieces -- each from
    a view of the one buffer rather than a copy of what is left of it.
    """
    monkeypatch.syspath_prepend(WRAPPERS)
    import ocp_serialize
    import wrapper_common

    received = []
    handed = []

    def write(fd, data):
        handed.append(type(data))
        taken = bytes(data[:4096])
        received.append(taken)
        return len(taken)

    monkeypatch.setattr(wrapper_common, "_response_fd", 99)
    monkeypatch.setattr(wrapper_common, "os", types.SimpleNamespace(write=write))
    answer = {"success": True, "blob": "x" * (2 * 1024 * 1024)}

    wrapper_common.handle_output(answer)

    assert len(received) > 500
    assert set(handed) == {memoryview}
    assert ocp_serialize.deserialize(b"".join(received).decode("utf-8")) == answer
