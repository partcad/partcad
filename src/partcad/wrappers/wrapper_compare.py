#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within the python sandbox environment (python runtime)
# to measure how far the surface of one model is from the surface of another --
# what 'pc compare --surface-distance' reports. The core never holds a live OCP
# object, so both models arrive here as BREP (already placed, an assembly as the
# compound of its parts) and only numbers go back.
#
# What is measured is one-sided, from the *reference* to the *current* model:
#
#   1. Points are chosen on the reference's surface, no two of them closer than
#      the spacing asked for. Every vertex is one, whatever the spacing: a
#      vertex is where a feature starts or ends, and it is measured however close
#      it is to another. Then the edges are walked, and a point of an edge is
#      taken where it is at least the spacing away from every point already
#      taken. Then the faces, the same way.
#
#   2. At each point the reference's surface has a normal, pointing out of the
#      material, and the distance measured is how far along that line the
#      current model's surface is: positive where the current model stands
#      outside the reference, negative where it stands inside. A vertex or a
#      point of an edge lies on several faces and has a normal on each; it is
#      measured along each one, and the nearest surface found answers for it --
#      so a box that grew by a millimetre is a millimetre away at its corners
#      too, and not the 1.7 mm along the diagonal an averaged normal would say.
#
#      A point with nothing of the current model anywhere along its normal --
#      the rim of a reference that is larger than the current model, whose
#      normals pass beside it -- is measured to the nearest point of the current
#      model instead, signed the same way (by the side of the reference's
#      surface that point is on), and counted apart: 'nearest' rather than
#      'normal'. Only a point with no current model to be near at all is
#      missed.
#
# Choosing the points is the half that has to be fast, because a part a hundred
# millimetres across at one point a millimetre is tens of thousands of them.
# Each candidate is accepted or not by asking whether any point already taken is
# closer than the spacing, and a hash of cubes one spacing wide answers that by
# looking at the 27 cubes around it -- constant time per candidate, so choosing
# the points is linear in the number of candidates. The candidates are walked
# finer than the spacing (an edge at a quarter of it, a face at half), so every
# place on the surface ends up within about one spacing of a point measured:
# nothing larger than that can hide between two of them.
#
# A face's candidates come from its triangulation, but are evaluated on the face
# itself: each is a point of a triangle in the face's (u, v) parameters, and the
# surface is evaluated there, so the point and its normal are the exact
# surface's and the triangulation only decides where to look. That is also what
# keeps a trimmed face's points inside its boundary without classifying each
# one against it. A face that is a mesh and nothing else -- an STL, an SDF part
# -- has no surface to evaluate, and its triangles are the surface.
#
# The current model is asked along each line by OCCT's own line/face
# intersector for the faces that have a surface. A face that is only a mesh has
# none, and is asked by a ray cast through a grid of its triangles here.

import heapq
import math
import os
import sys

# Pinned before the CAD imports below, which load OCP and with it VTK's
# bundled copy of expat: see the note in ocp_serialize.
import pyexpat  # noqa: F401

from OCP.Bnd import Bnd_Box
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Curve2d
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepGProp import BRepGProp, BRepGProp_Face
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.GCPnts import GCPnts_AbscissaPoint, GCPnts_UniformAbscissa
from OCP.gp import gp_Dir, gp_Lin, gp_Pnt, gp_Vec
from OCP.GProp import GProp_GProps
from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_REVERSED, TopAbs_VERTEX
from OCP.TopExp import TopExp
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS
from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape, TopTools_IndexedMapOfShape

sys.path.append(os.path.dirname(__file__))
import ocp_serialize  # noqa: E402
import wrapper_common  # noqa: E402

# What this wrapper reports for what it produces (see 'partcad.code_version'):
# raise it with any change that changes that, and everything it produced
# before is produced again.
CACHE_VERSION = 1

# How finely an edge and a face are walked for candidates, as fractions of the
# spacing. Finer covers the surface more evenly and costs candidates; these
# leave nothing uncovered wider than about one and a quarter spacings.
EDGE_STEP = 0.25
FACE_STEP = 0.5

# How many points one measurement may take. The surface's area over the
# spacing squared is how many it would take, and a measurement asked for more
# is refused, saying which spacing would do, rather than left to run for an
# hour: every point is one intersection in Python.
MAX_POINTS = 200_000

# How many of the points furthest from the current model are reported, by
# default, with where they are.
WORST = 10

# How far apart two surfaces may be and still be one surface, in millimetres:
# OCCT's own Precision::Confusion. Below this a distance is noise.
CONFUSION = 1e-7

KIND_VERTEX = "vertex"
KIND_EDGE = "edge"
KIND_FACE = "face"

# How a point's distance was found: along a normal of the reference, or -- for
# a point no normal of which meets the current model -- to its nearest point.
HOW_NORMAL = "normal"
HOW_NEAREST = "nearest"


# ---------------------------------------------------------------------------
# Points no two of which are closer than the spacing.


class Spaced:
    """The points taken so far, hashed by the cube of side 'spacing' each is in.

    Two points closer than the spacing are in the same cube or in neighbouring
    ones, so whether a candidate is far enough from all of them is a look at
    the 27 cubes around it -- however many points there are.
    """

    def __init__(self, spacing):
        self.spacing = float(spacing)
        # A hair under the spacing, so that two candidates exactly one spacing
        # apart -- which a lattice walked at a fraction of it produces all the
        # time -- are far enough apart in spite of the last bit of the arithmetic.
        self.limit = self.spacing * self.spacing * (1.0 - 1e-9)
        self.cells = {}
        self.count = 0

    def _cell(self, point):
        s = self.spacing
        return (math.floor(point[0] / s), math.floor(point[1] / s), math.floor(point[2] / s))

    def far(self, point):
        """Whether 'point' is at least the spacing away from every point taken."""
        ci, cj, ck = self._cell(point)
        x, y, z = point
        limit = self.limit
        cells = self.cells
        for i in (ci - 1, ci, ci + 1):
            for j in (cj - 1, cj, cj + 1):
                for k in (ck - 1, ck, ck + 1):
                    for q in cells.get((i, j, k), ()):
                        dx, dy, dz = x - q[0], y - q[1], z - q[2]
                        if dx * dx + dy * dy + dz * dz < limit:
                            return False
        return True

    def add(self, point):
        self.cells.setdefault(self._cell(point), []).append(point)
        self.count += 1


# ---------------------------------------------------------------------------
# Small vector arithmetic on tuples: a point here is a plain (x, y, z).


def _xyz(pnt):
    return (pnt.X(), pnt.Y(), pnt.Z())


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a):
    return math.sqrt(_dot(a, a))


def _unit(a):
    """'a' scaled to unit length, or None for a vector too short to point anywhere."""
    length = _norm(a)
    if length <= 1e-300:
        return None
    return (a[0] / length, a[1] / length, a[2] / length)


def _faces(shape):
    """Every face of 'shape', each once."""
    found = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, found)
    return [TopoDS.Face_s(found.FindKey(i)) for i in range(1, found.Extent() + 1)]


def _geometric(face):
    """Whether a face has a surface, as opposed to being a mesh and nothing else."""
    return BRep_Tool.IsGeometric_s(face)


def _with_faces(shape, what):
    """(own, adjacent faces) for every vertex or every edge of 'shape'."""
    found = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, what, TopAbs_FACE, found)
    result = []
    for i in range(1, found.Extent() + 1):
        faces = []
        for face in found.FindFromIndex(i):
            face = TopoDS.Face_s(face)
            # A seam edge is in its face twice, once in each direction.
            if not any(face.IsSame(other) for other in faces):
                faces.append(face)
        result.append((found.FindKey(i), faces))
    return result


def _normal(face, u, v):
    """(point, outward unit normal or None) of a face with a surface, at (u, v).

    'BRepGProp_Face' orients the normal the way the face is oriented in its
    shell, which for a closed solid is out of the material: what the volume of
    a solid is integrated with, so what 'outward' already means everywhere.
    """
    point, normal = gp_Pnt(), gp_Vec()
    BRepGProp_Face(face).Normal(u, v, point, normal)
    return _xyz(point), _unit((normal.X(), normal.Y(), normal.Z()))


# ---------------------------------------------------------------------------
# Choosing the points.


class Sample:
    """One point of the reference to measure from, and the normals to measure along."""

    __slots__ = ("point", "normals", "kind")

    def __init__(self, point, normals, kind):
        self.point = point
        self.normals = normals
        self.kind = kind


def area(shape):
    """The area of every face of 'shape', a surface with or without a mesh."""
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, props, True, False)
    total = props.Mass()
    # A face that is only a mesh has no surface for the exact integration, and
    # is measured by its triangles.
    for face in _faces(shape):
        if not _geometric(face):
            total += sum(_triangle_area(*corners) for corners, _normal in _triangles(face))
    return total


def _triangle_area(a, b, c):
    return 0.5 * _norm(_cross(_sub(b, a), _sub(c, a)))


def _triangles(face):
    """(corners, outward unit normal or None) of each triangle of a face's mesh, in place.

    A reversed face's triangles are turned over, so that the corners go round
    the outward normal: the mesh is stored the way the face's surface is
    oriented, and the face may use it the other way round.
    """
    location = TopLoc_Location()
    mesh = BRep_Tool.Triangulation_s(face, location)
    if mesh is None:
        return []
    trsf = location.Transformation()
    nodes = [_xyz(mesh.Node(i).Transformed(trsf)) for i in range(1, mesh.NbNodes() + 1)]
    reversed_ = face.Orientation() == TopAbs_REVERSED
    result = []
    for k in range(1, mesh.NbTriangles() + 1):
        n1, n2, n3 = mesh.Triangle(k).Get()
        if reversed_:
            n2, n3 = n3, n2
        a, b, c = nodes[n1 - 1], nodes[n2 - 1], nodes[n3 - 1]
        result.append(((a, b, c), _unit(_cross(_sub(b, a), _sub(c, a)))))
    return result


def _mesh(shape, spacing):
    """Give every face with a surface a triangulation to walk for candidates.

    Only as fine as the spacing needs: a face's points are evaluated on the face
    itself, so the triangles only say where to look. A face that already has a
    finer one keeps it.
    """
    faces = [face for face in _faces(shape) if _geometric(face)]
    if faces:
        BRepMesh_IncrementalMesh(ocp_serialize.compound_of(faces), max(spacing * 0.5, 1e-3), False, 0.35, True)


def _vertex_samples(shape, spaced):
    """A sample per vertex, with the normal of each face it is on: every vertex is taken, whatever the spacing."""
    samples = []
    for vertex, faces in _with_faces(shape, TopAbs_VERTEX):
        vertex = TopoDS.Vertex_s(vertex)
        point = _xyz(BRep_Tool.Pnt_s(vertex))
        normals = []
        for face in faces:
            if not _geometric(face):
                continue
            try:
                uv = BRep_Tool.Parameters_s(vertex, face)
                _at, normal = _normal(face, uv.X(), uv.Y())
            except Exception:  # pylint: disable=broad-except
                continue
            if normal is not None:
                normals.append(normal)
        # Every vertex, however close to another: where a feature starts and
        # ends is measured whatever the spacing is.
        spaced.add(point)
        samples.append(Sample(point, normals, KIND_VERTEX))
    return samples


def _edge_parameters(curve, length, step):
    """Parameters along an edge at equal lengths no longer than 'step', ends excluded."""
    count = max(2, int(math.ceil(length / step)) + 1)
    first, last = curve.FirstParameter(), curve.LastParameter()
    try:
        uniform = GCPnts_UniformAbscissa(curve, count)
        if uniform.IsDone() and uniform.NbPoints() >= 2:
            return [uniform.Parameter(i) for i in range(2, uniform.NbPoints())]
    except Exception:  # pylint: disable=broad-except
        pass
    # A curve the uniform abscissa cannot walk is walked by its parameter.
    return [first + (last - first) * i / (count - 1) for i in range(1, count - 1)]


def _edge_samples(shape, spacing, spaced, budget):
    """Samples along the edges, each the spacing from every point taken, with the normals of the faces it bounds."""
    samples = []
    step = spacing * EDGE_STEP
    for edge, faces in _with_faces(shape, TopAbs_EDGE):
        edge = TopoDS.Edge_s(edge)
        if BRep_Tool.Degenerated_s(edge):
            continue
        try:
            curve = BRepAdaptor_Curve(edge)
            length = GCPnts_AbscissaPoint.Length_s(curve)
        except Exception:  # pylint: disable=broad-except
            continue
        if not length > spacing:
            # Nothing of it is a spacing away from both of its vertices.
            continue
        pcurves = []
        for face in faces:
            if not _geometric(face):
                continue
            try:
                pcurves.append((face, BRepAdaptor_Curve2d(edge, face)))
            except Exception:  # pylint: disable=broad-except
                continue
        for parameter in _edge_parameters(curve, length, step):
            point = _xyz(curve.Value(parameter))
            if not spaced.far(point):
                continue
            normals = []
            for face, pcurve in pcurves:
                try:
                    uv = pcurve.Value(parameter)
                    _at, normal = _normal(face, uv.X(), uv.Y())
                except Exception:  # pylint: disable=broad-except
                    continue
                if normal is not None:
                    normals.append(normal)
            spaced.add(point)
            samples.append(Sample(point, normals, KIND_EDGE))
            budget.spend()
    return samples


def _face_samples(shape, spacing, spaced, budget):
    """Samples over the faces, each at least the spacing from every point taken.

    A lattice over each triangle of a face's mesh, evaluated on the face's own surface where it has one.
    """
    samples = []
    step = spacing * FACE_STEP
    for face in _faces(shape):
        geometric = _geometric(face)
        location = TopLoc_Location()
        mesh = BRep_Tool.Triangulation_s(face, location)
        if mesh is None:
            continue
        uv_nodes = None
        if geometric and mesh.HasUVNodes():
            uv_nodes = [(mesh.UVNode(i).X(), mesh.UVNode(i).Y()) for i in range(1, mesh.NbNodes() + 1)]
            surface = BRepGProp_Face(face)
            at, vector = gp_Pnt(), gp_Vec()
        trsf = location.Transformation()
        nodes = [_xyz(mesh.Node(i).Transformed(trsf)) for i in range(1, mesh.NbNodes() + 1)]
        reversed_ = face.Orientation() == TopAbs_REVERSED
        for k in range(1, mesh.NbTriangles() + 1):
            n1, n2, n3 = mesh.Triangle(k).Get()
            if reversed_:
                n2, n3 = n3, n2
            a, b, c = nodes[n1 - 1], nodes[n2 - 1], nodes[n3 - 1]
            flat = _unit(_cross(_sub(b, a), _sub(c, a)))
            longest = max(_norm(_sub(b, a)), _norm(_sub(c, b)), _norm(_sub(a, c)))
            divisions = max(1, int(math.ceil(longest / step)))
            if uv_nodes is not None:
                ua, ub, uc = uv_nodes[n1 - 1], uv_nodes[n2 - 1], uv_nodes[n3 - 1]
            # A lattice over the triangle, row by row: (i, j) is the point
            # a + i/n (b - a) + j/n (c - a), every one of them inside it.
            for i in range(divisions + 1):
                for j in range(divisions + 1 - i):
                    wb, wc = i / divisions, j / divisions
                    wa = 1.0 - wb - wc
                    normal = flat
                    if uv_nodes is not None:
                        u = wa * ua[0] + wb * ub[0] + wc * uc[0]
                        v = wa * ua[1] + wb * ub[1] + wc * uc[1]
                        surface.Normal(u, v, at, vector)
                        point = (at.X(), at.Y(), at.Z())
                        if not spaced.far(point):
                            continue
                        # At a singular point of the surface -- the apex of a
                        # cone, the pole of a sphere -- it has no normal, and
                        # the triangle's stands in for it.
                        normal = _unit((vector.X(), vector.Y(), vector.Z())) or flat
                    else:
                        point = (
                            wa * a[0] + wb * b[0] + wc * c[0],
                            wa * a[1] + wb * b[1] + wc * c[1],
                            wa * a[2] + wb * b[2] + wc * c[2],
                        )
                        if not spaced.far(point):
                            continue
                    spaced.add(point)
                    samples.append(Sample(point, [normal] if normal is not None else [], KIND_FACE))
                    budget.spend()
    return samples


class Budget:
    """How many more points may be taken, and the refusal once there are none."""

    def __init__(self, limit, spacing):
        self.left = limit
        self.limit = limit
        self.spacing = spacing

    def spend(self):
        """Count one more point, and refuse once more than the limit would be needed."""
        self.left -= 1
        if self.left < 0:
            raise ValueError(
                "More than %d points %s mm apart are needed to cover the reference: measure them further apart"
                % (self.limit, _number(self.spacing))
            )


def _number(value):
    return "%g" % value


def sample(shape, spacing, limit=MAX_POINTS):
    """The points of 'shape' to measure from: every vertex, then the edges, then the faces.

    No two points of an edge or a face are closer than 'spacing' to each other
    or to a vertex; the vertices are all taken, however close. Refused, saying
    which spacing would do, when covering the surface would take more than
    'limit' points.
    """
    if not spacing > 0:
        raise ValueError("The spacing of the points measured has to be a positive length, not %r" % (spacing,))
    surface = area(shape)
    if not surface > 0:
        raise ValueError("The reference has no surface to measure from")
    estimate = surface / (spacing * spacing)
    if estimate > limit:
        raise ValueError(
            "Covering %s mm^2 of the reference at points %s mm apart takes about %d points, more than %d: "
            "measure them at least %s mm apart"
            % (_number(surface), _number(spacing), estimate, limit, _number(math.sqrt(surface / limit) * 1.01))
        )
    _mesh(shape, spacing)
    spaced = Spaced(spacing)
    budget = Budget(limit, spacing)
    samples = _vertex_samples(shape, spaced)
    samples += _edge_samples(shape, spacing, spaced, budget)
    samples += _face_samples(shape, spacing, spaced, budget)
    return samples, surface


# ---------------------------------------------------------------------------
# Asking the current model along a line.


def _box(*shapes):
    """The bounding box of all of 'shapes' together, faces that are only a mesh included."""
    box = Bnd_Box()
    for shape in shapes:
        # 'useTriangulation': a face that is only a mesh has an empty box
        # otherwise.
        BRepBndLib.Add_s(shape, box, True)
    return box


class Triangles:
    """The faces of a model that are meshes and nothing else, for a ray to be cast at.

    A grid of cubes over their box, each listing the triangles whose box
    reaches into it, walked from cube to cube along the ray (Amanatides and
    Woo): a ray looks only at the triangles in the cubes it passes through, and
    stops at the first cube that cannot hold anything nearer than what it has
    already hit.
    """

    def __init__(self, triangles):
        """Hash each triangle into every cube of the grid its bounding box reaches."""
        self.triangles = triangles
        self.cells = {}
        if not triangles:
            return
        xs = [p[0] for corners in triangles for p in corners]
        ys = [p[1] for corners in triangles for p in corners]
        zs = [p[2] for corners in triangles for p in corners]
        self.lo = (min(xs), min(ys), min(zs))
        hi = (max(xs), max(ys), max(zs))
        longest = max(hi[0] - self.lo[0], hi[1] - self.lo[1], hi[2] - self.lo[2]) or 1.0
        # About two cubes per triangle across, along the longest side.
        per_side = max(1, int(round(2.0 * len(triangles) ** (1.0 / 3.0))))
        self.size = longest / per_side
        self.counts = tuple(max(1, int(math.floor((hi[a] - self.lo[a]) / self.size)) + 1) for a in range(3))
        for index, corners in enumerate(triangles):
            lo = [self._index(min(p[a] for p in corners), a) for a in range(3)]
            hi_ = [self._index(max(p[a] for p in corners), a) for a in range(3)]
            for i in range(lo[0], hi_[0] + 1):
                for j in range(lo[1], hi_[1] + 1):
                    for k in range(lo[2], hi_[2] + 1):
                        self.cells.setdefault((i, j, k), []).append(index)

    def _index(self, value, axis):
        return min(self.counts[axis] - 1, max(0, int(math.floor((value - self.lo[axis]) / self.size))))

    def cast(self, origin, direction, reach):
        """The least t in [-CONFUSION, reach] at which origin + t * direction meets a triangle, or None."""
        if not self.cells:
            return None
        # Where the ray is inside the grid's box.
        t_in, t_out = -CONFUSION, reach
        for a in range(3):
            lo = self.lo[a]
            hi = lo + self.counts[a] * self.size
            if abs(direction[a]) < 1e-300:
                if origin[a] < lo - CONFUSION or origin[a] > hi + CONFUSION:
                    return None
                continue
            t1 = (lo - origin[a]) / direction[a]
            t2 = (hi - origin[a]) / direction[a]
            if t1 > t2:
                t1, t2 = t2, t1
            t_in, t_out = max(t_in, t1), min(t_out, t2)
            if t_in > t_out:
                return None
        start = [origin[a] + direction[a] * max(t_in, 0.0) for a in range(3)]
        cell = [self._index(start[a], a) for a in range(3)]
        step, t_next, t_delta = [0, 0, 0], [math.inf] * 3, [math.inf] * 3
        for a in range(3):
            if direction[a] > 0:
                step[a] = 1
                boundary = self.lo[a] + (cell[a] + 1) * self.size
                t_next[a] = (boundary - origin[a]) / direction[a]
                t_delta[a] = self.size / direction[a]
            elif direction[a] < 0:
                step[a] = -1
                boundary = self.lo[a] + cell[a] * self.size
                t_next[a] = (boundary - origin[a]) / direction[a]
                t_delta[a] = -self.size / direction[a]
        best = None
        tested = set()
        while True:
            for index in self.cells.get(tuple(cell), ()):
                if index in tested:
                    continue
                tested.add(index)
                t = _ray_triangle(origin, direction, self.triangles[index])
                if t is not None and -CONFUSION <= t <= reach and (best is None or t < best):
                    best = t
            leaving = min(t_next)
            if best is not None and best <= leaving:
                return best
            if leaving > t_out:
                return best
            axis = t_next.index(leaving)
            cell[axis] += step[axis]
            if not 0 <= cell[axis] < self.counts[axis]:
                return best
            t_next[axis] += t_delta[axis]

    def nearest(self, point):
        """(distance, the nearest point of any triangle) to 'point', or None when there are none.

        The cubes are visited in rings around the one the point is in, and the
        search stops once the nearest point found so far is nearer than anything
        outside the rings visited could be.
        """
        if not self.cells:
            return None
        centre = [self._index(point[a], a) for a in range(3)]
        best, best_at = None, None
        tested = set()
        ring = 0
        while True:
            lo = [centre[a] - ring for a in range(3)]
            hi = [centre[a] + ring for a in range(3)]
            for i in range(max(lo[0], 0), min(hi[0], self.counts[0] - 1) + 1):
                for j in range(max(lo[1], 0), min(hi[1], self.counts[1] - 1) + 1):
                    for k in range(max(lo[2], 0), min(hi[2], self.counts[2] - 1) + 1):
                        if ring and max(abs(i - centre[0]), abs(j - centre[1]), abs(k - centre[2])) != ring:
                            continue
                        for index in self.cells.get((i, j, k), ()):
                            if index in tested:
                                continue
                            tested.add(index)
                            at = _closest_on_triangle(point, self.triangles[index])
                            distance = _norm(_sub(at, point))
                            if best is None or distance < best:
                                best, best_at = distance, at
            # How near something outside the rings visited could be: the
            # nearest side of them that is not the side of the grid itself.
            bound = math.inf
            for a in range(3):
                if lo[a] > 0:
                    bound = min(bound, point[a] - (self.lo[a] + lo[a] * self.size))
                if hi[a] < self.counts[a] - 1:
                    bound = min(bound, self.lo[a] + (hi[a] + 1) * self.size - point[a])
            if bound == math.inf or (best is not None and best <= max(bound, 0.0)):
                return (best, best_at) if best is not None else None
            ring += 1


def _closest_on_triangle(p, corners):
    """The point of a triangle nearest 'p' (Ericson, Real-Time Collision Detection, 5.1.5)."""
    a, b, c = corners
    ab, ac, ap = _sub(b, a), _sub(c, a), _sub(p, a)
    d1, d2 = _dot(ab, ap), _dot(ac, ap)
    if d1 <= 0 and d2 <= 0:
        return a
    bp = _sub(p, b)
    d3, d4 = _dot(ab, bp), _dot(ac, bp)
    if d3 >= 0 and d4 <= d3:
        return b
    vc = d1 * d4 - d3 * d2
    if vc <= 0 and d1 >= 0 and d3 <= 0:
        v = d1 / (d1 - d3)
        return (a[0] + v * ab[0], a[1] + v * ab[1], a[2] + v * ab[2])
    cp = _sub(p, c)
    d5, d6 = _dot(ab, cp), _dot(ac, cp)
    if d6 >= 0 and d5 <= d6:
        return c
    vb = d5 * d2 - d1 * d6
    if vb <= 0 and d2 >= 0 and d6 <= 0:
        w = d2 / (d2 - d6)
        return (a[0] + w * ac[0], a[1] + w * ac[1], a[2] + w * ac[2])
    va = d3 * d6 - d5 * d4
    if va <= 0 and (d4 - d3) >= 0 and (d5 - d6) >= 0:
        w = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        return (b[0] + w * (c[0] - b[0]), b[1] + w * (c[1] - b[1]), b[2] + w * (c[2] - b[2]))
    denominator = va + vb + vc
    if denominator == 0:
        return a
    v, w = vb / denominator, vc / denominator
    return (a[0] + ab[0] * v + ac[0] * w, a[1] + ab[1] * v + ac[1] * w, a[2] + ab[2] * v + ac[2] * w)


def _ray_triangle(origin, direction, corners):
    """Where origin + t * direction meets a triangle, as t, or None (Moller and Trumbore)."""
    a, b, c = corners
    e1, e2 = _sub(b, a), _sub(c, a)
    p = _cross(direction, e2)
    det = _dot(e1, p)
    scale = _norm(e1) * _norm(e2)
    if abs(det) <= 1e-12 * scale:
        return None
    inv = 1.0 / det
    s = _sub(origin, a)
    u = _dot(s, p) * inv
    if u < -1e-9 or u > 1.0 + 1e-9:
        return None
    q = _cross(s, e1)
    v = _dot(direction, q) * inv
    if v < -1e-9 or u + v > 1.0 + 1e-9:
        return None
    return _dot(e2, q) * inv


class Target:
    """The current model, as something a line can be asked where it meets."""

    def __init__(self, shape, reach):
        """Faces with a surface for OCCT's intersector, meshes for the grid; 'reach' is how far to look along a line."""
        self.reach = reach
        geometric, meshes = [], []
        for face in _faces(shape):
            if _geometric(face):
                geometric.append(face)
            else:
                meshes.extend(corners for corners, _normal in _triangles(face))
        self.exact = None
        self.distance = None
        if geometric:
            # The faces, not the solids they bound: a point inside a solid is
            # at no distance from the solid, and at some distance from its
            # surface, which is what is asked.
            faces = ocp_serialize.compound_of(geometric)
            self.exact = IntCurvesFace_ShapeIntersector()
            self.exact.Load(faces, CONFUSION)
            self.distance = BRepExtrema_DistShapeShape()
            self.distance.LoadS2(faces)
        self.mesh = Triangles(meshes)
        if self.exact is None and not meshes:
            raise ValueError("The current model has no surface to measure to")

    def nearest(self, point):
        """(distance, the nearest point of the current model's surface) to 'point', or None."""
        best = None
        if self.distance is not None:
            self.distance.LoadS1(BRepBuilderAPI_MakeVertex(gp_Pnt(*point)).Vertex())
            if self.distance.Perform() and self.distance.IsDone() and self.distance.NbSolution() > 0:
                best = (self.distance.Value(), _xyz(self.distance.PointOnShape2(1)))
        found = self.mesh.nearest(point)
        if found is not None and (best is None or found[0] < best[0]):
            best = found
        return best

    def along(self, point, normal):
        """The t of the current model's surface nearest 'point' along 'normal', or None."""
        best = None
        if self.exact is not None:
            self.exact.Perform(gp_Lin(gp_Pnt(*point), gp_Dir(*normal)), -self.reach, self.reach)
            if self.exact.IsDone():
                for i in range(1, self.exact.NbPnt() + 1):
                    t = self.exact.WParameter(i)
                    if best is None or abs(t) < abs(best):
                        best = t
        if self.mesh.cells:
            forward = self.mesh.cast(point, normal, self.reach)
            backward = self.mesh.cast(point, (-normal[0], -normal[1], -normal[2]), self.reach)
            for t in (forward, None if backward is None else -backward):
                if t is not None and (best is None or abs(t) < abs(best)):
                    best = t
        return best


# ---------------------------------------------------------------------------
# The measurement.


def _rounded(vector):
    """A vector as a list of plain floats, for the JSON answer."""
    return [float(value) for value in vector]


def _percentile(ordered, fraction):
    """The nearest-rank percentile of an ascending list."""
    if not ordered:
        return None
    rank = max(1, int(math.ceil(fraction * len(ordered))))
    return ordered[rank - 1]


def surface_distance(reference, current, spacing, allowance=None, worst=WORST, limit=MAX_POINTS):
    """How far the current model's surface is from the reference's, point by point.

    'allowance', when given, is how far apart the two may be anywhere -- the
    tolerances of both models, which the caller adds up -- and the answer says
    how many points are further apart than that. 'worst' is how many of the
    furthest points are listed, with where they are.
    """
    samples, surface = sample(reference, spacing, limit)
    box = _box(reference, current)
    if box.IsVoid():
        raise ValueError("Neither model has a surface to measure")
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    # Nothing of either model is further than this from any point of the other.
    reach = math.sqrt((xmax - xmin) ** 2 + (ymax - ymin) ** 2 + (zmax - zmin) ** 2) + 1.0
    target = Target(current, reach)

    measured = []
    missed = []
    counts = {KIND_VERTEX: 0, KIND_EDGE: 0, KIND_FACE: 0}
    nearest = 0
    for item in samples:
        counts[item.kind] += 1
        best, along, how = None, None, HOW_NORMAL
        for normal in item.normals:
            t = target.along(item.point, normal)
            if t is not None and (best is None or abs(t) < abs(best)):
                best, along = t, normal
        if best is None:
            best, along = _nearest(target, item)
            how = HOW_NEAREST
            if best is not None:
                nearest += 1
        if best is None:
            missed.append(item)
        else:
            if abs(best) < CONFUSION:
                best = 0.0
            measured.append((best, along, item, how))

    result = {
        "spacing": float(spacing),
        "area": float(surface),
        "reach": float(reach),
        "points": counts,
        "measured": len(measured),
        "nearest": nearest,
        "missed": len(missed),
        "distance": None,
        "allowance": None if allowance is None else float(allowance),
        "beyond": None,
        "worst": [],
        "missedAt": [{"at": _rounded(item.point), "on": item.kind} for item in missed[: max(0, int(worst))]],
    }
    if measured:
        values = [entry[0] for entry in measured]
        magnitudes = sorted(abs(d) for d in values)
        count = len(values)
        result["distance"] = {
            "min": min(values),
            "max": max(values),
            "mean": sum(values) / count,
            "meanAbs": sum(magnitudes) / count,
            "rms": math.sqrt(sum(d * d for d in values) / count),
            "maxAbs": magnitudes[-1],
            "p50": _percentile(magnitudes, 0.50),
            "p95": _percentile(magnitudes, 0.95),
            "p99": _percentile(magnitudes, 0.99),
        }
        if allowance is not None:
            result["beyond"] = sum(1 for d in magnitudes if d > allowance + CONFUSION)
        furthest = heapq.nlargest(max(0, int(worst)), measured, key=lambda entry: abs(entry[0]))
        result["worst"] = [
            {
                "at": _rounded(item.point),
                "normal": None if normal is None else _rounded(normal),
                "distance": d,
                "on": item.kind,
                "how": how,
            }
            for d, normal, item, how in furthest
        ]
    return result


def _nearest(target, item):
    """(signed distance, the normal it is signed by) from a point to the nearest of the current model.

    Signed as a distance along a normal is: positive when the nearest point is
    on the outside of the reference's surface. A vertex or a point of an edge is
    on several faces, and the side is read off their normals together.
    """
    found = target.nearest(item.point)
    if found is None:
        return None, None
    distance, at = found
    normal = _unit(tuple(sum(n[a] for n in item.normals) for a in range(3))) if item.normals else None
    if normal is not None and _dot(_sub(at, item.point), normal) < 0:
        distance = -distance
    return distance, normal


def process(request):
    """Answer one request; 'surface' is the only operation there is."""
    operation = request.get("operation")
    if operation == "surface":
        return surface_distance(
            request["reference"],
            request["current"],
            float(request["spacing"]),
            request.get("allowance"),
            request.get("worst", WORST),
            request.get("limit", MAX_POINTS),
        )
    raise ValueError("Unknown compare operation: %r" % (operation,))


if __name__ == "__main__":
    # argv[1] carries the operation name for readability in process listings and
    # logs; the authoritative copy travels in the request.
    _, request = wrapper_common.handle_input()
    try:
        result = process(request)
        model = {"success": True, "exception": None, "result": result}
    except Exception as e:
        wrapper_common.handle_exception(e)
        model = {"success": False, "exception": str(e), "result": None}
    wrapper_common.handle_output(model)
