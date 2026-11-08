#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A triangle mesh as the bodies it is: a solid per closed piece, a shell per open one, a planar face per triangle.

What a mesh read as a part becomes ('wrapper_import_gltf'). A part is a body,
and a mesh file states only triangles, so the triangles that make one body have
to be found and made into it:

1. **Welded.** A mesh made for drawing repeats a vertex wherever its normal or
   its texture coordinate changes - at every hard edge - so the triangles on
   either side share no vertex. Vertices at the very same place are made one.
2. **Cleaned.** A triangle with two corners at one place, or all three on one
   line, bounds nothing and has no plane to be a face on; it is dropped, and
   counted.
3. **Split.** Triangles that share an edge are one piece. A file that draws
   three boxes in one mesh is three bodies, not one solid with three outer
   shells, which is not a valid solid at all.
4. **Oriented.** A piece whose every edge is shared by exactly two triangles is
   closed; its triangles are turned to agree with each other and then, if the
   volume they bound comes out negative, all turned over, so the faces point
   out of the solid.
5. **Built** by OCCT's 'BRepBuilderAPI_MakeShapeOnMesh', which makes a planar
   face per triangle with the edges between them shared - in C++, at hundreds
   of thousands of triangles a minute rather than build123d's 'Mesher', which
   took half a minute for twenty thousand.

A face is made per triangle, in the triangles' order, which is how the caller
finds each face's triangle again (to give it its material's colour). Coplanar
faces are not merged: that is a separate, slower step a part does not need to
be a valid solid, and it would lose that correspondence.

'split' does steps 1 to 4 and 'build' step 5, so that a caller can put pieces
that do not close on their own together before building them (see
'wrapper_import_gltf'); 'bodies' does all five.
"""

import numpy as np

# What this produces is what a 'gltf' part is made of: a change to what it
# builds is a change to 'wrapper_import_gltf''s CACHE_VERSION, which is the
# number the cache reads (see 'partcad.code_version').

# The area (in the units of the points, squared) below which a triangle bounds
# nothing: far under anything a float32 vertex of a real model can tell apart.
DEGENERATE_AREA = 1e-12


class Body:
    """One piece of a mesh: its shape (a solid, or a shell when it is open) and its faces, a triangle each.

    'triangles' indexes the triangles of the mesh it was split from, in the
    order of 'faces', so 'faces[i]' is triangle 'triangles[i]'.
    """

    __slots__ = ("shape", "faces", "triangles", "closed")

    def __init__(self, shape, faces, triangles, closed):
        self.shape = shape
        self.faces = faces
        self.triangles = triangles
        self.closed = closed


def weld(points: np.ndarray, triangles: np.ndarray):
    """'(points, triangles)' with every vertex at one place made one, and the triangles numbered by them."""
    unique, inverse = np.unique(np.asarray(points, dtype=np.float64), axis=0, return_inverse=True)
    return unique, inverse.reshape(-1)[np.asarray(triangles, dtype=np.int64)]


def usable(points: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    """Which triangles bound something: three distinct corners, not on one line."""
    a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    distinct = (a != b) & (b != c) & (a != c)
    cross = np.cross(points[b] - points[a], points[c] - points[a])
    area = 0.5 * np.linalg.norm(cross, axis=1)
    return distinct & (area > DEGENERATE_AREA)


def _edges(triangles: np.ndarray):
    """'(undirected edge ids, the edge's direction in its triangle)' for the three edges of each triangle, in order."""
    starts = triangles.reshape(-1)
    ends = triangles[:, [1, 2, 0]].reshape(-1)
    low, high = np.minimum(starts, ends), np.maximum(starts, ends)
    _, ids = np.unique(np.stack([low, high], axis=1), axis=0, return_inverse=True)
    return ids.reshape(-1), starts < ends


def pieces(triangles: np.ndarray) -> list:
    """The triangles split into pieces that share an edge: a list of arrays of triangle indices."""
    count = len(triangles)
    if count == 0:
        return []
    ids, _forward = _edges(triangles)
    owner = np.repeat(np.arange(count), 3)
    # Union-find over the triangles, joining the ones on each edge.
    parent = list(range(count))

    def find(node):
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    order = np.argsort(ids, kind="stable")
    sorted_ids = ids[order]
    sorted_owner = owner[order]
    same = np.nonzero(sorted_ids[1:] == sorted_ids[:-1])[0]
    for index in same:
        first, second = find(int(sorted_owner[index])), find(int(sorted_owner[index + 1]))
        if first != second:
            parent[second] = first
    roots = np.array([find(node) for node in range(count)])
    _, labels = np.unique(roots, return_inverse=True)
    # Grouped in one pass: a stable sort keeps each piece's triangles in their
    # order, which is what 'split' and a face's triangle are read by. Selecting
    # each label's triangles in turn was a pass over all of them per piece, and a
    # mesh of a hundred thousand pieces took that many passes.
    labels = labels.reshape(-1)
    order = np.argsort(labels, kind="stable")
    return np.split(order, np.cumsum(np.bincount(labels))[:-1])


def orient(points: np.ndarray, triangles: np.ndarray):
    """'(triangles, closed)' of one piece: turned to agree, and outward if they close a volume.

    'closed' says whether every edge is shared by exactly two triangles, which
    is what bounding a volume takes. A piece whose triangles cannot all be made
    to agree - a Moebius strip, two triangles on an edge facing apart in a way
    no turning mends - is left as it is, and is not closed.
    """
    triangles = triangles.copy()
    ids, forward = _edges(triangles)
    uses = np.bincount(ids)
    closed = bool(np.all(uses == 2))
    # Walk from triangle to triangle across each edge two of them share, turning
    # a neighbour that runs the edge the same way as the triangle it is reached from.
    by_edge = {}
    for position, edge in enumerate(ids):
        if uses[edge] == 2:
            by_edge.setdefault(int(edge), []).append(position)
    neighbours = [[] for _ in range(len(triangles))]
    for first, second in by_edge.values():
        neighbours[first // 3].append((second // 3, first, second))
        neighbours[second // 3].append((first // 3, second, first))
    flipped = np.zeros(len(triangles), dtype=bool)
    seen = np.zeros(len(triangles), dtype=bool)
    consistent = True
    for start in range(len(triangles)):
        if seen[start]:
            continue
        seen[start] = True
        stack = [start]
        while stack:
            current = stack.pop()
            for other, mine, theirs in neighbours[current]:
                # The two agree when they run the shared edge opposite ways.
                runs = forward[mine] ^ flipped[current]
                if not seen[other]:
                    seen[other] = True
                    flipped[other] = forward[theirs] == runs
                    stack.append(other)
                elif (forward[theirs] ^ flipped[other]) == runs:
                    consistent = False
    triangles[flipped] = triangles[flipped][:, [0, 2, 1]]
    if not consistent:
        return triangles, False
    if closed and _signed_volume(points, triangles) < 0:
        triangles = triangles[:, [0, 2, 1]]
    return triangles, closed


def _signed_volume(points: np.ndarray, triangles: np.ndarray) -> float:
    a, b, c = points[triangles[:, 0]], points[triangles[:, 1]], points[triangles[:, 2]]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)


def _faces_on(points: np.ndarray, triangles: np.ndarray) -> list:
    """A planar face per triangle, in order, with shared edges: 'BRepBuilderAPI_MakeShapeOnMesh'."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeShapeOnMesh
    from OCP.gp import gp_Pnt
    from OCP.Poly import Poly_Triangle, Poly_Triangulation
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape

    used, local = np.unique(triangles, return_inverse=True)
    local = local.reshape(-1, 3) + 1  # OCCT counts from 1
    mesh = Poly_Triangulation(len(used), len(triangles), False)
    for index, (x, y, z) in enumerate(points[used].tolist(), start=1):
        mesh.SetNode(index, gp_Pnt(x, y, z))
    for index, (a, b, c) in enumerate(local.tolist(), start=1):
        mesh.SetTriangle(index, Poly_Triangle(a, b, c))
    maker = BRepBuilderAPI_MakeShapeOnMesh(mesh)
    maker.Build()
    if not maker.IsDone():
        raise RuntimeError("OCCT could not make faces of the mesh")
    found = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(maker.Shape(), TopAbs_FACE, found)
    if found.Extent() != len(triangles):
        raise RuntimeError("OCCT made %d faces of %d triangles" % (found.Extent(), len(triangles)))
    return [found.FindKey(index) for index in range(1, found.Extent() + 1)]


class Piece:
    """One piece of a split mesh: which of its triangles it is, turned to agree ('oriented'), and whether it closes."""

    __slots__ = ("triangles", "oriented", "closed")

    def __init__(self, triangles, oriented, closed):
        self.triangles = triangles
        self.oriented = oriented
        self.closed = closed


def split(points, triangles):
    """'(points, pieces, how many triangles were dropped)': steps 1 to 4 of the module docstring.

    The points that come back are the welded ones, which each piece's
    'oriented' triangles index; its 'triangles' index the triangles passed in.
    """
    points, triangles = weld(points, triangles)
    keep = usable(points, triangles) if len(triangles) else np.zeros(0, dtype=bool)
    original = np.nonzero(keep)[0]
    triangles = triangles[keep]
    found = []
    for piece in pieces(triangles):
        oriented, closed = orient(points, triangles[piece])
        found.append(Piece(original[piece], oriented, closed))
    return points, found, int(len(keep) - len(original))


def build(points, piece: Piece) -> Body:
    """Step 5: a piece made into a solid if it closes, a shell if it does not."""
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Shell, TopoDS_Solid

    builder = BRep_Builder()
    faces = _faces_on(points, piece.oriented)
    shell = TopoDS_Shell()
    builder.MakeShell(shell)
    for face in faces:
        builder.Add(shell, face)
    if not piece.closed:
        return Body(shell, faces, piece.triangles, False)
    shell.Closed(True)
    solid = TopoDS_Solid()
    builder.MakeSolid(solid)
    builder.Add(solid, shell)
    return Body(solid, faces, piece.triangles, True)


def bodies(points, triangles):
    """'(bodies, how many triangles were dropped)': the mesh 'points'/'triangles' as a list of 'Body'."""
    points, found, dropped = split(points, triangles)
    return [build(points, piece) for piece in found], dropped
