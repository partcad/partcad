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
import json
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

    It does when the shape is made of closed, valid solids of positive volume,
    and not otherwise - 'wrapper_common.solid_problems', which is the same test
    every part is held to as it is built, whatever built it.

    This used to ask only for a positive volume, on the grounds that open
    meshes - LDraw bricks, whose studs stand on faces nothing cuts - fail
    OCCT's validity check and still intersect correctly. They do not. Measured
    on the LEGO F1 car, an open shell's volume integral is positive as often as
    not, and a boolean against it answers with whatever it likes: an axle
    "sharing" 12.457 mm^3 with a cross block whose hole is wider than it at
    every corner, overlaps of negative volume, and single pairs taking over a
    minute to say so. A part that is not a solid is reported as not checked,
    which is the truth, rather than checked wrongly.
    """
    try:
        return not wrapper_common.solid_problems(shape)
    except Exception:
        return False


def _within(path, root):
    """Whether 'path' is the node 'root' or a node anywhere under it.

    The rule 'partcad.test.interference' names pairs by, repeated here: a
    wrapper runs in a sandbox that cannot import PartCAD, so the two copies are
    held to each other by a test rather than by an import. Paths are exact -
    built from the tree's root down - so a pattern is a subtree, never a tail:
    'battery' covers 'battery/pin-1' and not 'spare-battery'.
    """
    return path == root or path.startswith(root + "/")


def _is_expected(path_a, path_b, expected):
    """Whether a joint already says these two subtrees share space."""
    for a, b in expected:
        if _within(path_a, a) and _within(path_b, b):
            return True
        if _within(path_a, b) and _within(path_b, a):
            return True
    return False


class _Node:
    """One node of the placed tree: a part, or an assembly and what is under it.

    'box' is the box around everything under the node, so a node whose box
    misses another's has nothing under it that could touch anything under the
    other - which is what lets whole subtrees be dismissed at once instead of
    every part of one being boxed against every part of the other.
    """

    __slots__ = ("path", "shape", "children", "box")

    def __init__(self, path, shape=None, children=None):
        self.path = path
        self.shape = shape
        self.children = children if children is not None else []
        self.box = None


def _node(obj, prefix):
    """'obj' as a node of the tree, placed in its parent's frame.

    Named by the label first, deliberately. Assembly._place() puts the object's
    identity in "name" - '//pkg:3010' - and what this placement of it is called
    in "label" - 'buttS8'. An assembly is mostly repeats of a few parts, so
    naming by identity would say "3010 overlaps 3010", and the pairs the joints
    declare, which are written as link names, would never match.

    A node's placement applies to everything under it; a part's is composed
    onto the geometry it carries, an assembly's onto every part beneath it.
    """
    name = obj.get("label") or obj.get("name") or ""
    path = "%s/%s" % (prefix, name) if prefix else name
    location = obj.get(ocp_serialize.KEY_LOCATION)
    toploc = ocp_serialize.toploc_from_packed(location) if location is not None else None
    if ocp_serialize.is_assembly_object(obj):
        node = _Node(path, children=[_node(child, path) for child in obj[ocp_serialize.KEY_ASSEMBLY]])
        if toploc is not None:
            _move(node, toploc)
        return node
    if ocp_serialize.is_shape_object(obj):
        shape = ocp_serialize._shape_from_b64(obj[ocp_serialize.KEY_BREP])
        return _Node(path, shape.Moved(toploc) if toploc is not None else shape)
    return _Node(path, children=[])


def _move(node, toploc):
    if node.shape is not None:
        node.shape = node.shape.Moved(toploc)
    for child in node.children:
        _move(child, toploc)


def _parts(node):
    if node.shape is not None:
        yield node
    for child in node.children:
        yield from _parts(child)


def _box_up(node):
    """Give every assembly node the box around the parts under it that can be checked."""
    if node.shape is not None:
        return node.box
    box = None
    for child in node.children:
        child_box = _box_up(child)
        if child_box is None:
            continue
        if box is None:
            box = Bnd_Box()
        box.Add(child_box)
    node.box = box
    return box


def process(path, request):
    try:
        # Not 'wrapped': that key is decoded into OCCT geometry on arrival, and
        # an assembly decodes into one compound, which is the one thing this
        # cannot use. The names have to survive - a report that two parts
        # overlap has to say which two - so the tree arrives as JSON and is
        # decoded here, leaf by leaf.
        payload = request.get("assembly_json")
        if payload is None:
            raise Exception("No assembly provided to check")
        obj = json.loads(payload) if isinstance(payload, str) else payload

        # The floor under the arithmetic. Two surfaces that merely touch bound
        # no volume, and a boolean over tessellated faces answers with a sliver
        # instead of zero; this is above that noise and far below any overlap
        # worth the name.
        min_volume = float(request.get("min_volume", 0.05))
        min_fraction = float(request.get("min_fraction", 0.0))

        # The pairs whose joint says they share space - a pin snapped into its
        # hole, a screw cutting its own thread, whatever a connection names in
        # 'interferes'. The caller discards whatever is measured for them, so
        # measuring it is only cost, and it is the dominant cost: a pin seated
        # in its hole is the very case in which two tessellated surfaces lie a
        # hair apart along their whole length, which is where a boolean is at
        # its slowest. Skipping them changes no verdict.
        expected = [tuple(pair) for pair in (request.get("expected") or []) if len(pair) == 2]

        # Declared sub-assemblies whose own verdict the caller has already
        # taken: what happens inside one is that sub-assembly's business and
        # is not looked at again here. Only pairs that cross its boundary are.
        opaque = set(request.get("opaque") or [])

        # The root's own name is on every part below it and says nothing, so
        # the paths are built from its children down: 'gearbox/shaft', not
        # 'assembly/gearbox/shaft'.
        if ocp_serialize.is_assembly_object(obj):
            root = _Node("", children=[_node(child, "") for child in obj[ocp_serialize.KEY_ASSEMBLY]])
            root_location = obj.get(ocp_serialize.KEY_LOCATION)
            if root_location is not None:
                _move(root, ocp_serialize.toploc_from_packed(root_location))
        else:
            root = _Node("", children=[_node(obj, "")])

        checked = 0
        unchecked = []
        for part in _parts(root):
            box = _box(part.shape)
            if box is None or not _is_solid_enough_to_intersect(part.shape):
                # An empty shape, or one that is not a solid, is not a part
                # that overlaps nothing; it is a part nothing could be asked
                # about. Dropping it silently would take it out of 'parts' and
                # 'unchecked' both, and a caller reading either would never
                # learn it existed.
                unchecked.append(part.path)
                continue
            part.box = box
            checked += 1
        _box_up(root)

        # Broadphase, down the tree. Two subtrees whose boxes miss are done
        # with in one test however many parts are under them; two the joints
        # say overlap are done with without a test at all; only where neither
        # holds does it go a level down, until it reaches two parts.
        candidates = []
        skipped = [0]

        def cross(a, b):
            if a.box is None or b.box is None or a.box.IsOut(b.box):
                return
            if _is_expected(a.path, b.path, expected):
                skipped[0] += 1
                return
            if a.shape is not None and b.shape is not None:
                candidates.append((a, b))
                return
            # Go down the side that has a level to go down, the larger first.
            if a.shape is None and (b.shape is not None or a.box.SquareExtent() >= b.box.SquareExtent()):
                for child in a.children:
                    cross(child, b)
            else:
                for child in b.children:
                    cross(a, child)

        def within(node):
            if node.shape is not None or node.path in opaque:
                return
            children = [child for child in node.children if child.box is not None]
            for i, first in enumerate(children):
                for second in children[i + 1 :]:
                    cross(first, second)
            for child in children:
                within(child)

        within(root)

        overlaps = []
        indeterminate = []
        for a, b in candidates:
            name_a, shape_a = a.path, a.shape
            name_b, shape_b = b.path, b.shape
            try:
                common = BRepAlgoAPI_Common(shape_a, shape_b)
                done = common.IsDone()
                volume = _volume(common.Shape()) if done else None
            except Exception as e:
                done, volume = False, None
                reason = str(e)
            else:
                reason = "the boolean did not complete"
            if not done or volume is None:
                # Not "they do not overlap". The question was asked and did not
                # come back, and answering a pass on that is how a check comes
                # to certify what it never looked at.
                indeterminate.append({"a": name_a, "b": name_b, "reason": reason})
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
            "parts": checked,
            "candidates": len(candidates),
            "expected": skipped[0],
            "overlaps": overlaps,
            "unchecked": unchecked,
            "indeterminate": indeterminate,
        }
    except Exception as e:
        wrapper_common.handle_exception(e)
        return {
            "success": False,
            "exception": str(e),
            "parts": 0,
            "candidates": 0,
            "expected": 0,
            "overlaps": [],
            "unchecked": [],
            "indeterminate": [],
        }


if __name__ == "__main__":
    path, request = wrapper_common.handle_input()
    response = process(path, request)
    wrapper_common.handle_output(response)
