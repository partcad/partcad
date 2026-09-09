import build123d as bd

# The *fluid volume*, not the tube around it: a solid cylinder of the bore.
# 10 mm across and 100 mm long, centred on the origin and lying along Z, so it
# runs from z = -50 (the inlet) to z = +50 (the outlet).
#
# Declaring the bore rather than the casting is what `cfd:` means by a part.
with bd.BuildPart() as result:
    bd.Cylinder(radius=5, height=100)

if "show_object" in locals():
    show_object(result.part.wrapped, name="pipe")
