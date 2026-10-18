#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Export a PartCAD part or assembly as a SolidCraft design ('.solidcraft').

The shape is written to STEP, which SolidCraft opens as a new design holding it
as an imported component, and saves in its own container format: what comes
out opens in SolidCraft ready to be modelled on.

Run by PartCAD's export wrapper with the shape in 'request["wrapped"]', the
file to write as 'path', and 'request["cache_dir"]' to where 'solidcraft-cli'
is kept.
"""

import os
import subprocess
import sys
import tempfile

# Siblings are imported by bare name, and the sandbox sets PYTHONSAFEPATH.
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Raise with any change to what this produces (see PartCAD's 'code_version').
CACHE_VERSION = 1


def write_step(shape, path):
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.Message import Message
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

    # The writer reports every transfer through OpenCASCADE's messenger, which
    # prints to the console: on stderr here, where it reads as a complaint.
    messenger = Message.DefaultMessenger_s()
    for printer in list(messenger.Printers()):
        messenger.RemovePrinter(printer)

    writer = STEPControl_Writer()
    writer.Transfer(shape, STEPControl_AsIs)
    if writer.Write(path) != IFSelect_RetDone:
        raise RuntimeError("Failed to write the shape as STEP")


def process(path, request):
    try:
        import solidcraft_tool

        shape = request.get("wrapped")
        if shape is None:
            raise ValueError("No shape to export")
        cli = solidcraft_tool.executable(request.get("cache_dir"))

        path = os.path.abspath(path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="partcad-solidcraft-") as tmp:
            step = os.path.join(tmp, "%s.step" % (request.get("shape_name") or "part").replace("/", "_"))
            write_step(shape, step)
            result = subprocess.run(
                [cli, "run", step, "--save", path, "--quiet"], capture_output=True, text=True, check=False
            )
        if result.returncode != 0 or not os.path.isfile(path):
            detail = (result.stderr or result.stdout or "").strip().splitlines()
            raise RuntimeError("SolidCraft failed: %s" % (detail[-1] if detail else "exit %d" % result.returncode))
        return {"success": True, "exception": None}
    except Exception as e:
        return {"success": False, "exception": str(e)}
