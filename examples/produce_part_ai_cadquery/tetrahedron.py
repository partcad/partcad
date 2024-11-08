import math
import cadquery as cq

# Define vertices
A = (0, 0, 0)
B = (10, 0, 0)
C = (5, 8.66, 0)
D = (3.33, 2.89, 8.16)

# Create edges
edges = [
    cq.Edge.makeLine(A, B),
    cq.Edge.makeLine(A, C),
    cq.Edge.makeLine(A, D),
    cq.Edge.makeLine(B, C),
    cq.Edge.makeLine(B, D),
    cq.Edge.makeLine(C, D)
]

# Create faces
faces = [
    cq.Face.makeFromWires(cq.Wire.assembleEdges([edges[0], edges[1], edges[3]])),
    cq.Face.makeFromWires(cq.Wire.assembleEdges([edges[0], edges[2], edges[4]])),
    cq.Face.makeFromWires(cq.Wire.assembleEdges([edges[1], edges[2], edges[5]])),
    cq.Face.makeFromWires(cq.Wire.assembleEdges([edges[3], edges[4], edges[5]]))
]

# Create solid
tetrahedron = cq.Solid.makeSolid(cq.Shell.makeShell(faces))

show_object(tetrahedron)
