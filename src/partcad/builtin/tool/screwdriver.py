# The likeness of a screwdriver, for the assembly instruction book to draw
# wherever a step names one as its driver.
#
# It follows the same convention every tool visual in PartCAD does: the working
# end - here the very tip of the bit - is at the origin, and the tool extends
# along -Z, because a port's +Z points *into* the object it belongs to. A driver
# drawn at a screw's drive port therefore stands on the head of the screw,
# pointing the way the screw goes in.
#
# 'tip' is what makes one screwdriver of this script rather than another, which
# is why `//builtin` declares the same file twice with different parameters
# instead of carrying two nearly identical scripts.

import build123d as bd

# Which recess the bit fits: "philips", "hex" or "slotted".
tip = "philips"
# The size of that recess, in mm: across the flats of a hex, across the cross of
# a Phillips, along the blade of a slotted one.
tip_size = 4.0

TIP_LENGTH = 6.0
SHAFT_RADIUS = 2.5
SHAFT_LENGTH = 45.0
HANDLE_RADIUS = 11.0
HANDLE_LENGTH = 55.0


def _bit():
    """The business end, from the tip at z=0 up to where the shaft starts."""
    if tip == "hex":
        # 'radius' is the apothem with 'major_radius=False', which is half of
        # the across-flats size a hex key is named by.
        profile = bd.RegularPolygon(radius=tip_size / 2.0, side_count=6, major_radius=False)
        return bd.extrude(profile, amount=TIP_LENGTH)

    if tip == "slotted":
        return bd.Box(
            tip_size,
            tip_size / 4.0,
            TIP_LENGTH,
            align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN),
        )

    # Phillips: a cross, tapered so that it wedges into the recess rather than
    # standing on it. The taper is a cone the cross is cut down to.
    arm = tip_size / 5.0
    cross = bd.extrude(bd.Rectangle(tip_size, arm) + bd.Rectangle(arm, tip_size), amount=TIP_LENGTH)
    taper = bd.Cone(
        bottom_radius=0.4,
        top_radius=SHAFT_RADIUS,
        height=TIP_LENGTH,
        align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN),
    )
    return cross & taper


_shaft_base = TIP_LENGTH
_handle_base = _shaft_base + SHAFT_LENGTH

_driver = _bit()
_driver += bd.Pos(0, 0, _shaft_base) * bd.Cylinder(
    SHAFT_RADIUS, SHAFT_LENGTH, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN)
)
_driver += bd.Pos(0, 0, _handle_base) * bd.Cylinder(
    HANDLE_RADIUS, HANDLE_LENGTH, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN)
)
# The rounded end of the handle, which is what the palm sits against.
_driver += bd.Pos(0, 0, _handle_base + HANDLE_LENGTH) * bd.Sphere(HANDLE_RADIUS)

# Built pointing up, from the tip at the origin, and then turned over: the
# convention above puts the tool on the -Z side of the port it works on.
result = bd.mirror(_driver, about=bd.Plane.XY)

if "show_object" in locals():
    show_object(result.wrapped, name="screwdriver")
