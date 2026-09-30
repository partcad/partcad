import build123d as bd

# A 300 x 200 x 18 mm panel with rounded corners and two 20 mm cable holes: a
# piece of sheet stock, which is what a router cuts. Prismatic over its whole
# thickness on purpose -- the outline is the same at every depth, which is the
# case a 2.5D route is exactly right for and the one `pc cam` does not have to
# warn about.
with bd.BuildPart() as result:
    with bd.BuildSketch() as outline:
        bd.Rectangle(300, 200)
        bd.fillet(outline.vertices(), radius=20)
        with bd.Locations((-100, 0), (100, 0)):
            bd.Circle(10, mode=bd.Mode.SUBTRACT)
    bd.extrude(amount=18)

if "show_object" in locals():
    show_object(result.part.wrapped, name="panel")
