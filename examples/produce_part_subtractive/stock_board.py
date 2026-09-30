# A board: a length of 38 x 89 mm section, lying along Y with one end at the
# origin. Parametric in its length, because a board is sold in a handful of
# lengths and cut to any length -- the stock and the pieces cut from it are
# the same profile, and 'rail' is one of the pieces.

import build123d as bd

length = 600.0
WIDTH = 89.0
THICKNESS = 38.0

with bd.BuildPart() as result:
    with bd.Locations((WIDTH / 2.0, length / 2.0, THICKNESS / 2.0)):
        bd.Box(WIDTH, length, THICKNESS)

if "show_object" in locals():
    show_object(result.part.wrapped, name="stock_board")
