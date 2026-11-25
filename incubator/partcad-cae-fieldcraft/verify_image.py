#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Check that a fieldcraft-cli answers, over MCP, a cantilever whose answer is known.

    python3 verify_image.py [path/to/fieldcraft-cli]

Run by the Dockerfile on the image it builds, and by CI on the release this
package pins. Standard library only, and no mesher: the beam is FieldCraft's own
`mesh.block`, exactly its oracle `tests/oracle/cantilever-tet10` -- 10 x 1 x 1,
E = 1000, a unit tip load, in its default units -- whose tip deflection is PL^3/3EI = 4.0, and 4.024 with shear
and the mesh, which is what FieldCraft's own suite holds it to.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

SCRIPT = [
    {
        "command": "mesh.block",
        "params": {
            "body": "Beam",
            "kind": "tet10",
            "corners": [[0, 0, 0], [10, 0, 0], [10, 1, 0], [0, 1, 0], [0, 0, 1], [10, 0, 1], [10, 1, 1], [0, 1, 1]],
            "divisions": [20, 2, 2],
            "faces": {"6": "root", "4": "tip"},
        },
    },
    {"command": "model.set.create", "params": {"name": "all", "geometry": [{"body": "Beam"}]}},
    {"command": "model.set.create", "params": {"name": "root", "geometry": [{"body": "Beam", "face": "root"}]}},
    {"command": "model.set.create", "params": {"name": "tip", "geometry": [{"body": "Beam", "face": "tip"}]}},
    {
        "command": "model.material.create",
        "params": {"name": "Mat", "elastic": {"type": "isotropic", "young": 1000.0, "poisson": 0.0}},
    },
    {
        "command": "model.section.create",
        "params": {"name": "beam", "set": "all", "material": "Mat", "kind": {"type": "solid"}},
    },
    {
        "command": "model.boundary_condition.create",
        "params": {"name": "clamp", "type": "fixed", "target": {"set": "root"}},
    },
    {
        "command": "model.load.create",
        "params": {"name": "P", "type": "force", "target": {"set": "tip"}, "vector": [0, 0, -1]},
    },
    {
        "command": "model.step.create",
        "params": {"name": "Bend", "procedure": {"type": "static"}, "boundary_conditions": ["clamp"], "loads": ["P"]},
    },
    {"command": "solve.static", "params": {"step": "Bend"}},
    {"command": "solve.probe", "params": {"step": "Bend", "at": [[10.0, 0.5, 0.5]]}},
]


def main():
    cli = sys.argv[1] if len(sys.argv) > 1 else shutil.which("fieldcraft-cli")
    if not cli:
        sys.exit("verify_image: no fieldcraft-cli")
    with tempfile.TemporaryDirectory() as work:
        messages = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "batch", "arguments": {"commands": SCRIPT}},
            },
        ]
        done = subprocess.run(
            [cli, "mcp", "--headless", "--automation-read-root", work, "--automation-write-root", work],
            input="".join(json.dumps(m) + "\n" for m in messages),
            capture_output=True,
            text=True,
            timeout=600,
            env=dict(os.environ, FIELDCRAFT_GPU="cpu"),
        )
    replies = {}
    for line in done.stdout.splitlines():
        message = json.loads(line)
        replies[message.get("id")] = message
    result = (replies.get(2) or {}).get("result") or {}
    text = "".join(block.get("text", "") for block in result.get("content") or [])
    if result.get("isError") or not text:
        sys.exit("verify_image: the batch failed: %s\n%s" % (text or replies.get(2), done.stderr[-2000:]))
    answer = json.loads(text)
    deflection = answer["results"][-1]["nodes"][0]["displacement"][2]
    reaction = answer["results"][-2]["reaction_total"][2]
    if abs(deflection - -4.024) > 0.005 * 4.024 or abs(reaction - 1.0) > 1e-6:
        sys.exit("verify_image: tip deflection %r (expected -4.024), reaction %r (expected 1)" % (deflection, reaction))
    print("fieldcraft-cli answers: tip deflection %.4f, reaction %.6f" % (deflection, reaction))


if __name__ == "__main__":
    main()
