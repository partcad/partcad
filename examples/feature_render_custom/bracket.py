#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
# A mounting plate: something with enough features to be worth a drawing.
# Rounded corners, four fixing holes and a cable slot each show up as a
# dimension, a radius callout or a "4x" note in the rendered drawing.
#

import build123d as bd

LENGTH = 90.0
WIDTH = 60.0
THICKNESS = 8.0
CORNER_RADIUS = 10.0
HOLE_DIAMETER = 6.5
HOLE_INSET = 12.0
SLOT_LENGTH = 34.0
SLOT_WIDTH = 12.0

with bd.BuildPart() as result:
    with bd.BuildSketch():
        bd.RectangleRounded(LENGTH, WIDTH, CORNER_RADIUS)
        with bd.Locations(
            (-LENGTH / 2 + HOLE_INSET, -WIDTH / 2 + HOLE_INSET),
            (LENGTH / 2 - HOLE_INSET, -WIDTH / 2 + HOLE_INSET),
            (-LENGTH / 2 + HOLE_INSET, WIDTH / 2 - HOLE_INSET),
            (LENGTH / 2 - HOLE_INSET, WIDTH / 2 - HOLE_INSET),
        ):
            bd.Circle(HOLE_DIAMETER / 2, mode=bd.Mode.SUBTRACT)
        bd.SlotOverall(SLOT_LENGTH, SLOT_WIDTH, mode=bd.Mode.SUBTRACT)
    bd.extrude(amount=THICKNESS)

if "show_object" in locals():
    show_object(result.part.wrapped, name="bracket")
