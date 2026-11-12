#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Which faces and edges of a part have no manufacturing tolerance, and where they are.

The sandbox half of the 'tolerance-surfaces' and 'tolerance-edges' checks
('partcad.qual.topology.tolerance'). The core has already decided that the part states no
general tolerance -- one that would cover every feature at once -- so what is
left to ask is which features are toleranced on their own, by the GD&T of the
STEP file the part is read from, and which are not.

What is read from the file is the shapes every dimension and every geometric
tolerance refers to, through OCCT's XDE ('XCAFDoc_DimTolTool'): a face a
flatness or a position tolerance is on, an edge a length is dimensioned along, a
solid a profile tolerance covers. Those are the file's shapes, read afresh, and
not the part's -- the part was built by another read of the same file, perhaps
moved since -- so a feature of the part is matched to one of the file's by what
it is: its kind of surface or curve and its size, and where there is more than
one candidate, the nearest centre, measured from the centre of the whole so that
a part moved as a whole still matches.

An edge is toleranced when the file refers to it, or when every face it bounds
is toleranced: an edge is where two faces meet, and two faces held in place hold
it there. A seam -- the edge a closed surface is cut along to be parametrized --
and a degenerate edge are not features of anything and are not counted.

Answers the counts and, for what is not toleranced, the geometry to show it by:
the faces themselves, and each edge as a thin tube along it, since a renderer
that draws surfaces draws nothing for a curve.
"""

import math
import os
import sys

import pyexpat  # noqa: F401

sys.path.append(os.path.dirname(__file__))
import ocp_serialize
import wrapper_common

# Raised to 2 when the verdict made of it stopped drawing a finding that is the
# whole part (see 'partcad.qual.highlight.covers_all'): a verdict cached before
# that carries such a drawing.
CACHE_VERSION = 2

# How many untoleranced features are described one by one in the answer, and
# how many edges get a tube. A part that tolerances nothing has every one of its
# features untoleranced, and a description of each of two thousand edges says
# nothing the count does not.
MAX_DESCRIBED = 50
MAX_TUBES = 400

# Two sizes are the same size within this share of the larger.
_SAME_SIZE = 1e-4


def _features(shape, kind):
    """The faces or edges of 'shape', in the order OCCT indexes them, without seams and degenerate edges."""
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape, TopTools_IndexedMapOfShape

    found = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE if kind == "face" else TopAbs_EDGE, found)
    result = []
    if kind == "face":
        for index in range(1, found.Extent() + 1):
            result.append(TopoDS.Face_s(found.FindKey(index)))
        return result, None

    ancestors = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, ancestors)
    return edges_between(found, ancestors, 1, found.Extent() + 1)


def edges_between(found, ancestors, first: int, end: int):
    """The edges at places 'first' to 'end' (not included) of 'found', without seams and degenerate edges.

    'found' is the map of every edge of a shape ('TopExp.MapShapes'), and
    'ancestors' every face each edge bounds ('TopExp.MapShapesAndAncestors').
    Answers the edges kept, in order, and the faces each of them bounds. This is
    '_features' for a run of the edges, which is what lets a shard of the
    'defects' check list its own edges only and still number them as the
    whole shape does: an edge's place among the kept ones is the number kept
    before its run plus its place in it.
    """
    from OCP.BRep import BRep_Tool
    from OCP.TopoDS import TopoDS

    result = []
    faces_of = []
    # Bound once: this loop runs once per edge, hundreds of thousands of times
    # on a 3D print, and what it costs is mostly the Python around the calls.
    find_key, find_index, find_list = found.FindKey, ancestors.FindIndex, ancestors.FindFromIndex
    as_edge, as_face = TopoDS.Edge_s, TopoDS.Face_s
    degenerated, closed = BRep_Tool.Degenerated_s, BRep_Tool.IsClosed_s
    for index in range(first, end):
        edge = as_edge(find_key(index))
        if degenerated(edge):
            continue
        place = find_index(edge)
        faces = [as_face(face) for face in ocp_serialize.members(find_list(place))] if place else []
        seam = False
        for face in faces:
            if closed(edge, face):
                # A seam: the one edge a closed surface is cut along, bounding
                # the same face on both sides.
                seam = True
                break
        if seam:
            continue
        result.append(edge)
        faces_of.append(faces)
    return result, faces_of


def _signature(feature, kind):
    """What a feature is: (its type, its size, its centre) -- area for a face, length for an edge."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopoDS import TopoDS

    props = GProp_GProps()
    if kind == "face":
        feature = TopoDS.Face_s(feature)
        BRepGProp.SurfaceProperties_s(feature, props)
        geometry = str(BRepAdaptor_Surface(feature).GetType()).rsplit(".", 1)[-1]
    else:
        feature = TopoDS.Edge_s(feature)
        BRepGProp.LinearProperties_s(feature, props)
        geometry = str(BRepAdaptor_Curve(feature).GetType()).rsplit(".", 1)[-1]
    centre = props.CentreOfMass()
    return geometry, props.Mass(), (centre.X(), centre.Y(), centre.Z())


def _centre(shape):
    """Where the middle of a whole shape is, which a feature's centre is measured from."""
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    if box.IsVoid():
        return (0.0, 0.0, 0.0)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    return ((xmin + xmax) / 2.0, (ymin + ymax) / 2.0, (zmin + zmax) / 2.0)


def _diagonal(shape) -> float:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    if box.IsVoid():
        return 0.0
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    return math.sqrt((xmax - xmin) ** 2 + (ymax - ymin) ** 2 + (zmax - zmin) ** 2)


def referenced_shapes(path):
    """Every shape the dimensions and geometric tolerances of the STEP file at 'path' refer to, and its whole.

    (references, whole): 'references' a list of OCCT shapes -- faces, edges, a
    solid -- and 'whole' the file's own shape, which the references are
    sub-shapes of and whose centre their centres are measured from. ([], None)
    for a file that cannot be read, or states no GD&T.
    """
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDF import TDF_LabelSequence
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFDoc import XCAFDoc_DimTolTool, XCAFDoc_DocumentTool, XCAFDoc_ShapeTool

    document = TDocStd_Document(TCollection_ExtendedString("partcad-tolerance"))
    reader = STEPCAFControl_Reader()
    reader.SetGDTMode(True)
    reader.SetNameMode(False)
    reader.SetColorMode(False)
    reader.SetLayerMode(False)
    if reader.ReadFile(path) != IFSelect_RetDone or not reader.Transfer(document):
        return [], None

    main = document.Main()
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(main)
    dimtol_tool = XCAFDoc_DocumentTool.DimTolTool_s(main)

    labels = []
    for getter in ("GetDimensionLabels", "GetGeomToleranceLabels"):
        sequence = TDF_LabelSequence()
        getattr(dimtol_tool, getter)(sequence)
        labels.extend(sequence.Value(index) for index in range(1, sequence.Length() + 1))
    # The tolerances of the older, non-semantic representation are kept as
    # 'DimTol' labels, for a file that predates AP242's semantic GD&T.
    sequence = TDF_LabelSequence()
    dimtol_tool.GetDimTolLabels(sequence)
    labels.extend(sequence.Value(index) for index in range(1, sequence.Length() + 1))

    references = []
    for label in labels:
        first, second = TDF_LabelSequence(), TDF_LabelSequence()
        if not XCAFDoc_DimTolTool.GetRefShapeLabel_s(label, first, second):
            continue
        for sequence in (first, second):
            for index in range(1, sequence.Length() + 1):
                shape = XCAFDoc_ShapeTool.GetShape_s(sequence.Value(index))
                if not shape.IsNull():
                    references.append(shape)

    roots = TDF_LabelSequence()
    shape_tool.GetFreeShapes(roots)
    whole = None
    if roots.Length() == 1:
        whole = XCAFDoc_ShapeTool.GetShape_s(roots.Value(1))
    elif roots.Length() > 1:
        from OCP.BRep import BRep_Builder
        from OCP.TopoDS import TopoDS_Compound

        builder = BRep_Builder()
        whole = TopoDS_Compound()
        builder.MakeCompound(whole)
        for index in range(1, roots.Length() + 1):
            builder.Add(whole, XCAFDoc_ShapeTool.GetShape_s(roots.Value(index)))
    return references, whole


def _toleranced_signatures(references, whole, kind):
    """The signatures of the features of 'kind' the references cover, relative to the centre of 'whole'."""
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape

    if whole is None or not references:
        return []
    origin = _centre(whole)
    from OCP.TopAbs import TopAbs_WIRE

    covered = TopTools_IndexedMapOfShape()
    for reference in references:
        # A reference to a face covers that face, and one to a solid or a shell
        # all of its faces. An edge is covered by a reference to it (or to a
        # wire of it) and otherwise only through its faces, which 'untoleranced'
        # works out: a tolerance on a face does not say where the face ends.
        if kind == "edge" and reference.ShapeType() not in (TopAbs_EDGE, TopAbs_WIRE):
            continue
        TopExp.MapShapes_s(reference, TopAbs_FACE if kind == "face" else TopAbs_EDGE, covered)
    result = []
    for index in range(1, covered.Extent() + 1):
        geometry, size, centre = _signature(covered.FindKey(index), kind)
        result.append((geometry, size, tuple(c - o for c, o in zip(centre, origin))))
    return result


def _same_size(a: float, b: float) -> bool:
    return abs(a - b) <= _SAME_SIZE * max(abs(a), abs(b), 1e-9)


def _match(signatures, candidates):
    """Which of 'candidates' (index, signature) each of 'signatures' is: a set of indices.

    By type and size, and the nearest centre among those that agree; each
    candidate is matched at most once.
    """
    matched = set()
    for geometry, size, centre in signatures:
        best, best_distance = None, None
        for index, (other_geometry, other_size, other_centre) in candidates:
            if index in matched or other_geometry != geometry or not _same_size(size, other_size):
                continue
            distance = math.dist(centre, other_centre)
            if best is None or distance < best_distance:
                best, best_distance = index, distance
        if best is not None:
            matched.add(best)
    return matched


def _tube(edge, radius):
    """A solid tube of 'radius' along 'edge', or None if OCCT will not sweep one."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeWire
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipe
    from OCP.gp import gp_Ax2, gp_Circ, gp_Dir, gp_Pnt, gp_Vec

    try:
        curve = BRepAdaptor_Curve(edge)
        start = curve.FirstParameter()
        point, tangent = gp_Pnt(), gp_Vec()
        curve.D1(start, point, tangent)
        if tangent.Magnitude() <= 1e-12:
            return None
        profile = gp_Circ(gp_Ax2(point, gp_Dir(tangent)), radius)
        circle = BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(profile).Edge()).Wire()
        disc = BRepBuilderAPI_MakeFace(circle).Face()
        spine = BRepBuilderAPI_MakeWire(edge).Wire()
        pipe = BRepOffsetAPI_MakePipe(spine, disc)
        pipe.Build()
        if not pipe.IsDone():
            return None
        return pipe.Shape()
    except Exception:  # pylint: disable=broad-except
        return None


def _compound(shapes):
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    for shape in shapes:
        builder.Add(compound, shape)
    return compound


def untoleranced(request):
    """The faces or edges ('kind') of the part with no tolerance of their own.

    'step' is the file the part is read from, when it is a STEP file whose GD&T
    may tolerance some of them; without it nothing is toleranced. 'minSize'
    leaves out what is smaller than it -- an area in mm^2 for a face, a length
    in mm for an edge -- which is how a fillet or a chamfer nobody dimensions
    separately is kept out of the answer.
    """
    shape = request["shape"]
    kind = request.get("kind") or "face"
    min_size = float(request.get("minSize") or 0.0)

    features, faces_of = _features(shape, kind)
    signatures = [_signature(feature, kind) for feature in features]
    origin = _centre(shape)
    relative = [(geometry, size, tuple(c - o for c, o in zip(centre, origin))) for geometry, size, centre in signatures]

    references, whole = [], None
    step = request.get("step")
    if step and os.path.isfile(step):
        references, whole = referenced_shapes(step)

    toleranced = _match(_toleranced_signatures(references, whole, kind), list(enumerate(relative)))
    if kind == "edge" and references:
        # An edge both of whose faces are toleranced is held in place by them.
        face_features, _ = _features(shape, "face")
        face_signatures = [_signature(face, "face") for face in face_features]
        face_relative = [
            (geometry, size, tuple(c - o for c, o in zip(centre, origin))) for geometry, size, centre in face_signatures
        ]
        held = _match(_toleranced_signatures(references, whole, "face"), list(enumerate(face_relative)))
        held_faces = [face_features[index] for index in held]
        for index, faces in enumerate(faces_of):
            if faces and all(any(face.IsSame(other) for other in held_faces) for face in faces):
                toleranced.add(index)

    missing = []
    small = 0
    for index, (geometry, size, centre) in enumerate(signatures):
        if index in toleranced:
            continue
        if size < min_size:
            small += 1
            continue
        missing.append(index)

    described = [
        {
            "index": index + 1,
            "type": signatures[index][0],
            "size": signatures[index][1],
            "center": list(signatures[index][2]),
        }
        for index in sorted(missing, key=lambda i: -signatures[i][1])[:MAX_DESCRIBED]
    ]

    highlight = None
    tubes = 0
    if missing:
        if kind == "face":
            highlight = _compound([features[index] for index in missing])
        else:
            radius = max(_diagonal(shape) * 0.004, 0.05)
            pieces = []
            for index in missing:
                tube = _tube(features[index], radius) if tubes < MAX_TUBES else None
                if tube is not None:
                    tubes += 1
                    pieces.append(tube)
            highlight = _compound(pieces) if pieces else None

    return {
        "total": len(features),
        "toleranced": len(toleranced),
        "references": len(references),
        "untoleranced": len(missing),
        "smaller": small,
        "described": described,
        "highlight": highlight,
        "tubes": tubes,
    }


if __name__ == "__main__":
    _, request = wrapper_common.handle_input()
    try:
        model = {"success": True, "exception": None}
        model.update(untoleranced(request))
    except Exception as e:
        wrapper_common.handle_exception(e)
        model = {"success": False, "exception": str(e)}
    wrapper_common.handle_output(model)
