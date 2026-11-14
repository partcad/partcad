#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The 'voxels' partType: a grid of filled cells, as the solids they make.

A voxel is a box, so the part is exact: the union of the filled cells, 'size'
mm a side, taken into boxes and fused (see 'voxel_solid'), a solid per colour or
label. What is read, by the file's extension:

  * '.vox' - a MagicaVoxel model: every model its scene places, where its
    scene places it and turned as it says, each voxel in its palette colour.
    Each colour is a solid of its own, stated under the 'vox' convention by its
    palette index ('1' to '255'), so that a package's colour, material or
    finish claims an index - 'ids: {vox: "17"}' - and the voxels of that index
    are made of it. A model of a palette it does not carry (an old file) is
    drawn in PartCAD's palette for its indices instead;
  * '.binvox' - binvox's run-length grid, as voxelizers of meshes write it: one
    solid, its voxels 'size' mm, or what the file's own scale makes them;
  * '.npy' - a three-dimensional NumPy array: of booleans, filled where true;
    of integers, a solid per value other than nought - the labels of a
    segmentation - unless a 'threshold' says the integers are densities; of
    floats, filled at 'threshold' (0.5) and above - a CT scan, a simulation's
    density field.

The grid's axes are X, Y and Z, Z up, unless 'up: y' says it is a Y-up model -
binvox files made of meshes often are - which is turned onto Z. The grid's
middle is put over the origin and its bottom on z = 0, unless 'origin: file'
keeps it where the file has it. Each voxel is 'size' mm (1, for a MagicaVoxel
model or an array, by default) along all three axes, or three numbers' worth.

Run by 'wrappers/wrapper_part_type.py' with 'request["path"]' set to the file.
"""

import os
import struct
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

CACHE_VERSION = 1

# The most labels an array is made into before it is taken for a density
# field that needs a 'threshold': a segmentation has tens, a scan thousands.
MAX_LABELS = 255


class Grid:
    """'labels' (x, y, z; 0 empty), the voxel size the file states (mm, or None), its corner, and its colours."""

    def __init__(self, labels, size=None, corner=(0.0, 0.0, 0.0), colours=None, convention=None, what=""):
        self.labels = labels
        self.size = size
        self.corner = corner
        self.colours = colours
        self.convention = convention
        self.what = what


# -- MagicaVoxel -------------------------------------------------------------------------------------------------


def _chunks(data, start, end):
    """'[(id, content, children)]' of the chunks between 'start' and 'end'."""
    found = []
    while start + 12 <= end:
        chunk, content, children = struct.unpack_from("<4sii", data, start)
        body = start + 12
        found.append(
            (chunk.decode("ascii", "replace"), data[body : body + content], (body + content, body + content + children))
        )
        start = body + content + children
    return found


def _string(data, at):
    (length,) = struct.unpack_from("<i", data, at)
    return data[at + 4 : at + 4 + length].decode("utf-8", "replace"), at + 4 + length


def _dictionary(data, at):
    (count,) = struct.unpack_from("<i", data, at)
    at += 4
    result = {}
    for _ in range(count):
        key, at = _string(data, at)
        value, at = _string(data, at)
        result[key] = value
    return result, at


def _rotation(byte):
    """MagicaVoxel's packed rotation: the row each axis's 1 is in, and its sign."""
    import numpy

    first, second = byte & 3, (byte >> 2) & 3
    third = ({0, 1, 2} - {first, second}).pop()
    matrix = numpy.zeros((3, 3), dtype=int)
    for row, (column, bit) in enumerate(((first, 4), (second, 5), (third, 6))):
        matrix[row, column] = -1 if byte >> bit & 1 else 1
    return matrix


def read_vox(path):
    import numpy

    name = os.path.basename(path)
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"VOX ":
        raise ValueError("%s is not a MagicaVoxel file" % name)
    main = _chunks(data, 8, len(data))
    if not main or main[0][0] != "MAIN":
        raise ValueError("%s has no MAIN chunk" % name)
    children = _chunks(data, *main[0][2])
    sizes, models, palette, nodes = [], [], None, {}
    for chunk, content, _ in children:
        if chunk == "SIZE":
            sizes.append(struct.unpack_from("<iii", content, 0))
        elif chunk == "XYZI":
            (count,) = struct.unpack_from("<i", content, 0)
            models.append(numpy.frombuffer(content, dtype=numpy.uint8, count=count * 4, offset=4).reshape(count, 4))
        elif chunk == "RGBA":
            palette = numpy.frombuffer(content, dtype=numpy.uint8, count=1024).reshape(256, 4)
        elif chunk in ("nTRN", "nGRP", "nSHP"):
            (node,) = struct.unpack_from("<i", content, 0)
            _, at = _dictionary(content, 4)
            if chunk == "nTRN":
                child, _, _, frames = struct.unpack_from("<iiii", content, at)
                attributes, _ = _dictionary(content, at + 16) if frames else ({}, None)
                nodes[node] = ("trn", child, attributes)
            elif chunk == "nGRP":
                (count,) = struct.unpack_from("<i", content, at)
                nodes[node] = ("grp", list(struct.unpack_from("<%di" % count, content, at + 4)))
            else:
                (count,) = struct.unpack_from("<i", content, at)
                ids, at = [], at + 4
                for _ in range(count):
                    (model,) = struct.unpack_from("<i", content, at)
                    _, at = _dictionary(content, at + 4)
                    ids.append(model)
                nodes[node] = ("shp", ids)
    if not models:
        raise ValueError("%s holds no model" % name)

    placed = []

    def visit(node, rotation, translation):
        kind = nodes.get(node)
        if kind is None:
            return
        if kind[0] == "trn":
            attributes = kind[2]
            local = _rotation(int(attributes["_r"])) if "_r" in attributes else numpy.eye(3, dtype=int)
            offset = numpy.array([int(v) for v in attributes.get("_t", "0 0 0").split()])
            visit(kind[1], rotation @ local, rotation @ offset + translation)
        elif kind[0] == "grp":
            for child in kind[1]:
                visit(child, rotation, translation)
        else:
            for model in kind[1]:
                placed.append((model, rotation, translation))

    if nodes:
        visit(0, numpy.eye(3, dtype=int), numpy.zeros(3, dtype=int))
    if not placed:
        placed = [(index, numpy.eye(3, dtype=int), numpy.zeros(3, dtype=int)) for index in range(len(models))]

    points, indices = [], []
    for model, rotation, translation in placed:
        if model >= len(models):
            continue
        voxels = models[model].astype(int)
        # A model turns about its middle: the voxel at half its size.
        middle = numpy.array(sizes[model]) // 2
        points.append((voxels[:, :3] - middle) @ rotation.T + translation)
        indices.append(voxels[:, 3])
    points, indices = numpy.concatenate(points), numpy.concatenate(indices)
    low = points.min(axis=0)
    shape = tuple(points.max(axis=0) - low + 1)
    labels = numpy.zeros(shape, dtype=numpy.int32)
    labels[tuple((points - low).T)] = indices
    colours = None
    if palette is not None:
        # Index i is the palette's entry i - 1.
        colours = {i: tuple(int(c) for c in palette[i - 1]) for i in numpy.unique(indices) if i}
    return Grid(
        labels,
        colours=colours,
        convention="vox",
        corner=tuple(float(v) for v in low),
        what="MagicaVoxel, %d model%s" % (len(placed), "" if len(placed) == 1 else "s"),
    )


# -- binvox ------------------------------------------------------------------------------------------------------


def read_binvox(path):
    import numpy

    name = os.path.basename(path)
    with open(path, "rb") as f:
        if not f.readline().startswith(b"#binvox"):
            raise ValueError("%s is not a binvox file" % name)
        dims, translate, scale = None, (0.0, 0.0, 0.0), 1.0
        while True:
            line = f.readline()
            if not line:
                raise ValueError("%s has no 'data'" % name)
            words = line.decode("ascii", "replace").split()
            if not words:
                continue
            if words[0] == "data":
                break
            if words[0] == "dim":
                dims = tuple(int(v) for v in words[1:4])
            elif words[0] == "translate":
                translate = tuple(float(v) for v in words[1:4])
            elif words[0] == "scale":
                scale = float(words[1])
        if dims is None:
            raise ValueError("%s says no 'dim'" % name)
        runs = numpy.frombuffer(f.read(), dtype=numpy.uint8)
    values, counts = runs[0::2], runs[1::2].astype(int)
    flat = numpy.repeat(values, counts)
    if flat.size != dims[0] * dims[1] * dims[2]:
        raise ValueError("%s is %d voxels, and says it is %d x %d x %d" % (name, flat.size, *dims))
    # Stored with y fastest, then z, then x.
    grid = flat.reshape(dims[0], dims[2], dims[1]).transpose(0, 2, 1)
    size = scale / max(dims)
    corner = tuple(t / size for t in translate)  # in voxels, as every grid's corner is
    return Grid((grid > 0).astype(numpy.int32), size=size, corner=corner, what="binvox %d x %d x %d" % dims)


# -- NumPy -------------------------------------------------------------------------------------------------------


def read_npy(path, threshold):
    import numpy

    name = os.path.basename(path)
    array = numpy.load(path, allow_pickle=False)
    if array.ndim != 3:
        raise ValueError("%s holds a %d-dimensional array, and voxels are three" % (name, array.ndim))
    if threshold is not None:
        return Grid((array >= float(threshold)).astype(numpy.int32), what="array, filled at %s and above" % threshold)
    if array.dtype == bool:
        return Grid(array.astype(numpy.int32), what="array of booleans")
    if numpy.issubdtype(array.dtype, numpy.integer):
        found = numpy.unique(array)
        found = found[found != 0]
        if len(found) > MAX_LABELS:
            raise ValueError(
                "%s holds %d values, too many to be the labels of a segmentation: give the part a "
                "'threshold' to read them as a density" % (name, len(found))
            )
        labels = numpy.zeros(array.shape, dtype=numpy.int32)
        for index, value in enumerate(found, 1):
            labels[array == value] = index
        return Grid(labels, what="array of %d labels" % len(found))
    return Grid((array >= 0.5).astype(numpy.int32), what="array, filled at 0.5 and above")


# -- The part ----------------------------------------------------------------------------------------------------


def read(path, parameters):
    extension = os.path.splitext(path)[1].lower()
    if extension == ".vox":
        return read_vox(path)
    if extension == ".binvox":
        return read_binvox(path)
    if extension == ".npy":
        threshold = parameters.get("threshold")
        return read_npy(path, None if threshold in (None, "") else threshold)
    raise ValueError("voxels are a .vox, a .binvox or a .npy, and %s is none of them" % os.path.basename(path))


def _size(value, stated):
    if value in (None, "", 0, "0"):
        return (stated,) * 3 if stated else (1.0, 1.0, 1.0)
    if isinstance(value, str):
        value = [v for v in value.replace(",", " ").split() if v]
    if isinstance(value, (list, tuple)):
        values = [float(v) for v in value]
        return tuple(values) if len(values) == 3 else (values[0],) * 3
    return (float(value),) * 3


def run(request):
    """The part 'request' asks for, as the 'output' 'wrapper_part_type' reads."""
    import numpy

    import voxel_solid

    parameters = request.get("parameters") or {}
    name = os.path.basename(request.get("path", ""))
    try:
        grid = read(request["path"], parameters)
        labels = grid.labels
        up = str(parameters.get("up") or "z").strip().lower()
        if up not in ("z", "y"):
            raise ValueError("'up' is 'z' or 'y', not '%s'" % up)
        corner = numpy.array(grid.corner, dtype=float)
        # The grid cut to what is filled, so that the voxels, not the file's
        # empty margin, are what stands on z = 0 over the origin.
        filled = numpy.argwhere(labels > 0)
        if filled.size:
            low, high = filled.min(axis=0), filled.max(axis=0) + 1
            labels = labels[low[0] : high[0], low[1] : high[1], low[2] : high[2]]
            corner = corner + low
        if up == "y":
            # (x, y, z) Y up is (x, -z, y) Z up.
            labels = numpy.flip(labels.transpose(0, 2, 1), axis=1)
            corner = numpy.array([corner[0], -(corner[2] + labels.shape[1]), corner[1]])
        size = _size(parameters.get("size"), grid.size)
        if str(parameters.get("origin") or "center").strip().lower() == "file":
            origin = tuple(corner * numpy.array(size))
        else:
            origin = (-labels.shape[0] * size[0] / 2.0, -labels.shape[1] * size[1] / 2.0, 0.0)
        shape, per_solid, per_face = voxel_solid.solids(
            labels,
            size,
            origin,
            max_boxes=int(float(parameters.get("maxBoxes") or voxel_solid.DEFAULT_MAX_BOXES)),
        )
        cmf = voxel_solid.cmf(
            per_solid, per_face, grid.colours, grid.convention or "partcad", named=grid.convention is not None
        )
    except (ValueError, OSError, struct.error) as e:
        return {"exception": "%s: %s" % (name, e)}
    output = {"shape": shape}
    if cmf:
        output["cmf"] = cmf
    return output


if __name__ == "__partcad_part__":
    output = run(request)  # noqa: F821
