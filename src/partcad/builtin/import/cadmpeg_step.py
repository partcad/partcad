#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A native CAD file as the STEP file cadmpeg converts it to, and the bodies that file shows.

The readers here that go through cadmpeg -- the part types and the assembly
types of '//builtin/import' -- all start the same way: cadmpeg decodes the
native file and writes STEP, and OpenCASCADE reads that. What is in this module
is that much and no more, so that there is one way of doing it:

  * 'to_step' runs the cadmpeg 'cadmpeg_tool' finds or fetches;
  * 'read' reads the STEP file as it *shows*: what it declares invisible is left
    out ('step_visible') -- cadmpeg keeps a body its author hid and marks it so --
    and what OpenCASCADE would crash on is repaired first ('step_repair');
  * 'bodies' is what of that a part can be made of: the solids, and the shells
    and faces that belong to none. Sketch curves and points, which every native
    format keeps beside its bodies, are not.

What is deliberately *not* here is any judgement of the result. A body cadmpeg
read wrongly -- an open shell where a face could not be decoded, an invalid
solid -- is handed over as it is, and the part types declare 'requireSolid', so
that PartCAD holds it to the definition every part is held to
('wrapper_common.solid_problems') and fails it there.

Runs inside the sandbox, beside the scripts that import it by bare name.
"""

import os
import subprocess
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))


def run(command):
    """Run cadmpeg, raising with what it said when it fails."""
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        raise RuntimeError("%s failed: %s" % (" ".join(command[:2]), detail[-1] if detail else result.returncode))


def executable(cache_dir):
    """The cadmpeg to run, fetched into 'cache_dir' if need be."""
    import cadmpeg_tool

    return cadmpeg_tool.executable(cache_dir)


def to_step(source, cache_dir, directory, cadmpeg=None):
    """Convert 'source' to a STEP file in 'directory' and return its path."""
    step = os.path.join(directory, os.path.splitext(os.path.basename(source))[0] + ".step")
    run([cadmpeg or executable(cache_dir), "convert", source, "-o", step])
    return step


def read(step):
    """The shape of everything the STEP file at 'step' shows, as one shape."""
    import step_repair
    import step_visible
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_Reader

    reader = STEPControl_Reader()
    with step_visible.shown(step) as shown, step_repair.readable(shown) as readable:
        status = reader.ReadFile(readable)
    if status != IFSelect_RetDone or reader.TransferRoots() == 0:
        raise RuntimeError("OpenCASCADE could not read %s" % os.path.basename(step))
    return reader.OneShape()


def _found(shape, kind, avoid=None):
    from OCP.TopExp import TopExp_Explorer

    explorer = TopExp_Explorer(shape, kind) if avoid is None else TopExp_Explorer(shape, kind, avoid)
    found = []
    while explorer.More():
        found.append(explorer.Current())
        explorer.Next()
    return found


def solids(shape):
    """The solids in 'shape'."""
    from OCP.TopAbs import TopAbs_SOLID

    return _found(shape, TopAbs_SOLID)


def bodies(shape):
    """What a part can be made of in 'shape': its solids, then the shells and faces outside them.

    A shell or a face that bounds nothing is kept rather than dropped, because
    it may be a solid that did not come through whole -- and a part that is
    missing a body says nothing about it, where one with an open shell in it is
    failed by name. Edges and vertices outside any face are left out: they are
    the sketches, axes and points a CAD document keeps beside its bodies.
    """
    from OCP.TopAbs import TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID

    return solids(shape) + _found(shape, TopAbs_SHELL, TopAbs_SOLID) + _found(shape, TopAbs_FACE, TopAbs_SHELL)


def has_faces(shape):
    """Whether 'shape' has any face at all, which is whether it is anything a part can be made of."""
    from OCP.TopAbs import TopAbs_FACE

    return bool(_found(shape, TopAbs_FACE))


def compound(shapes):
    """One shape of 'shapes': itself when there is one, a compound when there are more."""
    if len(shapes) == 1:
        return shapes[0]
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    builder = BRep_Builder()
    result = TopoDS_Compound()
    builder.MakeCompound(result)
    for shape in shapes:
        builder.Add(result, shape)
    return result
