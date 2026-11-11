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

A large shape is asked about in shards, each a run of this wrapper of its own
side by side with the others ('partcad.qual.topology.defects.shard_count'): a
request with 'shard': [index, count] answers what that shard finds ('examine'),
and one with 'shards', the list of those answers, puts them together and draws
the pieces ('finish') into exactly what one request for the whole would have
answered ('find'). One shard of one is that request, and is how 'find' works.
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
# before is produced again. Raised to 2 when the check learnt to be run in
# shards side by side ('examine', 'combine', 'finish'): what it answers is the
# same, and the verdicts made before are made again rather than trusted to be.
CACHE_VERSION = 2

# How many defective pieces are described one by one, and how many edges get a
# tube. A mesh import can have thousands of free edges, and a description of
# each says nothing the count does not.
MAX_DESCRIBED = 50
MAX_TUBES = 400

# How thin, in millimetres, a piece may be before it is a sliver, unless the
# object says otherwise: the 'degenerate' check's own threshold for a whole part.
DEFAULT_MIN_LENGTH = 1e-3


def _result_statuses(result):
    """What OCCT finds wrong with one checked shape itself and where it meets its neighbours, by name."""
    from OCP.BRepCheck import BRepCheck_Status

    found = []
    if result is None:
        return found

    def take(statuses):
        for status in wrapper_tolerance.members(statuses):
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


def _statuses(analyzer, piece):
    """What OCCT finds wrong with 'piece' itself and where it meets its neighbours, by name; empty when nothing."""
    return _result_statuses(analyzer.Result(piece))


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


def _length(edge) -> float:
    """How long an edge is: the size 'wrapper_tolerance._signature' gives it, without its type and centre."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.LinearProperties_s(edge, props)
    return props.Mass()


def _min_length(request) -> float:
    min_length = request.get("minLength")
    if not isinstance(min_length, (int, float)) or isinstance(min_length, bool) or min_length < 0:
        return DEFAULT_MIN_LENGTH
    return min_length


class _Pieces:
    """The faces of a shape and its edges, numbered as the answer numbers them: all the edges, or one shard's run.

    One shard of one is the whole shape, listed as 'wrapper_tolerance._features'
    lists it. Of more, every shard lists every face, and deals them into runs
    of about equal work ('_deal') the same way, so that all of them agree on
    which shard a face is in; but it lists only its own run of the edges, which
    is most of the work of listing them, and 'combine' numbers an edge by
    adding up the edges the shards before it kept.
    """

    def __init__(self, shape, shard: int = 0, count: int = 1):
        from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
        from OCP.TopExp import TopExp
        from OCP.TopoDS import TopoDS
        from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape, TopTools_IndexedMapOfShape

        self.shape = shape
        indexed = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(shape, TopAbs_FACE, indexed)
        self.faces = [TopoDS.Face_s(indexed.FindKey(index)) for index in range(1, indexed.Extent() + 1)]
        found = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(shape, TopAbs_EDGE, found)
        ancestors = TopTools_IndexedDataMapOfShapeListOfShape()
        TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, ancestors)
        if count > 1:
            self.face_shard, bounds = self._deal(found.Extent(), count)
            first, end = bounds[shard], bounds[shard + 1]
        else:
            self.face_shard = None
            first, end = 1, found.Extent() + 1
        self.edges, faces_of = wrapper_tolerance.edges_between(found, ancestors, first, end)
        # The faces each edge bounds, by their places among the faces: what a
        # shard has to check an edge of its own against.
        self.faces_of = None
        if count > 1:
            self.faces_of = [sorted(indexed.FindIndex(face) - 1 for face in faces) for faces in faces_of]

    def _deal(self, edges: int, count: int):
        """Which shard each face is in, and where each shard's run of the edges starts: (shards, starts).

        Faces are dealt in their order, in runs of about equal work. The work of
        checking a face grows faster than the number of its edges -- OCCT checks
        its wires against each other -- so a face weighs that number to the
        power 1.5, which is what a plate drilled with 3,600 holes measured: each
        of its two faces with the holes in them took sixteen seconds, and its
        3,604 others a quarter of a millisecond between them. Then the edges are
        cut where the faces are, near enough: a shard's run starts after the
        edges of the faces before its own, so that it is mostly its own faces'
        edges it checks, and the faces it has to be handed besides for them are
        few. Where the runs are cut changes how long the shards take, and never
        what they find.

        'starts' holds 'count' + 1 places in the map of the edges, from 1 to
        'edges' + 1, never decreasing.
        """
        from OCP.TopAbs import TopAbs_EDGE
        from OCP.TopExp import TopExp
        from OCP.TopTools import TopTools_IndexedMapOfShape

        map_shapes = TopExp.MapShapes_s
        weights = []
        for face in self.faces:
            own = TopTools_IndexedMapOfShape()
            map_shapes(face, TopAbs_EDGE, own)
            weights.append(1.0 + own.Extent() ** 1.5)
        total = sum(weights)
        shards = []
        before = 0.0
        for weight in weights:
            shards.append(min(count - 1, int((before + weight / 2.0) * count / total)))
            before += weight

        starts = [1]
        seen = TopTools_IndexedMapOfShape()
        for face, shard in zip(self.faces, shards):
            while len(starts) <= shard:
                starts.append(seen.Extent() + 1)
            map_shapes(face, TopAbs_EDGE, seen)
        while len(starts) < count:
            starts.append(seen.Extent() + 1)
        starts.append(edges + 1)
        for index in range(1, len(starts)):
            starts[index] = min(edges + 1, max(starts[index], starts[index - 1]))
        return shards, starts


def _loose(shape):
    """What 'shape' holds outside every face: wires, edges and vertices of its own, which a face's check never reaches."""
    from OCP.TopAbs import TopAbs_COMPOUND, TopAbs_COMPSOLID, TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID
    from OCP.TopoDS import TopoDS_Iterator

    containers = (TopAbs_COMPOUND, TopAbs_COMPSOLID, TopAbs_SOLID, TopAbs_SHELL)
    if shape.ShapeType() not in containers:
        return [] if shape.ShapeType() == TopAbs_FACE else [shape]
    found = []
    stack = [shape]
    while stack:
        iterator = TopoDS_Iterator(stack.pop())
        while iterator.More():
            child = iterator.Value()
            if child.ShapeType() in containers:
                stack.append(child)
            elif child.ShapeType() != TopAbs_FACE:
                found.append(child)
            iterator.Next()
    return found


def _first_is_no_error(statuses) -> bool:
    from OCP.BRepCheck import BRepCheck_Status

    return statuses.Size() == 0 or statuses.First() == BRepCheck_Status.BRepCheck_NoError


def _whole_shard(shape, shard: int, count: int):
    """What OCCT finds wrong with the shells and solids this shard answers for, and whether they are valid.

    'BRepCheck_Analyzer' checks a shell by itself ('BRepCheck_Shell', made
    afresh for it) and then in the context of each solid it is a shell of; a
    solid by itself ('BRepCheck_Solid'); and nothing in either looks at the
    checks of the faces. So they are asked here directly, of the shells and
    solids alone, which is what lets a solid of 137,000 faces have its shell
    checked without its faces being checked a second time; and validity is
    worked out the way 'BRepCheck_Analyzer::IsValid' works it out of them.

    A solid, and the shells in it, belong to the shard its place among the
    solids deals it to; a shell in no solid, to the shard its place among the
    shells does. Answers ([(shell index, names)], [(solid index, names)], valid).
    """
    from OCP.BRepCheck import BRepCheck_Shell, BRepCheck_Solid, BRepCheck_Status
    from OCP.TopAbs import TopAbs_SHELL, TopAbs_SOLID
    from OCP.TopExp import TopExp, TopExp_Explorer
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape, TopTools_IndexedMapOfShape

    shells = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_SHELL, shells)
    solids = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_SOLID, solids)
    of_shell = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_SHELL, TopAbs_SOLID, of_shell)

    def shard_of_solid(index):
        return index * count // solids.Extent()

    def owners_of(shell):
        """The solids 'shell' is a shell of, by their places among the solids, in the analyzer's order."""
        if not of_shell.Contains(shell):
            return []
        return sorted(solids.FindIndex(solid) - 1 for solid in wrapper_tolerance.members(of_shell.FindFromKey(shell)))

    results = {}

    def shell_result(index):
        """The shell's check, in the context of every solid it is a shell of, as the analyzer makes it."""
        if index not in results:
            shell = TopoDS.Shell_s(shells.FindKey(index + 1))
            result = BRepCheck_Shell(shell)
            for owner in owners_of(shell):
                result.InContext(solids.FindKey(owner + 1))
            results[index] = result
        return results[index]

    valid = True
    found_shells = []
    for index in range(shells.Extent()):
        owners = owners_of(shells.FindKey(index + 1))
        mine = shard_of_solid(owners[0]) if owners else index * count // shells.Extent()
        if mine != shard:
            continue
        result = shell_result(index)
        valid = valid and _first_is_no_error(result.Status())
        names = _result_statuses(result)
        if names:
            found_shells.append((index, names))

    found_solids = []
    for index in range(solids.Extent()):
        if shard_of_solid(index) != shard:
            continue
        solid = TopoDS.Solid_s(solids.FindKey(index + 1))
        result = BRepCheck_Solid(solid)
        valid = valid and _first_is_no_error(result.Status())
        names = _result_statuses(result)
        if names:
            found_solids.append((index, names))
        # 'ValidSub(solid, TopAbs_SHELL)', to the letter: the first shell with
        # no check in this solid's context ends the look, and any status but
        # NoError in that context makes the solid invalid.
        explorer = TopExp_Explorer(solid, TopAbs_SHELL)
        while explorer.More() and valid:
            check = shell_result(shells.FindIndex(explorer.Current()) - 1)
            check.InitContextIterator()
            while check.MoreShapeInContext() and not check.ContextualShape().IsSame(solid):
                check.NextShapeInContext()
            if not check.MoreShapeInContext():
                break
            if any(
                status != BRepCheck_Status.BRepCheck_NoError
                for status in wrapper_tolerance.members(check.StatusOnShape())
            ):
                valid = False
            explorer.Next()
    return found_shells, found_solids, valid


def examine(shape, min_length, shard: int = 0, count: int = 1, pieces: _Pieces = None) -> dict:
    """What is wrong with the faces and edges shard 'shard' of 'count' answers for, to be put together by 'combine'.

    One shard is the whole shape, checked as it always was: OCCT's analyzer is
    run over all of it. Of more than one, each runs the analyzer over a
    compound of its own faces and of every face an edge of its own bounds --
    which is everything OCCT checks a face or an edge against: a face by
    itself, an edge by itself and in each face it bounds. What a face is found
    to be is therefore the same whichever shard checks it, and so is an edge,
    and so is whether the whole is valid, which is asked of each shard's
    compound and of the shells and solids ('_whole_shard'). The first shard also
    checks what lies outside every face (see '_loose').

    Every shard reads the whole shape and numbers its faces the way 'find'
    does; its edges are its own run of them ('_Pieces'), numbered from the
    first, which 'combine' renumbers after the edges of the shards before it.
    """
    from OCP.BRep import BRep_Builder
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.TopAbs import TopAbs_SHELL, TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS_Compound
    from OCP.TopTools import TopTools_MapOfShape

    if pieces is None:
        pieces = _Pieces(shape, shard, count)
    faces, edges = pieces.faces, pieces.edges
    my_edges = list(range(len(edges)))
    if count > 1:
        my_faces = [index for index, owner in enumerate(pieces.face_shard) if owner == shard]
        builder = BRep_Builder()
        compound = TopoDS_Compound()
        builder.MakeCompound(compound)
        checked = set(my_faces)
        for index in my_faces:
            builder.Add(compound, faces[index])
        for index in my_edges:
            if not pieces.faces_of[index]:
                builder.Add(compound, edges[index])
            for face in pieces.faces_of[index]:
                if face not in checked:
                    checked.add(face)
                    builder.Add(compound, faces[face])
        if shard == 0:
            for loose in _loose(shape):
                builder.Add(compound, loose)
        analyzer = BRepCheck_Analyzer(compound)
        analyzer_valid = bool(analyzer.IsValid())
        found_shells, found_solids, whole_valid = _whole_shard(shape, shard, count)
        valid = analyzer_valid and whole_valid
    else:
        my_faces = list(range(len(faces)))
        analyzer = BRepCheck_Analyzer(shape)
        valid = analyzer_valid = bool(analyzer.IsValid())
        found_shells, found_solids = [], []
        if not valid:
            # What OCCT finds wrong with a shell or a solid as a whole - a shell
            # that is not closed, a solid whose shells disagree - which no one
            # face or edge carries, and is said in words beside the pieces.
            for kind, found in ((TopAbs_SHELL, found_shells), (TopAbs_SOLID, found_solids)):
                explorer = TopExp_Explorer(shape, kind)
                while explorer.More():
                    names = _statuses(analyzer, explorer.Current())
                    if names:
                        found.append((len(found), names))
                    explorer.Next()

    # What is wrong with each piece, by its index among the faces or the edges.
    face_problems = {}
    edge_problems = {}
    if not analyzer_valid:
        for index in my_faces:
            names = _statuses(analyzer, faces[index])
            if names:
                face_problems.setdefault(index, []).extend(names)
        for index in my_edges:
            names = _statuses(analyzer, edges[index])
            if names:
                edge_problems.setdefault(index, []).extend(names)

    free = 0
    free_edges = TopTools_MapOfShape()
    for edge in _free_edges(shape):
        free_edges.Add(edge)
    for index in my_edges:
        # The map compares as 'IsSame' does: the same edge, either way round.
        if free_edges.Contains(edges[index]):
            edge_problems.setdefault(index, []).append("free")
            free += 1

    slivers = 0
    if min_length > 0.0:
        for index in my_faces:
            if _width(faces[index]) < min_length:
                face_problems.setdefault(index, []).append("sliver")
                slivers += 1
        for index in my_edges:
            if _length(edges[index]) < min_length:
                edge_problems.setdefault(index, []).append("sliver")
                slivers += 1

    # Described, by 'combine', are the first of the defective pieces of all the
    # shards together; those are among the first of each shard's.
    signatures = []
    for kind, problems, items in (("face", face_problems, faces), ("edge", edge_problems, edges)):
        for index in sorted(problems)[:MAX_DESCRIBED]:
            geometry, size, centre = wrapper_tolerance._signature(items[index], kind)
            signatures.append([kind, index, geometry, size, list(centre)])

    return {
        "shard": shard,
        "count": count,
        "valid": valid,
        "faces": len(faces),
        # The edges this shard kept, which the edges of the shards after it
        # are numbered after; an edge's index here is its place among them.
        "edges": len(edges),
        "face_problems": sorted([index, names] for index, names in face_problems.items()),
        "edge_problems": sorted([index, names] for index, names in edge_problems.items()),
        "free": free,
        "slivers": slivers,
        "shells": [[index, names] for index, names in found_shells],
        "solids": [[index, names] for index, names in found_solids],
        "signatures": signatures,
    }


def combine(shards, min_length) -> dict:
    """The answer of 'find', but for the pieces' geometry, put together from what every shard of the shape found.

    'shards' is what 'examine' answered for each shard, in any order. Each
    piece belongs to exactly one shard, so its problems are that shard's; the
    shells and the solids are in the order the shape holds them, shells first,
    which is the order 'find' names what is wrong with them in.
    """
    shards = sorted(shards, key=lambda found: found["shard"])
    valid = all(found["valid"] for found in shards)
    face_problems = {}
    edge_problems = {}
    signatures = {}
    shells, solids = [], []
    edges = 0
    for found in shards:
        face_problems.update((index, names) for index, names in found["face_problems"])
        edge_problems.update((edges + index, names) for index, names in found["edge_problems"])
        signatures.update(
            ((kind, (edges if kind == "edge" else 0) + index), rest) for kind, index, *rest in found["signatures"]
        )
        shells.extend(found["shells"])
        solids.extend(found["solids"])
        edges += found["edges"]

    whole = []
    if not valid:
        for _, names in sorted(shells, key=lambda item: item[0]) + sorted(solids, key=lambda item: item[0]):
            for name in names:
                if name not in whole:
                    whole.append(name)

    described = []
    for kind, problems in (("face", face_problems), ("edge", edge_problems)):
        for index in sorted(problems)[:MAX_DESCRIBED]:
            geometry, size, centre = signatures[(kind, index)]
            described.append(
                {
                    "kind": kind,
                    "index": index + 1,
                    "type": geometry,
                    "size": size,
                    "center": list(centre),
                    "problems": problems[index],
                }
            )

    faces = shards[0]["faces"]
    return {
        "valid": valid,
        "faces": faces,
        "edges": edges,
        "defective_faces": len(face_problems),
        "defective_edges": len(edge_problems),
        "free": sum(found["free"] for found in shards),
        "slivers": sum(found["slivers"] for found in shards),
        "whole": whole,
        "minLength": float(min_length),
        # Only the pieces: when every face is defective, drawing them is drawing
        # the part, and singles nothing out (see the module's docstring).
        "whole_faces": bool(faces) and len(face_problems) >= faces,
        "whole_edges": bool(edges) and len(edge_problems) >= edges,
        "described": described,
        "drawn_faces": sorted(face_problems),
        "drawn_edges": sorted(edge_problems),
    }


def to_draw(combined) -> bool:
    """Whether the answer 'combine' put together has any pieces to draw, which takes the shape to do."""
    return bool(
        (combined["drawn_faces"] and not combined["whole_faces"])
        or (combined["drawn_edges"] and not combined["whole_edges"])
    )


def draw(pieces: _Pieces, combined) -> dict:
    """The geometry to show the defective pieces by: the faces themselves, and a tube along each edge."""
    drawn = []
    faces = combined.pop("drawn_faces")
    edges = combined.pop("drawn_edges")
    if faces and not combined["whole_faces"]:
        drawn.append({"kind": "face", "shape": wrapper_tolerance._compound([pieces.faces[i] for i in faces])})
    tubes = 0
    if edges and not combined["whole_edges"]:
        radius = max(wrapper_tolerance._diagonal(pieces.shape) * 0.004, 0.05)
        found = []
        for index in edges:
            tube = wrapper_tolerance._tube(pieces.edges[index], radius) if tubes < MAX_TUBES else None
            if tube is not None:
                tubes += 1
                found.append(tube)
        if found:
            drawn.append({"kind": "edge", "shape": wrapper_tolerance._compound(found)})
    combined["pieces"] = drawn
    combined["tubes"] = tubes
    return combined


def find(request):
    """The defective faces and edges of 'shape', and the geometry to show them by."""
    shape = request["shape"]
    min_length = _min_length(request)
    pieces = _Pieces(shape)
    return draw(pieces, combine([examine(shape, min_length, pieces=pieces)], min_length))


def finish(request):
    """'find''s answer, out of what the shards of the shape found ('shards'): drawn when there is something to draw.

    The shape is needed only for that, and the caller sends it only then (see
    'to_draw').
    """
    min_length = _min_length(request)
    combined = combine(request["shards"], min_length)
    if to_draw(combined):
        return draw(_Pieces(request["shape"]), combined)
    combined.pop("drawn_faces")
    combined.pop("drawn_edges")
    combined["pieces"] = []
    combined["tubes"] = 0
    return combined


def answer(request):
    """What a request asks for: one shard's findings ('shard': [index, count]), the shards' put together, or all."""
    shard = request.get("shard")
    if shard is not None:
        index, count = int(shard[0]), int(shard[1])
        return examine(request["shape"], _min_length(request), index, count)
    if request.get("shards") is not None:
        return finish(request)
    return find(request)


if __name__ == "__main__":
    _, request = wrapper_common.handle_input()
    try:
        model = {"success": True, "exception": None}
        model.update(answer(request))
    except Exception as e:
        wrapper_common.handle_exception(e)
        model = {"success": False, "exception": str(e)}
    wrapper_common.handle_output(model)
