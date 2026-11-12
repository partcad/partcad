#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within the python sandbox environment (python runtime)
# to cut a shape tree by a section, as 'wrapper_section' does, and to take out of
# every print in it the faces that nothing can see.
#
# A print is what its printer deposits ('//builtin/cam''s 'cam_fff.deposit'): per
# layer, the regions the layer's beads cover, extruded by the layer - a compound
# of planar prisms, never fused: a wall ring with the space for the infill as its
# hole, a band of skin, a line of infill. Drawn as it is, that is every face of
# every prism: the top of each layer lying on the bottom of the next, every side
# of every infill line, the inside of every wall - tens of thousands of faces
# the viewer tessellates, sends and draws, which nobody can see, because the
# walls and the skins close them in. Cut, a print is worth looking into: what
# the cut opens is the inside, the infill exposed by it, and that has to be
# drawn - while what stays closed still need not be.
#
# What "can be seen" means here - an approximation, chosen to be conservative:
#
#   * Every layer is sampled on a grid, and its empty space - more than
#     'OPENING_CELLS' cells from anything the layer deposits - falls apart into
#     pieces: the space round the print, the space inside a wall ring between the
#     infill lines, a design's own hole, a gap between beads.
#   * A piece is joined to every piece of the layer above and below it lies
#     over or under, and to the outside where it reaches the edge of the grid
#     (the space round the print, and a ring a section cut open) or where its
#     layer has no layer over it or under it (the first and the last layer, and
#     one the section cut across).
#   * A piece joined, that way, to the outside is *exposed*: from outside the
#     cut print there is a way into it. A top face is kept where some of what
#     lies over it is exposed space, or nothing; a bottom face where some of what
#     lies under it is; a side face where what lies in front of it - sampled
#     along it, a little out - is. Everything else is dropped: a layer lying on
#     the next and two beads side by side have nothing in front of them, and
#     the infill of a print the section does not reach into, the inside of its
#     walls, face only space with no way in.
#
# That is a topological answer, not a line of sight: it keeps every face a camera
# allowed to move through every opening could see, which is more than can be
# seen from any one place - the far side of the infill seen through the gaps of
# a section is kept although the near infill hides most of it. And an opening has
# to be wide enough to look through: the grid's cell is half a layer's height
# (coarser where a large print would make that more than 'MAX_SAMPLES' points a
# layer), and a gap narrower than about a layer is no way in. That is what
# keeps the crevices - where the round end of every skin line meets the wall -
# from opening every print's infill to the outside through its top; it is also
# why what is dropped wrongly is what can be seen only through a gap that narrow,
# and why an overlap of two pieces narrower than a cell can be missed. A prism too
# small to hold a point of the grid is kept whole rather than guessed about.
#
# Only a node whose geometry is such a compound is stripped: two or more solids,
# every face of them planar and either horizontal or vertical, each solid a prism
# from one height to another. Anything else - a cut part, a molding, a print kept
# as an SDF mesh - is not a print's deposit, and is cut exactly as
# 'wrapper_section' cuts it. A deposit is cut solid by solid instead, because it
# is tens of thousands of them and a box misses most: only a solid the box passes
# through goes through a boolean. What is kept of a deposit is a compound of faces
# rather than of solids: it is drawn, never measured, and what the node says
# about its size stays the object's.

import math
import os
import sys

# Pinned before the CAD imports below, which load OCP and with it VTK's bundled
# copy of expat: see the note in ocp_serialize.
import pyexpat  # noqa: F401

sys.path.append(os.path.dirname(__file__))
import ocp_serialize
import wrapper_common
import wrapper_section

# What this wrapper reports for what it produces (see 'partcad.code_version'):
# raise it with any change that changes that, and everything it produced
# before is produced again.
CACHE_VERSION = 1

# How many points of the grid a layer is sampled at, at most: the cell grows past
# half a layer's height where a print is so large that a finer one would be more.
MAX_SAMPLES = 120000

# How many cells of the grid are taken off every side of a layer's empty space
# before what is left of it counts as open: with a cell half a layer high, a gap
# narrower than about a layer is taken to be closed. Measured on a 20 x 10 x 5 mm
# plate with a hole, printed at 20%: one cell keeps 2024 of its 14994 faces, the
# walls' outsides, the hole, the top and the bottom (2012 of them) and a dozen
# more, and the same plate at 50% infill cut across shows its infill; two keep
# fewer of what can be seen (1887) and close a 50% infill's gaps altogether.
OPENING_CELLS = 1

# How near a face's normal has to be to an axis to count as along it.
_FLAT = 1e-6

# What two heights are rounded to before they are compared, in mm.
_Z_QUANTUM = 1e-4


def _plane(face):
    """A planar face's outward normal and the height of a point on it, as ((x, y, z), z); None where it is not planar."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.TopAbs import TopAbs_REVERSED

    surface = BRepAdaptor_Surface(face)
    if surface.GetType() != GeomAbs_Plane:
        return None
    plane = surface.Plane()
    direction = plane.Axis().Direction()
    normal = (direction.X(), direction.Y(), direction.Z())
    if face.Orientation() == TopAbs_REVERSED:
        normal = (-normal[0], -normal[1], -normal[2])
    return normal, plane.Location().Z()


def _explore(shape, kind, cast):
    from OCP.TopExp import TopExp_Explorer

    explorer = TopExp_Explorer(shape, kind)
    while explorer.More():
        yield cast(explorer.Current())
        explorer.Next()


def _solids(shape):
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopoDS import TopoDS

    return list(_explore(shape, TopAbs_SOLID, TopoDS.Solid_s))


def _wire_points(wire, face):
    """The corners of a wire, in order round it, as a list of (x, y)."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepTools import BRepTools_WireExplorer

    points = []
    explorer = BRepTools_WireExplorer(wire, face)
    while explorer.More():
        point = BRep_Tool.Pnt_s(explorer.CurrentVertex())
        points.append((point.X(), point.Y()))
        explorer.Next()
    return points


def _wires(face):
    """The wires of a face: the outer one first, then its holes."""
    from OCP.BRepTools import BRepTools
    from OCP.TopAbs import TopAbs_WIRE
    from OCP.TopoDS import TopoDS

    outer = BRepTools.OuterWire_s(face)
    return [outer] + [wire for wire in _explore(face, TopAbs_WIRE, TopoDS.Wire_s) if not wire.IsSame(outer)]


class _Prism:
    """One solid of a deposit: its faces by which way they face, the heights it runs between, and its outline."""

    def __init__(self, solid, index):
        self.solid = solid
        self.index = index
        self.top = []
        self.bottom = []
        self.sides = []
        # The way each of 'sides' faces, in plan: (x, y).
        self.normals = []
        # A side face standing on no wire of the bottom: kept, since it cannot be placed.
        self.other = []
        # How many side faces are too narrow to be drawn (see 'prism_of').
        self.slivers = 0
        self.z0 = None
        self.z1 = None
        # Per wire of the bottom: its corners, whether it is a face's outer wire,
        # and the side faces standing on it, each with the edge it stands on and
        # the way it faces, as '(face, (x0, y0, x1, y1, nx, ny))'. A face's outer
        # wire comes before its holes.
        self.regions = []

    @property
    def layer(self):
        return (self.z0, self.z1)

    def faces(self):
        """Every face of it but the slivers: what it is drawn as when it is kept whole."""
        placed = [face for _, _, standing in self.regions for face, _ in standing]
        return self.top + self.bottom + placed + self.other


def _corner(x, y):
    """A corner, rounded to '_Z_QUANTUM', as the key an edge is found by."""
    return (round(x / _Z_QUANTUM), round(y / _Z_QUANTUM))


def _foot(face, z0):
    """The corners a vertical face stands on, at the height 'z0' (quantized): two, but for an odd face."""
    from OCP.BRep import BRep_Tool
    from OCP.TopAbs import TopAbs_VERTEX
    from OCP.TopoDS import TopoDS

    corners = set()
    for vertex in _explore(face, TopAbs_VERTEX, TopoDS.Vertex_s):
        point = BRep_Tool.Pnt_s(vertex)
        if round(point.Z() / _Z_QUANTUM) == z0:
            corners.add(_corner(point.X(), point.Y()))
    return frozenset(corners)


def prism_of(solid, index):
    """'solid' read as a layer's prism, or None where it is not one."""
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopoDS import TopoDS

    prism = _Prism(solid, index)
    tops, bottoms = set(), set()
    for face in _explore(solid, TopAbs_FACE, TopoDS.Face_s):
        plane = _plane(face)
        if plane is None:
            return None
        normal, height = plane
        if abs(abs(normal[2]) - 1.0) < _FLAT:
            if normal[2] > 0:
                prism.top.append(face)
                tops.add(round(height / _Z_QUANTUM))
            else:
                prism.bottom.append(face)
                bottoms.add(round(height / _Z_QUANTUM))
        elif abs(normal[2]) < _FLAT:
            prism.sides.append(face)
            prism.normals.append((normal[0], normal[1]))
        else:
            return None
    if len(tops) != 1 or len(bottoms) != 1:
        return None
    prism.z1 = next(iter(tops))
    prism.z0 = next(iter(bottoms))
    if prism.z1 <= prism.z0:
        return None

    # Which side face stands on which wire of the bottom, found by the corners
    # it stands on: an edge of the bottom is two of its wire's corners in a row.
    # By position rather than by topology, which costs a lookup of a shape in a
    # map per edge and was most of the time this took.
    wires = []
    standing = {}
    for bottom in prism.bottom:
        for position, wire in enumerate(_wires(bottom)):
            points = _wire_points(wire, bottom)
            wires.append((points, position == 0, []))
            for (xa, ya), (xb, yb) in zip(points, points[1:] + points[:1]):
                standing[frozenset((_corner(xa, ya), _corner(xb, yb)))] = (len(wires) - 1, (xa, ya, xb, yb))
    for side, normal in zip(prism.sides, prism.normals):
        foot = _foot(side, prism.z0)
        if len(foot) < 2:
            # Narrower than '_Z_QUANTUM': a sliver Clipper's integer
            # coordinates leave where two beads all but meet, which has no
            # width to be drawn with.
            prism.slivers += 1
            continue
        found = standing.get(foot)
        if found is None:
            # It stands on no wire of the bottom: kept, since it cannot be placed.
            prism.other.append(side)
            continue
        wire, segment = found
        # Where it stands, and which way it faces: what is looked at to find
        # whether anything is in front of it.
        wires[wire][2].append((side, segment + normal))
    prism.regions = wires
    return prism


def deposit_of(shape):
    """'shape' read as a print's deposit, a prism per solid, or None where it is not one."""
    solids = _solids(shape)
    if len(solids) < 2:
        return None
    prisms = []
    for solid in solids:
        prism = prism_of(solid, len(prisms) + 1)
        if prism is None:
            return None
        prisms.append(prism)
    return prisms


def cut_deposit(prisms, placement, slabs):
    """'prisms' cut by a section: '(prisms, loose)', what is left of them, solid by solid.

    A solid the box misses is dropped and one it holds kept as it is, without a
    boolean; one it passes through is intersected with it, and what comes back
    read as prisms again. A piece that is not one any more is 'loose', and is
    drawn whole.
    """
    kept, loose = [], []
    index = max((prism.index for prism in prisms), default=0)
    for prism in prisms:
        result = wrapper_section._cut(prism.solid, placement, slabs)
        if result is None:
            continue
        if result is prism.solid:
            kept.append(prism)
            continue
        for solid in _solids(result):
            index += 1
            piece = prism_of(solid, index)
            if piece is None:
                loose.append(solid)
            else:
                kept.append(piece)
    return kept, loose


def _fill(polygons, x0, y0, nx, ny, cell):
    """Which points of an 'nx' by 'ny' grid lie inside 'polygons', by the even-odd rule.

    The grid's points are at '(x0 + (i + 1/2) cell, y0 + (j + 1/2) cell)'. Every
    edge crossing a row of points toggles the row from where it crosses onwards,
    so a polygon costs its crossings and one running sum, however many points it
    covers.
    """
    import numpy as np

    flags = np.zeros((ny, nx + 1), dtype=np.int32)
    for polygon in polygons:
        if len(polygon) < 3:
            continue
        points = np.asarray(polygon, dtype=np.float64)
        xa, ya = points[:, 0], points[:, 1]
        xb, yb = np.roll(xa, -1), np.roll(ya, -1)
        low, high = np.minimum(ya, yb), np.maximum(ya, yb)
        # The rows whose points are at heights in [low, high): half open, so
        # that a corner shared by two edges is crossed once.
        first = np.clip(np.ceil((low - y0) / cell - 0.5), 0, ny).astype(np.int64)
        last = np.clip(np.ceil((high - y0) / cell - 0.5), 0, ny).astype(np.int64)
        counts = np.maximum(last - first, 0)
        total = int(counts.sum())
        if total == 0:
            continue
        edge = np.repeat(np.arange(len(points)), counts)
        offsets = np.arange(total) - np.repeat(np.cumsum(counts) - counts, counts)
        row = first[edge] + offsets
        y = y0 + (row + 0.5) * cell
        t = (y - ya[edge]) / (yb[edge] - ya[edge])
        x = xa[edge] + t * (xb[edge] - xa[edge])
        column = np.clip(np.ceil((x - x0) / cell - 0.5), 0, nx).astype(np.int64)
        np.add.at(flags, (row, column), 1)
    return (np.cumsum(flags[:, :nx], axis=1) % 2).astype(bool)


def _box(points):
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    return min(xs), min(ys), max(xs), max(ys)


class _Grid:
    """The points every layer of one deposit is sampled at: its box, and a margin of empty space round it."""

    def __init__(self, prisms):
        boxes = [_box(points) for prism in prisms for points, outer, _ in prism.regions if outer and points]
        left = min(box[0] for box in boxes)
        bottom = min(box[1] for box in boxes)
        width = max(box[2] for box in boxes) - left
        depth = max(box[3] for box in boxes) - bottom
        layer = min(prism.z1 - prism.z0 for prism in prisms) * _Z_QUANTUM
        cell = max(layer / 2.0, 1e-3)
        if (width / cell) * (depth / cell) > MAX_SAMPLES:
            cell = math.sqrt(width * depth / MAX_SAMPLES)
        self.cell = cell
        # Round the box, enough of what is outside the deposit that the space
        # round it is open space like any other (see 'OPENING_CELLS').
        margin = (OPENING_CELLS + 2) * cell
        self.x0 = left - margin
        self.y0 = bottom - margin
        self.nx = max(1, int(math.ceil((width + 2 * margin) / cell)))
        self.ny = max(1, int(math.ceil((depth + 2 * margin) / cell)))

    def window(self, points):
        """The columns and rows a polygon's box covers: (i0, j0, nx, ny), or None where it holds no point."""
        left, bottom, right, top = _box(points)
        i0 = max(0, int(math.floor((left - self.x0) / self.cell)))
        j0 = max(0, int(math.floor((bottom - self.y0) / self.cell)))
        i1 = min(self.nx, int(math.ceil((right - self.x0) / self.cell)) + 1)
        j1 = min(self.ny, int(math.ceil((top - self.y0) / self.cell)) + 1)
        if i1 <= i0 or j1 <= j0:
            return None
        return i0, j0, i1 - i0, j1 - j0

    def mask(self, polygons, window):
        i0, j0, nx, ny = window
        return _fill(polygons, self.x0 + i0 * self.cell, self.y0 + j0 * self.cell, nx, ny, self.cell)


class _Spaces:
    """Which pieces of open space are joined to which: a union-find, the outside being piece 0."""

    def __init__(self):
        self.parent = [0]

    def add(self, count: int) -> int:
        """Make 'count' new pieces, and say what is added to a layer's own number for one of them to name it here."""
        base = len(self.parent) - 1
        self.parent.extend(range(len(self.parent), len(self.parent) + count))
        return base

    def find(self, piece: int) -> int:
        root = piece
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[piece] != root:
            self.parent[piece], piece = root, self.parent[piece]
        return root

    def join(self, one, other) -> None:
        a, b = self.find(int(one)), self.find(int(other))
        if a != b:
            # The outside stays its own root, so 'exposed' is one comparison.
            if a == 0:
                self.parent[b] = a
            else:
                self.parent[a] = b

    def exposed(self, piece) -> bool:
        return self.find(int(piece)) == 0


# The neighbours a point of open space is joined to in its layer: all eight.
_EIGHT = [[1, 1, 1], [1, 1, 1], [1, 1, 1]]


class _Layer:
    """One layer of a deposit, sampled: which prism each point of the grid is in, and its pieces of open space."""

    def __init__(self, key, prisms, grid, spaces):
        import numpy as np
        from scipy import ndimage

        self.key = key
        self.prisms = prisms
        # Which prism each point is in, by its index; 0 where it is in none.
        self.label = np.zeros((grid.ny, grid.nx), dtype=np.int32)
        # Per prism, the windows of the grid its faces cover; absent for a
        # prism that holds no point.
        self.own = {}
        for prism in prisms:
            # A face's region is its outer wire less its holes: all of its
            # wires filled together, by the even-odd rule.
            for polygons in _faces_of(prism):
                window = grid.window(polygons[0])
                if window is None:
                    continue
                inside = grid.mask(polygons, window)
                if inside.any():
                    i0, j0, nx, ny = window
                    self.label[j0 : j0 + ny, i0 : i0 + nx][inside] = prism.index
                    self.own.setdefault(prism.index, []).append(window)
        # The open space - empty, and more than 'OPENING_CELLS' from anything
        # deposited - in pieces, each one a node of 'spaces': its number there
        # at each of its points, and 0 where a point is not open.
        opened = ndimage.binary_erosion(self.label == 0, structure=_EIGHT, iterations=OPENING_CELLS, border_value=1)
        pieces, count = ndimage.label(opened, structure=_EIGHT)
        base = spaces.add(count)
        self.piece = np.where(pieces > 0, pieces + base, 0)
        # The space round the deposit - what reaches the edge of the grid - is
        # the outside.
        edge = np.concatenate([self.piece[0], self.piece[-1], self.piece[:, 0], self.piece[:, -1]])
        for value in np.unique(edge[edge > 0]):
            spaces.join(value, 0)
        # Per wire of each prism, by (prism, position among its regions): the
        # pieces of open space in front of each side face standing on it.
        self.front = self._front(grid)

    def _front(self, grid):
        """The pieces of open space in front of each side face of the layer: sampled along its edge, a little out."""
        import numpy as np

        keys, segments = [], []
        for prism in self.prisms:
            for position, (_, _, standing) in enumerate(prism.regions):
                keys.append((prism.index, position, len(standing)))
                segments.extend(segment for _, segment in standing)
        if not segments:
            return {(index, position): [] for index, position, _ in keys}
        data = np.asarray(segments, dtype=np.float64)
        length = np.hypot(data[:, 2] - data[:, 0], data[:, 3] - data[:, 1])
        counts = np.clip(np.ceil(length / (2.0 * grid.cell)), 1, 64).astype(np.int64)
        which = np.repeat(np.arange(len(data)), counts)
        step = np.arange(int(counts.sum())) - np.repeat(np.cumsum(counts) - counts, counts)
        t = (step + 0.5) / counts[which]
        # Out past the band 'OPENING_CELLS' takes off, into the open space a
        # face with nothing in front of it is in front of.
        out = (OPENING_CELLS + 1) * grid.cell
        x = data[which, 0] + t * (data[which, 2] - data[which, 0]) + out * data[which, 4]
        y = data[which, 1] + t * (data[which, 3] - data[which, 1]) + out * data[which, 5]
        i = np.clip(np.floor((x - grid.x0) / grid.cell).astype(np.int64), 0, grid.nx - 1)
        j = np.clip(np.floor((y - grid.y0) / grid.cell).astype(np.int64), 0, grid.ny - 1)
        found = self.piece[j, i]
        # Each side's pieces, from its run of samples.
        ends = np.cumsum(counts)
        front = {}
        side = 0
        for index, position, number in keys:
            facing = []
            for _ in range(number):
                start = ends[side] - counts[side]
                pieces = found[start : ends[side]]
                facing.append(set(pieces[pieces > 0].tolist()))
                side += 1
            front[(index, position)] = facing
        return front

    def beside(self, prism, other):
        """The pieces of open space of the layer 'other' over or under some point of 'prism', one of this layer's."""
        import numpy as np

        found = set()
        for i0, j0, nx, ny in self.own.get(prism.index, []):
            mine = self.label[j0 : j0 + ny, i0 : i0 + nx] == prism.index
            theirs = other.piece[j0 : j0 + ny, i0 : i0 + nx][mine]
            found.update(np.unique(theirs[theirs > 0]).tolist())
        return found


def _faces_of(prism):
    """A prism's regions grouped by the bottom face they bound: [[outer, hole, ...], ...]."""
    grouped = []
    for points, outer, _ in prism.regions:
        if outer or not grouped:
            grouped.append([])
        grouped[-1].append(points)
    return grouped


def visible(prisms, loose=(), report=None):
    """What of a deposit can be seen: '(compound, kept, dropped)', the faces kept and how many were dropped.

    'prisms' are the deposit's, cut or whole ('deposit_of', 'cut_deposit'), and
    'loose' solids of it that are not prisms any more, drawn whole. See the
    module's description for what "can be seen" means.

    'report', a dict, is given how many faces of each kind were kept: 'top',
    'bottom', 'side', 'whole' (every face of a prism too small to sample, and of
    a loose solid) and 'other' (a side face that stands on no wire of the
    bottom).
    """
    import numpy as np
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopoDS import TopoDS

    report = {} if report is None else report

    def count(kind, faces):
        report[kind] = report.get(kind, 0) + len(faces)

    kept = []
    for solid in loose:
        faces = list(_explore(solid, TopAbs_FACE, TopoDS.Face_s))
        kept.extend(faces)
        count("whole", faces)
    if not prisms:
        return ocp_serialize.compound_of(kept), len(kept), 0

    grid = _Grid(prisms)
    by_layer = {}
    for prism in prisms:
        by_layer.setdefault(prism.layer, []).append(prism)
    order = sorted(by_layer)
    # Two layers touch where one ends at the height the other starts at.
    ending = {}
    for key in order:
        ending.setdefault(key[1], []).append(key)
    starting = {key[0] for key in order}

    spaces = _Spaces()
    # Per prism: the pieces of open space over it and under it, and in front of
    # each of its side faces - kept as each layer is sampled, since the samples
    # of a layer are let go of once the layers beside it have been.
    over, under, front = {}, {}, {}
    sampled = set()
    layers = {}
    for key in order:
        layer = _Layer(key, by_layer[key], grid, spaces)
        layers[key] = layer
        front.update(layer.front)
        sampled.update(layer.own)
        if key[0] not in ending or key[1] not in starting:
            # Nothing under it, or nothing over it: every piece of its open
            # space is open to the outside.
            for value in np.unique(layer.piece[layer.piece > 0]):
                spaces.join(value, 0)
        for below_key in ending.get(key[0], []):
            below = layers[below_key]
            # A piece of one layer is joined to each piece of the other it lies
            # over, where both are open.
            both = (below.piece > 0) & (layer.piece > 0)
            if both.any():
                pairs = np.unique(np.stack([below.piece[both], layer.piece[both]], axis=1), axis=0)
                for a, b in pairs:
                    spaces.join(a, b)
            for prism in below.prisms:
                over.setdefault(prism.index, set()).update(below.beside(prism, layer))
            for prism in layer.prisms:
                under.setdefault(prism.index, set()).update(layer.beside(prism, below))
        # A layer that ends below where this one starts lies under nothing to
        # come, and its samples are let go of.
        for done in [done for done in layers if done[1] < key[0]]:
            del layers[done]
    layers.clear()

    def seen(pieces):
        return any(spaces.exposed(piece) for piece in pieces)

    dropped = 0
    for prism in prisms:
        if prism.index not in sampled:
            faces = prism.faces()
            kept.extend(faces)
            count("whole", faces)
            continue
        # A top with no layer over it is the top of what is left, and is seen.
        top = prism.z1 not in starting or seen(over.get(prism.index, ()))
        bottom = prism.z0 not in ending or seen(under.get(prism.index, ()))
        for kind, faces, shown in (("top", prism.top, top), ("bottom", prism.bottom, bottom)):
            if shown:
                kept.extend(faces)
                count(kind, faces)
            else:
                dropped += len(faces)
        for position, (_, _, standing) in enumerate(prism.regions):
            pieces = front.get((prism.index, position)) or [set()] * len(standing)
            for (face, _), facing in zip(standing, pieces):
                if seen(facing):
                    kept.append(face)
                    count("side", [face])
                else:
                    dropped += 1
        kept.extend(prism.other)
        count("other", prism.other)
        dropped += prism.slivers
    return ocp_serialize.compound_of(kept), len(kept), dropped


def strip(shape, report=None):
    """What of 'shape', a print's deposit, can be seen: '(compound, kept, dropped)', or None where it is not a deposit."""
    prisms = deposit_of(shape)
    if prisms is None:
        return None
    return visible(prisms, report=report)


def _payload(node_payload, shape):
    """'shape' as a node's payload, keeping the part's own CMF set from the payload it replaces.

    A face's own set is not followed: the faces kept are no longer the solid's,
    and a deposit lent its design's CMF carries it as the part's own.
    """
    section = ocp_serialize.cmf_of_payload(node_payload)
    own = section.own() if section is not None else None
    cmf = ocp_serialize.cmf_section_for(shape, own=own) if own is not None else None
    return wrapper_section._payload(shape, cmf)


def visible_tree(tree, section, errors, counts):
    """'tree' cut by 'section' (None: not cut), with every print in it stripped of what cannot be seen.

    'tree' is a BREP-form tree as it travelled, and so is what comes back. A node
    left with nothing in the box loses its geometry, as 'wrapper_section' leaves
    it for a reader that draws the tree. 'errors' collects a line per node that
    could not be looked at; such a node is cut the way 'wrapper_section' cuts
    it, and left whole if that fails too. 'counts' adds up the faces of prints
    kept and dropped.
    """
    if not isinstance(tree, dict):
        return tree
    return _walk(tree, None, wrapper_section.limits(section), errors, counts)


def _walk(node, parent, slabs, errors, counts):
    from OCP.TopLoc import TopLoc_Location

    if not isinstance(node, dict):
        return node
    own = node.get(ocp_serialize.KEY_LOCATION)
    placement = parent if parent is not None else TopLoc_Location()
    if own is not None:
        placement = placement.Multiplied(ocp_serialize.toploc_from_packed(own))

    result = {
        key: value for key, value in node.items() if key not in (ocp_serialize.KEY_BREP, ocp_serialize.KEY_ASSEMBLY)
    }
    brep = node.get(ocp_serialize.KEY_BREP)
    if brep:
        try:
            shape = ocp_serialize.shape_from_payload(brep)
            prisms = None
            try:
                prisms = deposit_of(shape)
                if prisms is not None:
                    loose = []
                    if wrapper_section.cuts_anything(slabs):
                        prisms, loose = cut_deposit(prisms, placement, slabs)
                    if prisms or loose:
                        compound, kept, dropped = visible(prisms, loose)
                        counts[0] += kept
                        counts[1] += dropped
                        result[ocp_serialize.KEY_BREP] = _payload(brep, compound)
            except Exception as e:
                errors.append("%s: %s" % (node.get("label") or node.get("name") or "a shape", e))
                prisms = None
            if prisms is None:
                # Not a print, or one that could not be looked at: cut as
                # 'wrapper_section' cuts any shape.
                cut = _cut_node(brep, shape, placement, slabs)
                if cut is not None:
                    result[ocp_serialize.KEY_BREP] = cut
        except Exception as e:
            errors.append("%s: %s" % (node.get("label") or node.get("name") or "a shape", e))
            result[ocp_serialize.KEY_BREP] = brep

    children = node.get(ocp_serialize.KEY_ASSEMBLY)
    if children is not None:
        result[ocp_serialize.KEY_ASSEMBLY] = [_walk(child, placement, slabs, errors, counts) for child in children]
    return result


def _cut_node(brep, shape, placement, slabs):
    """A node's payload cut by the section, as 'wrapper_section' cuts it: its CMF carried; None where nothing is left."""
    if not wrapper_section.cuts_anything(slabs):
        return brep
    history = []
    result = wrapper_section._cut(shape, placement, slabs, history)
    if result is shape:
        return brep
    if result is None:
        return None
    section = ocp_serialize.cmf_of_payload(brep)
    if section is not None and history:
        section = wrapper_section._carried(section, shape, result, history[0])
    return wrapper_section._payload(result, section)


def process(request):
    tree = request.get("tree")
    if not isinstance(tree, dict):
        raise Exception("No shape tree to look at")
    errors = []
    counts = [0, 0]
    result = visible_tree(tree, request.get("section"), errors, counts)
    return {
        "success": True,
        "exception": None,
        "tree": result,
        "errors": errors,
        "kept": counts[0],
        "dropped": counts[1],
    }


if __name__ == "__main__":
    # The tree arrives undecoded, for the reason it does in 'wrapper_section.py'.
    # argv[1] is required by handle_input() and unused: the answer comes back
    # over the pipe, and the caller passes the operation name there.
    _, request = wrapper_common.handle_input(decode=False)
    try:
        model = process(request)
    except Exception as e:
        wrapper_common.handle_exception(e)
        model = {"success": False, "exception": str(e), "tree": None, "errors": []}
    wrapper_common.handle_output(model)
