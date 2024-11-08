import math
from build123d import *

# Define the side length of the hexagon
s = 5  # Example side length, can be adjusted

# Calculate the radius of the circumscribed circle
r = s / math.sqrt(3)

# Define the vertices of the hexagon
vertices = [
    (r, 0, 0),
    (r * math.cos(math.radians(60)), r * math.sin(math.radians(60)), 0),
    (r * math.cos(math.radians(120)), r * math.sin(math.radians(120)), 0),
    (-r, 0, 0),
    (r * math.cos(math.radians(240)), r * math.sin(math.radians(240)), 0),
    (r * math.cos(math.radians(300)), r * math.sin(math.radians(300)), 0)
]

# Create the hexagon base
hexagon = Polygon(vertices)

# Extrude the hexagon to form the prism
hex_prism = extrude(hexagon, 10)

# Display the part
show_object(hex_prism)
