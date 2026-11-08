#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The 'iges' partType: an IGES file's solids, as one part, read by OpenCASCADE.

Read through OpenCASCADE's XCAF reader, 'IGESCAFControl_Reader', the
counterpart of the writer 'pc export -t iges' uses, so what PartCAD writes it
reads back. It keeps what the plain reader discards: the colours an IGES file
puts on its entities, which come with the part the way a STEP file's do
('step_cmf' reads either kind of XCAF document), in STEP's terms. Only the
entities the file shows are read: one it blanks is construction geometry or a
body its author hid, not the part.

An IGES file states a solid in one of two ways, and both are read:

  * **as a solid** -- a manifold solid B-rep object (entity 186), which is what
    OCCT writes when 'write.iges.brep.mode' asks for it. It is read as it is.
  * **as the faces that bound it** -- trimmed surfaces with nothing to say they
    are one body, which is how OCCT writes IGES by default and how many CAD
    applications write it too. Those faces are sewn back into the shell they
    make, which the wrapper then states as the solid it bounds when it closes
    ('wrapper_common.solidify'), as it does for every part type. Faces are sewn
    only with the others of their group -- an IGES associativity, which OCCT
    writes one of per body and reads as a compound -- so that two bodies that
    touch stay two. The gap sewing closes is the widest the file's own geometry
    already admits: the tolerance OpenCASCADE gave the faces' vertices as it
    read them.

What is deliberately *not* here is any judgement of the result. Faces that do
not close -- one missing, one that came through wrong -- are handed over as the
open shell they make, and the part type declares 'requireSolid', so that
PartCAD fails the part by the definition every part is held to
('wrapper_common.solid_problems') rather than this script deciding what broken
means.

Run by 'wrappers/wrapper_part_type.py' with 'request["path"]' set to the file.
"""

import os
import sys

# Siblings are imported by bare name, and the sandbox sets PYTHONSAFEPATH.
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Raise with any change to what this produces (see 'partcad.code_version').
CACHE_VERSION = 1

# The narrowest gap sewing closes, whatever the faces' tolerances say: OCCT's
# own default for sewing, and well inside any IGES file's resolution.
MIN_SEWING_TOLERANCE = 1e-6


def _open(source):
    """'(document, reader)': the IGES file at 'source' read into an XCAF document."""
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.IGESCAFControl import IGESCAFControl_Reader
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFApp import XCAFApp_Application

    document = TDocStd_Document(TCollection_ExtendedString("XmlOcaf"))
    XCAFApp_Application.GetApplication_s().NewDocument(TCollection_ExtendedString("MDTV-XCAF"), document)
    reader = IGESCAFControl_Reader()
    reader.SetColorMode(True)
    reader.SetNameMode(True)
    reader.SetLayerMode(True)
    # The reader's own flag, which it sets 'read.iges.onlyvisible' from as it
    # picks the entities to read: setting that parameter itself does nothing.
    reader.SetReadVisible(True)
    name = os.path.basename(source)
    if reader.ReadFile(source) != IFSelect_RetDone:
        raise RuntimeError("OpenCASCADE could not read %s" % name)
    if not reader.Transfer(document):
        raise RuntimeError("OpenCASCADE could not read the geometry of %s" % name)
    return document, reader


def _children(shape):
    from OCP.TopoDS import TopoDS_Iterator

    found = []
    iterator = TopoDS_Iterator(shape)
    while iterator.More():
        found.append(iterator.Value())
        iterator.Next()
    return found


def _gather(shape, kept, groups):
    """Sort what 'shape' holds into what is kept as it is -- solids and shells -- and its loose faces, by group."""
    from OCP.TopAbs import TopAbs_COMPOUND, TopAbs_COMPSOLID, TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID

    kind = shape.ShapeType()
    if kind in (TopAbs_SOLID, TopAbs_SHELL):
        kept.append(shape)
    elif kind == TopAbs_FACE:
        groups.append([shape])
    elif kind in (TopAbs_COMPOUND, TopAbs_COMPSOLID):
        faces = []
        for child in _children(shape):
            if child.ShapeType() == TopAbs_FACE:
                faces.append(child)
            else:
                _gather(child, kept, groups)
        if faces:
            groups.append(faces)
    # Edges and vertices outside any face are curves and points: not a body.


def _sewn(faces):
    """'(shapes, sewing)': 'faces' sewn into the shells they make, and the sewing that made them."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing
    from OCP.ShapeAnalysis import ShapeAnalysis_ShapeTolerance
    from OCP.TopAbs import TopAbs_COMPOUND

    measure = ShapeAnalysis_ShapeTolerance()
    tolerance = max([MIN_SEWING_TOLERANCE] + [measure.Tolerance(face, 1) for face in faces])
    sewing = BRepBuilderAPI_Sewing(tolerance)
    for face in faces:
        sewing.Add(face)
    sewing.Perform()
    sewn = sewing.SewedShape()
    # A shell, or a face when there was one, or a compound of the several
    # shells and faces left over that sewing could join no further.
    return (_children(sewn) if sewn.ShapeType() == TopAbs_COMPOUND else [sewn]), sewing


def bodies(shape):
    """'(bodies, sewings)': what a part can be made of in 'shape', and the sewings that made some of it.

    Its solids and shells as they are, and its loose faces sewn group by group.
    Whatever does not close is kept rather than dropped, because it is a solid
    that did not come through whole, and a part missing a body says nothing
    about it, where one with an open shell in it is failed by name.
    """
    found, groups = [], []
    _gather(shape, found, groups)
    sewings = []
    for faces in groups:
        sewn, sewing = _sewn(faces)
        found.extend(sewn)
        sewings.append(sewing)
    return found, sewings


def _stated(part, raw, section, sewings):
    """What 'section' (of 'raw', the shape as read) says of 'part', made of it, as a part type's 'output["cmf"]'."""
    from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape

    import cmf_section

    if section is None or section.is_empty():
        return None

    def mapped(of, kind):
        found = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(of, kind, found)
        return found

    def at(indices, index):
        return indices[index - 1] if 0 < index <= len(indices) else cmf_section.NONE

    raw_faces, raw_solids = mapped(raw, TopAbs_FACE), mapped(raw, TopAbs_SOLID)
    faces, solids = mapped(part, TopAbs_FACE), mapped(part, TopAbs_SOLID)
    # Each face of the part is a face of the file, or what sewing made of one.
    face_sets = [cmf_section.NONE] * faces.Extent()
    for index in range(1, raw_faces.Extent() + 1):
        face = raw_faces.FindKey(index)
        for sewing in sewings:
            if sewing.IsModified(face):
                face = sewing.Modified(face)
                break
        found = faces.FindIndex(face)
        if found > 0:
            face_sets[found - 1] = at(section.faces, index)
    # Each solid is one the file states, as it is: what sewing makes is a
    # shell, which its faces say what it is in.
    solid_sets = [cmf_section.NONE] * solids.Extent()
    for index in range(1, raw_solids.Extent() + 1):
        found = solids.FindIndex(raw_solids.FindKey(index))
        if found > 0:
            solid_sets[found - 1] = at(section.solids, index)
    return cmf_section.as_stated(cmf_section.Section(section.sets, cmf_section.NONE, solid_sets, face_sets), "step")


def read(source):
    """'(shape, cmf)' of the IGES file at 'source': one OCCT shape, and what it is in (or None)."""
    import ocp_serialize
    import step_cmf

    document, reader = _open(source)
    raw = reader.OneShape()
    found, sewings = bodies(raw)
    if not found:
        raise RuntimeError("%s holds no solid" % os.path.basename(source))
    part = found[0] if len(found) == 1 else ocp_serialize.compound_of(found)
    facts = step_cmf.Facts(document)
    section = step_cmf.section_of(raw, facts) if facts else None
    return part, _stated(part, raw, section, sewings)


if __name__ == "__partcad_part__":
    try:
        shape, cmf = read(request["path"])  # noqa: F821
        output = {"shape": shape}
        if cmf is not None:
            output["cmf"] = cmf
    except Exception as e:
        output = {"exception": str(e)}
