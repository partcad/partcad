#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The partTypes this package declares: a file SolidCraft reads, as a part.

One script for all three, because SolidCraft treats them alike: it opens the
file -- a SolidCraft design, a Rhino '.3dm' or an IGES file -- and writes the
solids in it to STEP, which OCP reads back here.

A SolidCraft design is parametric, and so is a PartCAD part: every parameter
the part declares is set on the design before it is rebuilt, so
'plate;height=35' is the plate with its 'height' parameter at 35. The other two
formats carry no parameters of SolidCraft's and are read as they are.

Run by PartCAD's partType wrapper with 'request["path"]' set to the file and
'request["cache_dir"]' to where 'solidcraft-cli' is kept.
"""

import json
import os
import subprocess
import sys
import tempfile

# Siblings are imported by bare name, and the sandbox sets PYTHONSAFEPATH.
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Raise with any change to what this produces (see PartCAD's 'code_version').
CACHE_VERSION = 1

# The extensions SolidCraft opens as one of its own designs.
DESIGN_EXTENSIONS = (".solidcraft", ".json")


def run(command):
    """Run 'solidcraft-cli', raising with what it said when it fails."""
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        raise RuntimeError("SolidCraft failed: %s" % (detail[-1] if detail else "exit %d" % result.returncode))


def parameter_script(parameters):
    """The SolidCraft commands that set each of a part's parameters on the design."""
    commands = []
    for name, value in sorted(parameters.items()):
        if value is None or isinstance(value, bool):
            continue  # SolidCraft parameters are numbers and expressions
        commands.append({"command": "parameters.change", "params": {"name": name, "expression": str(value)}})
    return commands


def read_step(path):
    """The shape a STEP file holds, as one OCCT shape."""
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_Reader

    reader = STEPControl_Reader()
    if reader.ReadFile(path) != IFSelect_RetDone or reader.TransferRoots() == 0:
        raise RuntimeError("SolidCraft wrote a STEP file OCP cannot read")
    shape = reader.OneShape()
    if shape is None or shape.IsNull():
        raise RuntimeError("SolidCraft found no solid to write")
    return shape


def convert(source, parameters, cache_dir):
    """Read 'source' into an OCCT shape, with 'parameters' set if it is a design."""
    import solidcraft_tool

    cli = solidcraft_tool.executable(cache_dir)
    with tempfile.TemporaryDirectory(prefix="partcad-solidcraft-") as tmp:
        step = os.path.join(tmp, "part.step")
        commands = parameter_script(parameters) if source.lower().endswith(DESIGN_EXTENSIONS) else []
        if commands:
            script = os.path.join(tmp, "parameters.json")
            with open(script, "w", encoding="utf-8") as f:
                json.dump(commands, f)
            run([cli, "run", script, "--in", source, "--out", step, "--quiet"])
        else:
            run([cli, "run", source, "--out", step, "--quiet"])
        return read_step(step)


if __name__ == "__partcad_part__":
    try:
        output = {
            "shape": convert(
                request["path"],  # noqa: F821 - injected by the partType wrapper
                request.get("parameters") or {},  # noqa: F821
                request.get("cache_dir"),  # noqa: F821
            )
        }
    except Exception as e:
        output = {"exception": str(e)}
