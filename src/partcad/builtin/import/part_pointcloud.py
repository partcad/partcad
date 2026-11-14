#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The 'pointcloud' partType: points a scanner or a lidar measured, as the solid they describe.

Points bound nothing, so a part of them is what they are made into, by the
part's 'as':

  * 'heightfield' (the default) - the ground or a relief: the points are
    binned on the plan into cells 'cell' mm wide, each cell's height the
    'statistic' of its points' ('max', the default, keeps roofs and canopies;
    'min' keeps the ground under them; 'mean'), an empty cell the nearest
    full one's, and the part is the solid under those heights (see
    'heightfield'). What an airborne lidar scan and a photogrammetry survey are
    best made into.
  * 'voxels' - an object or a space: the cells, 'cell' mm a side, that hold at
    least 'minPoints' points, as the solids they make (see 'voxel_solid'). A
    scan's points lie on surfaces, so the solid is the scanned skin a cell
    thick. Where the points have colours, each cell is in its points' mean
    colour, to 64 shades, and is a solid of that colour.

What is read, by the file's extension:

  * '.ply' - ASCII or binary, its 'vertex' element's x, y and z, and its red,
    green and blue where it has them (a mesh's faces are not read: a PLY mesh
    is a part of its own type);
  * '.xyz', '.txt', '.csv', '.pts' - a point a line, x y z first, split by
    spaces, commas or semicolons, then r g b where there are six columns (a
    '.pts' with seven: x y z, intensity, r g b); a line of words, or a lone
    count, is a header;
  * '.las', '.laz' - lidar, read with laspy (and lazrs, for the compressed
    form): x, y and z as the file scales them, its colours, and its points'
    classes, which 'classes' filters on - '2' is the ground, '6' buildings,
    '3,4,5' vegetation.

Coordinates are in 'unit' (metres, unless the part says otherwise) and are
moved so that the cloud's middle is over the origin and its lowest point is at
'base' mm above z = 0 ('origin: file' keeps them where the file has them).
At most 'maxPoints' points are read, evenly through the file.

Run by 'wrappers/wrapper_part_type.py' with 'request["path"]' set to the file.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

CACHE_VERSION = 1

AS = ("heightfield", "voxels")
STATISTICS = ("max", "min", "mean")
TEXT = (".xyz", ".txt", ".csv", ".pts")

DEFAULT_MAX_POINTS = 20000000

# The grid a cloud is binned on, at most, along its longer side: what a
# height field is averaged down from, and the most voxels along a side.
MAX_HEIGHTFIELD_CELLS = 2048
DEFAULT_VOXELS_ALONG = 128

PLY_TYPES = {
    "char": "i1",
    "int8": "i1",
    "uchar": "u1",
    "uint8": "u1",
    "short": "i2",
    "int16": "i2",
    "ushort": "u2",
    "uint16": "u2",
    "int": "i4",
    "int32": "i4",
    "uint": "u4",
    "uint32": "u4",
    "float": "f4",
    "float32": "f4",
    "double": "f8",
    "float64": "f8",
}


class Cloud:
    """Points read from a file: 'xyz' (n x 3, in the file's unit), and 'rgb' (n x 3, 0-255) and 'classes' where it has them."""

    def __init__(self, xyz, rgb=None, classes=None, what=""):
        self.xyz = xyz
        self.rgb = rgb
        self.classes = classes
        self.what = what


def read_ply(path):
    import numpy

    name = os.path.basename(path)
    with open(path, "rb") as f:
        if f.readline().strip() != b"ply":
            raise ValueError("%s is not a PLY file" % name)
        form, elements = None, []
        while True:
            line = f.readline()
            if not line:
                raise ValueError("%s has no 'end_header'" % name)
            words = line.decode("ascii", "replace").split()
            if not words or words[0] in ("comment", "obj_info"):
                continue
            if words[0] == "end_header":
                break
            if words[0] == "format":
                form = words[1]
            elif words[0] == "element":
                elements.append((words[1], int(words[2]), []))
            elif words[0] == "property" and elements:
                if words[1] == "list":
                    elements[-1][2].append((words[4], None))
                else:
                    elements[-1][2].append((words[2], words[1]))
        if form not in ("ascii", "binary_little_endian", "binary_big_endian"):
            raise ValueError("%s is a PLY of format '%s', which is not one PartCAD reads" % (name, form))
        endian = ">" if form == "binary_big_endian" else "<"
        for element, count, properties in elements:
            if element == "vertex":
                break
            if form != "ascii" and any(kind is None for _, kind in properties):
                raise ValueError("%s has a '%s' element of lists before its vertices" % (name, element))
            if form == "ascii":
                for _ in range(count):
                    f.readline()
            else:
                f.seek(count * sum(numpy.dtype(PLY_TYPES[kind]).itemsize for _, kind in properties), 1)
        else:
            raise ValueError("%s holds no vertices" % name)
        names = [prop for prop, _ in properties]
        if any(kind is None for _, kind in properties):
            raise ValueError("%s's vertices have a list property, which a point cloud does not" % name)
        if form == "ascii":
            lines = [f.readline() for _ in range(count)]
            data = numpy.loadtxt(lines, dtype=float, ndmin=2)
            columns = {prop: data[:, index] for index, prop in enumerate(names)}
        else:
            dtype = numpy.dtype([(prop, endian + PLY_TYPES[kind]) for prop, kind in properties])
            data = numpy.frombuffer(f.read(count * dtype.itemsize), dtype=dtype, count=count)
            columns = {prop: data[prop].astype(float) for prop in names}
    if not all(axis in columns for axis in "xyz"):
        raise ValueError("%s's vertices have no x, y and z" % name)
    xyz = numpy.column_stack([columns["x"], columns["y"], columns["z"]])
    rgb = None
    for keys in (("red", "green", "blue"), ("r", "g", "b"), ("diffuse_red", "diffuse_green", "diffuse_blue")):
        if all(key in columns for key in keys):
            rgb = numpy.column_stack([columns[key] for key in keys])
            break
    return Cloud(xyz, rgb, what="PLY (%s)" % form.replace("_", " "))


def read_text(path):
    import numpy

    name = os.path.basename(path)
    header, delimiter, columns = 0, None, None
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            text = line.strip()
            if not text or text.startswith(("#", "//")):
                header += 1
                continue
            for candidate in (",", ";", None):
                words = text.split(candidate) if candidate else text.split()
                if len(words) >= 3:
                    break
            if len(words) >= 3 and all(_number(word) for word in words):
                delimiter, columns = candidate, len(words)
                break
            header += 1
    if columns is None:
        raise ValueError("%s has no line of three numbers or more: x y z" % name)
    data = numpy.loadtxt(path, delimiter=delimiter, skiprows=header, comments=("#", "//"), ndmin=2, dtype=float)
    rgb = None
    extension = os.path.splitext(path)[1].lower()
    if extension == ".pts" and data.shape[1] >= 7:
        rgb = data[:, 4:7]
    elif data.shape[1] >= 6:
        rgb = data[:, 3:6]
    if rgb is not None and not (0.0 <= rgb.min() and rgb.max() <= 255.0):
        rgb = None
    return Cloud(data[:, :3], rgb, what="text, %d columns" % data.shape[1])


def read_las(path):
    import numpy

    try:
        import laspy
    except ImportError:  # pragma: no cover - the type installs it
        raise ValueError("reading lidar takes laspy, which this sandbox does not have")
    las = laspy.read(path)
    xyz = numpy.column_stack([numpy.asarray(las.x), numpy.asarray(las.y), numpy.asarray(las.z)])
    rgb = None
    names = set(las.point_format.dimension_names)
    if {"red", "green", "blue"} <= names:
        rgb = numpy.column_stack([numpy.asarray(las.red), numpy.asarray(las.green), numpy.asarray(las.blue)]).astype(
            float
        )
        # LAS colours are 16-bit; some writers put 8-bit values in them.
        rgb = rgb / 257.0 if rgb.max() > 255.0 else rgb
        if not rgb.any():
            rgb = None
    classes = numpy.asarray(las.classification).astype(int) if "classification" in names else None
    return Cloud(xyz, rgb, classes, what="LAS %s, point format %d" % (las.header.version, las.point_format.id))


def _number(text):
    try:
        float(text)
        return True
    except ValueError:
        return False


def read(path):
    extension = os.path.splitext(path)[1].lower()
    if extension == ".ply":
        return read_ply(path)
    if extension in (".las", ".laz"):
        return read_las(path)
    if extension in TEXT:
        return read_text(path)
    raise ValueError(
        "a point cloud is a .ply, a .las or .laz, or text (%s), and %s is none of them"
        % (", ".join(TEXT), os.path.basename(path))
    )


def _classes(value):
    if value in (None, "", []):
        return None
    if isinstance(value, (int, float)):
        return [int(value)]
    if isinstance(value, str):
        return [int(v) for v in value.replace(",", " ").split()]
    return [int(v) for v in value]


def heightfield_of(xyz, parameters, origin):
    """The solid under the cloud's binned heights, and a line for the log."""
    import numpy

    import heightfield

    low, high = xyz.min(axis=0), xyz.max(axis=0)
    width, depth = max(high[0] - low[0], 1e-9), max(high[1] - low[1], 1e-9)
    cell = parameters.get("cell")
    if cell:
        cell = float(cell)
    else:
        # About four points a cell, as fine as that is and as the grid allows.
        cell = max(2.0 * (width * depth / len(xyz)) ** 0.5, max(width, depth) / MAX_HEIGHTFIELD_CELLS)
    # Cells from the lowest point on, as many as reach the highest: a point on
    # the far edge is in a cell of its own, not folded into the one before.
    nx, ny = max(2, int(width // cell) + 1), max(2, int(depth // cell) + 1)
    if max(nx, ny) > 4 * MAX_HEIGHTFIELD_CELLS:
        raise ValueError("a 'cell' of %s mm makes a grid of %d x %d: make it coarser" % (cell, nx, ny))
    ix = numpy.clip(((xyz[:, 0] - low[0]) / cell).astype(int), 0, nx - 1)
    iy = numpy.clip(((xyz[:, 1] - low[1]) / cell).astype(int), 0, ny - 1)
    flat = ix * ny + iy
    statistic = str(parameters.get("statistic") or "max").strip().lower()
    if statistic not in STATISTICS:
        raise ValueError("'statistic' is one of %s, not '%s'" % (", ".join(STATISTICS), statistic))
    if statistic == "mean":
        sums = numpy.bincount(flat, weights=xyz[:, 2], minlength=nx * ny)
        counts = numpy.bincount(flat, minlength=nx * ny)
        with numpy.errstate(invalid="ignore", divide="ignore"):
            grid = numpy.where(counts > 0, sums / numpy.maximum(counts, 1), numpy.nan)
    else:
        fill = -numpy.inf if statistic == "max" else numpy.inf
        grid = numpy.full(nx * ny, fill)
        (numpy.maximum if statistic == "max" else numpy.minimum).at(grid, flat, xyz[:, 2])
        grid[~numpy.isfinite(grid)] = numpy.nan
    grid = grid.reshape(nx, ny)
    base = float(parameters.get("base") or 2.0 * cell)
    corner = (low[0], low[1]) if origin == "file" else None
    shape, info = heightfield.build(
        grid,
        cell,
        base,
        exaggeration=float(parameters.get("exaggeration") or 1.0),
        origin=corner,
        max_poles=int(float(parameters.get("maxPoles") or heightfield.DEFAULT_MAX_POLES)),
    )
    empty = int(numpy.isnan(grid).sum())
    if empty > grid.size / 2:
        # Said, because it is a choice somebody can make better: most of the
        # surface is then the nearest cell's height, not a measured one.
        print(
            "pointcloud: %d of the %d cells of %s mm hold no point, and take the nearest one's height: "
            "a larger 'cell' measures more of them" % (empty, grid.size, heightfield._number(cell)),
            file=sys.stderr,
        )
    return shape, None, "%s, %d of its cells empty" % (heightfield.describe(info), empty)


def voxels_of(xyz, rgb, parameters, origin):
    """The solids of the cells the cloud's points fall in, their colours, and a line for the log."""
    import numpy

    import voxel_solid

    low, high = xyz.min(axis=0), xyz.max(axis=0)
    cell = parameters.get("cell")
    cell = float(cell) if cell else max(float((high - low).max()) / DEFAULT_VOXELS_ALONG, 1e-6)
    counts = numpy.floor((high - low) / cell).astype(int) + 1
    index = numpy.clip(((xyz - low) / cell).astype(int), 0, counts - 1)
    flat = numpy.ravel_multi_index(index.T, counts)
    occupied, inverse, hits = numpy.unique(flat, return_inverse=True, return_counts=True)
    keep = hits >= int(float(parameters.get("minPoints") or 1))
    labels = numpy.zeros(int(numpy.prod(counts)), dtype=numpy.int32)
    colours = None
    if rgb is not None:
        # Each cell in its points' mean colour, to four levels a channel.
        sums = numpy.zeros((len(occupied), 3))
        numpy.add.at(sums, inverse, rgb)
        mean = sums / hits[:, None]
        levels = numpy.clip(numpy.round(mean / 85.0), 0, 3).astype(int)
        codes = 1 + levels[:, 0] * 16 + levels[:, 1] * 4 + levels[:, 2]
        labels[occupied[keep]] = codes[keep]
        colours = {int(code): (int(r) * 85, int(g) * 85, int(b) * 85, 255) for code, (r, g, b) in zip(codes, levels)}
    else:
        labels[occupied[keep]] = 1
    labels = labels.reshape(tuple(counts))
    if origin == "file":
        corner = tuple(float(v) for v in low)
    else:
        corner = (-counts[0] * cell / 2.0, -counts[1] * cell / 2.0, 0.0)
    shape, per_solid, per_face = voxel_solid.solids(
        labels,
        cell,
        corner,
        max_boxes=int(float(parameters.get("maxBoxes") or voxel_solid.DEFAULT_MAX_BOXES)),
    )
    cmf = voxel_solid.cmf(per_solid, per_face, colours, named=False) if colours else None
    return shape, cmf, "%d of %d x %d x %d voxels, %s mm each" % (int(keep.sum()), *counts, cell)


def run(request):
    """The part 'request' asks for, as the 'output' 'wrapper_part_type' reads."""
    import numpy

    import heightfield

    parameters = request.get("parameters") or {}
    name = os.path.basename(request.get("path", ""))
    try:
        cloud = read(request["path"])
        xyz, rgb = cloud.xyz, cloud.rgb
        wanted = _classes(parameters.get("classes"))
        if wanted is not None:
            if cloud.classes is None:
                raise ValueError("'classes' filters lidar by its points' classes, and this file has none")
            keep = numpy.isin(cloud.classes, wanted)
            xyz, rgb = xyz[keep], (rgb[keep] if rgb is not None else None)
        limit = int(float(parameters.get("maxPoints") or DEFAULT_MAX_POINTS))
        if len(xyz) > limit:
            step = int(numpy.ceil(len(xyz) / float(limit)))
            xyz, rgb = xyz[::step], (rgb[::step] if rgb is not None else None)
        if len(xyz) < 3:
            raise ValueError(
                "it holds %d points%s, and a part takes three at least"
                % (len(xyz), " of those classes" if wanted else "")
            )
        xyz = heightfield.finite(xyz, "a point") * heightfield.unit_scale(parameters.get("unit") or "m")
        origin = str(parameters.get("origin") or "center").strip().lower()
        if origin not in ("center", "file"):
            raise ValueError("'origin' is 'center' or 'file', not '%s'" % origin)
        built = str(parameters.get("as") or "heightfield").strip().lower()
        if built not in AS:
            raise ValueError("'as' is one of %s, not '%s'" % (", ".join(AS), built))
        if built == "heightfield":
            shape, cmf, said = heightfield_of(xyz, parameters, origin)
        else:
            shape, cmf, said = voxels_of(xyz, rgb, parameters, origin)
    except (ValueError, OSError) as e:
        return {"exception": "%s: %s" % (name, e)}
    output = {"shape": shape}
    if cmf:
        output["cmf"] = cmf
    return output


if __name__ == "__partcad_part__":
    output = run(request)  # noqa: F821
