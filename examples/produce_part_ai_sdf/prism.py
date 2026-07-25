# Example SDF script for the 'ai-sdf' part type (checked in so the example
# renders without contacting an AI provider; regenerated on demand otherwise).
from sdf import *

f = hexagon(6).extrude(10)

show_object(f)
