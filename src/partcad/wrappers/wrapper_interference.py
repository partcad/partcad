#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within a python runtime environment to find the pairs
# of parts in an assembly whose solids share space. The core has no CAD library,
# so the only place this can be answered is a runtime that has one.
#
# Bounding boxes are not enough to answer it. Two boxes overlapping says very
# little - a bracket around a shaft, an L around a corner, anything rotated -
# so boxes are used here only to pick the pairs worth asking about, and the
# answer itself comes from a boolean common and the volume of what it produces.

import itertools
import os
import sys

# Pinned before the CAD imports below, which load OCP and with it VTK's
# bundled copy of expat: see the note in ocp_serialize.
import pyexpat  # noqa: F401

from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepGProp import BRepGProp
from OCP.Bnd import Bnd_Box
from OCP.GProp import GProp_GProps

sys.path.append(os.path.dirname(__file__))
import ocp_serialize
import wrapper_common


def _leaves(obj, prefix=""):
    """Every solid in the tree, placed, with the name it is known by.

    decode_shape() flattens an assembly into one compound, which is what a
    renderer wants and the opposite of what this needs: a report saying two
    parts overlap has to be able to say which two.
    """
    name = obj.get("name") or obj.get("label") or ""
    path = "%s/%s" % (prefix, name) if prefix else name
    if ocp_serialize.is_assembly_object(obj):
        placed = []
        for child in obj[ocp_serialize.KEY_ASSEMBLY]:
            placed.extend(_leaves(child, path))
        location = obj.get(ocp_serialize.KEY_LOCATION)
        if location is None:
            return placed
        toploc = ocp_serialize.toploc_from_packed(location)
        return [(nm, shape.Moved(toploc)) for nm, shape in placed]
    if ocp_serialize.is_shape_object(obj):
        shape = ocp_serialize._shape_from_b64(obj[ocp_serialize.KEY_BREP])
        location = obj.get(ocp_serialize.KEY_LOCATION)
        if location is not None:
            shape = shape.Moved(ocp_serialize.toploc_from_packed(location))
        return [(path, shape)]
    return []


def _box(shape):
    box = Bnd_Box()
    # 'useTriangulation': a shape carrying a mesh but no exact geometry - an
    # imported STL, an SDF part - has an empty box otherwise.
    BRepBndLib.Add_s(shape, box, True)
    return None if box.IsVoid() else box


def _volume(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def _is_solid_enough_to_intersect(shape):
    """Whether a boolean against this shape would mean anything.

    It is not a formality. A shape whose faces are inconsistently oriented is
    inside out, which OCCT reports as a negative volume, and a boolean common
    against it returns a number with no relation to any shared space: two LDraw
    bricks meshed from triangles and placed 100 mm apart came back sharing
    2282 mm^3. Reporting that as interference would be worse than not checking
    at all, so a shape whose volume is not positive is left out and counted.

    The test is the volume's sign and not BRepCheck_Analyzer, deliberately.
    Plenty of usable geometry is not a valid solid in OCCT's sense and
    intersects perfectly well regardless: an LDraw brick is an open mesh - a
    stud is a cylinder and a top disc with no bottom, resting on a face the
    parent never cuts - so it has hundreds of free boundary edges and fails
    IsValid, while two copies of it 100 mm apart correctly share nothing.
    Gating on validity would refuse to check any assembly built from such
    parts, forever, which is most of what this test exists for.
    """
    try:
        return _volume(shape) > 0.0
    except Exception:
        return False


def process(path, request):
    try:
        obj = request.get("wrapped")
        if obj is None:
            raise Exception("No assembly provided to check")

        # How much shared volume is worth reporting. Parts that are meant to fit
        # together touch, and meshed geometry touching is numerically noisy, so
        # a threshold is not a convenience here - it is the difference between
        # reporting a design fault and reporting that the design fits together.
        min_volume = float(request.get("min_volume", 1.0))
        min_fraction = float(request.get("min_fraction", 0.0))

        # The root's own name is on every part below it and says nothing, so
        # the paths are built from its children down: 'gearbox/shaft', not
        # 'assembly/gearbox/shaft'.
        if ocp_serialize.is_assembly_object(obj):
            leaves = []
            for child in obj[ocp_serialize.KEY_ASSEMBLY]:
                leaves.extend(_leaves(child))
            root_location = obj.get(ocp_serialize.KEY_LOCATION)
            if root_location is not None:
                toploc = ocp_serialize.toploc_from_packed(root_location)
                leaves = [(nm, shape.Moved(toploc)) for nm, shape in leaves]
        else:
            leaves = _leaves(obj)

        boxes = []
        unchecked = []
        for name, shape in leaves:
            box = _box(shape)
            if box is None:
                continue
            if not _is_solid_enough_to_intersect(shape):
                unchecked.append(name)
                continue
            boxes.append((name, shape, box))

        # Broadphase. Boxes are cheap, booleans are not, so only the pairs whose
        # boxes meet are asked the expensive question.
        candidates = [
            (a, b)
            for a, b in itertools.combinations(range(len(boxes)), 2)
            if not boxes[a][2].IsOut(boxes[b][2])
        ]

        overlaps = []
        for a, b in candidates:
            name_a, shape_a, _ = boxes[a]
            name_b, shape_b, _ = boxes[b]
            try:
                common = BRepAlgoAPI_Common(shape_a, shape_b)
                if not common.IsDone():
                    continue
                volume = _volume(common.Shape())
            except Exception:
                # A boolean that will not run says nothing either way; a part
                # that cannot be intersected is the 'cad' test's business.
                continue
            if volume < min_volume:
                continue
            if min_fraction > 0.0:
                smaller = min(_volume(shape_a), _volume(shape_b))
                if smaller > 0.0 and volume / smaller < min_fraction:
                    continue
            overlaps.append({"a": name_a, "b": name_b, "volume": volume})

        overlaps.sort(key=lambda o: -o["volume"])
        return {
            "success": True,
            "exception": None,
            "parts": len(boxes),
            "candidates": len(candidates),
            "overlaps": overlaps,
            "unchecked": unchecked,
        }
    except Exception as e:
        wrapper_common.handle_exception(e)
        return {
            "success": False,
            "exception": str(e),
            "parts": 0,
            "candidates": 0,
            "overlaps": [],
            "unchecked": [],
        }


if __name__ == "__main__":
    path, request = wrapper_common.handle_input()
    response = process(path, request)
    wrapper_common.handle_output(response)
