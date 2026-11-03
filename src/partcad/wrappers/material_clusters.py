#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Where each material is: the surfaces of one material, gathered into clusters.

What the "Materials" callout writes - the IDE's 3D and 2D tabs, and 'pc render
--with-materials' - is one name per *cluster* of a material rather than one per
face or per part: a steel frame of twelve welded tubes is one steel thing, and
twelve "Steel" callouts on it would say less, not more. A cluster is the faces
of one material, of one part or of several, each of which touches another of
them or is closer to it than a distance the user configures
('materialClusterDistance', ten millimetres unless it says otherwise). Two
faces that share an edge are one cluster at any distance; nought counts only
those, and the parts that touch.

What a face is made of is what CMF says (docs/design/cmf.md, sections 5 and 6):
the material of the solid it bounds, as the CMF section of its part's payload
records it ('cmf_export.solid_sets'), else what the face's own set says - which
is where a sheet with no solid, a wall, has one - else the 'material' its
node's properties name, which is what a part said before CMF existed. A face
none of those names a material for is in no cluster and gets no callout:
"unspecified" is not a material.

The work, for a tree of N pieces of one material, is one pass over the faces of
each distinct geometry - a bolt placed a hundred times is read once - and then
a distance between two pieces only where their boxes, grown by the distance,
overlap. Plain Python until it needs a shape, and then OCP; it runs in a
sandbox, wherever a renderer or 'wrapper_measure' does.
"""

import appearance
import cmf_export
import ocp_serialize

# Closer than this is touching: what two faces sharing an edge measure apart,
# give or take the kernel's own arithmetic.
TOUCHING = 1e-6


class _Piece:
    """Faces of one material of one placed node that are joined edge to edge."""

    __slots__ = ("material", "faces", "shape", "box", "path")

    def __init__(self, material, faces, shape, box, path):
        self.material = material
        self.faces = faces
        self.shape = shape
        self.box = box
        self.path = path


class _Sets:
    """Union-find over indices, which is what "closer than the distance to one of them" chains through."""

    def __init__(self, count):
        self.parent = list(range(count))

    def find(self, index):
        while self.parent[index] != index:
            self.parent[index] = self.parent[self.parent[index]]
            index = self.parent[index]
        return index

    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.parent[max(a, b)] = min(a, b)
        return a != b


def shape_leaves(tree) -> list:
    """'[(leaf, path), ...]': every shape node of 'tree' with its geometry, and where it is in it.

    'path' is the index of each node below the root on the way to it, which is
    how the IDE's 3D view names the nodes of the same tree ('nodeId' in the
    extension's 'nodes.ts'): the root is '[]', and the third thing the second
    thing it holds holds is '[1, 2]'.
    """
    found = []

    def walk(node, path, above):
        if not isinstance(node, dict):
            return
        if ocp_serialize.is_shape_object(node):
            if ocp_serialize.KEY_SHAPE in node:
                found.append((cmf_export.Leaf(node, None, above), path))
        elif ocp_serialize.is_assembly_object(node):
            location = node.get(ocp_serialize.KEY_LOCATION)
            inner = above + [location] if location is not None else above
            for index, child in enumerate(node[ocp_serialize.KEY_ASSEMBLY]):
                walk(child, path + [index], inner)

    walk(tree, [], [])
    return found


def _property_material(node):
    """The material a node's properties name, made absolute against its own package, or None.

    The way a part named its material before CMF: relative to the package that
    declared it (':steel', 'steel'), which is the package its full name is in.
    """
    properties = node.get(appearance.PROPERTIES_KEY) if isinstance(node, dict) else None
    reference = properties.get("material") if isinstance(properties, dict) else None
    if not isinstance(reference, str) or not reference.strip():
        return None
    reference = reference.strip()
    if reference.startswith("//"):
        return reference
    package = str(node.get("name") or "").rpartition(":")[0]
    return "%s:%s" % (package, reference.lstrip(":")) if package else reference


def face_materials(leaf, memo=None) -> list:
    """The material of each face of a leaf's own geometry, in 'TopExp::MapShapes' order; None where none is said.

    The solid's, else the face's own set's, else the node's properties' (see the
    module's docstring).
    """
    from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape

    shape = leaf.definition
    faces = cmf_export._mapped(shape, TopAbs_FACE)
    solids = cmf_export._mapped(shape, TopAbs_SOLID)
    face_sets = cmf_export.face_sets(leaf, memo, shape)
    solid_sets = cmf_export.solid_sets(leaf, memo, shape)
    bounding = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_FACE, TopAbs_SOLID, bounding)
    fallback = _property_material(leaf.node)

    materials = []
    for index in range(faces.Extent()):
        face = faces.FindKey(index + 1)
        material = None
        if bounding.Contains(face):
            for solid in bounding.FindFromKey(face):
                position = solids.FindIndex(solid)
                if 0 < position <= len(solid_sets) and solid_sets[position - 1].material:
                    material = solid_sets[position - 1].material
                    break
        if not material and index < len(face_sets):
            material = face_sets[index].material
        materials.append(material or fallback)
    return materials


def _joined(shape, materials) -> list:
    """'[(material, [face index, ...]), ...]': the faces of one material that are joined edge to edge."""
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape

    faces = cmf_export._mapped(shape, TopAbs_FACE)
    sets = _Sets(len(materials))
    sharing = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, sharing)
    for edge in range(1, sharing.Extent() + 1):
        indices = [faces.FindIndex(face) - 1 for face in sharing.FindFromIndex(edge)]
        indices = [index for index in indices if 0 <= index < len(materials) and materials[index]]
        for a, b in zip(indices, indices[1:]):
            if materials[a] == materials[b]:
                sets.union(a, b)
    groups = {}
    for index, material in enumerate(materials):
        if material:
            groups.setdefault(sets.find(index), (material, []))[1].append(index)
    return list(groups.values())


def _box(shape):
    """'[xmin, ymin, zmin, xmax, ymax, zmax]' of 'shape', or None for nothing to measure."""
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box, True)
    if box.IsVoid():
        return None
    return list(box.Get())


def _near(a, b, distance) -> bool:
    """Whether two boxes are no farther apart than 'distance' along every axis."""
    return all(a[axis] - distance <= b[axis + 3] and b[axis] - distance <= a[axis + 3] for axis in range(3))


def _distance(a, b):
    """The least distance between two shapes, or None when the kernel cannot say."""
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape

    measured = BRepExtrema_DistShapeShape(a, b)
    if not measured.IsDone():
        return None
    return measured.Value()


def _pieces(tree, memo) -> list:
    """Every piece of every leaf of 'tree', placed where the tree puts it."""
    from OCP.TopAbs import TopAbs_FACE

    pieces = []
    joined = {}
    for leaf, path in shape_leaves(tree):
        node = leaf.node
        payload = node.get(ocp_serialize.KEY_BREP)
        key = None
        if isinstance(payload, (str, bytes, bytearray, memoryview)):
            key = (bytes(payload) if not isinstance(payload, str) else payload, str(node.get(ocp_serialize.KEY_CHILD)))
            key = key + (_property_material(node),)
        definition = leaf.definition
        if key is not None and key in joined:
            found = joined[key]
        else:
            found = _joined(definition, face_materials(leaf, memo))
            if key is not None:
                joined[key] = found
        if not found:
            continue
        faces = cmf_export._mapped(definition, TopAbs_FACE)
        for material, indices in found:
            compound = ocp_serialize.compound_of([faces.FindKey(index + 1) for index in indices])
            placed = leaf.placed(compound)
            box = _box(placed)
            if box is None:
                continue
            pieces.append(_Piece(material, len(indices), placed, box, path))
    return pieces


def _anchor(shapes, box):
    """The point of 'shapes' nearest the middle of 'box': on the material, where a callout's leader can end."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.gp import gp_Pnt

    middle = [(box[axis] + box[axis + 3]) / 2 for axis in range(3)]
    try:
        vertex = BRepBuilderAPI_MakeVertex(gp_Pnt(*middle)).Vertex()
        measured = BRepExtrema_DistShapeShape(vertex, ocp_serialize.compound_of(shapes))
        if measured.IsDone() and measured.NbSolution() > 0:
            point = measured.PointOnShape2(1)
            return [point.X(), point.Y(), point.Z()]
    except Exception:  # pylint: disable=broad-except
        pass  # the middle of the box is still somewhere to point at
    return middle


def clusters(tree, distance, memo=None) -> list:
    """The clusters of each material in 'tree', as the "Materials" callout writes them.

    'tree' is a shape tree with every shape node's geometry decoded (as
    'ocp_serialize.decode_tree' answers, and as 'shape_tree' is handed to an
    implementation); 'distance' is how far apart two surfaces of one material
    may be and still be one cluster, in millimetres. Each cluster is:

    - 'material': the material's canonical reference;
    - 'name': what a person reads it as ('cmf_export.reference_name');
    - 'at': the point of the cluster nearest the middle of its box, in the frame
      of the whole tree - where the callout's leader ends;
    - 'nodes': the path of every node with a face in it ('shape_leaves');
    - 'faces': how many faces it is.

    In the order of their names, and then of where they are, so that one tree
    is answered the same way every time.
    """
    distance = max(float(distance or 0), 0.0)
    pieces = _pieces(tree, memo if memo is not None else {})
    sets = _Sets(len(pieces))
    by_material = {}
    for index, piece in enumerate(pieces):
        by_material.setdefault(piece.material, []).append(index)
    for indices in by_material.values():
        # Swept along X: a piece is compared with the ones whose boxes start
        # before its own ends, grown by the distance, and nothing further.
        indices = sorted(indices, key=lambda index: pieces[index].box[0])
        for position, a in enumerate(indices):
            reach = pieces[a].box[3] + distance
            for b in indices[position + 1 :]:
                if pieces[b].box[0] > reach:
                    break
                if sets.find(a) == sets.find(b) or not _near(pieces[a].box, pieces[b].box, distance):
                    continue
                apart = _distance(pieces[a].shape, pieces[b].shape)
                if apart is not None and (apart < distance or apart <= TOUCHING):
                    sets.union(a, b)

    gathered = {}
    for index in range(len(pieces)):
        gathered.setdefault(sets.find(index), []).append(pieces[index])
    found = []
    for members in gathered.values():
        boxes = [piece.box for piece in members]
        box = [min(b[axis] for b in boxes) for axis in range(3)] + [max(b[axis] for b in boxes) for axis in range(3, 6)]
        nodes = sorted({tuple(piece.path) for piece in members})
        material = members[0].material
        found.append(
            {
                "material": material,
                "name": cmf_export.reference_name(material),
                "at": [round(value, 6) for value in _anchor([piece.shape for piece in members], box)],
                "nodes": [list(path) for path in nodes],
                "faces": sum(piece.faces for piece in members),
            }
        )
    found.sort(key=lambda cluster: (cluster["name"], cluster["material"], cluster["at"]))
    return found
