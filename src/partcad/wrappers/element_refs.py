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
# Or by a *selection*, written the way the part's script would select it: a
# CadQuery one, 'faces(">Z")', or a build123d one, 'faces().sort_by(Axis.Z)[-1]'
# (see 'selector_refs', whose grammar a selection is held to before it is
# evaluated, with 'eval()', against the shape). 'locate' answers with one of
# those for a part made by that library: the shortest chain of the library's own
# selectors that selects the clicked face or edge and nothing else, found by
# trying them on the shape and kept only once evaluating it as written selects
# exactly that ('selection_for'). A CadQuery selection is evaluated by CadQuery,
# and so in the layer CadQuery runs in ('partcad.measure').
#

# Every point is in the shape's own frame, in millimetres: the frame the 3D
# view's node draws the shape in.

import time


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
    import selector_refs

    result = {}
    by_element = {}
    for ref in refs or []:
        if not isinstance(ref, str) or ref in result:
            continue
        if selector_refs.style(ref) is not None:
            # A selection that selects nothing, or that the shape cannot answer,
            # is left out like a face it no longer has.
            try:
                at = selection_anchor(shape, ref)
            except Exception:  # pylint: disable=broad-except
                at = None
            if at is not None:
                result[ref] = [round(value, 6) for value in at]
            continue
        parsed = _parse(ref)
        if parsed is None:
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


def locate(shape, point, tolerance=0.0, style=None):
    """Which face or edge of 'shape' the point 'point' is on, as a comment points at it.

    '{"ref", "element", "index", "at", "distance", "numbered"}': 'face:12' or
    'edge:3', the two halves of it, the point of it nearest 'point', how far that
    is, and the element by its number whatever 'ref' is. An edge within
    'tolerance' millimetres is what was meant, since it is a line and a click
    lands beside it; otherwise the nearest face is. A shape with no face - a
    sketch of open lines - answers its nearest edge whatever the distance. None
    for a shape with neither.

    With 'style' 'cadquery' or 'build123d', 'ref' is a selection of that one
    element written in that library's terms where one is found
    ('selection_for'), and its number otherwise.
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
    numbered = "%s:%d" % (element, index + 1)
    selection = selection_for(shape, element, index + 1, style) if style in ("cadquery", "build123d") else None
    return {
        "ref": selection or numbered,
        "element": element,
        "index": index + 1,
        "at": [round(value, 6) for value in _xyz(at)],
        "distance": distance,
        "numbered": numbered,
    }


def counts(shape):
    """How many faces and edges 'shape' has, as '{"faces", "edges"}': what a reference may number up to."""
    return {"faces": len(_elements(shape, "face")), "edges": len(_elements(shape, "edge"))}


# -- Selections -------------------------------------------------------------------


def _wrapped(value) -> list:
    """The OCCT shapes a selection came to: a Workplane's values, a ShapeList, a group, one shape."""
    vals = getattr(value, "vals", None)
    if callable(vals):
        value = vals()
    if hasattr(value, "wrapped"):
        return [value.wrapped]
    found = []
    try:
        items = list(value)
    except TypeError:
        return found
    for item in items:
        found.extend(_wrapped(item))
    return found


def select(shape, ref) -> list:
    """The OCCT shapes the selection 'ref' selects of 'shape', in its order; ValueError for no selection.

    Evaluated with 'eval()', with no builtins and nothing in reach but the shape
    and the names 'selector_refs' lets a selection use -- after it has been held
    to that grammar, which is what makes evaluating it no more than calling the
    library's own selectors.
    """
    import selector_refs

    style, problem = selector_refs.classify(ref)
    if style is None:
        raise ValueError("'%s' is not a selection: %s" % (ref, problem or "it is not written as one"))
    code = compile(ref.strip(), "<comment ref>", "eval")
    if style == selector_refs.CADQUERY:
        import cadquery as cq

        workplane = cq.Workplane().add(cq.Shape.cast(shape))
        names = {name: getattr(workplane, name) for name in selector_refs.KINDS}
    else:
        import build123d as bd

        whole = bd.Compound(shape)
        names = {name: getattr(whole, name) for name in selector_refs.KINDS}
        names.update({name: getattr(bd, name) for name in selector_refs.BUILD123D_NAMES})
    return _wrapped(eval(code, {"__builtins__": {}}, names))  # noqa: S307 -- held to 'selector_refs' first


def _anchor_of(piece):
    """A point on one selected shape: as 'anchors' pins a face or an edge, and anything else at its point nearest its middle."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_VERTEX
    from OCP.TopoDS import TopoDS

    kind = piece.ShapeType()
    if kind == TopAbs_FACE:
        return _face_point(piece)
    if kind == TopAbs_EDGE:
        return _edge_middle(piece)
    if kind == TopAbs_VERTEX:
        return _xyz(BRep_Tool.Pnt_s(TopoDS.Vertex_s(piece)))
    props = GProp_GProps()
    BRepGProp.LinearProperties_s(piece, props)
    centre = props.CentreOfMass()
    nearest = _nearest_on(_vertex(_xyz(centre)), piece)
    return _xyz(nearest[1]) if nearest is not None else _xyz(centre)


def selection_anchor(shape, ref):
    """Where a selection's callout is pinned: on the one it selects nearest the middle of them all; None for none."""
    points = [_anchor_of(piece) for piece in select(shape, ref)]
    if not points:
        return None
    middle = [sum(point[axis] for point in points) / len(points) for axis in range(3)]
    return min(points, key=lambda point: sum((point[axis] - middle[axis]) ** 2 for axis in range(3)))


# How deep a chain 'selection_for' tries, how many of the narrowest chains it
# carries from one depth to the next, and for how long, in seconds, before it
# answers the element's number instead.
SEARCH_DEPTH = 3
SEARCH_BEAM = 4
SEARCH_SECONDS = 5.0

_AXES = ("Z", "X", "Y")


def _contains(pieces, target) -> bool:
    return any(piece.wrapped.IsSame(target) for piece in pieces)


def _signature(pieces) -> frozenset:
    return frozenset(hash(piece.wrapped) for piece in pieces)


def _direction(shape, target):
    """Which way 'target' faces, out of 'shape', as a unit vector rounded to 4 places; None where it has no such way.

    A flat face's own outward normal; for anything else, the way from the
    middle of the whole shape to the middle of it. Along it the target is often
    the farthest of all, which is what selects a side of a polygon that no
    axis singles out.
    """
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepGProp import BRepGProp
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopoDS import TopoDS

    direction = None
    if target.ShapeType() == TopAbs_FACE:
        face = TopoDS.Face_s(target)
        surface = BRepAdaptor_Surface(face)
        if surface.GetType() == GeomAbs_Plane:
            normal = surface.Plane().Axis().Direction()
            sign = -1.0 if face.Orientation() == TopAbs_REVERSED else 1.0
            direction = [sign * normal.X(), sign * normal.Y(), sign * normal.Z()]
    if direction is None:
        props = GProp_GProps()
        BRepGProp.LinearProperties_s(shape, props)
        whole = props.CentreOfMass()
        props = GProp_GProps()
        BRepGProp.LinearProperties_s(target, props)
        own = props.CentreOfMass()
        direction = [own.X() - whole.X(), own.Y() - whole.Y(), own.Z() - whole.Z()]
    length = sum(value * value for value in direction) ** 0.5
    if length < 1e-9:
        return None
    rounded = [round(value / length, 4) + 0.0 for value in direction]
    # An axis is already tried as one, and reads better as one.
    if sorted(abs(value) for value in rounded) == [0.0, 0.0, 1.0]:
        return None
    return rounded


def _number_text(value) -> str:
    return ("%.4f" % value).rstrip("0").rstrip(".") or "0"


class _CadQuery:
    """How CadQuery narrows a list of faces or edges: a string selector, chained as 'faces(...).faces(...)'."""

    def __init__(self, shape, kind, target):
        import cadquery as cq

        self.cq = cq
        self.kind = kind
        self.target = target
        whole = cq.Shape.cast(shape)
        self.start = whole.Faces() if kind == "faces" else whole.Edges()
        own = next((piece for piece in self.start if piece.wrapped.IsSame(target)), None)
        self.type = own.geomType().upper() if own is not None else None
        self.direction = _direction(shape, target)
        self.use_direction = False

    def steps(self, current):
        """Every selector worth trying on 'current', in the order a person would rather read it."""
        selectors = []
        for axis in _AXES:
            selectors += [">" + axis, "<" + axis]
        if self.type:
            selectors.append("%" + self.type)
        for axis in _AXES:
            selectors += ["+" + axis, "-" + axis, "|" + axis, "#" + axis]
        if self.direction is not None and self.use_direction:
            selectors.append(">(%s)" % ",".join(_number_text(value) for value in self.direction))
        selectors += self._nth(current)
        for selector in selectors:
            try:
                narrowed = self.cq.selectors.StringSyntaxSelector(selector).filter(list(current))
            except Exception:  # pylint: disable=broad-except
                continue
            yield '%s("%s")' % (self.kind, selector), narrowed

    def _nth(self, current):
        """'>Z[n]': the cluster along an axis the target is in, where it is neither the first nor the last."""
        found = []
        for axis in _AXES:
            vector = self.cq.Vector(*[1.0 if axis == name else 0.0 for name in "XYZ"])
            try:
                clusters = self.cq.selectors.DirectionNthSelector(vector, 0, directionMax=True).cluster(list(current))
            except Exception:  # pylint: disable=broad-except
                continue
            for index, cluster in enumerate(clusters):
                if _contains(cluster, self.target) and 0 < index < len(clusters) - 1:
                    found.append(">%s[%d]" % (axis, index if index <= len(clusters) // 2 else index - len(clusters)))
        return found

    def render(self, fragments):
        return ".".join(fragments)


class _Build123d:
    """How build123d narrows a ShapeList of faces or edges: its methods, chained after 'faces()'."""

    def __init__(self, shape, kind, target):
        import build123d as bd

        self.bd = bd
        self.kind = kind
        self.target = target
        whole = bd.Compound(shape)
        self.start = whole.faces() if kind == "faces" else whole.edges()
        own = next((piece for piece in self.start if piece.wrapped.IsSame(target)), None)
        self.type = own.geom_type if own is not None else None
        self.direction = _direction(shape, target)
        self.use_direction = False

    def steps(self, current):
        bd = self.bd
        current = bd.ShapeList(current)
        for axis in _AXES:
            yield from self._ends("Axis.%s" % axis, getattr(bd.Axis, axis), current)
        if self.type is not None:
            name = getattr(self.type, "name", str(self.type))
            yield "filter_by(GeomType.%s)" % name, self._try(lambda: current.filter_by(self.type))
        size = bd.SortBy.AREA if self.kind == "faces" else bd.SortBy.LENGTH
        yield from self._ends("SortBy.%s" % size.name, size, current, middle=False)
        for axis in _AXES:
            yield "filter_by(Axis.%s)" % axis, self._try(lambda: current.filter_by(getattr(bd.Axis, axis)))
        if self.direction is not None and self.use_direction:
            spelled = "Axis((0, 0, 0), (%s))" % ", ".join(_number_text(value) for value in self.direction)
            along = bd.Axis((0, 0, 0), tuple(self.direction))
            yield from self._ends(spelled, along, current, middle=False)

    def _ends(self, spelled, key, current, middle=True):
        """'sort_by(key)[-1]' where the target alone is the last of 'current' by 'key', 'group_by(key)[n]' otherwise."""
        groups = self._try(lambda: list(current.group_by(key)))
        if not groups:
            return
        index = next((n for n, group in enumerate(groups) if _contains(group, self.target)), None)
        if index is None:
            return
        last = len(groups) - 1
        if len(groups[index]) == 1 and index in (0, last):
            yield "sort_by(%s)[%d]" % (spelled, -1 if index == last else 0), self.bd.ShapeList(groups[index])
        elif middle or index in (0, last):
            written = -1 if index == last and index else index if index <= len(groups) // 2 else index - len(groups)
            yield "group_by(%s)[%d]" % (spelled, written), self.bd.ShapeList(groups[index])

    @staticmethod
    def _try(make):
        try:
            return make()
        except Exception:  # pylint: disable=broad-except
            return None

    def render(self, fragments):
        return "%s()" % self.kind + "".join("." + fragment for fragment in fragments)


def selection_for(shape, element, index, style, seconds=SEARCH_SECONDS):
    """The shortest selection, in 'style' (CadQuery's or build123d's), of face or edge 'index' of 'shape' alone; None for none.

    A beam search over chains of the library's own selectors, each step one
    that keeps the target and leaves fewer than before: the chains that select
    the target and nothing else at the shallowest depth are tried in the order
    their steps were preferred -- an extreme along an axis first, then the type,
    then a direction, then a cluster -- and the first that evaluates, as
    written, to exactly the target is the answer ('select'). None when no chain
    of up to 'SEARCH_DEPTH' steps does within 'seconds': the caller names the
    element by its number then.
    """
    import selector_refs

    found = _elements(shape, element)
    if not 0 < index <= len(found):
        return None
    target = found[index - 1]
    kind = "faces" if element == "face" else "edges"
    search = (_CadQuery if style == selector_refs.CADQUERY else _Build123d)(shape, kind, target)
    deadline = time.monotonic() + seconds

    def exact(text):
        try:
            chosen = select(shape, text)
        except Exception:  # pylint: disable=broad-except
            return False
        return len(chosen) == 1 and chosen[0].IsSame(target)

    # The axes first, which read as what a person would write; the target's
    # own direction only where they do not single it out (a side of a polygon).
    for use_direction in (False, True):
        search.use_direction = use_direction
        found = _beam(search, target, exact, deadline)
        if found is not None or time.monotonic() > deadline:
            return found
    return None


def _beam(search, target, exact, deadline):
    """The shallowest chain of 'search''s steps that 'exact' agrees selects 'target' alone; None for none."""
    frontier = [((), list(search.start))]
    for _ in range(SEARCH_DEPTH):
        children = []
        seen = set()
        for fragments, current in frontier:
            for fragment, narrowed in search.steps(current):
                if time.monotonic() > deadline:
                    return None
                if not narrowed or len(narrowed) >= len(current) or not _contains(narrowed, target):
                    continue
                signature = (_signature(narrowed), len(fragments))
                if len(narrowed) > 1 and signature in seen:
                    continue
                seen.add(signature)
                children.append((fragments + (fragment,), list(narrowed)))
        for fragments, narrowed in children:
            if len(narrowed) == 1 and exact(search.render(fragments)):
                return search.render(fragments)
        children.sort(key=lambda child: len(child[1]))
        frontier = children[:SEARCH_BEAM]
        if not frontier:
            return None
    return None
