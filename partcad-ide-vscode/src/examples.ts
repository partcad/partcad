//
// PartCAD, 2024
//
// Author: Roman Kuzmenko
// Created: 2024-12-28
//
// Licensed under Apache License, Version 2.0.
//

export const examples: { [kind: string]: { [name: string]: string } } = {
    // eslint-disable-next-line @typescript-eslint/naming-convention
    CadQuery: {
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 01: Simple Rectangular Plate': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq
result = cq.Workplane("front").box(2.0, 2.0, 0.5)
if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 02: Plate with Hole': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

# The dimensions of the box. These can be modified rather than changing the
# object's code directly.
length = 80.0
height = 60.0
thickness = 10.0
center_hole_dia = 22.0

# Create a box based on the dimensions above and add a 22mm center hole
result = (
    cq.Workplane("XY")
    .box(length, height, thickness)
    .faces(">Z")
    .workplane()
    .hole(center_hole_dia)
)

if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 03: An extruded prismatic solid': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

result = cq.Workplane("front").circle(2.0).rect(0.5, 0.75).extrude(0.5)

if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 04: Building Profiles using lines and arcs': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

result = (
    cq.Workplane("front")
    .lineTo(2.0, 0)
    .lineTo(2.0, 1.0)
    .threePointArc((1.0, 1.5), (0.0, 1.0))
    .close()
    .extrude(0.25)
)

if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 05: Moving The Current working point': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

result = cq.Workplane("front").circle(
    3.0
)  # current point is the center of the circle, at (0, 0)
result = result.center(1.5, 0.0).rect(0.5, 0.5)  # new work center is (1.5, 0.0)

result = result.center(-1.5, 1.5).circle(0.25)  # new work center is (0.0, 1.5).
# The new center is specified relative to the previous center, not global coordinates!

result = result.extrude(0.25)

if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 06: Using Point Lists': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

result = cq.Workplane("front").box(2.0, 2.0, 0.5)

if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 07: Polygons': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

result = (
    cq.Workplane("front")
    .box(3.0, 4.0, 0.25)
    .pushPoints([(0, 0.75), (0, -0.75)])
    .polygon(6, 1.0)
    .cutThruAll()
)

if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 08: Polylines': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

(L, H, W, t) = (100.0, 20.0, 20.0, 1.0)
pts = [
    (0, H / 2.0),
    (W / 2.0, H / 2.0),
    (W / 2.0, (H / 2.0 - t)),
    (t / 2.0, (H / 2.0 - t)),
    (t / 2.0, (t - H / 2.0)),
    (W / 2.0, (t - H / 2.0)),
    (W / 2.0, H / -2.0),
    (0, H / -2.0),
]
result = cq.Workplane("front").polyline(pts).mirrorY().extrude(L)

if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 09: Defining an Edge with a Spline': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

s = cq.Workplane("XY")
sPnts = [
    (2.75, 1.5),
    (2.5, 1.75),
    (2.0, 1.5),
    (1.5, 1.0),
    (1.0, 1.25),
    (0.5, 1.0),
    (0, 1.0),
]
r = s.lineTo(3.0, 0).lineTo(3.0, 1.0).spline(sPnts, includeCurrent=True).close()
result = r.extrude(0.5)

if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 10: Mirroring Symmetric Geometry': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

r = cq.Workplane("front").hLine(1.0)  # 1.0 is the distance, not coordinate
r = (
    r.vLine(0.5).hLine(-0.25).vLine(-0.25).hLineTo(0.0)
)  # hLineTo allows using xCoordinate not distance
result = r.mirrorY().extrude(0.25)  # mirror the geometry and extrude

if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 11: Mirroring 3D Objects': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

result0 = (
    cq.Workplane("XY")
    .moveTo(10, 0)
    .lineTo(5, 0)
    .threePointArc((3.9393, 0.4393), (3.5, 1.5))
    .threePointArc((3.0607, 2.5607), (2, 3))
    .lineTo(1.5, 3)
    .threePointArc((0.4393, 3.4393), (0, 4.5))
    .lineTo(0, 13.5)
    .threePointArc((0.4393, 14.5607), (1.5, 15))
    .lineTo(28, 15)
    .lineTo(28, 13.5)
    .lineTo(24, 13.5)
    .lineTo(24, 11.5)
    .lineTo(27, 11.5)
    .lineTo(27, 10)
    .lineTo(22, 10)
    .lineTo(22, 13.2)
    .lineTo(14.5, 13.2)
    .lineTo(14.5, 10)
    .lineTo(12.5, 10)
    .lineTo(12.5, 13.2)
    .lineTo(5.5, 13.2)
    .lineTo(5.5, 2)
    .threePointArc((5.793, 1.293), (6.5, 1))
    .lineTo(10, 1)
    .close()
)
result = result0.extrude(100)

result = result.rotate((0, 0, 0), (1, 0, 0), 90)

result = result.translate(result.val().BoundingBox().center.multiply(-1))

mirXY_neg = result.mirror(mirrorPlane="XY", basePointVector=(0, 0, -30))
mirXY_pos = result.mirror(mirrorPlane="XY", basePointVector=(0, 0, 30))
mirZY_neg = result.mirror(mirrorPlane="ZY", basePointVector=(-30, 0, 0))
mirZY_pos = result.mirror(mirrorPlane="ZY", basePointVector=(30, 0, 0))

result = result.union(mirXY_neg).union(mirXY_pos).union(mirZY_neg).union(mirZY_pos)

if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 12: Mirroring From Faces': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

result = cq.Workplane("XY").line(0, 1).line(1, 0).line(0, -0.5).close().extrude(1)

result = result.mirror(result.faces(">X"), union=True)

if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 13: Creating Workplanes on Faces': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

result = cq.Workplane("front").box(2, 3, 0.5)  # make a basic prism
result = (
    result.faces(">Z").workplane().hole(0.5)
)  # find the top-most face and make a hole

if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 14: Locating a Workplane on a vertex': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

result = cq.Workplane("front").box(3, 2, 0.5)  # make a basic prism
result = (
    result.faces(">Z").vertices("<XY").workplane(centerOption="CenterOfMass")
)  # select the lower left vertex and make a workplane
result = result.circle(1.0).cutThruAll()  # cut the corner out

if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 15: Offset Workplanes': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

result = cq.Workplane("front").box(3, 2, 0.5)  # make a basic prism
result = result.faces("<X").workplane(
    offset=0.75
)  # workplane is offset from the object surface
result = result.circle(1.0).extrude(0.5)  # disc

if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 16: Copying Workplanes': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

result = (
    cq.Workplane("front")
    .circle(1)
    .extrude(10)  # make a cylinder
    # We want to make a second cylinder perpendicular to the first,
    # but we have no face to base the workplane off
    .copyWorkplane(
        # create a temporary object with the required workplane
        cq.Workplane("right", origin=(-5, 0, 0))
    )
    .circle(1)
    .extrude(10)
)

if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 17: Rotated Workplanes': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

result = (
    cq.Workplane("front")
    .box(4.0, 4.0, 0.25)
    .faces(">Z")
    .workplane()
    .transformed(offset=cq.Vector(0, -1.5, 1.0), rotate=cq.Vector(60, 0, 0))
    .rect(1.5, 1.5, forConstruction=True)
    .vertices()
    .hole(0.25)
)

if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 18: Using construction Geometry': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

result = (
    cq.Workplane("front")
    .box(2, 2, 0.5)
    .faces(">Z")
    .workplane()
    .rect(1.5, 1.5, forConstruction=True)
    .vertices()
    .hole(0.125)
)

if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 19: Shelling To Create Thin features': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

result = cq.Workplane("front").box(2, 2, 2).faces("+Z or -X or +X").shell(0.1)

if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 20: Making Lofts': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

result = (
    cq.Workplane("front")
    .box(4.0, 4.0, 0.25)
    .faces(">Z")
    .circle(1.5)
    .workplane(offset=3.0)
    .rect(0.75, 0.5)
    .loft(combine=True)
)

if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 21: Extruding until a given face (1)': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

result = (
    cq.Workplane(origin=(20, 0, 0))
    .circle(2)
    .revolve(180, (-20, 0, 0), (-20, -1, 0))
    .center(-20, 0)
    .workplane()
    .rect(20, 4)
    .extrude("next")
)

if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 22: Extruding until a given face (2)': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

skyscrapers_locations = [(-16, 1), (-8, 0), (7, 0.2), (17, -1.2)]
angles = iter([15, 0, -8, 10])
skyscrapers = (
    cq.Workplane()
    .pushPoints(skyscrapers_locations)
    .eachpoint(
        lambda loc: (
            cq.Workplane()
            .rect(5, 16)
            .workplane(offset=10)
            .ellipse(3, 8)
            .workplane(offset=10)
            .slot2D(20, 5, 90)
            .loft()
            .rotateAboutCenter((0, 0, 1), next(angles))
            .val()
            .located(loc)
        )
    )
)

result = (
    skyscrapers.transformed((0, -90, 0))
    .moveTo(15, 0)
    .rect(3, 3, forConstruction=True)
    .vertices()
    .circle(1)
    .cutBlind("last")
)

if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 23: Extruding until a given face (3)': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

sphere = cq.Workplane().sphere(5)
base = cq.Workplane(origin=(0, 0, -2)).box(12, 12, 10).cut(sphere).edges("|Z").fillet(2)
sphere_face = base.faces(">>X[2] and (not |Z) and (not |Y)").val()
base = base.faces("<Z").workplane().circle(2).extrude(10)

shaft = cq.Workplane().sphere(4.5).circle(1.5).extrude(20)

spherical_joint = (
    base.union(shaft)
    .faces(">X")
    .workplane(centerOption="CenterOfMass")
    .move(0, 4)
    .slot2D(10, 2, 90)
    .cutBlind(sphere_face)
    .workplane(offset=10)
    .move(0, 2)
    .circle(0.9)
    .extrude("next")
)

result = spherical_joint

if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 24: Making Counter-bored and Counter-sunk Holes': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

result = (
    cq.Workplane(cq.Plane.XY())
    .box(4, 2, 0.5)
    .faces(">Z")
    .workplane()
    .rect(3.5, 1.5, forConstruction=True)
    .vertices()
    .cboreHole(0.125, 0.25, 0.125, depth=None)
)

if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 25: Offsetting wires in 2D (1)': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

original = cq.Workplane().polygon(5, 10).extrude(0.1).translate((0, 0, 2))
arc = cq.Workplane().polygon(5, 10).offset2D(1, "arc").extrude(0.1).translate((0, 0, 1))
intersection = cq.Workplane().polygon(5, 10).offset2D(1, "intersection").extrude(0.1)
result = original.add(arc).add(intersection)

if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 26: Offsetting wires in 2D (2)': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

result = (
    cq.Workplane()
    .box(4, 2, 0.5)
    .faces(">Z")
    .edges()
    .toPending()
    .offset2D(-0.25, forConstruction=True)
    .vertices()
    .cboreHole(0.125, 0.25, 0.125, depth=None)
)

if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 27: Rounding Corners with Fillet': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

result = cq.Workplane("XY").box(3, 3, 0.5).edges("|Z").fillet(0.125)

if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 28: Tagging objects (1)': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

result = (
    cq.Workplane("XY")
    # create and tag the base workplane
    .box(10, 10, 10)
    .faces(">Z")
    .workplane()
    .tag("baseplane")
    # extrude a cylinder
    .center(-3, 0)
    .circle(1)
    .extrude(3)
    # to reselect the base workplane, simply
    .workplaneFromTagged("baseplane")
    # extrude a second cylinder
    .center(3, 0)
    .circle(1)
    .extrude(2)
)

if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 29: Tagging objects (2)': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

result = (
    cq.Workplane("XY")
    # create a triangular prism and tag it
    .polygon(3, 5)
    .extrude(4)
    .tag("prism")
    # create a sphere that obscures the prism
    .sphere(10)
    # create features based on the prism's faces
    .faces("<X", tag="prism")
    .workplane()
    .circle(1)
    .cutThruAll()
    .faces(">X", tag="prism")
    .faces(">Y")
    .workplane()
    .circle(1)
    .cutThruAll()
)

if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 30: A Parametric Bearing Pillow Block': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

(length, height, bearing_diam, thickness, padding) = (30.0, 40.0, 22.0, 10.0, 8.0)

result = (
    cq.Workplane("XY")
    .box(length, height, thickness)
    .faces(">Z")
    .workplane()
    .hole(bearing_diam)
    .faces(">Z")
    .workplane()
    .rect(length - padding, height - padding, forConstruction=True)
    .vertices()
    .cboreHole(2.4, 4.4, 2.1)
)

if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 31: Splitting an Object': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

c = cq.Workplane("XY").box(1, 1, 1).faces(">Z").workplane().circle(0.25).cutThruAll()

# now cut it in half sideways
result = c.faces(">Y").workplane(-0.5).split(keepTop=True)

if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 32: The Classic OCC Bottle': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

(L, w, t) = (20.0, 6.0, 3.0)
s = cq.Workplane("XY")

# Draw half the profile of the bottle and extrude it
p = (
    s.center(-L / 2.0, 0)
    .vLine(w / 2.0)
    .threePointArc((L / 2.0, w / 2.0 + t), (L, w / 2.0))
    .vLine(-w / 2.0)
    .mirrorX()
    .extrude(30.0, True)
)

# Make the neck
p = p.faces(">Z").workplane(centerOption="CenterOfMass").circle(3.0).extrude(2.0, True)

# Make a shell
result = p.faces(">Z").shell(0.3)

if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 33: A Parametric Enclosure': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

# parameter definitions
p_outerWidth = 100.0  # Outer width of box enclosure
p_outerLength = 150.0  # Outer length of box enclosure
p_outerHeight = 50.0  # Outer height of box enclosure

p_thickness = 3.0  # Thickness of the box walls
p_sideRadius = 10.0  # Radius for the curves around the sides of the box
p_topAndBottomRadius = (
    2.0  # Radius for the curves on the top and bottom edges of the box
)

p_screwpostInset = 12.0  # How far in from the edges the screw posts should be place.
p_screwpostID = 4.0  # Inner Diameter of the screw post holes, should be roughly screw diameter not including threads
p_screwpostOD = 10.0  # Outer Diameter of the screw posts.\nDetermines overall thickness of the posts

p_boreDiameter = 8.0  # Diameter of the counterbore hole, if any
p_boreDepth = 1.0  # Depth of the counterbore hole, if
p_countersinkDiameter = 0.0  # Outer diameter of countersink. Should roughly match the outer diameter of the screw head
p_countersinkAngle = 90.0  # Countersink angle (complete angle between opposite sides, not from center to one side)
p_flipLid = True  # Whether to place the lid with the top facing down or not.
p_lipHeight = 1.0  # Height of lip on the underside of the lid.\nSits inside the box body for a snug fit.

# outer shell
oshell = (
    cq.Workplane("XY")
    .rect(p_outerWidth, p_outerLength)
    .extrude(p_outerHeight + p_lipHeight)
)

# weird geometry happens if we make the fillets in the wrong order
if p_sideRadius > p_topAndBottomRadius:
    oshell = oshell.edges("|Z").fillet(p_sideRadius)
    oshell = oshell.edges("#Z").fillet(p_topAndBottomRadius)
else:
    oshell = oshell.edges("#Z").fillet(p_topAndBottomRadius)
    oshell = oshell.edges("|Z").fillet(p_sideRadius)

# inner shell
ishell = (
    oshell.faces("<Z")
    .workplane(p_thickness, True)
    .rect((p_outerWidth - 2.0 * p_thickness), (p_outerLength - 2.0 * p_thickness))
    .extrude(
        (p_outerHeight - 2.0 * p_thickness), False
    )  # set combine false to produce just the new boss
)
ishell = ishell.edges("|Z").fillet(p_sideRadius - p_thickness)

# make the box outer box
box = oshell.cut(ishell)

# make the screw posts
POSTWIDTH = p_outerWidth - 2.0 * p_screwpostInset
POSTLENGTH = p_outerLength - 2.0 * p_screwpostInset

box = (
    box.faces(">Z")
    .workplane(-p_thickness)
    .rect(POSTWIDTH, POSTLENGTH, forConstruction=True)
    .vertices()
    .circle(p_screwpostOD / 2.0)
    .circle(p_screwpostID / 2.0)
    .extrude(-1.0 * (p_outerHeight + p_lipHeight - p_thickness), True)
)

# split lid into top and bottom parts
(lid, bottom) = (
    box.faces(">Z")
    .workplane(-p_thickness - p_lipHeight)
    .split(keepTop=True, keepBottom=True)
    .all()
)  # splits into two solids

# translate the lid, and subtract the bottom from it to produce the lid inset
lowerLid = lid.translate((0, 0, -p_lipHeight))
cutlip = lowerLid.cut(bottom).translate(
    (p_outerWidth + p_thickness, 0, p_thickness - p_outerHeight + p_lipHeight)
)

# compute centers for screw holes
topOfLidCenters = (
    cutlip.faces(">Z")
    .workplane(centerOption="CenterOfMass")
    .rect(POSTWIDTH, POSTLENGTH, forConstruction=True)
    .vertices()
)

# add holes of the desired type
if p_boreDiameter > 0 and p_boreDepth > 0:
    topOfLid = topOfLidCenters.cboreHole(
        p_screwpostID, p_boreDiameter, p_boreDepth, 2.0 * p_thickness
    )
elif p_countersinkDiameter > 0 and p_countersinkAngle > 0:
    topOfLid = topOfLidCenters.cskHole(
        p_screwpostID, p_countersinkDiameter, p_countersinkAngle, 2.0 * p_thickness
    )
else:
    topOfLid = topOfLidCenters.hole(p_screwpostID, 2.0 * p_thickness)

# flip lid upside down if desired
if p_flipLid:
    topOfLid = topOfLid.rotateAboutCenter((1, 0, 0), 180)

# return the combined result
result = topOfLid.union(bottom)

if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 34: Lego Brick': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

#####
# Inputs
######
lbumps = 6  # number of bumps long
wbumps = 2  # number of bumps wide
thin = True  # True for thin, False for thick

#
# Lego Brick Constants-- these make a Lego brick a Lego :)
#
pitch = 8.0
clearance = 0.1
bumpDiam = 4.8
bumpHeight = 1.8
if thin:
    height = 3.2
else:
    height = 9.6

t = (pitch - (2 * clearance) - bumpDiam) / 2.0
postDiam = pitch - t  # works out to 6.5
total_length = lbumps * pitch - 2.0 * clearance
total_width = wbumps * pitch - 2.0 * clearance

# make the base
s = cq.Workplane("XY").box(total_length, total_width, height)

# shell inwards not outwards
s = s.faces("<Z").shell(-1.0 * t)

# make the bumps on the top
s = (
    s.faces(">Z")
    .workplane()
    .rarray(pitch, pitch, lbumps, wbumps, True)
    .circle(bumpDiam / 2.0)
    .extrude(bumpHeight)
)

# add posts on the bottom. posts are different diameter depending on geometry
# solid studs for 1 bump, tubes for multiple, none for 1x1
tmp = s.faces("<Z").workplane(invert=True)

if lbumps > 1 and wbumps > 1:
    tmp = (
        tmp.rarray(pitch, pitch, lbumps - 1, wbumps - 1, center=True)
        .circle(postDiam / 2.0)
        .circle(bumpDiam / 2.0)
        .extrude(height - t)
    )
elif lbumps > 1:
    tmp = (
        tmp.rarray(pitch, pitch, lbumps - 1, 1, center=True)
        .circle(t)
        .extrude(height - t)
    )
elif wbumps > 1:
    tmp = (
        tmp.rarray(pitch, pitch, 1, wbumps - 1, center=True)
        .circle(t)
        .extrude(height - t)
    )
else:
    tmp = s

if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 35: Braille Example': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

from collections import namedtuple


# text_lines is a list of text lines.
# Braille (converted with braille-converter:
# https://github.com/jpaugh/braille-converter.git).
text_lines = ["⠠ ⠋ ⠗ ⠑ ⠑ ⠠ ⠉ ⠠ ⠁ ⠠ ⠙"]
# See http://www.tiresias.org/research/reports/braille_cell.htm for examples
# of braille cell geometry.
horizontal_interdot = 2.5
vertical_interdot = 2.5
horizontal_intercell = 6
vertical_interline = 10
dot_height = 0.5
dot_diameter = 1.3

base_thickness = 1.5

# End of configuration.
BrailleCellGeometry = namedtuple(
    "BrailleCellGeometry",
    (
        "horizontal_interdot",
        "vertical_interdot",
        "intercell",
        "interline",
        "dot_height",
        "dot_diameter",
    ),
)


class Point(object):
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __add__(self, other):
        return Point(self.x + other.x, self.y + other.y)

    def __len__(self):
        return 2

    def __getitem__(self, index):
        return (self.x, self.y)[index]

    def __str__(self):
        return "({}, {})".format(self.x, self.y)


def brailleToPoints(text, cell_geometry):
    # Unicode bit pattern (cf. https://en.wikipedia.org/wiki/Braille_Patterns).
    mask1 = 0b00000001
    mask2 = 0b00000010
    mask3 = 0b00000100
    mask4 = 0b00001000
    mask5 = 0b00010000
    mask6 = 0b00100000
    mask7 = 0b01000000
    mask8 = 0b10000000
    masks = (mask1, mask2, mask3, mask4, mask5, mask6, mask7, mask8)

    # Corresponding dot position
    w = cell_geometry.horizontal_interdot
    h = cell_geometry.vertical_interdot
    pos1 = Point(0, 2 * h)
    pos2 = Point(0, h)
    pos3 = Point(0, 0)
    pos4 = Point(w, 2 * h)
    pos5 = Point(w, h)
    pos6 = Point(w, 0)
    pos7 = Point(0, -h)
    pos8 = Point(w, -h)
    pos = (pos1, pos2, pos3, pos4, pos5, pos6, pos7, pos8)

    # Braille blank pattern (u'\u2800').
    blank = "⠀"
    points = []
    # Position of dot1 along the x-axis (horizontal).
    character_origin = 0
    for c in text:
        for m, p in zip(masks, pos):
            delta_to_blank = ord(c) - ord(blank)
            if m & delta_to_blank:
                points.append(p + Point(character_origin, 0))
        character_origin += cell_geometry.intercell
    return points


def get_plate_height(text_lines, cell_geometry):
    # cell_geometry.vertical_interdot is also used as space between base
    # borders and characters.
    return (
        2 * cell_geometry.vertical_interdot
        + 2 * cell_geometry.vertical_interdot
        + (len(text_lines) - 1) * cell_geometry.interline
    )


def get_plate_width(text_lines, cell_geometry):
    # cell_geometry.horizontal_interdot is also used as space between base
    # borders and characters.
    max_len = max([len(t) for t in text_lines])
    return (
        2 * cell_geometry.horizontal_interdot
        + cell_geometry.horizontal_interdot
        + (max_len - 1) * cell_geometry.intercell
    )


def get_cylinder_radius(cell_geometry):
    """Return the radius the cylinder should have
    The cylinder have the same radius as the half-sphere make the dots (the
    hidden and the shown part of the dots).
    The radius is such that the spherical cap with diameter
    cell_geometry.dot_diameter has a height of cell_geometry.dot_height.
    """
    h = cell_geometry.dot_height
    r = cell_geometry.dot_diameter / 2
    return (r**2 + h**2) / 2 / h


def get_base_plate_thickness(plate_thickness, cell_geometry):
    """Return the height on which the half spheres will sit"""
    return (
        plate_thickness + get_cylinder_radius(cell_geometry) - cell_geometry.dot_height
    )


def make_base(text_lines, cell_geometry, plate_thickness):
    base_width = get_plate_width(text_lines, cell_geometry)
    base_height = get_plate_height(text_lines, cell_geometry)
    base_thickness = get_base_plate_thickness(plate_thickness, cell_geometry)
    base = cq.Workplane("XY").box(
        base_width, base_height, base_thickness, centered=False
    )
    return base


def make_embossed_plate(text_lines, cell_geometry):
    """Make an embossed plate with dots as spherical caps
    Method:
        - make a thin plate on which sit cylinders
        - fillet the upper edge of the cylinders so to get pseudo half-spheres
        - make the union with a thicker plate so that only the sphere caps stay
          "visible".
    """
    base = make_base(text_lines, cell_geometry, base_thickness)

    dot_pos = []
    base_width = get_plate_width(text_lines, cell_geometry)
    base_height = get_plate_height(text_lines, cell_geometry)
    y = base_height - 3 * cell_geometry.vertical_interdot
    line_start_pos = Point(cell_geometry.horizontal_interdot, y)
    for text in text_lines:
        dots = brailleToPoints(text, cell_geometry)
        dots = [p + line_start_pos for p in dots]
        dot_pos += dots
        line_start_pos += Point(0, -cell_geometry.interline)

    r = get_cylinder_radius(cell_geometry)
    base = (
        base.faces(">Z")
        .vertices("<XY")
        .workplane()
        .pushPoints(dot_pos)
        .circle(r)
        .extrude(r)
    )
    # Make a fillet almost the same radius to get a pseudo spherical cap.
    base = base.faces(">Z").edges().fillet(r - 0.001)
    hidding_box = cq.Workplane("XY").box(
        base_width, base_height, base_thickness, centered=False
    )
    result = hidding_box.union(base)
    return result


_cell_geometry = BrailleCellGeometry(
    horizontal_interdot,
    vertical_interdot,
    horizontal_intercell,
    vertical_interline,
    dot_height,
    dot_diameter,
)

if base_thickness < get_cylinder_radius(_cell_geometry):
    raise ValueError("Base thickness should be at least {}".format(dot_height))

result = make_embossed_plate(text_lines, _cell_geometry)

if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 36: Panel With Various Connector Holes': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

# The dimensions of the model. These can be modified rather than changing the
# object's code directly.
width = 400
height = 500
thickness = 2

# Create a plate with two polygons cut through it
result = cq.Workplane("front").box(width, height, thickness)

h_sep = 60
for idx in range(4):
    result = (
        result.workplane(offset=1, centerOption="CenterOfBoundBox")
        .center(157, 210 - idx * h_sep)
        .moveTo(-23.5, 0)
        .circle(1.6)
        .moveTo(23.5, 0)
        .circle(1.6)
        .moveTo(-17.038896, -5.7)
        .threePointArc((-19.44306, -4.70416), (-20.438896, -2.3))
        .lineTo(-21.25, 2.3)
        .threePointArc((-20.25416, 4.70416), (-17.85, 5.7))
        .lineTo(17.85, 5.7)
        .threePointArc((20.25416, 4.70416), (21.25, 2.3))
        .lineTo(20.438896, -2.3)
        .threePointArc((19.44306, -4.70416), (17.038896, -5.7))
        .close()
        .cutThruAll()
    )

for idx in range(4):
    result = (
        result.workplane(offset=1, centerOption="CenterOfBoundBox")
        .center(157, -30 - idx * h_sep)
        .moveTo(-16.65, 0)
        .circle(1.6)
        .moveTo(16.65, 0)
        .circle(1.6)
        .moveTo(-10.1889, -5.7)
        .threePointArc((-12.59306, -4.70416), (-13.5889, -2.3))
        .lineTo(-14.4, 2.3)
        .threePointArc((-13.40416, 4.70416), (-11, 5.7))
        .lineTo(11, 5.7)
        .threePointArc((13.40416, 4.70416), (14.4, 2.3))
        .lineTo(13.5889, -2.3)
        .threePointArc((12.59306, -4.70416), (10.1889, -5.7))
        .close()
        .cutThruAll()
    )

h_sep4DB9 = 30
for idx in range(8):
    result = (
        result.workplane(offset=1, centerOption="CenterOfBoundBox")
        .center(91, 225 - idx * h_sep4DB9)
        .moveTo(-12.5, 0)
        .circle(1.6)
        .moveTo(12.5, 0)
        .circle(1.6)
        .moveTo(-6.038896, -5.7)
        .threePointArc((-8.44306, -4.70416), (-9.438896, -2.3))
        .lineTo(-10.25, 2.3)
        .threePointArc((-9.25416, 4.70416), (-6.85, 5.7))
        .lineTo(6.85, 5.7)
        .threePointArc((9.25416, 4.70416), (10.25, 2.3))
        .lineTo(9.438896, -2.3)
        .threePointArc((8.44306, -4.70416), (6.038896, -5.7))
        .close()
        .cutThruAll()
    )

for idx in range(4):
    result = (
        result.workplane(offset=1, centerOption="CenterOfBoundBox")
        .center(25, 210 - idx * h_sep)
        .moveTo(-23.5, 0)
        .circle(1.6)
        .moveTo(23.5, 0)
        .circle(1.6)
        .moveTo(-17.038896, -5.7)
        .threePointArc((-19.44306, -4.70416), (-20.438896, -2.3))
        .lineTo(-21.25, 2.3)
        .threePointArc((-20.25416, 4.70416), (-17.85, 5.7))
        .lineTo(17.85, 5.7)
        .threePointArc((20.25416, 4.70416), (21.25, 2.3))
        .lineTo(20.438896, -2.3)
        .threePointArc((19.44306, -4.70416), (17.038896, -5.7))
        .close()
        .cutThruAll()
    )

for idx in range(4):
    result = (
        result.workplane(offset=1, centerOption="CenterOfBoundBox")
        .center(25, -30 - idx * h_sep)
        .moveTo(-16.65, 0)
        .circle(1.6)
        .moveTo(16.65, 0)
        .circle(1.6)
        .moveTo(-10.1889, -5.7)
        .threePointArc((-12.59306, -4.70416), (-13.5889, -2.3))
        .lineTo(-14.4, 2.3)
        .threePointArc((-13.40416, 4.70416), (-11, 5.7))
        .lineTo(11, 5.7)
        .threePointArc((13.40416, 4.70416), (14.4, 2.3))
        .lineTo(13.5889, -2.3)
        .threePointArc((12.59306, -4.70416), (10.1889, -5.7))
        .close()
        .cutThruAll()
    )

for idx in range(8):
    result = (
        result.workplane(offset=1, centerOption="CenterOfBoundBox")
        .center(-41, 225 - idx * h_sep4DB9)
        .moveTo(-12.5, 0)
        .circle(1.6)
        .moveTo(12.5, 0)
        .circle(1.6)
        .moveTo(-6.038896, -5.7)
        .threePointArc((-8.44306, -4.70416), (-9.438896, -2.3))
        .lineTo(-10.25, 2.3)
        .threePointArc((-9.25416, 4.70416), (-6.85, 5.7))
        .lineTo(6.85, 5.7)
        .threePointArc((9.25416, 4.70416), (10.25, 2.3))
        .lineTo(9.438896, -2.3)
        .threePointArc((8.44306, -4.70416), (6.038896, -5.7))
        .close()
        .cutThruAll()
    )

for idx in range(4):
    result = (
        result.workplane(offset=1, centerOption="CenterOfBoundBox")
        .center(-107, 210 - idx * h_sep)
        .moveTo(-23.5, 0)
        .circle(1.6)
        .moveTo(23.5, 0)
        .circle(1.6)
        .moveTo(-17.038896, -5.7)
        .threePointArc((-19.44306, -4.70416), (-20.438896, -2.3))
        .lineTo(-21.25, 2.3)
        .threePointArc((-20.25416, 4.70416), (-17.85, 5.7))
        .lineTo(17.85, 5.7)
        .threePointArc((20.25416, 4.70416), (21.25, 2.3))
        .lineTo(20.438896, -2.3)
        .threePointArc((19.44306, -4.70416), (17.038896, -5.7))
        .close()
        .cutThruAll()
    )

for idx in range(4):
    result = (
        result.workplane(offset=1, centerOption="CenterOfBoundBox")
        .center(-107, -30 - idx * h_sep)
        .circle(14)
        .rect(24.7487, 24.7487, forConstruction=True)
        .vertices()
        .hole(3.2)
        .cutThruAll()
    )

for idx in range(8):
    result = (
        result.workplane(offset=1, centerOption="CenterOfBoundBox")
        .center(-173, 225 - idx * h_sep4DB9)
        .moveTo(-12.5, 0)
        .circle(1.6)
        .moveTo(12.5, 0)
        .circle(1.6)
        .moveTo(-6.038896, -5.7)
        .threePointArc((-8.44306, -4.70416), (-9.438896, -2.3))
        .lineTo(-10.25, 2.3)
        .threePointArc((-9.25416, 4.70416), (-6.85, 5.7))
        .lineTo(6.85, 5.7)
        .threePointArc((9.25416, 4.70416), (10.25, 2.3))
        .lineTo(9.438896, -2.3)
        .threePointArc((8.44306, -4.70416), (6.038896, -5.7))
        .close()
        .cutThruAll()
    )

for idx in range(4):
    result = (
        result.workplane(offset=1, centerOption="CenterOfBoundBox")
        .center(-173, -30 - idx * h_sep)
        .moveTo(-2.9176, -5.3)
        .threePointArc((-6.05, 0), (-2.9176, 5.3))
        .lineTo(2.9176, 5.3)
        .threePointArc((6.05, 0), (2.9176, -5.3))
        .close()
        .cutThruAll()
    )

if "show_object" in locals():
  show_object(result)
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 37: Cycloidal gear': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import cadquery as cq

import cadquery as cq
from math import sin, cos, pi, floor


# define the generating function
def hypocycloid(t, r1, r2):
    return (
        (r1 - r2) * cos(t) + r2 * cos(r1 / r2 * t - t),
        (r1 - r2) * sin(t) + r2 * sin(-(r1 / r2 * t - t)),
    )


def epicycloid(t, r1, r2):
    return (
        (r1 + r2) * cos(t) - r2 * cos(r1 / r2 * t + t),
        (r1 + r2) * sin(t) - r2 * sin(r1 / r2 * t + t),
    )


def gear(t, r1=4, r2=1):
    if (-1) ** (1 + floor(t / 2 / pi * (r1 / r2))) < 0:
        return epicycloid(t, r1, r2)
    else:
        return hypocycloid(t, r1, r2)


# create the gear profile and extrude it
result = (
    cq.Workplane("XY")
    .parametricCurve(lambda t: gear(t * 2 * pi, 6, 1))
    .twistExtrude(15, 90)
    .faces(">Z")
    .workplane()
    .circle(2)
    .cutThruAll()
)

if "show_object" in locals():
  show_object(result)
`,
    },
    build123d: {
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 1: Cube': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import build123d as bd

with bd.BuildPart() as result:
    bd.Box(5, 5, 5)

if "show_object" in locals():
    show_object(result.part.wrapped, name="art")
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 2: Rectangular cuboid': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

import build123d as bd

with bd.BuildPart() as result:
    bd.Box(1, 2, 4)

if "show_object" in locals():
    show_object(result.part.wrapped, name="art")
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 3: Bead': `# Once PartCAD reloads the package after this example is added,
# press "Save" to have the result inspected.

from math import pi, sin
from build123d import *

with BuildPart() as art:
    slice_count = 10
    for i in range(slice_count + 1):
        with BuildSketch(Plane(origin=(0, 0, i * 3), z_dir=(0, 0, 1))) as slice:
            Circle(10 * sin(i * pi / slice_count) + 5)
    loft()
    top_bottom = art.faces().filter_by(GeomType.PLANE)
    offset(openings=top_bottom, amount=0.5)

if "show_object" in locals():
    show_object(art.part.wrapped, name="art")
`,
    },
    // eslint-disable-next-line @typescript-eslint/naming-convention
    OpenSCAD: {
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 1: CSG': `// Once PartCAD reloads the package after this example is added,
// press "Save" to have the result inspected.

// CSG.scad - Basic example of CSG usage

translate([-24,0,0]) {
    union() {
        cube(15, center=true);
        sphere(10);
    }
}

intersection() {
    cube(15, center=true);
    sphere(10);
}

translate([24,0,0]) {
    difference() {
        cube(15, center=true);
        sphere(10);
    }
}

echo(version=version());
// Written by Marius Kintel <marius@kintel.net>
//
// To the extent possible under law, the author(s) have dedicated all
// copyright and related and neighboring rights to this software to the
// public domain worldwide. This software is distributed without any
// warranty.
//
// You should have received a copy of the CC0 Public Domain
// Dedication along with this software.
// If not, see <http://creativecommons.org/publicdomain/zero/1.0/>.
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 2: LetterBlock': `// Once PartCAD reloads the package after this example is added,
// press "Save" to have the result inspected.

// LetterBlock.scad - Basic usage of text() and linear_extrude()

// Module instantiation
LetterBlock("M");

// Module definition.
// size=30 defines an optional parameter with a default value.
module LetterBlock(letter, size=30) {
    difference() {
        translate([0,0,size/4]) cube([size,size,size/2], center=true);
        translate([0,0,size/6]) {
            // convexity is needed for correct preview
            // since characters can be highly concave
            linear_extrude(height=size, convexity=4)
                text(letter,
                     size=size*22/30,
                     font="Tahoma",
                     halign="center",
                     valign="center");
        }
    }
}

echo(version=version());
// Written by Marius Kintel <marius@kintel.net>
//
// To the extent possible under law, the author(s) have dedicated all
// copyright and related and neighboring rights to this software to the
// public domain worldwide. This software is distributed without any
// warranty.
//
// You should have received a copy of the CC0 Public Domain
// Dedication along with this software.
// If not, see <http://creativecommons.org/publicdomain/zero/1.0/>.
`,
        // eslint-disable-next-line @typescript-eslint/naming-convention
        'Example 3: Logo': `// Once PartCAD reloads the package after this example is added,
// press "Save" to have the result inspected.

// logo.scad - Basic example of module, top-level variable and $fn usage

Logo(50);

// The $fn parameter will influence all objects inside this module
// It can, optionally, be overridden when instantiating the module
module Logo(size=50, $fn=100) {
    // Temporary variables
    hole = size/2;
    cylinderHeight = size * 1.25;

    // One positive object (sphere) and three negative objects (cylinders)
    difference() {
        sphere(d=size);

        cylinder(d=hole, h=cylinderHeight, center=true);
        // The '#' operator highlights the object
        #rotate([90, 0, 0]) cylinder(d=hole, h=cylinderHeight, center=true);
        rotate([0, 90, 0]) cylinder(d=hole, h=cylinderHeight, center=true);
    }
}

echo(version=version());
// Written by Clifford Wolf <clifford@clifford.at> and Marius
// Kintel <marius@kintel.net>
//
// To the extent possible under law, the author(s) have dedicated all
// copyright and related and neighboring rights to this software to the
// public domain worldwide. This software is distributed without any
// warranty.
//
// You should have received a copy of the CC0 Public Domain
// Dedication along with this software.
// If not, see <http://creativecommons.org/publicdomain/zero/1.0/>.
`,
    },
};
