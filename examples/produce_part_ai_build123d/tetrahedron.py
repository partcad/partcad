import math
from build123d import *

# Define vertices of the tetrahedron
A = (0, 0, 0)
B = (10, 0, 0)
C = (5, 8.66, 0)
D = (5, 2.89, 4.71)

# Create edges
edge_AB = Edge.make_line(A, B)
edge_AC = Edge.make_line(A, C)
edge_AD = Edge.make_line(A, D)
edge_BC = Edge.make_line(B, C)
edge_BD = Edge.make_line(B, D)
edge_CD = Edge.make_line(C, D)

# Create faces from edges
face_ABC = Face.make_from_wires(Wire.make_wire([edge_AB, edge_BC, edge_AC]))
face_ABD = Face.make_from_wires(Wire.make_wire([edge_AB, edge_BD, edge_AD]))
face_ACD = Face.make_from_wires(Wire.make_wire([edge_AC, edge_CD, edge_AD]))
face_BCD = Face.make_from_wires(Wire.make_wire([edge_BC, edge_CD, edge_BD]))

# Create the tetrahedron by combining faces
tetrahedron = Solid.make_solid(Shell([face_ABC, face_ABD, face_ACD, face_BCD]))

show_object(tetrahedron)
