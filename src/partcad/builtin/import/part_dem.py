#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The 'dem' partType: a digital elevation model, in any raster format GDAL reads, as the solid under it.

What surveys publish terrain in: a GeoTIFF ('.tif'), an SRTM tile ('.hgt',
named for its corner, 'N38W078.hgt'), DTED ('.dt0', '.dt1', '.dt2'), ERDAS
Imagine ('.img'), an ESRI BIL ('.bil') - read with rasterio, whose wheels carry
GDAL, so that nothing has to be installed beside the sandbox. It is the
'heightmap' type's solid (see 'heightfield'), with what the file knows about
itself:

  * **its cell**, from its georeferencing: in the units of a projected
    reference system (feet included), or, in a geographic one, its degrees
    made metres at the raster's middle latitude - an SRTM tile's arc second is
    about 31 by 24 m at 38 degrees north;
  * **its holes**, from its no-data value: each the nearest present height's;
  * **which edge is north**: the raster's first row, unless its georeferencing
    says otherwise.

Heights are in the part's 'unit' (metres, as elevation models are). 'band' is
the band read (1). 'bounds' - 'west south east north', in the raster's own
reference system - takes the part of it there, since a tile of a survey is
usually much more than a scene needs: a whole SRTM tile is 111 km a side. The
lowest height stands 'base' mm above z = 0, every height 'exaggeration' times
what it is above the lowest, centred on the origin as a 'heightmap' is.

Run by 'wrappers/wrapper_part_type.py' with 'request["path"]' set to the file.
"""

import math
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

CACHE_VERSION = 1


def metres_per_degree(latitude):
    """(east, north): metres in a degree of longitude and of latitude, at 'latitude' on the WGS 84 ellipsoid."""
    phi = math.radians(latitude)
    north = 111132.92 - 559.82 * math.cos(2 * phi) + 1.175 * math.cos(4 * phi) - 0.0023 * math.cos(6 * phi)
    east = 111412.84 * math.cos(phi) - 93.5 * math.cos(3 * phi) + 0.118 * math.cos(5 * phi)
    return east, north


def _bounds(value):
    if value in (None, ""):
        return None
    values = [float(v) for v in (value.replace(",", " ").split() if isinstance(value, str) else value)]
    if len(values) != 4 or not (values[0] < values[2] and values[1] < values[3]):
        raise ValueError("'bounds' is 'west south east north', west before east and south before north")
    return values


def read(path, parameters):
    """'(heights, cell, what)': heights in mm indexed [x][y] with y north, the cell (x, y) in mm, and a log word."""
    import numpy

    import heightfield

    try:
        import rasterio
        import rasterio.windows
    except ImportError:  # pragma: no cover - the type installs it
        raise ValueError("reading an elevation model takes rasterio, which this sandbox does not have")

    name = os.path.basename(path)
    unit = heightfield.unit_scale(parameters.get("unit") or "m")
    band = int(float(parameters.get("band") or 1))
    bounds = _bounds(parameters.get("bounds"))
    with rasterio.open(path) as raster:
        if not 1 <= band <= raster.count:
            raise ValueError("%s has %d band(s), and 'band' is %d" % (name, raster.count, band))
        transform = raster.transform
        if transform.b or transform.d:
            raise ValueError("%s is rotated in its reference system, which a height field is not" % name)
        window = None
        if bounds is not None:
            full = rasterio.windows.Window(0, 0, raster.width, raster.height)
            asked = rasterio.windows.from_bounds(*bounds, transform=transform)
            try:
                window = asked.round_offsets().round_lengths().intersection(full)
            except Exception:
                raise ValueError("'bounds' %s are not over %s, which covers %s" % (bounds, name, tuple(raster.bounds)))
            transform = raster.window_transform(window)
        grid = raster.read(band, window=window, masked=True).astype(float).filled(numpy.nan)
        crs = raster.crs
        if crs is not None and crs.is_geographic:
            middle = transform.f + transform.e * grid.shape[0] / 2.0
            east, north = metres_per_degree(middle)
            cell = (abs(transform.a) * east * 1000.0, abs(transform.e) * north * 1000.0)
            what = "%s, %d x %d, geographic" % (raster.driver, grid.shape[1], grid.shape[0])
        else:
            factor = 1.0
            if crs is not None and crs.is_projected:
                factor = float(crs.linear_units_factor[1])
            cell = (abs(transform.a) * factor * 1000.0, abs(transform.e) * factor * 1000.0)
            what = "%s, %d x %d" % (raster.driver, grid.shape[1], grid.shape[0])
    if not numpy.isfinite(grid).any():
        raise ValueError("%s has no height there: every cell is its no-data value" % name)
    # North first, unless the raster runs south to north.
    if transform.e > 0:
        grid = grid[::-1, :]
    if transform.a < 0:
        grid = grid[:, ::-1]
    return (grid * unit)[::-1, :].T, cell, what


def run(request):
    """The part 'request' asks for, as the 'output' 'wrapper_part_type' reads."""
    import heightfield

    parameters = request.get("parameters") or {}
    name = os.path.basename(request.get("path", ""))
    try:
        heights, cell, _ = read(request["path"], parameters)
        base = float(parameters.get("base") or 2.0 * max(cell))
        shape, _ = heightfield.build(
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
