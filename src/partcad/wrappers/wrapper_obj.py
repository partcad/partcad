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


def build(vertices, faces):
    """'(compound, skipped)': the faces of an OBJ mesh as OCCT faces, and how many OCCT could not make.

    A planar polygon is one face, as it is in the file. One that is not planar
    (3ds Max and others write such quads) has no face OCCT can bound with it,
    and becomes the fan of triangles from its first vertex, each of which is
    planar; that is exact for the convex polygons such exporters write. A
    triangle OCCT still makes no face of - all three of its points the same -
    is left out and counted.
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
        if len(points) == 3:
            skipped += 1
            continue
        for i in range(1, len(points) - 1):
            triangle = _face([points[0], points[i], points[i + 1]])
            if triangle is None:
                skipped += 1
            else:
                builder.Add(compound, triangle)
    return compound, skipped


def process(path):
    with open(path, "r") as file:
        vertices, faces = parse(file)
    compound, skipped = build(vertices, faces)
    if skipped:
        sys.stderr.write("%d of the faces in %s bound no area, and are left out\n" % (skipped, path))
    return compound


if __name__ == "__main__":
    path, request = wrapper_common.handle_input()
    try:
        shape = process(path)
    except Exception as e:
        wrapper_common.handle_exception(e)
        model = {"success": False, "exception": str(e), "shape": None}
    else:
        # Validated and moved here, while it is live (see wrapper_common.finished).
        model = {"success": True, "exception": None, "shape": wrapper_common.finished(shape)}
    wrapper_common.handle_output(model)
