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
# build123d 0.11 dropped the make_wire/make_from_wires/make_solid class
# methods; the constructors take the same arguments.
face_ABC = Face(Wire([edge_AB, edge_BC, edge_AC]))
face_ABD = Face(Wire([edge_AB, edge_BD, edge_AD]))
face_ACD = Face(Wire([edge_AC, edge_CD, edge_AD]))
face_BCD = Face(Wire([edge_BC, edge_CD, edge_BD]))

# Create the tetrahedron by combining faces
tetrahedron = Solid(Shell([face_ABC, face_ABD, face_ACD, face_BCD]))

show_object(tetrahedron)