# The flat strip a laser cuts out of the sheet, and the piece the sheet metal
# example bends.
#
# Nothing but the outline: 120 mm is the developed length of that bracket, and
# 40 mm is its width. Holes and cut-outs would belong here too - they are the
# laser's work and not the brake's - but this one has none, because the parts
# folded from it are modelled as a swept rectangle and the two have to agree.

import build123d as bd

LENGTH = 120.0  # the developed length of the bent parts
WIDTH = 40.0
THICKNESS = 2.0  # the sheet it is cut from

with bd.BuildPart() as result:
    bd.Box(LENGTH, WIDTH, THICKNESS)

if "show_object" in locals():
    show_object(result.part.wrapped, name="blank")
