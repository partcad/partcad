# The sheet the laser cuts out of: bought by the square metre, flat, and with no
# manufacturing method of its own because nobody makes it here.
#
# Every laser part in this package names it as its `source`, which is what lets
# `pc test` check that the part actually fits what it is cut from.

import build123d as bd

LENGTH = 200.0
WIDTH = 120.0
THICKNESS = 2.0

with bd.BuildPart() as result:
    bd.Box(LENGTH, WIDTH, THICKNESS)

if "show_object" in locals():
    show_object(result.part.wrapped, name="stock_sheet")
