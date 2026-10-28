#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within the python sandbox environment (python runtime)
# to cut a shape tree by a box: the cross-section the Digital Thread's sliders
# ask for, applied to the geometry before anything is drawn of it.
#
# The box is axis-aligned in the frame of the tree's root - the frame the object
# is shown and rendered in, millimetres and Z up - and says, per axis, the slab of
# the object to keep: '{"x": [lo, hi], "z": [lo, hi]}' keeps what lies between
# those planes and cuts the rest away. An axis it does not name is not cut.
#
# The tree is cut where it is, node by node, rather than flattened into one
# compound and cut once. Its nodes are what the viewer draws and switches off and
# what a filter names, so a cut tree has to be the same tree: the same names, the
# same placements, the same ports, with less geometry at some of its nodes. So
# the box is taken into each node's own frame - the inverse of every placement
# above it, composed - and the node's geometry is intersected with it there, and
# the placement goes on saying where the node sits. What a node says about its
# size ('metadata') is left as it was, deliberately: it is the object's size and
# not the cut's, which is what the sliders span and what the tessellation budget
# is worked out from (see 'partcad.shape_gltf.size_of'), so a cut is drawn as
# finely as the whole object would be.
#
# Most nodes of a large assembly are not touched by a cut at all - wholly inside
# the box or wholly outside it - so each is measured first, and only a node the
# box boundary passes through goes through a boolean. A node wholly outside loses
# its geometry: dropped outright where whoever reads the tree copes with a node
# that has none (the glTF wrapper, which imports this one to cut and tessellate
# in one sandbox), and replaced by an empty compound where a node has to stay a
# shape (a render implementation, which decodes the whole tree).
#
# A node that will not cut is left whole, with the reason collected for the
# caller to report: a section that misses a part is worth less than one that
# draws it uncut, and the log says which one it is.

import base64
import os
import sys

# Pinned before the CAD imports below, which load OCP and with it VTK's bundled
# copy of expat: see the note in ocp_serialize.
import pyexpat  # noqa: F401

sys.path.append(os.path.dirname(__file__))
import ocp_serialize
import wrapper_common

# What this wrapper reports for what it produces (see 'partcad.code_version'):
# raise it with any change that changes that, and everything it produced
# before is produced again.
CACHE_VERSION = 1

# The axes a section names, in the order of a point's coordinates.
AXES = ("x", "y", "z")

# How far past a node's own extent the box it is cut with reaches on the sides
# the section does not cut, as a fraction of the node's size and never less than
# a millimetre. A box face lying exactly on a face of the shape is a coincident
# face for the boolean, which is the case booleans are least sure of; a box a
# little bigger than the shape cuts nothing on that side, which is what an axis
# left uncut means.
_MARGIN_SHARE = 0.01
_MARGIN_MIN = 1.0


def limits(section):
    """The slab each axis keeps, as a list of three (lo, hi) pairs or None.

    Read rather than validated: the core has refused a section that is not one
    before it got here (see 'partcad.shape_section.normalize'), so all this does
    is put it in the order a point's coordinates are in.
    """
    if not isinstance(section, dict):
        return [None, None, None]
    slabs = []
    for axis in AXES:
        value = section.get(axis)
        slabs.append(None if value is None else (float(value[0]), float(value[1])))
    return slabs


def cuts_anything(slabs) -> bool:
    """Whether a section keeps less than everything on at least one axis."""
    return any(slab is not None for slab in slabs)


def _bounds(shape):
    """The box 'shape' occupies, as ((x0, y0, z0), (x1, y1, z1)), or None for an empty one."""
    from OCP.BRepBndLib import BRepBndLib
    from OCP.Bnd import Bnd_Box

    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box, True)
    if box.IsVoid():
        return None
    x0, y0, z0, x1, y1, z1 = box.Get()
    return (x0, y0, z0), (x1, y1, z1)


def _is_empty(shape) -> bool:
    """Whether 'shape' holds nothing that can be drawn: no face, no edge, no vertex."""
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_VERTEX
    from OCP.TopExp import TopExp_Explorer

    return not any(TopExp_Explorer(shape, kind).More() for kind in (TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX))


def _empty_compound():
    return ocp_serialize.compound_of([])


def classify(low, high, slabs):
    """What the section does to something occupying [low, high]: 'inside', 'outside' or 'cut'."""
    inside = True
    for axis, slab in enumerate(slabs):
        if slab is None:
            continue
        lo, hi = slab
        if high[axis] < lo or low[axis] > hi:
            return "outside"
        if low[axis] < lo or high[axis] > hi:
            inside = False
    return "inside" if inside else "cut"


def cutter(low, high, slabs):
    """The box, in the root's frame, a node occupying [low, high] is intersected with.

    The section's planes where it names an axis, and a little past the node on
    every other side - see '_MARGIN_SHARE'.
    """
    size = max(high[axis] - low[axis] for axis in range(3))
    margin = max(_MARGIN_MIN, _MARGIN_SHARE * size)
    corner_low, corner_high = [], []
    for axis, slab in enumerate(slabs):
        start, end = low[axis] - margin, high[axis] + margin
        if slab is not None:
            start, end = max(start, slab[0]), min(end, slab[1])
        corner_low.append(start)
        corner_high.append(end)
    return corner_low, corner_high


def _cut(shape, placement, slabs):
    """'shape', in its own frame, intersected with the section; None when nothing of it is kept.

    'placement' is where the node's frame sits in the root's, every placement
    above it composed. The shape is left where it is and the box is taken to it:
    the answer is geometry in the node's frame, which the node's own placement
    goes on placing.
    """
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    bounds = _bounds(shape.Moved(placement))
    if bounds is None:
        return shape
    low, high = bounds
    verdict = classify(low, high, slabs)
    if verdict == "inside":
        return shape
    if verdict == "outside":
        return None

    corner_low, corner_high = cutter(low, high, slabs)
    if any(corner_high[axis] <= corner_low[axis] for axis in range(3)):
        return None
    box = BRepPrimAPI_MakeBox(gp_Pnt(*corner_low), gp_Pnt(*corner_high)).Shape()
    # Into the node's frame: the inverse of where that frame is.
    box = box.Moved(placement.Inverted())
    common = BRepAlgoAPI_Common(shape, box)
    if not common.IsDone():
        raise Exception("the boolean that cuts it did not complete")
    result = common.Shape()
    if result is None or result.IsNull() or _is_empty(result):
        return None
    return result


def _payload(shape) -> str:
    """'shape' as a node's "brep" travels over the pipe: compressed, then base64."""
    return base64.b64encode(ocp_serialize.compressed_brep(shape)).decode("ascii")


def section_tree(tree, section, errors, keep_empty=True):
    """'tree' with the geometry of every node cut by 'section'.

    'tree' is a BREP-form tree as it travelled - dicts, the payloads undecoded -
    and so is what comes back. Only the nodes are cut: what hangs off the root
    beside them (the sketches the ports are drawn with) is an annotation and is
    copied through, as is everything about a node that is not its geometry.

    'keep_empty' decides what becomes of a node with nothing left: an empty
    compound in its place (True), for a reader that decodes every node as a
    shape, or no geometry at all (False).

    'errors' collects one line per node that could not be cut; such a node is
    left whole.
    """
    slabs = limits(section)
    if not cuts_anything(slabs) or not isinstance(tree, dict):
        return tree
    return _walk(tree, None, slabs, errors, keep_empty)


def _walk(node, parent, slabs, errors, keep_empty):
    from OCP.TopLoc import TopLoc_Location

    if not isinstance(node, dict):
        return node
    own = node.get(ocp_serialize.KEY_LOCATION)
    placement = parent if parent is not None else TopLoc_Location()
    if own is not None:
        placement = placement.Multiplied(ocp_serialize.toploc_from_packed(own))

    cut = {key: value for key, value in node.items() if key not in (ocp_serialize.KEY_BREP, ocp_serialize.KEY_ASSEMBLY)}

    brep = node.get(ocp_serialize.KEY_BREP)
    if brep:
        try:
            shape = ocp_serialize.shape_from_payload(brep)
            result = _cut(shape, placement, slabs)
            if result is shape:
                cut[ocp_serialize.KEY_BREP] = brep
            elif result is not None:
                cut[ocp_serialize.KEY_BREP] = _payload(result)
            elif keep_empty:
                cut[ocp_serialize.KEY_BREP] = _payload(_empty_compound())
        except Exception as e:
            errors.append("%s: %s" % (node.get("label") or node.get("name") or "a shape", e))
            cut[ocp_serialize.KEY_BREP] = brep

    children = node.get(ocp_serialize.KEY_ASSEMBLY)
    if children is not None:
        cut[ocp_serialize.KEY_ASSEMBLY] = [_walk(child, placement, slabs, errors, keep_empty) for child in children]
    return cut


def process(request):
    tree = request.get("tree")
    if not isinstance(tree, dict):
        raise Exception("No shape tree to cut")
    errors = []
    cut = section_tree(tree, request.get("section"), errors, keep_empty=True)
    return {"success": True, "exception": None, "tree": cut, "errors": errors}


if __name__ == "__main__":
    # The tree arrives undecoded, for the reason it does in 'wrapper_gltf.py': the
    # tree is the answer, and decoding it would rebuild it as one compound with
    # the names and the placements gone.
    #
    # argv[1] is required by handle_input() and unused: the cut tree comes back
    # over the pipe, and the caller passes the operation name there.
    _, request = wrapper_common.handle_input(decode=False)
    try:
        model = process(request)
    except Exception as e:
        wrapper_common.handle_exception(e)
        model = {"success": False, "exception": str(e), "tree": None, "errors": []}
    wrapper_common.handle_output(model)
