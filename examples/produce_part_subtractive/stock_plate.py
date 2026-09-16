# The plate the router and the drill work on. Thicker than the sheet, because
# the two machines that use it take material away in depth rather than cutting
# a flat outline.

import build123d as bd

LENGTH = 120.0
WIDTH = 80.0
THICKNESS = 12.0

with bd.BuildPart() as result:
    bd.Box(LENGTH, WIDTH, THICKNESS)

if "show_object" in locals():
    show_object(result.part.wrapped, name="stock_plate")
