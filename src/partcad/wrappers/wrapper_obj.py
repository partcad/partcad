# This script is executed within the python sandbox environment (python runtime)
# to read OBJ files.

import os
import sys

# Pinned before the CAD imports below, which load OCP and with it VTK's
# bundled copy of expat: see the note in ocp_serialize. Without this the
# standard library's pyexpat binds to VTK's older expat and any later
# xml.dom use (build123d 0.11 imports IPython, which does exactly that)
# dies with an undefined-symbol ImportError.
import pyexpat  # noqa: F401

sys.path.append(os.path.dirname(__file__))
import wrapper_common

# What this wrapper reports for what it produces (see 'partcad.code_version'):
# raise it with any change that changes that, and everything it produced
# before is produced again.
CACHE_VERSION = 2


class ObjError(ValueError):
    """An OBJ file this reader cannot make sense of, said with the line it is on."""


def _vertex_index(token, defined, line_number):
    """The 0-based vertex a face's 'token' ('v', 'v/vt', 'v//vn' or 'v/vt/vn') names.

    A positive index counts from the first vertex of the file, from 1. A
    negative one counts back from the vertex defined last *at this point of the
    file*: -1 is the one just before the face, whatever is defined after it. So
    a negative index is resolved here, as the face is read, and a positive one
    is checked once the whole file has been ('parse').
    """
    text = token.split("/")[0]
    try:
        index = int(text)
    except ValueError:
        raise ObjError("line %d: '%s' is not a vertex index" % (line_number, token)) from None
    if index > 0:
        return index - 1
    if index < 0 and -index <= defined:
        return defined + index
    if index == 0:
        raise ObjError("line %d: a face refers to vertex 0; OBJ vertex indices start at 1" % line_number)
    raise ObjError(
        "line %d: a face refers to vertex %d, and only %d vertices are defined before it"
        % (line_number, index, defined)
    )


def parse(lines):
    """'(vertices, faces)' an OBJ file's 'lines' state: points, and polygons of 0-based indices into them.

    What a face is drawn from is all that is read: texture coordinates,
    normals, groups ('o', 'g'), smoothing groups and materials are not
    geometry, and a vertex keeps its x, y and z whatever follows them (a 'w',
    or the r, g and b of a vertex colour). Anything after a '#' is a comment,
    and a keyword is separated from what follows it by any whitespace.
    """
    vertices = []
    faces = []
    for line_number, line in enumerate(lines, start=1):
        fields = line.split("#", 1)[0].split()
        if not fields:
            continue
        keyword, values = fields[0], fields[1:]
        if keyword == "v":
            if len(values) < 3:
                raise ObjError(
                    "line %d: a vertex needs x, y and z, and this one has %d values" % (line_number, len(values))
                )
            try:
                vertices.append(tuple(float(value) for value in values[:3]))
            except ValueError:
                raise ObjError("line %d: '%s' is not a vertex" % (line_number, line.strip())) from None
        elif keyword == "f":
            if len(values) < 3:
                raise ObjError(
                    "line %d: a face needs at least 3 vertices, and this one has %d" % (line_number, len(values))
                )
            faces.append((line_number, [_vertex_index(value, len(vertices), line_number) for value in values]))

    for line_number, face in faces:
        for index in face:
            if index >= len(vertices):
                raise ObjError(
                    "line %d: a face refers to vertex %d, and the file defines only %d"
                    % (line_number, index + 1, len(vertices))
                )
    return vertices, [face for _, face in faces]


def _face(points):
    """The OCCT face bounded by the closed polygon through 'points', or None where OCCT makes none.

    That is the case for a polygon that is not planar, and for one whose
    points are all the same point. The face is asked for a plane and nothing
    else, and the answer is checked: OCCT reports a wire it cannot face as a
    null face, and adding a null shape to a compound is a segmentation fault
    rather than an error.
    """
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
    from OCP.gp import gp_Pnt

    polygon = BRepBuilderAPI_MakePolygon()
    for x, y, z in points:
        polygon.Add(gp_Pnt(x, y, z))
    # Not done when it has fewer than two distinct points: no edge, and so no wire to close.
    if not polygon.IsDone():
        return None
    polygon.Close()
    maker = BRepBuilderAPI_MakeFace(polygon.Wire(), True)
    if not maker.IsDone():
        return None
    face = maker.Face()
    return None if face.IsNull() else face


def _projected(points):
    """'points' as 2D points, in the plane they are closest to, turning counter-clockwise; None for no such plane.

    The plane is the one Newell's normal states, which is the best fit for a
    polygon that is not planar and the plane itself for one that is. Its
    dominant axis is dropped, and the other two swapped where that leaves the
    polygon turning clockwise.
    """
    normal = [0.0, 0.0, 0.0]
    for (x0, y0, z0), (x1, y1, z1) in zip(points, points[1:] + points[:1]):
        normal[0] += (y0 - y1) * (z0 + z1)
        normal[1] += (z0 - z1) * (x0 + x1)
        normal[2] += (x0 - x1) * (y0 + y1)
    axis = max(range(3), key=lambda i: abs(normal[i]))
    if normal[axis] == 0.0:
        return None
    # The two other axes in cyclic order - (y, z), (z, x), (x, y) - turn counter-clockwise about a
    # positive normal; ascending order would not for y, where (x, z) turns the other way.
    u, v = ((1, 2), (2, 0), (0, 1))[axis]
    if normal[axis] < 0:
        u, v = v, u
    return [(point[u], point[v]) for point in points]


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _crosses_itself(projected):
    """Whether two edges of the closed polygon through 'projected' that share no corner cross."""
    count = len(projected)
    edges = [(projected[i], projected[(i + 1) % count]) for i in range(count)]
    for i in range(count):
        for j in range(i + 2, count):
            if i == 0 and j == count - 1:
                continue
            (a, b), (c, d) = edges[i], edges[j]
            if _cross(a, b, c) * _cross(a, b, d) < 0 and _cross(c, d, a) * _cross(c, d, b) < 0:
                return True
    return False


def triangles(points):
    """The triangles, as index triples into 'points', that cover the polygon through them; None where none do.

    By ear clipping, in the plane the polygon is closest to ('_projected'): a
    corner is cut off only where it turns the polygon's way and no other corner
    lies in the triangle it cuts, so every triangle is inside the polygon,
    concave ones included. Corners are tried from the second one on, so a
    convex polygon is cut into the fan from its first corner. A polygon that
    crosses itself has no such cover, and is None.
    """
    projected = _projected(points)
    if projected is None or _crosses_itself(projected):
        return None
    remaining = list(range(len(points)))
    result = []
    while len(remaining) > 3:
        count = len(remaining)
        for k in list(range(1, count)) + [0]:
            a, b, c = remaining[k - 1], remaining[k], remaining[(k + 1) % count]
            pa, pb, pc = projected[a], projected[b], projected[c]
            if _cross(pa, pb, pc) <= 0:
                continue
            if any(
                _cross(pa, pb, projected[i]) >= 0
                and _cross(pb, pc, projected[i]) >= 0
                and _cross(pc, pa, projected[i]) >= 0
                for i in remaining
                if i not in (a, b, c)
            ):
                continue
            result.append((a, b, c))
            del remaining[k]
            break
        else:
            return None
    a, b, c = remaining
    if _cross(projected[a], projected[b], projected[c]) <= 0:
        return None
    result.append((a, b, c))
    return result


def build(vertices, faces):
    """'(compound, skipped)': the faces of an OBJ mesh as OCCT faces, and how many OCCT could not make.

    A planar polygon is one face, as it is in the file. One that is not planar
    (3ds Max and others write such quads) has no face OCCT can bound with it,
    and becomes triangles ('triangles'), each of which is planar: the fan
    from its first corner where it is convex, and triangles that stay inside it
    where it is not. A polygon that cannot be cut so - it crosses itself - and
    a triangle OCCT makes no face of - all three of its points the same - are
    left out and counted.
    """
    from OCP.TopoDS import TopoDS_Builder, TopoDS_Compound

    compound = TopoDS_Compound()
    builder = TopoDS_Builder()
    builder.MakeCompound(compound)
    skipped = 0
    for face in faces:
        points = [vertices[index] for index in face]
        made = _face(points)
        if made is not None:
            builder.Add(compound, made)
            continue
        cut = triangles(points) if len(points) > 3 else None
        if cut is None:
            skipped += 1
            continue
        for corners in cut:
            triangle = _face([points[i] for i in corners])
            if triangle is None:
                skipped += 1
            else:
                builder.Add(compound, triangle)
    return compound, skipped


def process(path):
    """The OBJ file at 'path' as a compound of OCCT faces, saying on standard error what was left out."""
    with open(path, "r") as file:
        vertices, faces = parse(file)
    compound, skipped = build(vertices, faces)
    if skipped:
        sys.stderr.write("%d of the faces in %s could not be made into faces, and are left out\n" % (skipped, path))
    return compound


if __name__ == "__main__":
    # Called for what it sets up as well: 'finished' reads the request it was handed.
    path, _request = wrapper_common.handle_input()
    try:
        shape = process(path)
    except Exception as e:
        wrapper_common.handle_exception(e)
        model = {"success": False, "exception": str(e), "shape": None}
    else:
        # Validated and moved here, while it is live (see wrapper_common.finished).
        model = {"success": True, "exception": None, "shape": wrapper_common.finished(shape)}
    wrapper_common.handle_output(model)
