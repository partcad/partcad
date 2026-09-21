# The billet one milled part is cut out of.
#
# An import hands over geometry and nothing else. 'AeroAssembly.step' says what
# each solid is; it does not say what any of them was cut from, and
# 'manufacturing.source' needs a part rather than a sentence. So this script
# makes that part: the smallest rectangular billet that holds the solid, in the
# solid's own orientation, with a machining allowance all round and the result
# rounded up to a size a stockist sells.
#
# Derived from the solid rather than typed out, and oriented to the solid rather
# than to the axes. An imported solid sits where the STEP file put it, at an
# angle to all three, so the box that is square with the coordinate system is not
# the box anybody saws: across the seven cut parts it is 2.4 times the metal, and
# 3.5 times for the mirrored strut. Here the same file that produces the part
# produces its stock, and 'dependencies:' in 'partcad.yaml' is what re-cuts the
# stock when the part is re-imported.

import math

import build123d as bd
from OCP.Bnd import Bnd_OBB
from OCP.BRepBndLib import BRepBndLib

# Which solid this is the stock for, relative to the package directory.
part = "AeroAssembly_assy_example/AeroFrame_Plate.step"

# What the saw and the facing cut take off each face before the shape appears.
allowance = 2.0

# Plate is sold by the millimetre of thickness and cut to length in coarser
# steps, so the two are rounded differently: the billet is as thin as the plate
# it can come off and as long as the next size up the stockist stacks.
plateStep = 1.0
sideStep = 5.0


def _up(value, step):
    """The next multiple of 'step' at or above 'value'."""
    return math.ceil(value / step - 1e-9) * step


shape = bd.import_step(part)

# The oriented box rather than the axis-aligned one: what a billet has to
# enclose is the solid, and the solid is not square with the coordinate system
# it was exported in. 'AddOBB_s(..., useTriangulation, useShapeTolerance,
# isOptimal=False)' is the cheap fit, which for these prismatic parts lands on
# the same box the optimal one finds.
obb = Bnd_OBB()
BRepBndLib.AddOBB_s(shape.wrapped, obb, True, True, False)

center = obb.Center()
axes = [obb.XDirection(), obb.YDirection(), obb.ZDirection()]
halves = [obb.XHSize(), obb.YHSize(), obb.ZHSize()]

# The thinnest of the three is the way the part lies on the plate, so it is the
# billet's thickness and the other two are what gets sawn off the sheet.
thin, mid, long = sorted(range(3), key=lambda i: halves[i])

thickness = _up(2.0 * halves[thin] + 2.0 * allowance, plateStep)
width = _up(2.0 * halves[mid] + 2.0 * allowance, sideStep)
length = _up(2.0 * halves[long] + 2.0 * allowance, sideStep)

plane = bd.Plane(
    origin=(center.X(), center.Y(), center.Z()),
    x_dir=(axes[long].X(), axes[long].Y(), axes[long].Z()),
    z_dir=(axes[thin].X(), axes[thin].Y(), axes[thin].Z()),
)

with bd.BuildPart() as result:
    with bd.Locations(plane.location):
        bd.Box(length, width, thickness)

if "show_object" in locals():
    show_object(result.part.wrapped, name="stock")
