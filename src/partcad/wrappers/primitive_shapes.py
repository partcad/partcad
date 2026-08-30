#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The primitives a robot or a world description names instead of a mesh file.

URDF and SDFormat both let a shape be given as a box, a cylinder or a sphere
rather than as a file, and both centre all three on the element's own origin.
PartCAD has no such primitive: a part is a file it reads. So the primitive is
written out once, as a STEP file, and referenced like any mesh - which is what
keeps the element's own pose a location in the tree rather than a transform
baked into geometry.

Shared by the two readers ('wrapper_import_urdf', 'wrapper_import_world') so
that the same box is the same file whichever format named it, and so that the
re-centring - the one thing that is easy to get wrong, because OCCT's builders
do not put any of the three where these formats say they are - is written once.

Dimensions arrive in millimetres, already scaled by the caller: converting from
the format's own units is the caller's business, and neither format states
these in anything but metres anyway.
"""

import os

# Rounded before it becomes a cache key, so that two shapes that differ only in
# double-rounding noise share one file.
_KEY_PRECISION = 9


def write_primitive_step(kind, dimensions, name, context):
    """Write one primitive as a STEP file and return its path.

    'kind' is "box", "cylinder" or "sphere"; 'dimensions' is (x, y, z) for a
    box, (radius, length) for a cylinder and (radius,) for a sphere, all in
    millimetres. Identical primitives share one file: a description that
    repeats a shape (wheels, bolts, a row of pallets) should not produce a file
    per use.

    'context' carries 'output_folder' (where the files go), 'primitives' (the
    shared cache, keyed by shape) and 'written' (the paths taken so far).
    """
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeSphere
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

    dimensions = tuple(round(float(v), _KEY_PRECISION) for v in dimensions)
    key = (kind,) + dimensions

    cache = context["primitives"]
    if key in cache:
        return cache[key]

    if kind == "box":
        size_x, size_y, size_z = dimensions
        shape = BRepPrimAPI_MakeBox(gp_Pnt(-size_x / 2.0, -size_y / 2.0, -size_z / 2.0), size_x, size_y, size_z).Shape()
    elif kind == "cylinder":
        radius, length = dimensions
        shape = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, 0, -length / 2.0), gp_Dir(0, 0, 1)), radius, length).Shape()
    elif kind == "sphere":
        shape = BRepPrimAPI_MakeSphere(dimensions[0]).Shape()
    else:
        raise ValueError("Unsupported primitive '%s'" % kind)

    os.makedirs(context["output_folder"], exist_ok=True)
    base = os.path.basename(str(name or "").replace("/", "_")) or kind
    path = os.path.join(context["output_folder"], "%s.step" % base)
    suffix = 1
    while path in context["written"]:
        path = os.path.join(context["output_folder"], "%s_%d.step" % (base, suffix))
        suffix += 1
    context["written"].add(path)

    writer = STEPControl_Writer()
    if writer.Transfer(shape, STEPControl_AsIs) != 1 or writer.Write(path) != 1:
        raise ValueError("Failed to write the STEP file for a %s primitive: %s" % (kind, path))

    cache[key] = path
    return path
