import math
from cadquery import *

s = 10  # assuming a side length of 10 mm for demonstration purposes

# calculate radius of circumscribed circle using trigonometry
r = s / (2 * math.sin(math.radians(60)))

# create the hexagonal prism
hexagon_prism = (
    Workplane("XY")
    .moveTo(r, 0)
    .lineTo(r + s/2, r*math.sqrt(3)/2)
    .lineTo(-r - s/2, r*math.sqrt(3)/2)
    .lineTo(-r, 0)
    .lineTo(-r - s/2, -r*math.sqrt(3)/2)
    .lineTo(r + s/2, -r*math.sqrt(3)/2)
    .close()
    .extrude(10)  # extrude to create the prism
)

show_object(hexagon_prism)
