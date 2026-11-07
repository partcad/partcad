#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The 'usd' part type: what an OpenUSD stage shows, as a part.

A part's file is a USD stage - a '.usd', '.usda' or '.usdc' layer, or a '.usdz'
package - and what is built of it is the meshes it shows. It is read one of two
ways, by the part's 'reader' parameter:

  * 'usd-core' (the default): with Pixar's own USD library, which the part
    type's 'pythonRequirements' install into the sandbox. The stage is composed
    as USD composes it, at the time asked for, of the purpose asked for, through
    native instancing and point instancers, skinning a character to the time
    asked for;
  * 'cadmpeg': with cadmpeg, which reads OpenUSD from 0.6.8 on
    ('cadmpeg_tool.USD_VERSION'). It composes the stage itself and hands over
    its meshes, placed, in its own CADIR form ('read_cadmpeg'). Best effort, and
    said to be: it reads the stage's static values only, what a render shows
    only, and no point instancer; a cube or a sphere it reads as a B-rep solid,
    which this reader leaves out and counts.

Either way the result is the same: triangles in millimetres (by the stage's
'metersPerUnit') with Z up (a 'Y' up stage is turned onto Z, as PartCAD's other
importers do), each in the look it is drawn in - its material's name, its
colour, its roughness and how metallic it is, and what it is made of where the
source says, face by face (see 'usd_look'; cadmpeg gives a name and a colour).
They are stated to PartCAD under the 'usd' convention, by which a package's
colour, material or finish claims a USD name ('ids: {usd: <name>}'). Of the stage, what a
reference to it would bring in is built - its default prim - unless 'prim'
names another, and '/' is the whole of it.

What it builds is a surface, and not necessarily a solid: USD describes what a
renderer draws, and that is meshes, which need not close and usually do not.
So the type does not declare 'requireSolid': a part that is no solid is built,
and PartCAD says so. Up to FACES_UP_TO triangles, each triangle is a face, and
two that share an edge share it - drawn as lines, written to STEP, made the
solid it bounds where it closes; past that, the triangles of each colour are
one face that is only a triangulation - fast at any size, drawn shaded and
written as a mesh ('surface' chooses). Each mesh is a shell of its own, so a
mesh that closes is a solid of its own.

A subdivision surface is read as its control mesh, and with 'usd-core' a cube,
a sphere, a cylinder, a cone or a capsule as a coarse mesh of it; curves,
points and volumes are not surfaces and are left out, and counted. Unless a
'time' is asked for, the stage is read as a viewer opens it: at its start time
code, or at its earliest sample.

Run by 'wrappers/wrapper_part_type.py' with 'request["path"]' set to the file
and 'request["cache_dir"]' to where cadmpeg is kept. Importable, for its tests:
nothing runs unless PartCAD runs it.
"""

import json
import math
import os
import struct
import sys
import tempfile

# Siblings are imported by bare name, and the sandbox sets PYTHONSAFEPATH.
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Raise with any change to what this produces (see 'partcad.code_version'),
# which includes every change of the cadmpeg release 'cadmpeg_tool' reads
# OpenUSD with ('USD_VERSION'), of the usd-core the part type installs and of
# 'usd_look', which says what each face looks like. 2: each face's look -
# colour, finish, material - stated under the 'usd' convention, face by face. 3:
# the files the stage was read from are reported, so a part is built again,
# and so keyed on them, rather than read back from before they were.
CACHE_VERSION = 3

# How a stage is read: see the module's docstring.
READERS = ("usd-core", "cadmpeg")

# The most triangles a part is built of unless its 'maxTriangles' says
# otherwise: past that, a part asks for a 'prim' under the stage's root.
DEFAULT_MAX_TRIANGLES = 5_000_000

PURPOSES = {
    "render": ("default", "render"),
    "proxy": ("default", "proxy"),
    "all": ("default", "render", "proxy", "guide"),
}


class TooManyTriangles(Exception):
    pass


def _srgb(channel):
    """A linear colour channel (0 to 1) as an sRGB one (0 to 255)."""
    channel = max(0.0, min(1.0, float(channel)))
    value = channel * 12.92 if channel <= 0.0031308 else 1.055 * channel ** (1 / 2.4) - 0.055
    return int(round(value * 255))


def _time_code(Usd, stage, value):
    """(time code, whether it was asked for): a number as it is, else what the stage opens at.

    That is its start time code when it says one, and otherwise its earliest
    sample: an attribute that has only samples - a point instancer's
    positions, often - has no value at USD's 'default' time at all.
    """
    value = str(value if value is not None else "default").strip().lower()
    if value in ("", "default"):
        if stage.HasAuthoredTimeCodeRange():
            return Usd.TimeCode(stage.GetStartTimeCode()), False
        return Usd.TimeCode.EarliestTime(), False
    try:
        return Usd.TimeCode(float(value)), True
    except ValueError:
        raise ValueError("'time' is a number or 'default', not '%s'" % value)


class Model:
    """What a stage is built of: its pieces, the looks they are drawn in, and what was left out.

    A piece is '(vertices n x 3, triangles m x 3, looks m)': a mesh, every
    placement of it, its vertices in millimetres and each triangle's look an
    index into 'looks' (see 'usd_look'). 'dropped' is {prim type: how many},
    of what is not a surface.
    """

    def __init__(self, pieces, looks, dropped, files=()):
        self.pieces = pieces
        self.looks = looks
        self.dropped = dropped
        # Every file on disk the stage was read from: its layers, and the
        # images, MaterialX documents and MDL modules its looks came from -
        # and the ones it names that are not there. None where that could not
        # be told (see 'stage_files').
        self.files = None if files is None else sorted(set(files))

    def triangle_count(self):
        return sum(len(triangles) for _, triangles, _ in self.pieces)


class _Collector:
    """The triangles of a stage, a piece per mesh, each triangle in the look it is drawn in."""

    def __init__(self, stage, time, purposes, max_triangles):
        import usd_look
        from pxr import UsdGeom

        self.stage = stage
        self.time = time
        self.purposes = purposes
        self.max_triangles = max_triangles
        self.xforms = UsdGeom.XformCache(time)
        scale = UsdGeom.GetStageMetersPerUnit(stage) * 1000.0
        # Row vectors, as Gf has them: a point is p * M. Y up turns onto Z:
        # (x, y, z) -> (x, -z, y), scaled to millimetres.
        if UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.y:
            self.out = [[scale, 0, 0, 0], [0, 0, scale, 0], [0, -scale, 0, 0], [0, 0, 0, 1]]
        else:
            self.out = [[scale, 0, 0, 0], [0, scale, 0, 0], [0, 0, scale, 0], [0, 0, 0, 1]]
        self.looks = usd_look.Looks(stage, time)
        self.pieces = []  # (vertices, triangles, each triangle's look arrays): a piece per mesh
        self.meshes = {}  # a mesh's (points, triangles, faces, corners, face count), read once
        self.mesh_looks = {}  # a mesh's triangles' looks, read once however often it is placed
        self.triangles = 0
        self.dropped = {}

    # -- the walk --
    #
    # A prim is placed once, by its own transform, or many times over - once
    # for every instance a point instancer makes of the prototype it is in.
    # 'placements' is then those instances' matrices, stacked, and 'inverse'
    # undoes the prototype root's own transform, which an instance's matrix
    # holds already. Every matrix is a numpy 4 x 4, applied to row vectors as
    # Gf's are (p @ M).

    def matrix(self, prim):
        import numpy

        return numpy.asarray(self.xforms.GetLocalToWorldTransform(prim), dtype=numpy.float64).reshape(4, 4)

    def collect(self, start, inverse=None, placements=None):
        import numpy
        from pxr import Usd, UsdGeom

        predicate = Usd.TraverseInstanceProxies(Usd.PrimDefaultPredicate)
        walk = iter(Usd.PrimRange(start, predicate))
        for prim in walk:
            imageable = UsdGeom.Imageable(prim)
            if imageable:
                if imageable.ComputeVisibility(self.time) == UsdGeom.Tokens.invisible:
                    walk.PruneChildren()
                    continue
                if imageable.ComputePurpose() not in self.purposes:
                    walk.PruneChildren()
                    continue
            if not (prim.IsA(UsdGeom.PointInstancer) or prim.IsA(UsdGeom.Gprim)):
                continue
            local = self.matrix(prim)
            if inverse is not None:
                local = local @ inverse
            worlds = local[None] if placements is None else numpy.matmul(local, placements)
            if prim.IsA(UsdGeom.PointInstancer):
                self.instancer(UsdGeom.PointInstancer(prim), worlds)
                walk.PruneChildren()
            elif prim.IsA(UsdGeom.Mesh):
                self.mesh(prim, worlds)
            else:
                self.implicit(prim, worlds)

    def instancer(self, instancer, worlds):
        import numpy

        targets = instancer.GetPrototypesRel().GetTargets()
        indices = numpy.asarray(instancer.GetProtoIndicesAttr().Get(self.time) or [], dtype=numpy.int64)
        matrices = instancer.ComputeInstanceTransformsAtTime(self.time, self.time)
        if matrices is None or len(matrices) == 0 or len(indices) != len(matrices):
            return
        matrices = numpy.asarray(matrices, dtype=numpy.float64).reshape(-1, 4, 4)
        for index, target in enumerate(targets):
            prototype = self.stage.GetPrimAtPath(target)
            chosen = matrices[indices == index]
            if not prototype or len(chosen) == 0:
                continue
            # Every instance of this prototype, under every placement of the
            # instancer itself: m_j @ world_k.
            placements = numpy.matmul(chosen[None, :, :, :], worlds[:, None, :, :]).reshape(-1, 4, 4)
            self.collect(prototype, numpy.linalg.inv(self.matrix(prototype)), placements)

    # -- what a prim is made of --

    def mesh(self, prim, worlds):
        import numpy
        from pxr import UsdGeom

        path = prim.GetPath()
        if path not in self.meshes:
            mesh = UsdGeom.Mesh(prim)
            points = mesh.GetPointsAttr().Get(self.time)
            counts = mesh.GetFaceVertexCountsAttr().Get(self.time)
            indices = mesh.GetFaceVertexIndicesAttr().Get(self.time)
            made = None
            if points and counts and indices:
                counts = numpy.asarray(counts, dtype=numpy.int64)
                indices = numpy.asarray(indices, dtype=numpy.int64)
                if counts.sum() != len(indices) or indices.max() >= len(points):
                    self._drop("Mesh (malformed)")
                else:
                    triangles, corners, faces = fan_corners(
                        counts, indices, mesh.GetHoleIndicesAttr().Get(self.time) or []
                    )
                    if mesh.GetOrientationAttr().Get(self.time) == UsdGeom.Tokens.leftHanded:
                        triangles, corners = triangles[:, [0, 2, 1]], corners[:, [0, 2, 1]]
                    made = (numpy.asarray(points, dtype=numpy.float64), triangles, faces, corners, len(counts))
            self.meshes[path] = made
        if self.meshes[path] is not None:
            points, triangles, faces, corners, face_count = self.meshes[path]
            self.add(prim, points, triangles, worlds, self._looks(prim, triangles, faces, corners, face_count))

    def implicit(self, prim, worlds):
        import numpy
        from pxr import UsdGeom

        made = implicit_mesh(prim, self.time, UsdGeom)
        if made is None:
            self._drop(prim.GetTypeName())
            return
        points, triangles = made
        faces = numpy.zeros(len(triangles), dtype=numpy.int64)
        self.add(prim, points, triangles, worlds, self._looks(prim, triangles, faces, triangles, 1))

    def _looks(self, prim, triangles, faces, corners, face_count):
        """Each triangle's look arrays (see 'usd_look.Looks.faces'), read once per prim."""
        path = prim.GetPath()
        if path not in self.mesh_looks:
            self.mesh_looks[path] = self.looks.faces(prim, faces, corners, triangles, face_count)
        return self.mesh_looks[path]

    def add(self, prim, points, triangles, worlds, looks):
        """'triangles' of 'points', placed by every matrix of 'worlds' (k x 4 x 4), in 'looks' (one per triangle)."""
        import numpy

        if len(triangles) == 0:
            return
        self.triangles += len(triangles) * len(worlds)
        if self.triangles > self.max_triangles:
            raise TooManyTriangles(
                "more than %d triangles; build a 'prim' under the stage's root, or raise 'maxTriangles'"
                % self.max_triangles
            )
        transforms = numpy.matmul(worlds, numpy.asarray(self.out, dtype=numpy.float64))
        homogeneous = numpy.hstack([points, numpy.ones((len(points), 1))])
        placed = numpy.matmul(homogeneous[None], transforms)[:, :, :3]
        # A mirroring placement turns the triangles inside out; wind them back.
        mirrored = numpy.linalg.det(worlds[:, :3, :3]) < 0
        windings = numpy.where(mirrored[:, None, None], triangles[None][:, :, [0, 2, 1]], triangles[None])
        offsets = (numpy.arange(len(worlds)) * len(points))[:, None, None]
        count = len(worlds)
        tiled = tuple(numpy.tile(a, (count,) + (1,) * (a.ndim - 1)) for a in looks)
        self.pieces.append((placed.reshape(-1, 3), (windings + offsets).reshape(-1, 3), tiled))

    def model(self):
        """The Model of what was collected: the looks settled (see 'usd_look.settle')."""
        import numpy
        import usd_look

        if not self.pieces:
            return Model([], [], self.dropped)
        arrays = [numpy.concatenate([piece[2][i] for piece in self.pieces]) for i in range(6)]
        looks, ids = usd_look.settle(*arrays, self.looks.names, self.looks.materials)
        pieces, start = [], 0
        for vertices, triangles, _ in self.pieces:
            pieces.append((vertices, triangles, ids[start : start + len(triangles)]))
            start += len(triangles)
        return Model(pieces, looks, self.dropped)

    def _drop(self, what):
        self.dropped[what] = self.dropped.get(what, 0) + 1


def fan(counts, indices, holes=()):
    """The triangles of polygons of 'counts' vertices, 'indices' into the points: each polygon a fan."""
    return fan_corners(counts, indices, holes)[0]


def fan_corners(counts, indices, holes=()):
    """'(triangles, corners, faces)' of polygons of 'counts' vertices, 'indices' into the points: each a fan.

    'triangles' are indices into the points; 'corners' the same three corners
    as indices into 'indices' (what a face-varying primvar is indexed by); and
    'faces' the polygon each triangle is of.
    """
    import numpy

    counts = numpy.asarray(counts, dtype=numpy.int64)
    indices = numpy.asarray(indices, dtype=numpy.int64)
    starts = numpy.cumsum(counts) - counts
    per_face = numpy.maximum(counts - 2, 0)
    if len(holes):
        per_face = per_face.copy()
        per_face[numpy.asarray(holes, dtype=numpy.int64)] = 0
    total = int(per_face.sum())
    if total == 0:
        empty = numpy.zeros((0, 3), dtype=numpy.int64)
        return empty, empty, numpy.zeros(0, dtype=numpy.int64)
    face = numpy.repeat(numpy.arange(len(counts)), per_face)
    k = numpy.arange(total) - numpy.repeat(numpy.cumsum(per_face) - per_face, per_face) + 1
    first = starts[face]
    corners = numpy.stack([first, first + k, first + k + 1], axis=1)
    return indices[corners], corners, face


def implicit_mesh(prim, time, UsdGeom, segments=32):
    """(points, triangles) of a cube, sphere, cylinder, cone or capsule, in its own space; None for anything else."""
    import numpy

    kind = prim.GetTypeName()
    if kind == "Cube":
        half = float(UsdGeom.Cube(prim).GetSizeAttr().Get(time) or 2.0) / 2
        points = numpy.array([[x, y, z] for x in (-half, half) for y in (-half, half) for z in (-half, half)])
        quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
        triangles = numpy.array([t for a, b, c, d in quads for t in ((a, b, c), (a, c, d))])
        return points, triangles
    if kind == "Sphere":
        radius = float(UsdGeom.Sphere(prim).GetRadiusAttr().Get(time) or 1.0)
        return _revolve([(0, -radius)] + [
            (radius * math.sin(math.pi * i / 16), -radius * math.cos(math.pi * i / 16)) for i in range(1, 16)
        ] + [(0, radius)], segments, "Z")  # fmt: skip
    if kind in ("Cylinder", "Cone", "Capsule"):
        schema = getattr(UsdGeom, kind)(prim)
        radius = float(schema.GetRadiusAttr().Get(time) or 1.0)
        height = float(schema.GetHeightAttr().Get(time) or 2.0)
        axis = schema.GetAxisAttr().Get(time) or "Z"
        half = height / 2
        if kind == "Cylinder":
            profile = [(0, -half), (radius, -half), (radius, half), (0, half)]
        elif kind == "Cone":
            profile = [(0, -half), (radius, -half), (0, half)]
        else:
            cap = [(radius * math.cos(math.pi / 2 * i / 8), radius * math.sin(math.pi / 2 * i / 8)) for i in range(9)]
            profile = [(0, -half - radius)] + [(r, -half - z) for r, z in reversed(cap[:-1])]
            profile += [(r, half + z) for r, z in cap[:-1]] + [(0, half + radius)]
        return _revolve(profile, segments, axis)
    return None


def _revolve(profile, segments, axis):
    """A surface of revolution of [(radius, height)], bottom to top, about 'axis', as (points, triangles).

    A radius of 0 is a pole: one point rather than a ring. Wound outwards.
    """
    import numpy

    points, rings = [], []
    for radius, height in profile:
        if radius == 0:
            rings.append([len(points)])
            points.append((0.0, 0.0, height))
            continue
        ring = []
        for i in range(segments):
            angle = 2 * math.pi * i / segments
            ring.append(len(points))
            points.append((radius * math.cos(angle), radius * math.sin(angle), height))
        rings.append(ring)
    triangles = []
    for lower, upper in zip(rings, rings[1:]):
        for i in range(segments):
            a, b = lower[i % len(lower)], lower[(i + 1) % len(lower)]
            c, d = upper[i % len(upper)], upper[(i + 1) % len(upper)]
            if len(lower) > 1:
                triangles.append((a, b, d))
            if len(upper) > 1:
                triangles.append((a, d, c))
    points = numpy.array(points, dtype=numpy.float64)
    if axis == "X":
        points = points[:, [2, 0, 1]]
    elif axis == "Y":
        points = points[:, [1, 2, 0]]
    return points, numpy.array(triangles, dtype=numpy.int64)


def read(path, prim="", purpose="render", time="default", max_triangles=DEFAULT_MAX_TRIANGLES):
    """The Model of the stage at 'path': its meshes, the look each triangle is in, and what was left out."""
    from pxr import Gf, Usd, UsdSkel

    if purpose not in PURPOSES:
        raise ValueError("'purpose' is one of %s, not '%s'" % (", ".join(PURPOSES), purpose))
    stage = Usd.Stage.Open(path, Usd.Stage.LoadAll)
    if stage is None:
        raise ValueError("%s is not a USD stage" % os.path.basename(path))
    code, asked = _time_code(Usd, stage, time)
    if asked and any(p.IsA(UsdSkel.Root) for p in stage.Traverse()):
        # Skinning is applied where the mesh is read, so it is baked into the
        # session layer at that one time, and the stage is read as baked.
        stage.SetEditTarget(stage.GetSessionLayer())
        UsdSkel.BakeSkinning(stage.Traverse(), Gf.Interval(code.GetValue(), code.GetValue()))
    # What a reference to the asset brings in, unless a prim is asked for: its
    # default prim. What is beside that - a thumbnail's studio, a camera rig -
    # is the file's, not the asset's. '/' is the whole stage.
    if prim in ("", None):
        start = stage.GetDefaultPrim() or stage.GetPseudoRoot()
    elif prim == "/":
        start = stage.GetPseudoRoot()
    else:
        start = stage.GetPrimAtPath(prim)
    if not start or not start.IsValid():
        raise ValueError("the stage has no prim '%s'" % prim)
    collector = _Collector(stage, code, PURPOSES[purpose], max_triangles)
    collector.collect(start)
    model = collector.model()
    # What USD's own walk of the stage finds - what it names that is not there
    # included - and what composing it and reading its looks opened: the walk
    # does not see a texture an MDL preset or a MaterialX document names.
    walked = stage_files(path)
    if walked is None:
        model.files = None
    else:
        read = [layer.realPath for layer in stage.GetUsedLayers()] + sorted(collector.looks.read)
        model.files = sorted(set(walked) | {_on_disk(p) for p in read if p})
    return model


def _on_disk(resolved):
    """The file on disk 'resolved' is in: the package, for a file in one ('a.usdz[b.png]')."""
    return resolved.split("[", 1)[0] if resolved.endswith("]") and "[" in resolved else resolved


def stage_files(path):
    """Every file the stage at 'path' names, by USD's own walk of it; None where it cannot be walked.

    Its layers, the assets they name, and the ones they name that are not
    there - where they would be, which is what a part is then keyed on as
    missing, so that one appearing builds it again. None says that what the
    part is read from is not known, and then the part is not cached at all
    (see 'partcad.discovered_dependencies').
    """
    try:
        from pxr import Sdf, UsdUtils

        layers, assets, unresolved = UsdUtils.ComputeAllDependencies(Sdf.AssetPath(os.path.abspath(path)))
    except Exception as e:  # noqa: BLE001 - no usd-core, or a stage it cannot walk: nothing is known
        print("usd: could not list the files %s is read from, so it is not cached: %s" % (os.path.basename(path), e),
              file=sys.stderr)  # fmt: skip
        return None
    named = [layer.realPath for layer in layers] + list(assets) + list(unresolved)
    return sorted({_on_disk(p) for p in named if p})


def reported(files, path):
    """'files' as the part reports them: relative to the directory of 'path' where under it, and not 'path' itself."""
    base = os.path.dirname(os.path.abspath(path))
    own = os.path.normcase(os.path.abspath(path))
    said = []
    for file in files:
        file = os.path.abspath(file)
        if os.path.normcase(file) == own:
            continue
        try:
            under = os.path.commonpath([os.path.normcase(file), os.path.normcase(base)]) == os.path.normcase(base)
        except ValueError:  # another drive
            under = False
        said.append(os.path.relpath(file, base).replace(os.sep, "/") if under else file)
    return said


# -- cadmpeg ---------------------------------------------------------------------
#
# cadmpeg composes a stage itself and writes what it found as CADIR, its JSON
# form of a model: a tree of occurrences, each placed by a 3 x 4 affine matrix
# (rotation and scale, then a translation in millimetres) relative to its
# parent, each an instance of a product definition, whose bodies are meshes
# ('tessellations': vertices in millimetres and triangles) or B-rep solids. Its
# STEP writer writes the B-rep and not the meshes, which is why CADIR is what is
# read here and not STEP.

# The most of CADIR this reads, in MB: about 500 bytes of JSON go to a triangle,
# and parsing it costs about three times that in memory. Past it, 'usd-core'.
CADIR_MAX_MB = 2048

# What a millimetre is in each of the units CADIR states its lengths in.
_MILLIMETRES = {"millimeter": 1.0, "meter": 1000.0, "centimeter": 10.0, "inch": 25.4, "foot": 304.8}


def _point(fields):
    """A CADIR point - {"x": .., "y": .., "z": ..} - as a tuple, as it is parsed; anything else as it is."""
    if len(fields) == 3 and "x" in fields and "y" in fields and "z" in fields:
        return (fields["x"], fields["y"], fields["z"])
    return fields


def read_cadmpeg(path, cache_dir, prim="", purpose="render", time="default", max_triangles=DEFAULT_MAX_TRIANGLES,
                 cadmpeg=None):  # fmt: skip
    """'read', by cadmpeg: the Model of the stage at 'path'."""
    import cadmpeg_step
    import cadmpeg_tool

    if purpose != "render":
        raise ValueError("cadmpeg reads what a render shows, so 'purpose' is 'render' with the 'cadmpeg' reader")
    if str(time if time is not None else "default").strip().lower() not in ("", "default"):
        raise ValueError("cadmpeg reads a stage's static values only; 'time' needs the 'usd-core' reader")
    if cadmpeg is None:
        cadmpeg = cadmpeg_tool.executable(cache_dir, cadmpeg_tool.USD_VERSION)
    with tempfile.TemporaryDirectory(prefix="partcad-usd-") as scratch:
        written = os.path.join(scratch, "stage.json")
        cadmpeg_step.run([cadmpeg, "convert", path, "-o", written])
        size = os.path.getsize(written)
        if size > CADIR_MAX_MB * (1 << 20):
            raise TooManyTriangles(
                "cadmpeg describes it in %d MB, more than the %d MB the 'cadmpeg' reader reads; read it with "
                "'usd-core'" % (size >> 20, CADIR_MAX_MB)
            )
        with open(written, encoding="utf-8") as f:
            model = json.load(f, object_hook=_point)
    read = cadir_model(model, prim, max_triangles, package=path)
    read.files = stage_files(path)
    return read


def cadir_model(model, prim="", max_triangles=DEFAULT_MAX_TRIANGLES, package=None):
    """The Model of a stage as cadmpeg describes it in CADIR, read as 'read' reads one.

    A face's look is its appearance's: its name, and its base colour - or,
    where a texture gives that and the texture is in 'package' (the USDZ read),
    the texture's mean colour. cadmpeg says nothing of a finish.
    """
    import numpy

    ir = model["model"]
    attributes = (model.get("source") or {}).get("attributes") or {}
    unit = _MILLIMETRES.get(str((model.get("units") or {}).get("length", "millimeter")).lower())
    if unit is None:
        raise ValueError("cadmpeg states its lengths in %s, which this does not read" % model["units"]["length"])
    # Column vectors, as CADIR's matrices are written: Y up turns onto Z,
    # (x, y, z) -> (x, -z, y).
    out = numpy.eye(4) * unit
    out[3, 3] = 1.0
    if str(attributes.get("up_axis", "Y")).upper() == "Y":
        out = numpy.array([[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [0, 0, 0, 1]], dtype=numpy.float64) @ out
    if prim in ("", None):
        root = "/" + attributes["default_prim"] if attributes.get("default_prim") else "/"
    else:
        root = prim
    definitions = {d["id"]: d for d in ir.get("product_definitions") or []}
    bodies = {b["id"]: b for b in ir.get("bodies") or []}
    meshes = {}
    for tessellation in ir.get("tessellations") or []:
        meshes.setdefault(tessellation["body"], []).append(tessellation)
    appearances = {a["id"]: a for a in ir.get("appearances") or []}
    looks, look_ids = [], {}

    def look_of(look):
        if look not in look_ids:
            look_ids[look] = len(looks)
            looks.append(look)
        return look_ids[look]

    bound = {}  # (kind, id) -> look
    for binding in ir.get("appearance_bindings") or []:
        target = binding.get("target") or {}
        appearance = appearances.get(binding.get("appearance"))
        if not isinstance(appearance, dict):
            continue
        rgba = _appearance_rgba(appearance, package)
        name = str(appearance.get("name") or "appearance")
        found = target.get("id")
        if target.get("kind") == "triangle_group" and isinstance(found, dict):
            bound[("group", found.get("tessellation"), found.get("group"))] = (name, rgba, None, None, None)
        elif target.get("kind") in ("tessellation", "body"):
            bound[(target["kind"], found)] = (name, rgba, None, None, None)
    occurrences = ir.get("occurrences") or []
    children = {}
    for occurrence in occurrences:
        parent = occurrence.get("parent") or {}
        children.setdefault(parent.get("occurrence") if parent.get("kind") == "occurrence" else None, []).append(
            occurrence
        )
    pieces, dropped, total = [], {}, [0]
    if not any(_under(o.get("native_ref", ""), root) for o in occurrences):
        raise ValueError("the stage has no prim '%s'" % root)

    def visit(occurrence, placement):
        if occurrence.get("visible") is False:
            return
        local = numpy.eye(4)
        local[:3, :] = numpy.asarray(occurrence.get("transform") or numpy.eye(4)[:3], dtype=numpy.float64)
        world = placement @ local
        if _under(occurrence.get("native_ref", ""), root):
            definition = definitions.get((occurrence.get("prototype") or {}).get("definition")) or {}
            for body_id in definition.get("bodies") or []:
                _add_body(body_id, world)
        for child in children.get(occurrence["id"], []):
            visit(child, world)

    def _add_body(body_id, world):
        body = bodies.get(body_id) or {}
        found = meshes.get(body_id)
        if not found:
            what = "B-rep body (read it with 'usd-core')" if body.get("regions") else "body with no mesh"
            dropped[what] = dropped.get(what, 0) + 1
            return
        for tessellation in found:
            mesh = tessellation.get("mesh") or {}
            if mesh.get("kind") == "list":
                triangles = mesh.get("triangles") or []
            elif mesh.get("kind") == "corner_shaded_list":
                triangles = [t["corners"] for t in mesh.get("triangles") or []]
            else:
                dropped["mesh of kind %s" % mesh.get("kind")] = dropped.get("mesh of kind %s" % mesh.get("kind"), 0) + 1
                continue
            vertices = mesh.get("vertices") or []
            if not triangles or not vertices:
                continue
            total[0] += len(triangles)
            if total[0] > max_triangles:
                raise TooManyTriangles(
                    "more than %d triangles; build a 'prim' under the stage's root, or raise 'maxTriangles'"
                    % max_triangles
                )
            points = numpy.asarray(vertices, dtype=numpy.float64).reshape(-1, 3)
            triangles = numpy.asarray(triangles, dtype=numpy.int64).reshape(-1, 3)
            transform = out @ world
            placed = points @ transform[:3, :3].T + transform[:3, 3]
            if numpy.linalg.det(world[:3, :3]) < 0:
                triangles = triangles[:, [0, 2, 1]]
            own = bound.get(("tessellation", tessellation.get("id"))) or bound.get(("body", body_id))
            if own is None:
                colour = _cadir_rgba(body.get("color"))
                own = (
                    ("displayColor", colour, None, None, None) if colour is not None else (None, None, None, None, None)
                )
            ids = numpy.full(len(triangles), look_of(own), dtype=numpy.int64)
            for subset in tessellation.get("triangle_groups") or []:
                look = bound.get(("group", tessellation.get("id"), subset.get("source_id")))
                chosen = numpy.asarray(subset.get("triangles") or [], dtype=numpy.int64)
                chosen = chosen[(chosen >= 0) & (chosen < len(triangles))]
                if look is not None and len(chosen):
                    ids[chosen] = look_of(look)
            pieces.append((placed, triangles, ids))

    for top in children.get(None, []):
        visit(top, numpy.eye(4))
    return Model(pieces, looks, dropped)


def _under(path, root):
    return root == "/" or path == root or path.startswith(root.rstrip("/") + "/")


def _cadir_rgba(colour):
    """A CADIR colour - linear, 0 to 1 - as (red, green, blue, alpha) the way 'read' gives one; None for none."""
    if not isinstance(colour, dict) or not all(k in colour for k in "rgb"):
        return None
    return (_srgb(colour["r"]), _srgb(colour["g"]), _srgb(colour["b"]), round(float(colour.get("a", 1.0)), 3))


def _appearance_rgba(appearance, package=None):
    """The colour an appearance draws in: its base colour, or the mean of the texture that gives it, where read."""
    if not isinstance(appearance, dict):
        return None
    for texture in appearance.get("textures") or []:
        if texture.get("slot") in ("diffuseColor", "base_color", "baseColor", "diffuse_texture"):
            mean = _texture_mean(package, texture.get("paths") or [])
            if mean is None:
                return None
            return tuple(int(round(v)) for v in mean) + (
                round(float((appearance.get("base_color") or {}).get("a", 1.0)), 3),
            )
    return _cadir_rgba(appearance.get("base_color"))


def _texture_mean(package, paths):
    """The mean sRGB colour (0-255) of the first of 'paths' found in the USDZ 'package' - by its own path's end."""
    import zipfile

    import usd_look

    if not package or not str(package).lower().endswith(".usdz"):
        return None
    try:
        with zipfile.ZipFile(package) as z:
            members = z.namelist()
    except (OSError, zipfile.BadZipFile):
        return None
    for path in paths:
        tail = "/".join(part for part in str(path).replace("\\", "/").split("/") if part not in ("", ".", ".."))
        for member in members:
            if tail and (member == tail or member.endswith("/" + tail)):
                image = usd_look._read_image("%s[%s]" % (package, member))
                if image is not None:
                    return image[:, :, :3].reshape(-1, 3).mean(axis=0) * 255.0
    return None


def stl_bytes(vertices, triangles):
    """A binary STL of 'triangles', indices into 'vertices'."""
    import numpy

    record = numpy.dtype([("normal", "<f4", (3,)), ("vertices", "<f4", (3, 3)), ("attribute", "<u2")])
    data = numpy.zeros(len(triangles), dtype=record)
    corners = vertices[triangles]
    normals = numpy.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    lengths = numpy.linalg.norm(normals, axis=1)
    lengths[lengths == 0] = 1
    data["normal"] = normals / lengths[:, None]
    data["vertices"] = corners
    return b"PartCAD usd".ljust(80, b" ") + struct.pack("<I", len(triangles)) + data.tobytes()


# How the triangles become a shape. A face of its own for each triangle, with
# the edges two triangles share shared, is a shape everything in PartCAD takes
# - a line drawing, a STEP file, a closed mesh made the solid it bounds - and
# costs a shape of OpenCASCADE's per triangle. A face that is only a
# triangulation is cheap at any size, and is drawn shaded and written as a mesh
# (STL, 3MF, glTF), but has no edges for a line drawing to draw nor a surface
# for a STEP file to hold. 'auto' is the first up to FACES_UP_TO triangles.
SURFACES = ("auto", "faces", "mesh")
FACES_UP_TO = 20000
# The distance two corners are one vertex within, in millimetres, and the
# smallest a triangle may be: what OpenCASCADE would refuse as degenerate.
WELD = 1e-4


def _triangulation_face(builder, scratch, n, vertices, triangles):
    from OCP.RWStl import RWStl
    from OCP.TopoDS import TopoDS_Face

    path = os.path.join(scratch, "%d.stl" % n)
    with open(path, "wb") as f:
        f.write(stl_bytes(vertices, triangles))
    triangulation = RWStl.ReadFile_s(path)
    if triangulation is None or triangulation.NbTriangles() == 0:
        return []
    face = TopoDS_Face()
    builder.MakeFace(face, triangulation)
    return [face]


def welded(vertices, triangles, tolerance=WELD, kept=False):
    """(points, triangles): corners within 'tolerance' made one, and the triangles that are then no area dropped.

    With 'kept', '(points, triangles, kept)': 'kept' the indices of the
    triangles that are left, into those given.
    """
    import numpy

    keys = numpy.round(vertices / tolerance).astype(numpy.int64)
    _, first, inverse = numpy.unique(keys, axis=0, return_index=True, return_inverse=True)
    points = vertices[first]
    triangles = inverse.reshape(-1)[triangles]
    distinct = (
        (triangles[:, 0] != triangles[:, 1])
        & (triangles[:, 1] != triangles[:, 2])
        & (triangles[:, 0] != triangles[:, 2])
    )
    left = numpy.nonzero(distinct)[0]
    triangles = triangles[distinct]
    corners = points[triangles]
    area = numpy.linalg.norm(numpy.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0]), axis=1)
    large = area > tolerance * tolerance
    if kept:
        return points, triangles[large], left[large]
    return points, triangles[large]


def _shell(builder, vertices, triangles):
    """'(shell, made)': a planar face per triangle, sharing the vertices and edges the triangles share.

    'made' is the index of the triangle each face of the shell is, in order.
    """
    import numpy
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeFace
    from OCP.gp import gp_Dir, gp_Pln, gp_Pnt
    from OCP.TopoDS import TopoDS_Shell, TopoDS_Vertex, TopoDS_Wire

    points, triangles, kept = welded(vertices, triangles, kept=True)
    # Each face lies on the plane its triangle's winding faces, so that the
    # faces of a closed mesh all face the same way and the shell bounds what
    # the mesh does: left to fit a plane to the wire, OpenCASCADE picks either
    # side.
    corners_of = points[triangles]
    normals = numpy.cross(corners_of[:, 1] - corners_of[:, 0], corners_of[:, 2] - corners_of[:, 0])
    corners = {}
    for index in sorted(set(triangles.reshape(-1).tolist())):
        vertex = TopoDS_Vertex()
        x, y, z = points[index]
        builder.MakeVertex(vertex, gp_Pnt(float(x), float(y), float(z)), WELD)
        corners[index] = vertex
    edges, faces = {}, []
    shell = TopoDS_Shell()
    builder.MakeShell(shell)
    for (a, b, c), normal, which in zip(triangles.tolist(), normals.tolist(), kept.tolist()):
        wire = TopoDS_Wire()
        builder.MakeWire(wire)
        for p, q in ((a, b), (b, c), (c, a)):
            key = (p, q) if p < q else (q, p)
            edge = edges.get(key)
            if edge is None:
                edge = edges[key] = BRepBuilderAPI_MakeEdge(corners[key[0]], corners[key[1]]).Edge()
            builder.Add(wire, edge if p < q else edge.Reversed())
        x, y, z = points[a]
        plane = gp_Pln(gp_Pnt(float(x), float(y), float(z)), gp_Dir(*(float(v) for v in normal)))
        face = BRepBuilderAPI_MakeFace(plane, wire, True)
        if face.IsDone():
            builder.Add(shell, face.Face())
            faces.append(which)
    return shell, faces


def entry(look):
    """What the part says a face drawn in 'look' is in, for 'wrapper_part_type' (see 'usd_look'); None for nothing."""
    if look is None:
        return None
    name, rgba, roughness, metallic, material = look
    said = {}
    if name:
        said["color"] = name
    if rgba is not None:
        said["rgba"] = list(rgba)
    if roughness is not None:
        said["roughness"] = roughness
    if metallic is not None:
        said["metallic"] = metallic
    if material:
        said["material"] = material
    return said or None


def build(model, surface="auto"):
    """(shape, cmf): the Model's triangles as a shape, and what each face is drawn in.

    'surface' is one of SURFACES: a face per triangle ('faces'), each mesh a
    shell of them; a face per look that is only a triangulation ('mesh'); or
    the first when there are no more than FACES_UP_TO triangles ('auto'). 'cmf'
    is what 'wrapper_part_type' reads: the 'usd' convention, and a set per face.
    """
    import numpy

    if surface not in SURFACES:
        raise ValueError("'surface' is one of %s, not '%s'" % (", ".join(SURFACES), surface))
    # Pin pyexpat before importing OCP (see PartCAD's wrapper_import_mesh.py).
    import pyexpat  # noqa: F401

    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    if surface == "auto":
        surface = "faces" if model.triangle_count() <= FACES_UP_TO else "mesh"
    entries = [entry(look) for look in model.looks]
    builder = BRep_Builder()
    shapes, drawn = [], []
    if surface == "faces":
        for vertices, triangles, looks in model.pieces:
            shell, made = _shell(builder, vertices, triangles)
            if made:
                shapes.append(shell)
                drawn.extend(entries[looks[index]] if len(entries) else None for index in made)
    else:
        vertices, triangles, looks, offset = [], [], [], 0
        for points, piece, piece_looks in model.pieces:
            vertices.append(points)
            triangles.append(piece + offset)
            looks.append(piece_looks)
            offset += len(points)
        vertices, triangles, looks = numpy.vstack(vertices), numpy.vstack(triangles), numpy.concatenate(looks)
        with tempfile.TemporaryDirectory(prefix="partcad-usd-") as scratch:
            for look in numpy.unique(looks).tolist():
                for face in _triangulation_face(builder, scratch, look, vertices, triangles[looks == look]):
                    shapes.append(face)
                    drawn.append(entries[look] if look < len(entries) else None)
    if not shapes:
        return None, None
    if len(shapes) == 1:
        shape = shapes[0]
    else:
        shape = TopoDS_Compound()
        builder.MakeCompound(shape)
        for each in shapes:
            builder.Add(shape, each)
    cmf = {"convention": "usd", "faces": drawn} if any(drawn) else None
    return shape, cmf


def describe(dropped):
    return ", ".join("%d %s" % (count, what) for what, count in sorted(dropped.items()))


def run(request):
    """The part 'request' asks for, as the 'output' 'wrapper_part_type' reads."""
    parameters = request.get("parameters") or {}
    name = os.path.basename(request.get("path", ""))
    reader = str(parameters.get("reader") or "usd-core").strip().lower()
    try:
        if reader not in READERS:
            raise ValueError("'reader' is one of %s, not '%s'" % (", ".join(READERS), reader))
        options = dict(
            prim=str(parameters.get("prim") or ""),
            purpose=str(parameters.get("purpose") or "render").strip().lower(),
            time=parameters.get("time"),
            max_triangles=int(float(parameters.get("maxTriangles") or DEFAULT_MAX_TRIANGLES)),
        )
        if reader == "cadmpeg":
            model = read_cadmpeg(request["path"], request.get("cache_dir"), **options)
        else:
            model = read(request["path"], **options)
        dropped = model.dropped
        if dropped:
            print("usd: left out what is not a mesh: %s" % describe(dropped), file=sys.stderr)
        surface = str(parameters.get("surface") or "auto").strip().lower()
        shape, cmf = build(model, surface) if model.pieces else (None, None)
    except (ValueError, TooManyTriangles, RuntimeError) as e:
        return {"exception": "%s: %s" % (name, e)}
    if shape is None:
        return {"exception": "%s shows no mesh%s" % (name, " (only %s)" % describe(dropped) if dropped else "")}
    output = {"shape": shape}
    if cmf:
        output["cmf"] = cmf
    # What else it was built from, so that changing one of those files builds
    # it again (the type says 'reportsDependencies').
    output["dependencies"] = None if model.files is None else reported(model.files, request["path"])
    return output


if __name__ == "__partcad_part__":
    output = run(request)  # noqa: F821 - injected by the sandbox
