#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A height field as a solid: one smooth face over a rectangle, on a flat base at z = 0.

What the 'heightmap' part type makes of a raster and the 'pointcloud' part type
of the points it bins: heights on a regular grid, some of them missing, become

  * a cubic B-spline surface whose poles stand at the Greville abscissae of its
    knots - which makes the surface's X and Y linear in its parameters, so that
    it is a true height field, z(x, y), and a point of the plan is found on it
    without solving for anything. Each pole is the grid's height there, read
    off the grid by bilinear interpolation after the grid is smoothed to the
    poles' spacing, so a surface of fewer poles than the grid has cells is the
    grid's mean and not an alias of it;
  * and under it, the solid the surface bounds: four sides standing on the
    rectangle's edges and a flat base, sewn to it.

One face, six in all, whatever the grid's size: what a STEP file, a hidden-line
drawing and a boolean each take best, where a triangle per sample would be
hundreds of thousands of faces. The surface smooths: a cubic B-spline does not
pass through its poles, and a sharp step - a wall in a lidar scan - comes out
as a slope a pole's spacing wide.

A missing height - a raster's no-data value, a cell no point fell in - is the
nearest present one's, so the surface does not fall to nought there.

Nothing here reads a file. It is shared by the scripts that do, and imports
OCP only to build.
"""

import math

import numpy

DEGREE = 3

# The most poles along a side unless a part says otherwise: 256 x 256 poles
# is a surface OCCT builds and draws in seconds, and a finer grid is averaged
# down to it.
DEFAULT_MAX_POLES = 256


def knot_vector(count, degree=DEGREE):
    """The clamped uniform knot vector of 'count' poles on [0, 1], flattened."""
    spans = count - degree
    return [0.0] * (degree + 1) + [k / spans for k in range(1, spans)] + [1.0] * (degree + 1)


def greville(count, degree=DEGREE):
    """Where each pole stands along [0, 1]: the mean of the 'degree' knots after it."""
    knots = knot_vector(count, degree)
    return [sum(knots[i + 1 : i + degree + 1]) / degree for i in range(count)]


def filled(heights):
    """'heights' with every NaN replaced by the nearest height that is not one.

    A grid with no height at all is an error rather than a flat plane: it means
    the source held nothing to build.
    """
    heights = numpy.asarray(heights, dtype=float)
    missing = ~numpy.isfinite(heights)
    if not missing.any():
        return heights
    if missing.all():
        raise ValueError("there is no height anywhere in it")
    from scipy import ndimage

    _, (rows, columns) = ndimage.distance_transform_edt(missing, return_indices=True)
    return heights[rows, columns]


def poles(heights, count_x, count_y):
    """The poles of the surface over the grid: 'count_x' by 'count_y' heights read off 'heights'.

    'heights[i][j]' is the height of the cell i along X, j along Y, its centre
    at (i + 0.5, j + 0.5) cells from the grid's corner. The surface spans the
    grid's outer edges, so a pole on an edge reads the cell beside it.
    """
    from scipy import ndimage

    heights = filled(heights)
    nx, ny = heights.shape
    # Smoothed to the poles' spacing where there are fewer poles than cells.
    step = (max(1.0, nx / max(count_x - DEGREE, 1)), max(1.0, ny / max(count_y - DEGREE, 1)))
    if step[0] > 1.0 or step[1] > 1.0:
        heights = ndimage.uniform_filter(heights, size=(int(round(step[0])), int(round(step[1]))), mode="nearest")
    gx = numpy.clip(numpy.array(greville(count_x)) * nx - 0.5, 0.0, nx - 1.0)
    gy = numpy.clip(numpy.array(greville(count_y)) * ny - 0.5, 0.0, ny - 1.0)
    grid_x, grid_y = numpy.meshgrid(gx, gy, indexing="ij")
    return ndimage.map_coordinates(heights, [grid_x, grid_y], order=1, mode="nearest")


def pole_counts(nx, ny, max_poles=DEFAULT_MAX_POLES):
    """How many poles along X and Y: one per cell plus the degree, the longer side at most 'max_poles'."""
    longest = max(nx, ny)
    scale = min(1.0, (max_poles - DEGREE) / float(longest)) if longest + DEGREE > max_poles else 1.0
    return (
        max(DEGREE + 1, int(round(nx * scale)) + DEGREE),
        max(DEGREE + 1, int(round(ny * scale)) + DEGREE),
    )


def evaluate(pole_heights, extent, x, y):
    """The surface's z at (x, y) of the plan: what OCCT evaluates, to rounding.

    For whoever places something on the result without building it.
    """
    x0, y0, x1, y1 = extent
    pole_heights = numpy.asarray(pole_heights, dtype=float)
    nu, nv = pole_heights.shape
    su, bu = _basis((float(x) - x0) / (x1 - x0), nu)
    sv, bv = _basis((float(y) - y0) / (y1 - y0), nv)
    block = pole_heights[su - DEGREE : su + 1, sv - DEGREE : sv + 1]
    return float(numpy.asarray(bu) @ block @ numpy.asarray(bv))


def _basis(u, count, degree=DEGREE):
    """(span, the basis functions not nought at 'u'): The NURBS Book's A2.1 and A2.2."""
    knots = knot_vector(count, degree)
    u = min(max(u, 0.0), 1.0)
    if u >= knots[count]:
        span = count - 1
    else:
        low, high = degree, count
        span = (low + high) // 2
        while u < knots[span] or u >= knots[span + 1]:
            if u < knots[span]:
                high = span
            else:
                low = span
            span = (low + high) // 2
    values = [1.0] + [0.0] * degree
    left = [0.0] * (degree + 1)
    right = [0.0] * (degree + 1)
    for j in range(1, degree + 1):
        left[j] = u - knots[span + 1 - j]
        right[j] = knots[span + j] - u
        saved = 0.0
        for r in range(j):
            temp = values[r] / (right[r + 1] + left[j - r])
            values[r] = saved + right[r + 1] * temp
            saved = left[j - r] * temp
        values[j] = saved
    return span, values


def surface(pole_heights, extent):
    """The OCCT B-spline surface of the poles over 'extent' = (x0, y0, x1, y1), in mm."""
    from OCP.Geom import Geom_BSplineSurface
    from OCP.gp import gp_Pnt
    from OCP.TColgp import TColgp_Array2OfPnt
    from OCP.TColStd import TColStd_Array1OfInteger, TColStd_Array1OfReal

    def array(values, kind):
        result = kind(1, len(values))
        for index, value in enumerate(values, 1):
            result.SetValue(index, value)
        return result

    x0, y0, x1, y1 = extent
    pole_heights = numpy.asarray(pole_heights, dtype=float)
    nu, nv = pole_heights.shape
    grid = TColgp_Array2OfPnt(1, nu, 1, nv)
    xs = [x0 + g * (x1 - x0) for g in greville(nu)]
    ys = [y0 + g * (y1 - y0) for g in greville(nv)]
    for i in range(nu):
        for j in range(nv):
            grid.SetValue(i + 1, j + 1, gp_Pnt(xs[i], ys[j], float(pole_heights[i, j])))
    knots = {}
    for count in (nu, nv):
        spans = count - DEGREE
        knots[count] = (
            array([k / spans for k in range(spans + 1)], TColStd_Array1OfReal),
            array([DEGREE + 1] + [1] * (spans - 1) + [DEGREE + 1], TColStd_Array1OfInteger),
        )
    return Geom_BSplineSurface(grid, knots[nu][0], knots[nv][0], knots[nu][1], knots[nv][1], DEGREE, DEGREE)


def solid(pole_heights, extent):
    """The solid under the surface: its top the surface, its sides standing on the rectangle, its base on z = 0.

    Every pole has to be above z = 0, which keeps the whole surface above it (a
    B-spline lies within the hull of its poles). The surface is a height field
    over the rectangle, so each side is flat: a vertical plane bounded by the
    surface's own edge over a side of the rectangle - the exact iso-curve, not
    an approximation of it - two verticals and the side itself.
    """
    from OCP.BRepBuilderAPI import (
        BRepBuilderAPI_MakeEdge,
        BRepBuilderAPI_MakeFace,
        BRepBuilderAPI_MakeSolid,
        BRepBuilderAPI_MakeWire,
        BRepBuilderAPI_Sewing,
    )
    from OCP.gp import gp_Pnt
    from OCP.ShapeFix import ShapeFix_Solid
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    if float(numpy.min(pole_heights)) <= 0.0:
        raise ValueError("the surface reaches z = 0 or below, where its base is: give it a 'base'")
    over = surface(pole_heights, extent)

    def wire(edges):
        made = BRepBuilderAPI_MakeWire()
        for edge in edges:
            made.Add(edge)
        return made.Wire()

    def line(a, b):
        return BRepBuilderAPI_MakeEdge(a, b).Edge()

    sewing = BRepBuilderAPI_Sewing(1e-3)
    sewing.Add(BRepBuilderAPI_MakeFace(over, 1e-6).Face())
    # Walked anticlockwise from above: along v = 0, then u = 1, then v = 1 back, then u = 0 back.
    sides = (
        (over.VIso(0.0), False),
        (over.UIso(1.0), False),
        (over.VIso(1.0), True),
        (over.UIso(0.0), True),
    )
    corners = []
    for curve, backwards in sides:
        if backwards:
            curve = curve.Reversed()
        first, last = curve.Value(curve.FirstParameter()), curve.Value(curve.LastParameter())
        p, q = gp_Pnt(first.X(), first.Y(), 0.0), gp_Pnt(last.X(), last.Y(), 0.0)
        corners.append(p)
        edges = [
            BRepBuilderAPI_MakeEdge(curve).Edge(),
            line(last, q),
            line(q, p),
            line(p, first),
        ]
        sewing.Add(BRepBuilderAPI_MakeFace(wire(edges), True).Face())
    sewing.Add(
        BRepBuilderAPI_MakeFace(wire([line(a, b) for a, b in zip(corners, corners[1:] + corners[:1])]), True).Face()
    )
    sewing.Perform()
    shells = TopExp_Explorer(sewing.SewedShape(), TopAbs_SHELL)
    if not shells.More():
        raise RuntimeError("the height field's faces did not sew into a shell")
    made = BRepBuilderAPI_MakeSolid(TopoDS.Shell_s(shells.Current())).Solid()
    fix = ShapeFix_Solid(made)
    fix.Perform()
    return fix.Solid()


def build(heights, cell, base, exaggeration=1.0, origin=None, max_poles=DEFAULT_MAX_POLES):
    """'(solid, info)': the height field of a grid of heights, as a solid.

    'heights[i][j]' are in mm (NaN where there is none), cell i along X and j
    along Y; 'cell' is a cell's size in mm, (along X, along Y) or one number;
    the lowest height stands 'base' mm above z = 0, and every height is
    'exaggeration' times what it was above the lowest. 'origin' is where the
    grid's corner is, (x, y) in mm; by default the grid is centred on the origin.
    'info' says what was built, for the part's log.
    """
    heights = filled(heights)
    nx, ny = heights.shape
    if nx < 2 or ny < 2:
        raise ValueError("a height field needs at least 2 x 2 heights, and this has %d x %d" % (nx, ny))
    cx, cy = (float(cell), float(cell)) if numpy.isscalar(cell) else (float(cell[0]), float(cell[1]))
    if not (cx > 0.0 and cy > 0.0):
        raise ValueError("a cell is larger than nothing, and this one is %s x %s mm" % (cx, cy))
    width, depth = nx * cx, ny * cy
    if origin is None:
        x0, y0 = -width / 2.0, -depth / 2.0
    else:
        x0, y0 = float(origin[0]), float(origin[1])
    extent = (x0, y0, x0 + width, y0 + depth)
    lowest = float(heights.min())
    if not base > 0.0:
        raise ValueError("'base' is how far above z = 0 the lowest height stands, and is more than nothing")
    lifted = base + (heights - lowest) * float(exaggeration)
    count_x, count_y = pole_counts(nx, ny, max_poles)
    pole_heights = poles(lifted, count_x, count_y)
    info = {
        "grid": [nx, ny],
        "cell": [cx, cy],
        "poles": [count_x, count_y],
        "extent": [round(v, 6) for v in extent],
        "lowest": lowest,
        "highest": float(heights.max()),
    }
    return solid(pole_heights, extent), info


def describe(info):
    """One line for the log: what grid became what surface."""
    return "%d x %d heights, %s x %s mm each, as %d x %d poles; %.1f to %.1f mm high" % (
        info["grid"][0],
        info["grid"][1],
        _number(info["cell"][0]),
        _number(info["cell"][1]),
        info["poles"][0],
        info["poles"][1],
        info["lowest"],
        info["highest"],
    )


def _number(value):
    return ("%.3f" % value).rstrip("0").rstrip(".")


def unit_scale(unit):
    """Millimetres in one of 'unit'."""
    scales = {"m": 1000.0, "cm": 10.0, "mm": 1.0, "um": 0.001, "in": 25.4, "ft": 304.8, "us-ft": 1200000.0 / 3937.0}
    key = str(unit or "m").strip().lower()
    if key not in scales:
        raise ValueError("'unit' is one of %s, not '%s'" % (", ".join(scales), unit))
    return scales[key]


def finite(values, what):
    """'values' as a float array, said to be wrong if any of them is not a number."""
    array = numpy.asarray(values, dtype=float)
    if not numpy.isfinite(array).all():
        raise ValueError("%s holds a value that is not a number" % what)
    return array


def is_number(text):
    try:
        return math.isfinite(float(text))
    except (TypeError, ValueError):
        return False
