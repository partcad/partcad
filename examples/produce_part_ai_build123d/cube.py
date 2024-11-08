from build123d import *

with BuildPart() as cube:
    Box(length=10, width=10, height=10)

show_object(cube)
