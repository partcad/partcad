#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
# The faces and edges of a shape, as a comment points at them: 'face:12',
# 'edge:3' (see 'partcad_utils.comments'). Imported by 'wrapper_measure', and so
# run in the sandbox: the core never holds a live OCP object.
#
# Two questions, the two halves of a comment pinned to a part in the 3D view:
#
#   * 'anchors': where each face or edge a comment names is - a point *on* it,
#     which is where its callout is pinned. A face's centre of mass is not on it
#     for anything curved (a cylinder's is on its axis), so it is the point of
#     the face nearest that centre; an edge's is the middle of its parameter
#     range, which is on it by construction.
#   * 'locate': which face or edge a point the user clicked is on. The point is
#     on the tessellation, which is within the preview's deflection of the
#     surface, so the nearest face is the one clicked; an edge wins over it when
#     it is nearer than 'tolerance', which the IDE works out from how big a few
#     pixels are where the click landed - an edge is a line, and nobody clicks
#     exactly on one.
#
# Numbered as OCCT numbers them: the one-based index in 'TopExp.MapShapes',
# every face and every edge, seams and degenerate edges included, so that the
# number is a property of the shape alone and not of which elements a reader
# chose to skip. It is the numbering a topology finding's "face 3" uses.
#

# Every point is in the shape's own frame, in millimetres: the frame the 3D
# view's node draws the shape in.


def _elements(shape, element):
    """Every face ('face') or edge ('edge') of 'shape', in OCCT's order: index 0 is 'face:1'."""
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape

    found = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE if element == "face" else TopAbs_EDGE, found)
    return [found.FindKey(index) for index in range(1, found.Extent() + 1)]


def _parse(ref):
    """('face' | 'edge', index) for 'face:12' / 'edge:3', or None: 'partcad_utils.comments.parse_element_ref'."""
    if not isinstance(ref, str):
        return None
    element, _, number = ref.strip().partition(":")
    if element not in ("face", "edge") or not number.isdigit() or int(number) < 1:
        return None
    return element, int(number)


def _xyz(point):
    return [point.X(), point.Y(), point.Z()]


def _vertex(point):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.gp import gp_Pnt

    return BRepBuilderAPI_MakeVertex(gp_Pnt(*[float(value) for value in point])).Vertex()


def _nearest_on(vertex, target):
    """(distance, the point of 'target' nearest 'vertex') or None where OCCT finds none."""
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape

    measure = BRepExtrema_DistShapeShape(vertex, target)
    if not measure.IsDone() or measure.NbSolution() < 1:
        return None
    return measure.Value(), measure.PointOnShape2(1)


def _edge_middle(edge):
    """The middle of an edge's parameter range: a point on it."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS

    edge = TopoDS.Edge_s(edge)
    if BRep_Tool.Degenerated_s(edge):
        # A degenerate edge is a point - a cone's apex - and has no curve.
        return _xyz(BRep_Tool.Pnt_s(TopExp.FirstVertex_s(edge)))
    curve = BRepAdaptor_Curve(edge)
    return _xyz(curve.Value((curve.FirstParameter() + curve.LastParameter()) / 2.0))


def _face_point(face):
    """A point on a face, near the middle of it: the point of the face nearest its centre of mass."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopoDS import TopoDS

    face = TopoDS.Face_s(face)
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    centre = props.CentreOfMass()
    nearest = _nearest_on(_vertex(_xyz(centre)), face)
    return _xyz(nearest[1]) if nearest is not None else _xyz(centre)


def anchors(shape, refs):
    """{ref: [x, y, z]} for every face or edge 'refs' names that 'shape' has; the rest are left out.

    What a comment's callout is pinned to. A reference to a face or an edge the
    shape no longer has - its model changed, and the numbering with it - is left
    out rather than pinned somewhere else, and the IDE pins its thread to the
    object as a whole.
    """
    result = {}
    by_element = {}
    for ref in refs or []:
        parsed = _parse(ref)
        if parsed is None or ref in result:
            continue
        element, index = parsed
        if element not in by_element:
            by_element[element] = _elements(shape, element)
        found = by_element[element]
        if index > len(found):
            continue
        at = _face_point(found[index - 1]) if element == "face" else _edge_middle(found[index - 1])
        result[ref] = [round(value, 6) for value in at]
    return result


def _box(shape):
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    return box


def _nearest(vertex, point_box, candidates):
    """(index, distance, point) of the candidate nearest 'vertex', or None for none.

    Candidates are taken nearest bounding box first, and the search stops at
    the first whose box is further than the best found so far: a part of a
    thousand faces is measured against a handful.
    """
    boxes = []
    for index, candidate in enumerate(candidates):
        box = _box(candidate)
        boxes.append((0.0 if box.IsVoid() else point_box.Distance(box), index))
    boxes.sort()
    best = None
    for bound, index in boxes:
        if best is not None and bound > best[1]:
            break
        nearest = _nearest_on(vertex, candidates[index])
        if nearest is None:
            continue
        if best is None or nearest[0] < best[1]:
            best = (index, nearest[0], nearest[1])
    return best


def locate(shape, point, tolerance=0.0):
    """Which face or edge of 'shape' the point 'point' is on, as a comment points at it.

    '{"ref", "element", "index", "at", "distance"}': 'face:12' or 'edge:3', the
    two halves of it, the point of it nearest 'point' and how far that is. An
    edge within 'tolerance' millimetres is what was meant, since it is a line
    and a click lands beside it; otherwise the nearest face is. A shape with no
    face - a sketch of open lines - answers its nearest edge whatever the
    distance. None for a shape with neither.
    """
    from OCP.Bnd import Bnd_Box
    from OCP.gp import gp_Pnt

    vertex = _vertex(point)
    point_box = Bnd_Box()
    point_box.Add(gp_Pnt(*[float(value) for value in point]))

    faces = _elements(shape, "face")
    edges = _elements(shape, "edge")
    face = _nearest(vertex, point_box, faces) if faces else None
    edge = _nearest(vertex, point_box, edges) if edges else None
    if edge is not None and (face is None or edge[1] <= max(float(tolerance or 0.0), 0.0)):
        element, (index, distance, at) = "edge", edge
    elif face is not None:
        element, (index, distance, at) = "face", face
    else:
        return None
    return {
        "ref": "%s:%d" % (element, index + 1),
        "element": element,
        "index": index + 1,
        "at": [round(value, 6) for value in _xyz(at)],
        "distance": distance,
    }


def counts(shape):
    """How many faces and edges 'shape' has, as '{"faces", "edges"}': what a reference may number up to."""
    return {"faces": len(_elements(shape, "face")), "edges": len(_elements(shape, "edge"))}
