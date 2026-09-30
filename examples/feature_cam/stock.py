import build123d as bd

# The sheet the panel and the tray recess are cut out of: a plain rectangular
# blank, 320 x 220 x 18 mm, bought rather than made.
#
# Oversized in X and Y and the same thickness in Z, which is what sheet stock
# is: a router takes material away around the outline and leaves the faces it
# was given. It has to *enclose* what is cut from it, because that is what
# `pc test -f manufacturability` checks -- a part bigger than its stock is one
# nobody can make, and saying so needs a stock that is a different shape from
# the part. Pointing `source:` at a copy of the part itself would remove
# nothing and be reported as such.
with bd.BuildPart() as result:
    bd.Box(320, 220, 18, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN))

if "show_object" in locals():
    show_object(result.part.wrapped, name="stock")
