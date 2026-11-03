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
    and what OpenCASCADE would crash on is repaired first ('step_repair'). It
    reads through OpenCASCADE's XCAF reader, as a STEP part's file is read
    ('wrapper_step'), so what the file states of its colours and materials
    comes with the geometry, and 'stated_cmf' says it of the part;
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


# How long one cadmpeg run may take before it is given up on. Generous on
# purpose: a conversion takes seconds for a part and can take minutes for a
# large assembly, and an assembly may declare a 'timeout:' longer than the
# client's default five minutes. What it is for is a converter that never
# returns on a file it cannot read, which would otherwise hold the sandbox's
# interpreter -- and the request waiting on it -- forever.
RUN_TIMEOUT_SECONDS = 1800


def run(command):
    """Run cadmpeg, raising with what it said when it fails or does not finish.

    What it says is read as the UTF-8 it writes, not in the locale's encoding:
    on Windows that is cp1252, which cannot decode the units in its reports
    (millimetres to the fifth, with a superscript), and a failed run would lose
    the message that says why.
    """
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=RUN_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("%s did not finish in %d seconds" % (" ".join(command[:2]), RUN_TIMEOUT_SECONDS)) from None
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
    """'(shape, facts)' of everything the STEP file at 'step' shows.

    'shape' is the whole of it, as one shape; 'facts' is what the file states
    of its colours and materials ('step_cmf.Facts'), for 'stated_cmf' to say of
    the part made of it. The XCAF reader transfers the very shapes the plain
    one does ('step_cmf'), so the geometry is the same either way: a file it
    refuses is read by the plain reader, for its geometry alone, with no facts.
    """
    import step_repair
    import step_visible

    with step_visible.shown(step) as shown, step_repair.readable(shown) as readable:
        try:
            return _read_with_facts(readable)
        except Exception as e:  # pylint: disable=broad-except
            sys.stderr.write("Reading the colours and materials of %s failed: %s\n" % (os.path.basename(step), e))
        return _read_plain(readable, step), None


def _read_with_facts(path):
    import ocp_serialize
    import step_cmf

    document, reader = step_cmf.open_document(path)
    inner = reader.ChangeReader()
    shape = ocp_serialize.compound_of([inner.Shape(index + 1) for index in range(inner.NbShapes())])
    return shape, step_cmf.Facts(document)


def _read_plain(path, step):
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_Reader

    reader = STEPControl_Reader()
    if reader.ReadFile(path) != IFSelect_RetDone or reader.TransferRoots() == 0:
        raise RuntimeError("OpenCASCADE could not read %s" % os.path.basename(step))
    return reader.OneShape()


def stated_cmf(shape, facts):
    """What 'facts' say 'shape' is in, as a part type's 'output["cmf"]' ('wrapper_part_type'), or None.

    'shape' is made of the file's own bodies, compounded anew ('bodies',
    'compound'): each of its faces and solids is one of the file's, where the
    file has it, so what the file states of it is found exactly, and listed in
    the order 'shape' has them. In STEP's own terms, which the package's
    'cmfConvention' converts, as it does a STEP part's.
    """
    if not facts:
        return None
    import cmf_section
    import step_cmf

    section = step_cmf.section_of(shape, facts)
    if section is None or section.is_empty():
        return None

    def plain(index):
        if index == cmf_section.NONE:
            return None
        found = section.sets[index]
        entry = {key: getattr(found, key) for key in cmf_section.COMPONENTS if getattr(found, key) is not None}
        if found.rgba is not None:
            entry["rgba"] = list(found.rgba)
        return entry or None

    stated = {"convention": "step"}
    if section.faces:
        stated["faces"] = [plain(index) for index in section.faces]
    if section.solids:
        stated["solids"] = [plain(index) for index in section.solids]
    return stated if len(stated) > 1 else None


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
