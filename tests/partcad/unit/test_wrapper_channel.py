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

import os
import subprocess
import sys
import textwrap

from partcad import wrapper as pc_wrapper

# Asked the way the core asks: 'partcad.wrappers' is a namespace package and has
# no '__file__', and in a frozen bundle the directory is not beside the source.
WRAPPERS = os.path.dirname(pc_wrapper.get("export.py"))

# argv[1] is the output path and argv[2] the working directory, which is what
# every wrapper is invoked with; argv[3] is this test telling it where the
# wrappers are, since it is not being run out of a sandbox.
SCRIPT = textwrap.dedent(
    """
    import os
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

    wrapper_common.handle_output({"success": True, "echo": request.get("echo")})
    """
)


def _run(tmp_path):
    """Run the script above as a wrapper would be run, and return what it said."""
    sys.path.insert(0, WRAPPERS)
    try:
        import ocp_serialize
    finally:
        sys.path.remove(WRAPPERS)

    script = tmp_path / "wrapper.py"
    script.write_text(SCRIPT)
    finished = subprocess.run(
        [sys.executable, str(script), str(tmp_path / "out.bin"), str(tmp_path), WRAPPERS],
        input=ocp_serialize.serialize({"echo": "hello"}),
        capture_output=True,
        text=True,
    )
    assert finished.returncode == 0, finished.stderr
    return ocp_serialize, finished


def test_the_response_survives_everything_else_that_prints(tmp_path):
    """The answer parses, and says what the wrapper meant it to say."""
    ocp_serialize, finished = _run(tmp_path)

    response = ocp_serialize.deserialize(finished.stdout)
    assert response["success"] is True
    assert response["echo"] == "hello"


def test_what_printed_is_not_lost_but_moved(tmp_path):
    """Both kinds of noise still reach the log, which is where they are useful.

    Silencing them would be the other way to protect the channel and is the
    wrong one: "the mesher said nothing" is how a diagnosable failure becomes an
    undiagnosable one.
    """
    _ocp_serialize, finished = _run(tmp_path)

    assert "a script talking to itself" in finished.stderr
    assert "OCCT: Transferring Shape" in finished.stderr
    assert "OCCT: writing... " in finished.stderr
    # And none of it is on the channel.
    assert "talking to itself" not in finished.stdout
    assert "OCCT" not in finished.stdout
