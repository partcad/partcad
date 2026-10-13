#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The half of a CAE implementation that does not depend on the solver.

Every 'cae:' implementation does the same four things around the one that is its
own: it works out which surfaces of the part each boundary condition is applied
to, meshes the part with those surfaces named, runs its solver, and draws the
answer as a coloured model. Only the third differs between CalculiX, Elmer,
OpenFOAM, Code_Aster, MOOSE and code_saturne -- so the other three are here, in
the sandbox beside the meta-wrapper, rather than copied into every package that
implements an analysis and left to drift apart.

**Where a condition lands.** A port is a coordinate frame, and a frame is a
point: it cannot say which surface a bolt clamps or how wide an inlet is. A port
whose interface draws it with a sketch can -- the sketch, placed by the port's
frame, *is* the surface. So before the implementation runs, 'prepare()' (called
by 'wrapper_export.py' for every analysis) imprints each port's sketch on the
part, splitting the faces it lies on along its outline, and tells each boundary
record which faces of the result it covers:

    record["faces"] = [{"index": 3, "centroid": [x, y, z], "area": a, "normal": [...]}]
    record["area"] = a          # the whole of what the port covers, in mm^2

'index' is a position in 'faces_of(request["wrapped"])', which is the part
*after* the imprint: the implementation is handed that shape, not the one it was
built as. A port with no sketch covers the face its frame lies on, when it lies
on one -- the root face of a cantilever whose port sits in the middle of it. A
port that lies on no face covers nothing, carries 'faces: []', and the
implementation decides what that means (CalculiX uses the nodes around it).

**The mesh.** 'mesh()' writes the part out, meshes it with gmsh, and names a
physical group per entry of 'groups' (name -> face indices), plus one for every
surface no group claimed when 'rest' is given -- the walls of a duct, the free
surface of a bracket. The physical groups are what every solver here can read
boundary conditions off: ElmerGrid, gmshToFoam, libMesh, a MED file and
code_saturne all keep them by name.

**The answer.** 'write_glb()' draws a surface coloured by a field as the binary
glTF the PartCAD Viewer shows, and 'outer_triangles()' finds that surface in a
volume mesh.

Imported by 'wrapper_export.py' for 'prepare()', and by implementation scripts
for the rest: the meta-wrapper's directory is on 'sys.path' when a script runs.
Nothing here imports gmsh until 'mesh()' is called, so a package that meshes
its own way pays nothing for it, and 'prepare()' needs only OCP, which every
PartCAD sandbox has.

All lengths here are the part's own, millimetres, until 'mesh()' scales them to
the metres every solver's material constants are written in.
"""

import json
import math
import os
import struct
import tempfile

MM_PER_M = 1000.0

# What a boundary record carries its sketch under, as 'render_overlay' puts it
# there. Consumed by 'prepare()': the faces it resolves to are what an
# implementation reads, and the geometry itself has no business in a result.
SKETCH_KEY = "sketch"


class ToolMissing(Exception):
    """The solver, or something it needs, is not available where this runs."""


class ToolFailed(Exception):
    """The solver ran and did not produce an answer, with what it said."""


def failed(exception):
    """The answer PartCAD's meta-wrapper expects when nothing was produced."""
    return {"success": False, "exception": str(exception)}


# --------------------------------------------------------------------------- #
# Faces                                                                       #
# --------------------------------------------------------------------------- #


def faces_of(shape):
    """The faces of a shape, in the order every index here refers to.

    An indexed map rather than an explorer, so that a face shared by two solids
    is one face and has one index -- and because it is the order gmsh, given the
    same shape, is matched against in 'mesh()'.
    """
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedMapOfShape

    found = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, found)
    return [TopoDS.Face_s(found.FindKey(index)) for index in range(1, found.Extent() + 1)]


def _area_and_centroid(shape):
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    properties = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, properties)
    centre = properties.CentreOfMass()
    return properties.Mass(), (centre.X(), centre.Y(), centre.Z())


def _normal(face):
    """The outward normal of a planar face, or None for a curved one."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.TopAbs import TopAbs_REVERSED

    surface = BRepAdaptor_Surface(face)
    if surface.GetType() != GeomAbs_Plane:
        return None
    direction = surface.Plane().Axis().Direction()
    normal = [direction.X(), direction.Y(), direction.Z()]
    if face.Orientation() == TopAbs_REVERSED:
        normal = [-component for component in normal]
    return normal


def fingerprint(face, index):
    """What identifies one face to someone who cannot share the OCP object."""
    area, centroid = _area_and_centroid(face)
    return {"index": index, "centroid": list(centroid), "area": area, "normal": _normal(face)}


def _box(shape, enlarge=0.0):
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    if enlarge:
        box.Enlarge(enlarge)
    return box


def extent_of(shape):
    """The largest dimension of a shape's bounding box."""
    xmin, ymin, zmin, xmax, ymax, zmax = _box(shape).Get()
    return max(xmax - xmin, ymax - ymin, zmax - zmin)


def _sketch_faces(sketch):
    """The faces a decoded port sketch is made of, whatever it arrived as.

    A sketch travels as a list of placed components (see
    'render_overlay.collect_async'), each a face, a wire, or a compound of
    either. A closed wire is made into the face it bounds: an outline is a
    region, and it is the region that a condition is applied to.
    """
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.TopAbs import TopAbs_FACE, TopAbs_WIRE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS, TopoDS_Shape

    if sketch is None:
        return []
    shapes = sketch if isinstance(sketch, list) else [sketch]
    faces = []
    for shape in shapes:
        if not isinstance(shape, TopoDS_Shape) or shape.IsNull():
            continue
        explorer = TopExp_Explorer(shape, TopAbs_FACE)
        found = False
        while explorer.More():
            faces.append(TopoDS.Face_s(explorer.Current()))
            found = True
            explorer.Next()
        if found:
            continue
        explorer = TopExp_Explorer(shape, TopAbs_WIRE)
        while explorer.More():
            maker = BRepBuilderAPI_MakeFace(TopoDS.Wire_s(explorer.Current()), True)
            if maker.IsDone():
                faces.append(maker.Face())
            explorer.Next()
    return faces


def _split(shape, tools, fuzzy):
    """The shape with every tool face imprinted on its surface."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Splitter
    from OCP.TopTools import TopTools_ListOfShape

    arguments = TopTools_ListOfShape()
    arguments.Append(shape)
    cutters = TopTools_ListOfShape()
    for tool in tools:
        cutters.Append(tool)
    splitter = BRepAlgoAPI_Splitter()
    splitter.SetArguments(arguments)
    splitter.SetTools(cutters)
    splitter.SetFuzzyValue(fuzzy)
    splitter.Build()
    if not splitter.IsDone():
        raise RuntimeError("the port sketches could not be imprinted on the part")
    return splitter.Shape()


def _common_area(face, tool, fuzzy):
    """How much of 'face' the region 'tool' covers, in the face's own units."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common

    common = BRepAlgoAPI_Common(face, tool)
    common.SetFuzzyValue(fuzzy)
    common.Build()
    if not common.IsDone():
        return 0.0
    area, _centroid = _area_and_centroid(common.Shape())
    return area


def _covered(face, area, tools, fuzzy):
    """Whether the sketch regions in 'tools' cover the whole of a face.

    By area, not by sampling points: after the imprint a face is either inside
    the sketch or outside it, and the face around an imprinted circle has its
    centroid in the middle of the hole -- inside the circle, on a face the
    circle does not touch. The common area of the two says which it is.
    """
    if area <= 0:
        return False
    face_box = _box(face, fuzzy)
    covered = 0.0
    for tool in tools:
        if face_box.IsOut(_box(tool, fuzzy)):
            continue
        covered += _common_area(face, tool, fuzzy)
    return covered >= area * (1.0 - 1e-3)


def _faces_at(faces, location, tolerance):
    """The faces a frame lies on: the fallback for a port with no sketch.

    The frame's origin has to be on the face. On an edge, where two faces meet,
    the one whose normal is the frame's Z axis wins -- a port is placed with Z
    out of the surface it belongs to -- and when neither is, both are returned
    rather than one picked at random.
    """
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.gp import gp_Pnt

    origin, axis = _frame(location)
    point = gp_Pnt(*origin)
    vertex = BRepBuilderAPI_MakeVertex(point).Vertex()
    on = []
    for index, face in enumerate(faces):
        if _box(face, tolerance).IsOut(point):
            continue
        distance = BRepExtrema_DistShapeShape(vertex, face)
        if distance.IsDone() and distance.Value() <= tolerance:
            on.append(index)
    if len(on) > 1:
        facing = []
        for index in on:
            normal = _normal(faces[index])
            if normal is not None and abs(sum(a * b for a, b in zip(normal, axis))) > 0.999:
                facing.append(index)
        if facing:
            return facing
    return on


def _frame(location):
    """A packed placement's origin and Z axis, as plain tuples.

    '[[x, y, z], [ax, ay, az], angle]' rotates about the axis by the angle; the
    Z axis of the result is what a port's surface faces along.
    """
    if not location:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)
    origin = tuple(float(value) for value in location[0])
    axis = [float(value) for value in (location[1] if len(location) > 1 else (0, 0, 1))]
    angle = math.radians(float(location[2])) if len(location) > 2 else 0.0
    length = math.sqrt(sum(value * value for value in axis)) or 1.0
    kx, ky, kz = (value / length for value in axis)
    # Rodrigues' rotation of (0, 0, 1) about k by the angle.
    cosine, sine = math.cos(angle), math.sin(angle)
    dot = kz
    z = (
        kx * dot * (1 - cosine) + ky * sine,
        ky * dot * (1 - cosine) - kx * sine,
        cosine + kz * dot * (1 - cosine),
    )
    return origin, z


def prepare(request):
    """Imprint the port sketches on the part and say which faces each port covers.

    Called by the meta-wrapper for every analysis, after the request has been
    decoded and before the implementation sees it. Changes the request in
    place: 'request["wrapped"]' becomes the part with every sketch imprinted on
    it, and every boundary record gains 'faces' and 'area' and loses its
    sketch. Returns warnings: a sketch that lies on no surface of the part is a
    condition that does nothing, which is worth saying every time.

    A failure to imprint is a warning too, and leaves the part as it was: the
    records then carry no 'faces', which is what an implementation written
    before any of this already copes with.
    """
    boundary = request.get("boundary")
    shape = request.get("wrapped")
    if not boundary or shape is None:
        return []

    sketches = {}
    for index, record in enumerate(boundary):
        faces = _sketch_faces(record.pop(SKETCH_KEY, None))
        if faces:
            sketches[index] = faces

    warnings = []
    extent = extent_of(shape) or 1.0
    # A sketch placed by the same numbers the part was built from lands on its
    # face to the last digit, so this only has to absorb arithmetic -- and must
    # stay well under any feature of the part, or two faces would merge.
    fuzzy = extent * 1e-6
    tolerance = extent * 1e-5

    if sketches:
        try:
            shape = _split(shape, [face for faces in sketches.values() for face in faces], fuzzy)
            request["wrapped"] = shape
        except Exception as e:
            return ["The port sketches could not be imprinted on the part, so no port covers a surface: %s" % e]

    faces = faces_of(shape)
    areas = [_area_and_centroid(face)[0] for face in faces]
    for index, record in enumerate(boundary):
        if index in sketches:
            covered = [k for k, face in enumerate(faces) if _covered(face, areas[k], sketches[index], fuzzy)]
            if not covered:
                warnings.append(
                    "The sketch of port '%s' lies on no surface of the part, so the condition on it does "
                    "nothing: check that the port's frame puts the sketch on a face, Z out of it"
                    % (record.get("port") or record.get("interface_label") or "?")
                )
        else:
            covered = _faces_at(faces, record.get("location"), tolerance)
        record["faces"] = [fingerprint(faces[k], k) for k in covered]
        record["area"] = sum(areas[k] for k in covered)
    return warnings


# --------------------------------------------------------------------------- #
# The mesh                                                                    #
# --------------------------------------------------------------------------- #


def gmsh_module():
    """The gmsh module, or raise saying both ways to get one.

    gmsh publishes wheels for macOS, Windows and x86_64 Linux, and none for
    64-bit ARM Linux and no source distribution -- so pip cannot supply it
    there however the requirements are written. An implementation's image can:
    Debian builds 'python3-gmsh' for arm64.
    """
    try:
        import gmsh
    except ImportError as e:
        raise ToolMissing(
            "gmsh is not importable here. Run with a container runtime available, which gets the image "
            "the implementation names in 'dockerImage:' -- or install it where this runs: pip can, except on "
            "64-bit ARM Linux, where 'python3-gmsh' or conda-forge can. Underlying error: %s" % e
        ) from e
    return gmsh


class Mesh:
    """A volume mesh of the part, with its boundary named.

    Attributes:
        node_tags: gmsh's node numbers, in the order 'coordinates' holds.
        coordinates: an (n, 3) array of node positions, in metres unless
            'mesh()' was asked otherwise.
        volumes: a list of (gmsh element type, element tags, node tags per
            element) -- tetrahedra, first or second order.
        groups: physical group name -> the boundary triangles in it, as node
            tags (corner nodes only).
        extent: the largest dimension of the part, in the mesh's units.
        unmatched: surfaces gmsh made that no face of the part accounts for.
    """

    def __init__(self, node_tags, coordinates, volumes, groups, extent, unmatched):
        """Hold what 'mesh()' read back from gmsh."""
        self.node_tags = node_tags
        self.coordinates = coordinates
        self.volumes = volumes
        self.groups = groups
        self.extent = extent
        self.unmatched = unmatched

    @property
    def element_count(self):
        """How many volume elements there are, of every type."""
        return sum(len(tags) for _type, tags, _nodes in self.volumes)


def _write_brep(shape, path):
    from OCP.BRepTools import BRepTools

    if not BRepTools.Write_s(shape, path):
        raise ToolFailed("the part could not be written out for meshing")


def mesh(request, groups, size=0.05, order=1, rest=None, scale=1.0 / MM_PER_M, files=(), volume="body"):
    """Mesh the part with gmsh, its boundary named after 'groups'.

    Args:
        request: what the implementation was handed; 'request["wrapped"]' is
            meshed, after 'prepare()' imprinted it.
        groups: physical group name -> the face indices in it, as a boundary
            record's 'faces' give them. A face may be in more than one group.
        size: the largest element, as a fraction of the part's largest
            dimension. A fraction rather than a length so that one setting
            means "coarse" for a washer and for a girder alike.
        order: 1 for linear tetrahedra, 2 for quadratic.
        rest: the name of a group holding every surface no other group claimed,
            or None for no such group.
        scale: what a millimetre becomes. Metres by default, because the
            material constants every solver is handed are SI.
        files: paths to write the mesh to, in whatever format the extension
            names to gmsh: '.msh' is written as version 2.2 ASCII, which every
            reader here accepts, '.med' and '.unv' as gmsh writes them.
        volume: the name of the physical group holding the solid.

    Returns:
        A 'Mesh'.
    """
    import numpy as np

    gmsh = gmsh_module()
    shape = request.get("wrapped")
    if shape is None:
        raise ToolFailed("No shape was handed to the analysis")

    faces = faces_of(shape)
    prints = [fingerprint(face, index) for index, face in enumerate(faces)]
    extent = extent_of(shape) * scale

    with tempfile.TemporaryDirectory() as work:
        brep = os.path.join(work, "part.brep")
        _write_brep(shape, brep)

        gmsh.initialize(interruptible=False)
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.option.setNumber("General.Verbosity", 1)
            gmsh.option.setNumber("Geometry.OCCScaling", scale)
            gmsh.model.add("partcad")
            gmsh.model.occ.importShapes(brep)
            gmsh.model.occ.synchronize()

            index_of, unmatched = _match_surfaces(gmsh, prints, scale)
            claimed = set()
            for name, indices in groups.items():
                wanted = set(indices)
                tags = [tag for tag, index in index_of.items() if index in wanted]
                if tags:
                    gmsh.model.addPhysicalGroup(2, tags, name=name)
                    claimed.update(tags)
            if rest:
                leftover = [tag for _dim, tag in gmsh.model.getEntities(2) if tag not in claimed]
                if leftover:
                    gmsh.model.addPhysicalGroup(2, leftover, name=rest)
            solids = [tag for _dim, tag in gmsh.model.getEntities(3)]
            if not solids:
                raise ToolFailed("The part has no volume to mesh: an analysis needs a solid")
            gmsh.model.addPhysicalGroup(3, solids, name=volume)

            target = extent * float(size)
            gmsh.option.setNumber("Mesh.MeshSizeMax", target)
            gmsh.option.setNumber("Mesh.MeshSizeMin", target / 3.0)
            gmsh.option.setNumber("Mesh.ElementOrder", int(order))
            gmsh.model.mesh.generate(3)

            for path in files:
                if path.endswith(".msh"):
                    gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
                    gmsh.option.setNumber("Mesh.Binary", 0)
                # Only what a physical group names, so the solver sees exactly
                # the boundaries that were asked for and the solid, and no
                # stray lower-dimensional elements of its own.
                gmsh.option.setNumber("Mesh.SaveAll", 0)
                gmsh.write(path)

            node_tags, raw, _ = gmsh.model.mesh.getNodes()
            coordinates = np.asarray(raw, dtype=float).reshape(-1, 3)
            types, tags, nodes = gmsh.model.mesh.getElements(3)
            volumes = []
            for element_type, element_tags, element_nodes in zip(types, tags, nodes):
                per = len(element_nodes) // max(len(element_tags), 1)
                volumes.append((int(element_type), list(element_tags), np.asarray(element_nodes).reshape(-1, per)))

            named = {}
            for dim, group in gmsh.model.getPhysicalGroups(2):
                name = gmsh.model.getPhysicalName(dim, group)
                triangles = []
                for entity in gmsh.model.getEntitiesForPhysicalGroup(dim, group):
                    entity_types, _entity_tags, entity_nodes = gmsh.model.mesh.getElements(dim, entity)
                    for entity_type, flat in zip(entity_types, entity_nodes):
                        per = gmsh.model.mesh.getElementProperties(entity_type)[3]
                        corners = np.asarray(flat).reshape(-1, per)[:, :3]
                        triangles.extend(corners.tolist())
                named[name] = triangles
        finally:
            gmsh.finalize()

    return Mesh(np.asarray(node_tags), coordinates, volumes, named, extent, unmatched)


def _match_surfaces(gmsh, prints, scale):
    """gmsh's surface tags, each to the index of the face of the part it is.

    By centroid and area rather than by order: gmsh numbers what it imports in
    the order it meets it, which is the order 'faces_of()' uses for every shape
    seen so far -- and "so far" is not a promise. A centroid and an area is.
    """
    matched = {}
    unmatched = []
    for _dim, tag in gmsh.model.getEntities(2):
        centre = gmsh.model.occ.getCenterOfMass(2, tag)
        area = gmsh.model.occ.getMass(2, tag)
        best, best_distance = None, None
        for candidate in prints:
            if abs(candidate["area"] * scale * scale - area) > max(area, 1e-30) * 1e-3:
                continue
            distance = math.dist([value * scale for value in candidate["centroid"]], centre)
            if best_distance is None or distance < best_distance:
                best, best_distance = candidate["index"], distance
        if best is None:
            unmatched.append(tag)
        else:
            matched[tag] = best
    return matched, unmatched


def match_points(points, targets, tolerance):
    """For each of 'points', the index of the target at the same place, or None.

    A solver writes its result on its own copy of the mesh, renumbered and often
    printed to fewer digits than gmsh wrote it with; position is what the two
    copies still share. Matched within 'tolerance' rather than by rounding, since
    two values a rounding boundary apart round differently however close they
    are: each point looks in its own cell of a grid that size and in the 26
    around it.
    """
    size = float(tolerance)
    cells = {}
    for index, target in enumerate(targets):
        key = tuple(int(math.floor(float(value) / size)) for value in target)
        cells.setdefault(key, []).append(index)
    found = []
    for point in points:
        key = tuple(int(math.floor(float(value) / size)) for value in point)
        best, best_distance = None, None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for index in cells.get((key[0] + dx, key[1] + dy, key[2] + dz), ()):
                        distance = math.dist(point, targets[index])
                        if distance <= size and (best_distance is None or distance < best_distance):
                            best, best_distance = index, distance
        found.append(best)
    return found


def flow_through(mesh, group, velocity_at, outward=None):
    """The volume flow out through one boundary group: velocity integrated over its triangles.

    'velocity_at' gives the velocity at a node of 'mesh', by its index in
    'mesh.coordinates', or None where the solver said nothing. Each triangle's
    normal is turned to agree with 'outward' when one is given -- the outward
    normal of the port's face, which a planar face carries -- and is taken as
    gmsh oriented it otherwise.
    """
    index = {int(tag): k for k, tag in enumerate(mesh.node_tags)}
    total = 0.0
    for triangle in mesh.groups.get(group, []):
        corners = [index[int(tag)] for tag in triangle]
        a, b, c = (mesh.coordinates[k] for k in corners)
        u = [b[i] - a[i] for i in range(3)]
        v = [c[i] - a[i] for i in range(3)]
        area = [
            0.5 * (u[1] * v[2] - u[2] * v[1]),
            0.5 * (u[2] * v[0] - u[0] * v[2]),
            0.5 * (u[0] * v[1] - u[1] * v[0]),
        ]
        if outward is not None and sum(area[i] * outward[i] for i in range(3)) < 0:
            area = [-component for component in area]
        speeds = [velocity_at(k) for k in corners]
        if any(speed is None for speed in speeds):
            continue
        mean = [sum(speed[i] for speed in speeds) / 3.0 for i in range(3)]
        total += sum(mean[i] * area[i] for i in range(3))
    return total


def outward_normal(record):
    """The outward normal of the first planar face a port covers, or None."""
    for face in record.get("faces") or []:
        if face.get("normal"):
            return face["normal"]
    return None


def condition_groups(request, key, prefix=None):
    """A group per boundary record that carries 'key', for 'mesh()'.

    Named '<prefix><n>' in the order the records come, so an implementation
    can find each record's group again by its position; returns
    '(groups, records, empty)', where 'empty' are the records whose port
    covers no face -- a condition that will do nothing, which the
    implementation reports as a finding.
    """
    groups, records, empty = {}, [], []
    for record in request.get("boundary") or []:
        value = record.get(key)
        # Absent is None or False -- except for 'load', which a stress or a
        # flow record has always carried as 0.0 when nothing pulls on it. A
        # temperature of 0 is a temperature, so only 'load' reads zero as none.
        if value is None or value is False or (key == "load" and not value):
            continue
        indices = [face["index"] for face in record.get("faces") or []]
        if not indices:
            empty.append(record)
            continue
        groups["%s%d" % (prefix or key, len(records))] = indices
        records.append(record)
    return groups, records, empty


# --------------------------------------------------------------------------- #
# The answer                                                                  #
# --------------------------------------------------------------------------- #

# Cool to hot, the same five stops CalculiX's results have always been drawn in,
# so that a stress drawn by one implementation and by another look alike.
_RAMP = (
    (0.23, 0.30, 0.75),
    (0.30, 0.65, 0.90),
    (0.45, 0.85, 0.55),
    (0.98, 0.85, 0.25),
    (0.90, 0.35, 0.15),
)

# The faces of each volume cell kind, by corner, outward. Enough for every cell a
# solver here writes back: tetrahedra, hexahedra, prisms and pyramids, first or
# second order -- a second-order cell lists its corners first.
_CELL_FACES = {
    4: ((0, 2, 1), (0, 1, 3), (1, 2, 3), (0, 3, 2)),
    8: ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)),
    6: ((0, 2, 1), (3, 4, 5), (0, 1, 4, 3), (1, 2, 5, 4), (2, 0, 3, 5)),
    5: ((0, 3, 2, 1), (0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)),
}


def outer_triangles(cells, corners):
    """The outward faces of a volume mesh, as triangles of point indices.

    A volume mesh has no surface of its own: what is drawn is the set of faces
    exactly one cell owns. 'cells' is an iterable of point-index lists and
    'corners' how many of each list are corners (4 for a tetrahedron of either
    order, 8 for a hexahedron, 6 for a prism, 5 for a pyramid).
    """
    owners = {}
    for cell in cells:
        for face in _CELL_FACES[corners]:
            points = tuple(int(cell[k]) for k in face)
            key = tuple(sorted(points))
            owners[key] = None if key in owners else points
    triangles = []
    for points in owners.values():
        if points is None:
            continue
        for k in range(1, len(points) - 1):
            triangles.append((points[0], points[k], points[k + 1]))
    return triangles


def colours_for(values, low=None, high=None):
    """A colour per value, low to high, as a list of (r, g, b, a) bytes."""
    values = [float(value) for value in values]
    finite = [value for value in values if math.isfinite(value)]
    low = min(finite, default=0.0) if low is None else float(low)
    high = max(finite, default=0.0) if high is None else float(high)
    span = high - low
    colours = []
    for value in values:
        # A uniform field is one colour rather than a divide by zero: it is
        # what an unloaded part looks like, and a legitimate answer.
        fraction = 0.0 if not math.isfinite(value) or span <= 0 else min(max((value - low) / span, 0.0), 1.0)
        position = fraction * (len(_RAMP) - 1)
        lower = int(math.floor(position))
        upper = min(lower + 1, len(_RAMP) - 1)
        weight = position - lower
        rgb = [_RAMP[lower][c] * (1 - weight) + _RAMP[upper][c] * weight for c in range(3)]
        colours.append(tuple(int(round(min(max(c, 0.0), 1.0) * 255)) for c in rgb) + (255,))
    return colours


def write_glb(path, points, triangles, values, low=None, high=None):
    """A surface coloured by a field, as a binary glTF.

    'points' are in metres and Z-up, as every solver here writes them; glTF is
    Y-up, so they are turned here -- (x, y, z) -> (x, z, -y), the rotation
    PartCAD's glTF exporter bakes into everything else the Viewer shows.
    Written by hand rather than through a library: a glTF of one coloured mesh
    is three arrays and a page of JSON, and a dependency for it is one more
    thing a sandbox has to install on every platform.
    """
    positions = [(float(x), float(z), -float(y)) for x, y, z in points]
    colours = colours_for(values, low, high)
    indices = [int(k) for triangle in triangles for k in triangle]
    if not positions or not indices:
        raise ToolFailed("There is no surface to draw the result on")

    position_bytes = b"".join(struct.pack("<3f", *p) for p in positions)
    colour_bytes = b"".join(struct.pack("<4B", *c) for c in colours)
    index_bytes = struct.pack("<%dI" % len(indices), *indices)

    def padded(blob):
        return blob + b"\0" * (-len(blob) % 4)

    chunks = [padded(position_bytes), padded(colour_bytes), padded(index_bytes)]
    offsets = [0, len(chunks[0]), len(chunks[0]) + len(chunks[1])]
    binary = b"".join(chunks)
    lows = [min(p[c] for p in positions) for c in range(3)]
    highs = [max(p[c] for p in positions) for c in range(3)]
    document = {
        "asset": {"version": "2.0", "generator": "PartCAD"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "COLOR_0": 1}, "indices": 2, "mode": 4}]}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": offsets[0], "byteLength": len(position_bytes), "target": 34962},
            {"buffer": 0, "byteOffset": offsets[1], "byteLength": len(colour_bytes), "target": 34962},
            {"buffer": 0, "byteOffset": offsets[2], "byteLength": len(index_bytes), "target": 34963},
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": len(positions),
                "type": "VEC3",
                "min": lows,
                "max": highs,
            },
            {"bufferView": 1, "componentType": 5121, "normalized": True, "count": len(colours), "type": "VEC4"},
            {"bufferView": 2, "componentType": 5125, "count": len(indices), "type": "SCALAR"},
        ],
    }
    header = json.dumps(document, separators=(",", ":")).encode()
    header += b" " * (-len(header) % 4)
    total = 12 + 8 + len(header) + 8 + len(binary)
    with open(path, "wb") as f:
        f.write(struct.pack("<4sII", b"glTF", 2, total))
        f.write(struct.pack("<I4s", len(header), b"JSON"))
        f.write(header)
        f.write(struct.pack("<I4s", len(binary), b"BIN\0"))
        f.write(binary)
