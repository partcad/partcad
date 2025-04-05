from sdf import *


sphere_radius = 2
cylinder_radius = 1
gear_count = 16


f = sphere(sphere_radius) & slab(z0=-0.5, z1=0.5).k(0.1)
f -= cylinder(cylinder_radius).k(0.1)
f -= cylinder(0.25).circular_array(gear_count, 2).k(0.1)

# f.save(f'{__name__}.stl', samples=2**26)
