#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within the python sandbox environment (python runtime)
# to run the shape analysis the 'pc test' manufacturability checks need, so
# the core process never has to touch a live OCP object. The shape arrives as a
# BREP envelope and the analysis result goes back as plain data.

import os
import sys

# Pinned before the CAD imports below, which load OCP and with it VTK's bundled
# copy of expat: see the note in ocp_serialize.
import pyexpat  # noqa: F401

sys.path.append(os.path.dirname(__file__))
import wrapper_common


def free_bounds(request):
    """How many free boundaries the shape has, which is how open it is.

    A solid a machine can make is closed: every edge of it is shared by two
    faces. A free boundary is an edge that is not, so a count above zero is a
    shape with a hole in its surface - a surface model, or a solid that failed
    to sew - and 'ManufacturabilityTest' reports it as a part nothing can be made from.
    """
    from OCP.ShapeAnalysis import ShapeAnalysis_FreeBoundsProperties

    shape = request["shape"]
    fbp = ShapeAnalysis_FreeBoundsProperties(shape)
    fbp.Perform()
    return {"free_bounds": fbp.NbFreeBounds()}


def flatness(request):
    """How much of the shape lies in the horizontal planes at its top and bottom.

    The question a sheet metal blank has to answer: it is a piece of sheet, so
    the plane through its highest point and the plane through its lowest one
    each meet it in a face rather than touching it at an edge or a point. The
    area of that meeting is the answer, and zero means it is not a blank.

    Computed as the area of the shape's own horizontal planar faces that sit at
    each extreme, which is exactly the area of the intersection and costs no
    boolean: a plane cannot cut a solid at the very limit of it, so anything the
    plane meets there is surface the shape already has. Doing it as a boolean
    instead would depend on a tolerance to decide whether the plane and the face
    are the same plane, which is the thing being measured.

    'z_min' and 'z_max' come from the bounding box rather than from those faces,
    and that is the whole reason the box is here: a dome has a horizontal face
    at its base and nothing at its top, and only the box knows where its top is.
    The box is asked for the geometry's own extent - no gap, and not inflated by
    the shapes' tolerances - because the question is about a plane through the
    extreme point and not about a plane near it.
    """
    from OCP.Bnd import Bnd_Box
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepGProp import BRepGProp
    from OCP.GeomAbs import GeomAbs_SurfaceType
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    shape = request["shape"]

    box = Bnd_Box()
    box.SetGap(0.0)
    BRepBndLib.AddOptimal_s(shape, box, False, False)
    if box.IsVoid():
        return {"z_min": None, "z_max": None, "area_min": 0.0, "area_max": 0.0}
    _, _, z_min, _, _, z_max = box.Get()

    # What counts as "at the extreme" and as "horizontal". Both are relative to
    # the shape: a plane is level if its normal is within a millionth of
    # vertical, and a face is at the top if it is within a millionth of the
    # height of it. A flat blank is flat to far better than that, and a curved
    # surface misses by far more.
    height = max(abs(z_max - z_min), 1.0)
    tolerance = 1e-6 * height
    area_min = 0.0
    area_max = 0.0

    explorer = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        explorer.Next()
        surface = BRepAdaptor_Surface(face)
        if surface.GetType() != GeomAbs_SurfaceType.GeomAbs_Plane:
            continue
        plane = surface.Plane()
        axis = plane.Axis().Direction()
        if abs(abs(axis.Z()) - 1.0) > 1e-6:
            continue
        z = plane.Location().Z()
        properties = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, properties)
        if abs(z - z_max) <= tolerance:
            area_max += properties.Mass()
        if abs(z - z_min) <= tolerance:
            area_min += properties.Mass()

    return {"z_min": z_min, "z_max": z_max, "area_min": area_min, "area_max": area_max}


# The analyses this wrapper performs, by the name the request asks for. Named
# rather than one per wrapper because each is a few lines of OCCT over a shape
# that has just been deserialized, and starting a second sandbox to run them
# would cost more than all of them together.
OPERATIONS = {
    "free_bounds": free_bounds,
    "flatness": flatness,
}


if __name__ == "__main__":
    _, request = wrapper_common.handle_input()
    try:
        # 'free_bounds' by default, because that is what this wrapper did before
        # it had more than one thing to do, and a request is not required to say.
        model = {"success": True, "exception": None}
        model.update(OPERATIONS[request.get("op") or "free_bounds"](request))
    except Exception as e:
        wrapper_common.handle_exception(e)
        model = {"success": False, "exception": str(e)}
    wrapper_common.handle_output(model)
