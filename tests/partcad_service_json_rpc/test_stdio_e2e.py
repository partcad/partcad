#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""End-to-end smoke test of the executable served over real stdio pipes."""

import io
import os
import subprocess
import sys

import partcad_service_json_rpc
from partcad_utils.framing import read_message, write_message


def test_module_serves_rpc_discover_over_stdio():
    src_root = os.path.dirname(os.path.dirname(partcad_service_json_rpc.__file__))
    env = dict(os.environ, PYTHONPATH=src_root + os.pathsep + os.environ.get("PYTHONPATH", ""))

    request = io.BytesIO()
    write_message(request, {"jsonrpc": "2.0", "id": 1, "method": "rpc.discover", "params": {}})

    proc = subprocess.Popen(
        [sys.executable, "-m", "partcad_service_json_rpc", "--stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        env=env,
    )
    out, _ = proc.communicate(request.getvalue(), timeout=60)

    response = read_message(io.BytesIO(out))
    assert response["id"] == 1
    names = {m["name"] for m in response["result"]["methods"]}
    assert "rpc.discover" in names
    assert "inspect.part" in names


def test_a_process_a_request_starts_does_not_read_the_requests():
    """It inherits the null device as its standard input, not the client's pipe.

    On Windows a child on that pipe waited on it for as long as the reader did,
    which hung every 'pc test' over this channel once requests were read while
    one ran; anywhere, it would take the client's requests.
    """
    src_root = os.path.dirname(os.path.dirname(partcad_service_json_rpc.__file__))
    env = dict(os.environ, PYTHONPATH=src_root + os.pathsep + os.environ.get("PYTHONPATH", ""))
    script = (
        "import subprocess, sys\n"
        "from partcad_service_json_rpc.transport import stdio\n"
        "requests = stdio._private_input()\n"
        "child = subprocess.run(\n"
        "    [sys.executable, '-c', 'import sys; sys.stdout.write(repr(sys.stdin.buffer.read()))'],\n"
        "    stdout=subprocess.PIPE, timeout=60,\n"
        ")\n"
        "sys.stdout.write(child.stdout.decode() + '|' + requests.read().decode())\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script], input=b"the client's request", stdout=subprocess.PIPE, env=env, timeout=120
    )
    assert proc.stdout.decode() == "b''|the client's request"
