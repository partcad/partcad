#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
# The doors and windows of one wall, drawn as the wall would look unrolled flat
# in front of you: X along its base from 0 to its length, Y up from the floor.
# A door stands on the floor, which an opening may: it may meet the edge of the
# wall, and only reaching past it is an error.

import build123d as bd

with bd.BuildSketch() as openings:
    # A door, 900 mm wide and 2100 mm high, 600 mm in from the start.
    with bd.Locations((600 + 450, 1050)):
        bd.Rectangle(900, 2100)
    # A window, 1500 by 1200, its sill 900 mm off the floor.
    with bd.Locations((2400 + 750, 900 + 600)):
        bd.Rectangle(1500, 1200)

# PartCAD hands a script 'show_object' to say what it made; run on its own, it
# has none.
if "show_object" in locals():
    show_object(openings.sketch)
