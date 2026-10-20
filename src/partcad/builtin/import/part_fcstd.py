#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The 'fcstd' partType: a FreeCAD document's solids, as one part.

FreeCAD is not needed. cadmpeg decodes the '.FCStd' archive, and what it says
about the document decides what the part is:

  * **Which shapes.** A FreeCAD document keeps a shape for every feature it has
    ever computed -- the Pad, the Pocket cut into it and the Fillet on top, each
    a solid of its own -- and the part is the last of those, not all three
    stacked. So the shapes read are those of the features nothing else in the
    document consumes, that are not hidden or suppressed: what the 3D view shows.
    Only their solids are kept, which leaves out sketches and datums.
  * **The geometry itself** is read from the archive as FreeCAD wrote it, in
    OpenCASCADE's own format, so nothing is translated on the way.

What that cannot read -- a document saved with binary shapes, or one whose
result is nowhere in the archive -- is converted by cadmpeg to STEP instead, and
read the way every STEP file is (see 'wrappers/step_repair.py' for what cadmpeg
writes that OpenCASCADE would otherwise crash on). That STEP holds every shape
the document stored, so it is the second choice and not the first.

The document's history (sketches, constraints, the parametric features) does
not survive either way: what PartCAD gets is the geometry FreeCAD last
computed. Objects placed through App::Link are not followed by the first route.

Run by 'wrappers/wrapper_part_type.py' with 'request["path"]' set to the
'.FCStd' file and 'request["cache_dir"]' to where cadmpeg is kept.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile

# Siblings are imported by bare name, and the sandbox sets PYTHONSAFEPATH.
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Raise with any change to what this produces (see 'partcad.code_version').
CACHE_VERSION = 1

# A feature's 'Shape' output in cadmpeg's model names the archive entry holding
# it: 'fcstd:model:body#Fillet:Shape:Fillet.Shape.brp:47'.
SHAPE_ENTRY = re.compile(r"#[^:]*:Shape:(?P<entry>[^:]+\.brp)(?::|$)")


def run(command):
    """Run cadmpeg, raising with what it said when it fails."""
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        raise RuntimeError("%s failed: %s" % (" ".join(command[:2]), detail[-1] if detail else result.returncode))


def result_entries(model):
    """The archive entries holding the shapes the document shows, in its order."""
    features = model.get("features") or []
    consumed = {dependency for feature in features for dependency in feature.get("dependencies") or []}
    entries = []
    for feature in sorted(features, key=lambda feature: feature.get("ordinal") or 0):
        if feature.get("id") in consumed or feature.get("suppressed"):
            continue
        if (feature.get("source_properties") or {}).get("Visibility") == "false":
            continue
        for output in feature.get("outputs") or []:
            match = SHAPE_ENTRY.search(output)
            if match:
                entries.append(match.group("entry"))
    return entries


def solids(shape):
    """The solids in 'shape'."""
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    found = []
    explorer = TopExp_Explorer(shape, TopAbs_SOLID)
    while explorer.More():
        found.append(explorer.Current())
        explorer.Next()
    return found


def read_brep(path):
    from OCP.BRep import BRep_Builder
    from OCP.BRepTools import BRepTools
    from OCP.TopoDS import TopoDS_Shape

    shape = TopoDS_Shape()
    if not BRepTools.Read_s(shape, path, BRep_Builder()) or shape.IsNull():
        raise RuntimeError("unreadable shape")
    return shape


def from_archive(source, cadmpeg, tmp):
    """The solids of the shapes the document shows, read from the archive."""
    dump = os.path.join(tmp, "document.cadir.json")
    run([cadmpeg, "dump", source, "-o", dump])
    with open(dump, encoding="utf-8") as f:
        model = json.load(f).get("model") or {}
    entries = result_entries(model)
    if not entries:
        return []

    found = []
    with zipfile.ZipFile(source) as archive:
        for entry in entries:
            path = os.path.join(tmp, "entry.brp")
            with open(path, "wb") as f:
                f.write(archive.read(entry))
            found.extend(solids(read_brep(path)))
    return found


def from_step(source, cadmpeg, tmp):
    """The solids of everything cadmpeg converts the document to."""
    import step_repair
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_Reader

    step = os.path.join(tmp, "document.step")
    run([cadmpeg, "convert", source, "-o", step])
    reader = STEPControl_Reader()
    with step_repair.readable(step) as readable_path:
        read = reader.ReadFile(readable_path)
    if read != IFSelect_RetDone or reader.TransferRoots() == 0:
        raise RuntimeError("cadmpeg converted %s to STEP, but OpenCASCADE could not read it" % os.path.basename(source))
    return solids(reader.OneShape())


def convert(source, cache_dir):
    """Read 'source', a '.FCStd' file, into one OCCT shape."""
    import cadmpeg_tool
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    cadmpeg = cadmpeg_tool.executable(cache_dir)
    with tempfile.TemporaryDirectory(prefix="partcad-fcstd-") as tmp:
        try:
            found = from_archive(source, cadmpeg, tmp)
        except Exception:
            found = []
        if not found:
            found = from_step(source, cadmpeg, tmp)
    if not found:
        raise RuntimeError("%s holds no solid" % os.path.basename(source))
    if len(found) == 1:
        return found[0]
    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    for solid in found:
        builder.Add(compound, solid)
    return compound


if __name__ == "__partcad_part__":
    try:
        output = {"shape": convert(request["path"], request["cache_dir"])}  # noqa: F821
    except Exception as e:
        output = {"exception": str(e)}
