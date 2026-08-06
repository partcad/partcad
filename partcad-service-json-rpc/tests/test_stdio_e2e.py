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
from partcad_service_json_rpc.transport.framing import read_message, write_message


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
