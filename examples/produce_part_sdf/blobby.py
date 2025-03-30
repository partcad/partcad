from sdf import *


small_sphere_radius = 0.75
translation_distance = 3.0
capsule_radius = 0.5
outer_sphere_radius = 1.5
blend_value = 1

s = sphere(small_sphere_radius)
s = s.translate(Z * -translation_distance) | s.translate(Z * translation_distance)
s = s.union(capsule(Z * -translation_distance, Z * translation_distance, capsule_radius), k=blend_value)

f = sphere(outer_sphere_radius).union(s.orient(X), s.orient(Y), s.orient(Z), k=blend_value)
