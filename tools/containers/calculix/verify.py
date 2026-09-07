#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What this image claims to be, checked while it is still being built.

Every one of these is a thing the image exists to provide, and a silent absence
would surface much later as an analysis that "did not run" on a machine the
user had every reason to think was equipped. An image that cannot decode a
shape, mesh it or solve it should fail to build rather than fail in front of a
user.

The first check is the one that is not obvious. This image holds *two*
OpenCASCADE builds -- Debian's, which `python3-gmsh` links against, and the one
bundled in the OCP wheel -- and an analysis loads both into one process: OCP to
rebuild the shape PartCAD sent it, gmsh to mesh that shape. Two OpenCASCADE
libraries in one process can collide when the second one loads rather than when
it is first used, so this exercises them in the order the wrapper does, on a
shape that goes all the way through: OCCT builds a box, writes it as STEP, and
gmsh reads that file back and meshes it. `mesh_shape()` in the CalculiX package
goes through a STEP file for exactly this reason -- handing gmsh an in-memory
shape would put a shape belonging to one OCCT into the other.

Run by the Dockerfile and by nothing else. It is not part of the image.
"""

import shutil
import subprocess
import sys
import tempfile
import os


def check_ocp_and_gmsh():
    """A shape from OCP, through a STEP file, into a gmsh mesh."""
    import OCP.BRepPrimAPI
    import OCP.IFSelect
    import OCP.STEPControl

    with tempfile.TemporaryDirectory() as work:
        step = os.path.join(work, "box.step")

        box = OCP.BRepPrimAPI.BRepPrimAPI_MakeBox(10.0, 20.0, 30.0).Shape()
        writer = OCP.STEPControl.STEPControl_Writer()
        writer.Transfer(box, OCP.STEPControl.STEPControl_AsIs)
        if writer.Write(step) != OCP.IFSelect.IFSelect_RetDone:
            raise AssertionError("OCP wrote no STEP file")

        import gmsh

        gmsh.initialize()
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.model.add("verify")
            gmsh.model.occ.importShapes(step)
            gmsh.model.occ.synchronize()
            gmsh.model.mesh.generate(3)
            node_ids, _, _ = gmsh.model.mesh.getNodes()
        finally:
            gmsh.finalize()

    if len(node_ids) == 0:
        raise AssertionError("gmsh meshed the STEP file into nothing")
    return "OCP + gmsh: %d nodes" % len(node_ids)


def check_numpy_and_trimesh():
    """What the analysis computes with, and what it writes its answer as."""
    import numpy
    import trimesh

    return "numpy %s, trimesh %s" % (numpy.__version__, trimesh.__version__)


def check_ccx():
    """The solver, which is a native executable rather than a Python package."""
    ccx = shutil.which("ccx")
    if not ccx:
        raise AssertionError("no `ccx` on the PATH")
    # `ccx -v` prints the version and exits non-zero on some builds, so what is
    # checked is that it runs and says something, not what it says.
    printed = subprocess.run([ccx, "-v"], capture_output=True, text=True)
    said = (printed.stdout + printed.stderr).strip().splitlines()
    return "ccx at %s: %s" % (ccx, said[0] if said else "(silent)")


def main():
    failed = False
    for check in (check_ocp_and_gmsh, check_numpy_and_trimesh, check_ccx):
        try:
            print("ok   %s: %s" % (check.__name__, check()))
        except Exception as e:
            print("FAIL %s: %s: %s" % (check.__name__, type(e).__name__, e))
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
