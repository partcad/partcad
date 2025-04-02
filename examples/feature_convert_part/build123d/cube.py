import build123d as bd

width = 5
length = 5
height = 5

with bd.BuildPart() as result:
    bd.Box(length, width, height)

if "show_object" in locals():
    show_object(result.part.wrapped, name="art")
