#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Which faces and edges of a part are defective, and where they are.

The sandbox half of the 'defects' check ('partcad.qual.topology.defects'). Two
basic checks ask about the whole of a part: 'validity' whether OCCT certifies
it, and 'degenerate' whether it has any size to it. This asks which pieces of it
are the reason either could have something to say, and answers them one by one:

- **invalid**: a face or an edge 'BRepCheck_Analyzer' finds fault with itself --
  a wire that intersects itself, a curve that leaves its surface, an edge with
  no 3D curve -- each with OCCT's own name for what is wrong with it;
- **free**: an edge of a solid that bounds one face only, which is a hole in
  the skin: the 224 edges of an LDraw brick meshed from triangles, along which
  nothing joins the triangles to the studs;
- **sliver**: an edge shorter than 'minLength', or a face narrower than it
  (twice its area over its perimeter): geometry of no size, in one place, which
  a mesher chokes on and a CAM path stalls at. 'degenerate' asks whether the
  whole part is that thin; this asks which pieces of it are.

A seam -- the edge a closed surface is cut along -- and a degenerated edge -- the
point at the tip of a cone, which OCCT stores as an edge -- are what they are on
purpose, and are none of these.

Answers the counts, a description of each piece found (up to 'MAX_DESCRIBED'),
and the geometry to show them by: the faces themselves, and each edge as a thin
tube along it. Only the pieces: when every face is defective the faces are the
whole part, and showing them singles nothing out, so they are counted and
described and not drawn -- and the same for the edges.
"""

import os
import sys

# Pinned before the CAD imports below, which load OCP and with it VTK's
# bundled copy of expat: see the note in ocp_serialize.
import pyexpat  # noqa: F401

sys.path.append(os.path.dirname(__file__))
import wrapper_common
import wrapper_tolerance

# What this wrapper reports for what it produces (see 'partcad.code_version'):
# raise it with any change that changes that, and everything it produced
# before is produced again.
CACHE_VERSION = 1

# How many defective pieces are described one by one, and how many edges get a
# tube. A mesh import can have thousands of free edges, and a description of
# each says nothing the count does not.
MAX_DESCRIBED = 50
MAX_TUBES = 400

# How thin, in millimetres, a piece may be before it is a sliver, unless the
# object says otherwise: the 'degenerate' check's own threshold for a whole part.
DEFAULT_MIN_LENGTH = 1e-3


def _statuses(analyzer, piece):
    """What OCCT finds wrong with 'piece' itself and where it meets its neighbours, by name; empty when nothing."""
    from OCP.BRepCheck import BRepCheck_Status

    found = []
    result = analyzer.Result(piece)
    if result is None:
        return found

    def take(statuses):
        for status in statuses:
            if status != BRepCheck_Status.BRepCheck_NoError:
                name = getattr(status, "name", str(status)).rsplit(".", 1)[-1].replace("BRepCheck_", "")
                if name not in found:
                    found.append(name)

    take(result.Status())
    result.InitContextIterator()
    while result.MoreShapeInContext():
        take(result.StatusOnShape())
        result.NextShapeInContext()
    return found


def _free_edges(shape):
    """The edges of the solids of 'shape' that bound one face only: holes in their skins."""
    from OCP.BRep import BRep_Tool
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_FORWARD, TopAbs_REVERSED, TopAbs_SOLID
    from OCP.TopExp import TopExp, TopExp_Explorer
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape

    free = []
    explorer = TopExp_Explorer(shape, TopAbs_SOLID)
    while explorer.More():
        edges = TopTools_IndexedDataMapOfShapeListOfShape()
        TopExp.MapShapesAndAncestors_s(explorer.Current(), TopAbs_EDGE, TopAbs_FACE, edges)
        for index in range(1, edges.Extent() + 1):
            edge = TopoDS.Edge_s(edges.FindKey(index))
            # Read as 'wrapper_common.solid_problems' reads an open solid: one
            # face, not degenerated, and not an edge a face carries inside
            # itself (INTERNAL), which is no hole.
            if (
                edges.FindFromIndex(index).Extent() == 1
                and not BRep_Tool.Degenerated_s(edge)
                and edge.Orientation() in (TopAbs_FORWARD, TopAbs_REVERSED)
            ):
                free.append(edge)
        explorer.Next()
    return free


def _width(face) -> float:
    """How wide a face is, roughly: twice its area over its perimeter, which is its width for a long thin one."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    area = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, area)
    perimeter = GProp_GProps()
    BRepGProp.LinearProperties_s(face, perimeter)
    if perimeter.Mass() <= 0.0:
        return 0.0
    return 2.0 * area.Mass() / perimeter.Mass()


def find(request):
    """The defective faces and edges of 'shape', and the geometry to show them by."""
    from OCP.BRepCheck import BRepCheck_Analyzer

    shape = request["shape"]
    min_length = request.get("minLength")
    if not isinstance(min_length, (int, float)) or isinstance(min_length, bool) or min_length < 0:
        min_length = DEFAULT_MIN_LENGTH

    faces, _ = wrapper_tolerance._features(shape, "face")
    edges, _ = wrapper_tolerance._features(shape, "edge")
    face_signatures = [wrapper_tolerance._signature(face, "face") for face in faces]
    edge_signatures = [wrapper_tolerance._signature(edge, "edge") for edge in edges]

    analyzer = BRepCheck_Analyzer(shape)
    valid = bool(analyzer.IsValid())

    # What is wrong with each piece, by its index among the faces or the edges.
    face_problems = {}
    edge_problems = {}
    if not valid:
        for index, face in enumerate(faces):
            names = _statuses(analyzer, face)
            if names:
                face_problems.setdefault(index, []).extend(names)
        for index, edge in enumerate(edges):
            names = _statuses(analyzer, edge)
            if names:
                edge_problems.setdefault(index, []).extend(names)

    from OCP.TopTools import TopTools_MapOfShape

    free = 0
    free_edges = TopTools_MapOfShape()
    for edge in _free_edges(shape):
        free_edges.Add(edge)
    for index, edge in enumerate(edges):
        # The map compares as 'IsSame' does: the same edge, either way round.
        if free_edges.Contains(edge):
            edge_problems.setdefault(index, []).append("free")
            free += 1

    slivers = 0
    if min_length > 0.0:
        for index, face in enumerate(faces):
            if _width(face) < min_length:
                face_problems.setdefault(index, []).append("sliver")
                slivers += 1
        for index, signature in enumerate(edge_signatures):
            if signature[1] < min_length:
                edge_problems.setdefault(index, []).append("sliver")
                slivers += 1

    # What OCCT finds wrong with a shell or a solid as a whole - a shell that
    # is not closed, a solid whose shells disagree - which no one face or edge
    # carries, and is said in words beside the pieces.
    whole = []
    if not valid:
        from OCP.TopAbs import TopAbs_SHELL, TopAbs_SOLID
        from OCP.TopExp import TopExp_Explorer

        for kind in (TopAbs_SHELL, TopAbs_SOLID):
            explorer = TopExp_Explorer(shape, kind)
            while explorer.More():
                for name in _statuses(analyzer, explorer.Current()):
                    if name not in whole:
                        whole.append(name)
                explorer.Next()

    described = []
    for kind, problems, signatures in (
        ("face", face_problems, face_signatures),
        ("edge", edge_problems, edge_signatures),
    ):
        for index in sorted(problems)[:MAX_DESCRIBED]:
            described.append(
                {
                    "kind": kind,
                    "index": index + 1,
                    "type": signatures[index][0],
                    "size": signatures[index][1],
                    "center": list(signatures[index][2]),
                    "problems": problems[index],
                }
            )

    # Only the pieces: when every face is defective, drawing them is drawing
    # the part, and singles nothing out (see the module's docstring).
    whole_faces = bool(faces) and len(face_problems) >= len(faces)
    whole_edges = bool(edges) and len(edge_problems) >= len(edges)
    pieces = []
    if face_problems and not whole_faces:
        pieces.append({"kind": "face", "shape": wrapper_tolerance._compound([faces[i] for i in sorted(face_problems)])})
    tubes = 0
    if edge_problems and not whole_edges:
        radius = max(wrapper_tolerance._diagonal(shape) * 0.004, 0.05)
        found = []
        for index in sorted(edge_problems):
            tube = wrapper_tolerance._tube(edges[index], radius) if tubes < MAX_TUBES else None
            if tube is not None:
                tubes += 1
                found.append(tube)
        if found:
            pieces.append({"kind": "edge", "shape": wrapper_tolerance._compound(found)})

    return {
        "valid": valid,
        "faces": len(faces),
        "edges": len(edges),
        "defective_faces": len(face_problems),
        "defective_edges": len(edge_problems),
        "free": free,
        "slivers": slivers,
        "whole": whole,
        "minLength": float(min_length),
        "whole_faces": whole_faces,
        "whole_edges": whole_edges,
        "described": described,
        "pieces": pieces,
        "tubes": tubes,
    }


if __name__ == "__main__":
    _, request = wrapper_common.handle_input()
    try:
        model = {"success": True, "exception": None}
        model.update(find(request))
    except Exception as e:
        wrapper_common.handle_exception(e)
        model = {"success": False, "exception": str(e)}
    wrapper_common.handle_output(model)
