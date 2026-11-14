#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The 'heightmap' partType: a raster of heights, as the solid under them.

A height map is pixels, each a height: an elevation model's grid, a game
engine's terrain, a relief to print. The part is the solid under the heights -
one smooth face on a flat base at z = 0, sides standing on its edges (see
'heightfield'). What is read, by the file's extension:

  * '.asc' - an ESRI ASCII grid, what GIS tools export a DEM as: its header
    says the cell size and the no-data value, and its heights are in the
    part's 'unit';
  * '.png', '.tif', '.tiff' and the other images Pillow reads - by 'encoding':
      - 'gray' (the default): one channel, 8 or 16 bits, or floating point.
        Integer levels go from nought to 'relief' mm at the brightest the
        format holds, as a game engine reads a 16-bit height map; floating
        point values are heights in 'unit', as a GeoTIFF's are;
      - 'terrarium': the AWS Terrain Tiles' RGB encoding, metres;
      - 'terrain-rgb': Mapbox's RGB encoding, metres;
  * '.npy' - a two-dimensional NumPy array of heights in 'unit'.

A raster's first row is its north edge, as an image and a grid are drawn, so
row r, column c is the cell at x = c, y = rows - 1 - r: the part looks the way
the file looks from above. The cell size is 'cell' mm where a part says it, the
file's own in 'unit' where it has one (an ASCII grid), and a metre otherwise.
A missing height - a no-data value, a pixel fully transparent - is the nearest
present one's. The part is centred on the origin, its lowest height 'base' mm
above z = 0 (twice the cell, by default), and every height 'exaggeration'
times what it is above the lowest.

Run by 'wrappers/wrapper_part_type.py' with 'request["path"]' set to the file.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

CACHE_VERSION = 1

ENCODINGS = ("gray", "terrarium", "terrain-rgb")


def read_ascii_grid(path):
    """'(heights, cell)' of an ESRI ASCII grid: heights[c][r] as the file has them (NaN for no data), and its cell size."""
    import numpy

    header, rows = {}, []
    with open(path, encoding="ascii", errors="replace") as f:
        for line in f:
            words = line.split()
            if not words:
                continue
            key = words[0].lower()
            if key in (
                "ncols",
                "nrows",
                "xllcorner",
                "yllcorner",
                "xllcenter",
                "yllcenter",
                "cellsize",
                "nodata_value",
            ):
                header[key] = float(words[1])
                continue
            if key in ("dx", "dy"):
                header[key] = float(words[1])
                continue
            rows.append([float(word) for word in words])
    if "ncols" not in header or "nrows" not in header:
        raise ValueError("%s is not an ESRI ASCII grid: it says no 'ncols' and 'nrows'" % os.path.basename(path))
    values = numpy.array([v for row in rows for v in row], dtype=float)
    ncols, nrows = int(header["ncols"]), int(header["nrows"])
    if values.size != ncols * nrows:
        raise ValueError(
            "%s says it is %d x %d and holds %d heights" % (os.path.basename(path), ncols, nrows, values.size)
        )
    grid = values.reshape(nrows, ncols)
    if "nodata_value" in header:
        grid[grid == header["nodata_value"]] = numpy.nan
    cell = header.get("cellsize") or (header.get("dx"), header.get("dy"))
    return grid, cell


def read_image(path, encoding, relief):
    """Heights in metres or mm, the raster's rows as the image's, and in what: '(grid, kind)'.

    'kind' is 'levels' for an integer gray image already scaled to 'relief' mm,
    'mm' for the RGB encodings (in mm), and 'unit' for floating point values.
    """
    import numpy
    from PIL import Image

    image = Image.open(path)
    name = os.path.basename(path)
    if encoding in ("terrarium", "terrain-rgb"):
        rgba = numpy.asarray(image.convert("RGBA"), dtype=float)
        r, g, b, a = rgba[..., 0], rgba[..., 1], rgba[..., 2], rgba[..., 3]
        if encoding == "terrarium":
            metres = r * 256.0 + g + b / 256.0 - 32768.0
        else:
            metres = -10000.0 + (r * 65536.0 + g * 256.0 + b) * 0.1
        metres[a == 0] = numpy.nan
        return metres * 1000.0, "mm"
    mode = image.mode
    if mode in ("F", "I;16F"):
        return numpy.asarray(image, dtype=float), "unit"
    if mode in ("I;16", "I;16B", "I;16L"):
        levels, full = numpy.asarray(image, dtype=float), 65535.0
    elif mode == "I":
        levels = numpy.asarray(image, dtype=float)
        full = 65535.0 if levels.max() <= 65535 else float(levels.max())
    elif mode in ("L", "P", "LA", "PA", "RGB", "RGBA", "1"):
        if mode in ("RGB", "RGBA"):
            rgb = numpy.asarray(image.convert("RGB"), dtype=int)
            if not ((rgb[..., 0] == rgb[..., 1]) & (rgb[..., 1] == rgb[..., 2])).all():
                raise ValueError(
                    "%s is in colour: a gray height map has one channel, and an encoded one names its "
                    "'encoding' (%s)" % (name, ", ".join(ENCODINGS[1:]))
                )
        alpha = numpy.asarray(image.convert("RGBA"), dtype=float)[..., 3] if "A" in mode else None
        levels, full = numpy.asarray(image.convert("L"), dtype=float), 255.0
        if alpha is not None:
            levels[alpha == 0] = numpy.nan
    else:
        raise ValueError("%s is a %s image, which is not a height map PartCAD reads" % (name, mode))
    return levels / full * float(relief), "levels"


def heights_of(path, parameters):
    """'(heights, cell, what)': heights in mm, indexed [x][y] with y north, the cell in mm, and a word for the log."""
    import numpy

    import heightfield

    unit = heightfield.unit_scale(parameters.get("unit") or "m")
    extension = os.path.splitext(path)[1].lower()
    cell = parameters.get("cell")
    if extension == ".asc":
        grid, file_cell = read_ascii_grid(path)
        grid = grid * unit
        what = "ASCII grid"
        if not cell and file_cell:
            cell = (
                float(file_cell) * unit
                if numpy.isscalar(file_cell)
                else [float(v) * unit for v in file_cell if v is not None]
            )
    elif extension == ".npy":
        grid = numpy.load(path, allow_pickle=False).astype(float)
        if grid.ndim != 2:
            raise ValueError(
                "%s holds a %d-dimensional array, and a height map is two" % (os.path.basename(path), grid.ndim)
            )
        grid = grid * unit
        what = "array"
    else:
        encoding = str(parameters.get("encoding") or "gray").strip().lower()
        if encoding not in ENCODINGS:
            raise ValueError("'encoding' is one of %s, not '%s'" % (", ".join(ENCODINGS), encoding))
        rows, columns = _image_size(path)
        relief = parameters.get("relief")
        grid, kind = read_image(path, encoding, float(relief) if relief else 0.0)
        if kind == "levels" and not relief:
            raise ValueError(
                "a gray height map of integer levels says nothing of how high its brightest level is: "
                "give the part a 'relief', in mm"
            )
        if kind == "unit":
            grid = grid * unit
        what = "%d x %d %s image" % (columns, rows, encoding)
    cell = _cell(cell)
    # The first row is the north edge: [x][y] with y growing north.
    heights = numpy.asarray(grid, dtype=float)[::-1, :].T
    return heights, cell, what


def _image_size(path):
    from PIL import Image

    with Image.open(path) as image:
        return image.height, image.width


def _cell(cell):
    """A cell's size in mm, (x, y): a part's 'cell', one number or two, or a metre."""
    if cell in (None, "", 0, "0"):
        return (1000.0, 1000.0)
    if isinstance(cell, str):
        cell = [v for v in cell.replace(",", " ").split() if v]
    if isinstance(cell, (list, tuple)):
        values = [float(v) for v in cell]
        return (values[0], values[-1])
    return (float(cell), float(cell))


def run(request):
    """The part 'request' asks for, as the 'output' 'wrapper_part_type' reads."""
    import heightfield

    parameters = request.get("parameters") or {}
    name = os.path.basename(request.get("path", ""))
    try:
        heights, cell, what = heights_of(request["path"], parameters)
        base = float(parameters.get("base") or 2.0 * max(cell))
        shape, info = heightfield.build(
            heights,
            cell,
            base,
            exaggeration=float(parameters.get("exaggeration") or 1.0),
            max_poles=int(float(parameters.get("maxPoles") or heightfield.DEFAULT_MAX_POLES)),
        )
    except (ValueError, OSError) as e:
        return {"exception": "%s: %s" % (name, e)}
    return {"shape": shape}


if __name__ == "__partcad_part__":
    output = run(request)  # noqa: F821
