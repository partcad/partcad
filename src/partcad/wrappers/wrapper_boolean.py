#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within the python sandbox environment (python runtime)
# to combine two parts by a boolean operation - 'and', 'or' or 'xor' - so the
# core process never has to touch a live OCP object to do it. The two operands
# arrive in the request as the envelopes their parts were built into, and the
# result goes back the same way, with the colour, material and finish of every
# face and solid it kept of either (docs/design/cmf.md, section 6: "an
# operation that rebuilds faces carries CMF through OCCT's history").
#
# Two ways of reading the operation, which the request's 'whole' chooses:
#
# * By volume (the default): what a CAD system means by a boolean. 'and' is the
#   material both parts occupy (BRepAlgoAPI_Common), 'or' the material either
#   occupies (BRepAlgoAPI_Fuse), 'xor' the material exactly one occupies - each
#   part with the other cut out of it, side by side.
#
# * By whole solids: each part is the set of its solids, and a solid of one is
#   in the other when it lies wholly inside it. 'and' is the first part's
#   solids that are in the second; 'or' all of the first's and the second's
#   that are not in the first; 'xor' the first's that are not in the second and
#   the second's that are not in the first. Nothing is cut: every solid kept is
#   kept as it was, faces and all. That is what takes one piece out of a model
#   of several that touch - a pinch bolt out of a hub, which a box around the
#   bolt cannot do by volume without cutting a slice of the hub along with it -
#   and what puts the rest back together without it: 'hub and box' is the
#   bolts, and 'hub xor bolts' is the hub's body.

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

OPERATIONS = ("and", "or", "xor")

# How much of a solid has to lie inside the other part for the solid to be in
# it, by whole solids: all of it, less what the arithmetic of a volume loses.
# Relative, with a floor for a solid too small for a relative bound to mean
# anything.
INSIDE_RELATIVE = 1e-6
INSIDE_ABSOLUTE = 1e-6


class Operand:
    """One part of the operation: its geometry, and the colour, material and finish of each face and solid."""

    def __init__(self, envelope, which: str):
        import cmf_section
        from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
        from OCP.TopExp import TopExp
        from OCP.TopTools import TopTools_IndexedMapOfShape

        self.which = which
        self.shape = ocp_serialize.decode_shape(envelope)
        # Each face and solid of the shape, in 'TopExp::MapShapes' order, and
        # what it is in (None for nothing): looked up through the map, since a
        # sub-shape found by walking the shape again is the same sub-shape but
        # not the same Python object.
        self.face_map, self.solid_map = TopTools_IndexedMapOfShape(), TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(self.shape, TopAbs_FACE, self.face_map)
        TopExp.MapShapes_s(self.shape, TopAbs_SOLID, self.solid_map)
        self.face_sets = [None] * self.face_map.Extent()
        self.solid_sets = [None] * self.solid_map.Extent()
        self._parents = None
        section = self._section(envelope)
        if section is None or section.is_empty():
            return
        nothing = cmf_section.CmfSet()
        # A face is in a colour and a finish; what it is made of is its solid's,
        # and the solid a face of the result bounds may be the other part's.
        for found, of, dropped in (
            (self.face_sets, section.face_set, ("material",)),
            (self.solid_sets, section.solid_set, ()),
        ):
            for index in range(len(found)):
                cmf_set = of(index)
                if cmf_set is not None and dropped:
                    cmf_set = cmf_set.without(dropped)
                found[index] = None if cmf_set is None or cmf_set == nothing else cmf_set

    def solid_set_of_face(self, face):
        """What the solid 'face' bounds is made of, or None."""
        from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
        from OCP.TopExp import TopExp
        from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape

        if self._parents is None:
            self._parents = TopTools_IndexedDataMapOfShapeListOfShape()
            TopExp.MapShapesAndAncestors_s(self.shape, TopAbs_FACE, TopAbs_SOLID, self._parents)
        if not self._parents.Contains(face):
            return None
        for solid in self._parents.FindFromKey(face):
            cmf_set = self.set_of(solid, solid=True)
            if cmf_set is not None:
                return cmf_set
        return None

    def stated(self) -> list:
        """'[(sub-shape, set, is a solid)]' for every face and solid of this operand that is in something."""
        found = []
        for mapped, sets, solid in ((self.face_map, self.face_sets, False), (self.solid_map, self.solid_sets, True)):
            for index, cmf_set in enumerate(sets):
                if cmf_set is not None:
                    found.append((mapped.FindKey(index + 1), cmf_set, solid))
        return found

    def set_of(self, sub, solid: bool):
        """What 'sub', a face or a solid of this operand's shape, is in; None for nothing or for no sub-shape of it."""
        mapped, sets = (self.solid_map, self.solid_sets) if solid else (self.face_map, self.face_sets)
        index = mapped.FindIndex(sub)
        return sets[index - 1] if index > 0 else None

    def _section(self, envelope):
        """The CMF section addressing this operand's shape, or None.

        A part is one node in nearly every case, and its payload's section
        addresses the very shape that node decodes to: a location moves the
        shape and keeps every face where it was in 'TopExp::MapShapes' order. A
        part that is a tree of nodes - a script that showed several shapes - is
        combined here without what its pieces state, and says so.
        """
        if ocp_serialize.is_shape_object(envelope) and envelope.get(ocp_serialize.KEY_CHILD) is None:
            return ocp_serialize.cmf_of_payload(envelope[ocp_serialize.KEY_BREP])
        sys.stderr.write(
            "The colours and materials of the %s part are not carried: it is several shapes, not one\n" % self.which
        )
        return None


def _solids(shape) -> list:
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    found = []
    explorer = TopExp_Explorer(shape, TopAbs_SOLID)
    while explorer.More():
        found.append(explorer.Current())
        explorer.Next()
    return found


def _volume(shape) -> float:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    properties = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, properties)
    return abs(properties.Mass())


def _shapes(*shapes):
    from OCP.TopTools import TopTools_ListOfShape

    listed = TopTools_ListOfShape()
    for shape in shapes:
        listed.Append(shape)
    return listed


def _run(algorithm, arguments, tools):
    """'algorithm' (a BRepAlgoAPI class) of 'arguments' with 'tools', built; it holds the history."""
    operation = algorithm()
    operation.SetArguments(_shapes(arguments))
    operation.SetTools(_shapes(tools))
    # The operands may share their geometry with whatever else the request
    # decoded (see 'ocp_serialize._shared_shape'), so neither is modified.
    operation.SetNonDestructive(True)
    operation.SetRunParallel(True)
    operation.Build()
    if not operation.IsDone():
        raise ValueError("OCCT could not compute the %s of the two parts" % algorithm.__name__)
    return operation


class Carried:
    """What the faces and solids of a result are in, as the operands' faces and solids are carried into it.

    Each face and solid of the result takes the set of the first sub-shape of
    an operand found to have become it, the operation's argument before its
    tool: where a result solid is a piece of both - what 'and' and 'or' make -
    it is made of what the argument is made of, and so is a face both left at
    one place. A solid the operation built anew out of several - two solids
    'or' fused into one - is no image of any of them in OCCT's history, and is
    made of what the solids its faces came from are made of, the argument's
    first ('lend').
    """

    def __init__(self):
        from OCP.TopTools import TopTools_IndexedMapOfShape

        self.faces, self.solids = {}, {}
        self._seen = {False: TopTools_IndexedMapOfShape(), True: TopTools_IndexedMapOfShape()}
        # A result face, and what the solid it came from was made of, with the
        # rank of the operand it came from: 0 for the argument.
        self._lent = []

    def carry(self, operation, operands) -> None:
        """Carry what 'operands' (the argument first) are in through 'operation'.

        A face the operation kept as it was is its own image; one it split, or
        trimmed, is the faces 'Modified' says it became; one it removed has none.
        """
        for rank, operand in enumerate(operands):
            for sub, cmf_set, solid in operand.stated():
                images = list(operation.Modified(sub))
                if not images and not operation.IsDeleted(sub):
                    images = [sub]
                for image in images:
                    if not self._seen[solid].Contains(image):
                        self._seen[solid].Add(image)
                        (self.solids if solid else self.faces)[image] = cmf_set
                    if not solid:
                        lent = operand.solid_set_of_face(sub)
                        if lent is not None:
                            self._lent.append((image, rank, lent))

    def lend(self, shape) -> None:
        """Give each solid of 'shape' that nothing was carried to what the solids its faces came from are made of."""
        from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
        from OCP.TopExp import TopExp
        from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape, TopTools_IndexedMapOfShape

        if not self._lent:
            return
        parents = TopTools_IndexedDataMapOfShapeListOfShape()
        TopExp.MapShapesAndAncestors_s(shape, TopAbs_FACE, TopAbs_SOLID, parents)
        # The solids still to be given something, by their index in here.
        pending = TopTools_IndexedMapOfShape()
        offers = {}
        for face, rank, cmf_set in self._lent:
            if not parents.Contains(face):
                continue
            for solid in parents.FindFromKey(face):
                if self._seen[True].Contains(solid):
                    continue
                offers.setdefault(pending.Add(solid), (solid, []))[1].append((rank, cmf_set))
        for solid, offered in offers.values():
            best = min(offered, key=lambda offer: offer[0])[0]
            sets = [cmf_set for rank, cmf_set in offered if rank == best]
            self.solids[solid] = max(set(sets), key=sets.count)


def by_volume(operation: str, first: Operand, second: Operand):
    """'(shape, carried)': the operation by volume, and what each face and solid of it is in."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse

    carried = Carried()
    if operation == "xor":
        # Each part with the other cut out of it. Side by side rather than
        # fused: the two touch only where the material both occupied was taken
        # out, and fusing them there would join solids that share a face.
        pieces = []
        for argument, tool in ((first, second), (second, first)):
            cut = _run(BRepAlgoAPI_Cut, argument.shape, tool.shape)
            carried.carry(cut, (argument, tool))
            pieces.append(cut.Shape())
        shape = ocp_serialize.compound_of(pieces)
    else:
        algorithm = BRepAlgoAPI_Common if operation == "and" else BRepAlgoAPI_Fuse
        done = _run(algorithm, first.shape, second.shape)
        carried.carry(done, (first, second))
        shape = done.Shape()
    carried.lend(shape)
    return shape, carried


def _same(solid, other) -> bool:
    """Whether two solids are the same solid, to within what a BREP round trip changes."""
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    if solid.IsSame(other):
        return True
    one, two = _volume(solid), _volume(other)
    if abs(one - two) > max(INSIDE_ABSOLUTE, INSIDE_RELATIVE * max(one, two)):
        return False
    boxes = []
    for shape in (solid, other):
        box = Bnd_Box()
        BRepBndLib.AddOptimal_s(shape, box, False, False)
        boxes.append(box.Get())
    tolerance = 1e-5 * max(1.0, max(abs(value) for value in boxes[0]))
    return all(abs(a - b) <= tolerance for a, b in zip(*boxes))


def inside(solid, other_solids) -> bool:
    """Whether 'solid' lies wholly inside the part whose solids are 'other_solids'.

    The same solid in the other part answers at once - which is what makes
    'hub xor bolts' cheap where the bolts were taken out of the hub - and
    anything else is measured: the material the two have in common is the
    whole of the solid.
    """
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    if any(_same(solid, other) for other in other_solids):
        return True
    box = Bnd_Box()
    BRepBndLib.Add_s(solid, box)
    near = []
    for other in other_solids:
        other_box = Bnd_Box()
        BRepBndLib.Add_s(other, other_box)
        if not box.IsOut(other_box):
            near.append(other)
    if not near:
        return False
    volume = _volume(solid)
    common = _run(BRepAlgoAPI_Common, solid, ocp_serialize.compound_of(near)).Shape()
    return _volume(common) >= volume - max(INSIDE_ABSOLUTE, INSIDE_RELATIVE * volume)


def by_whole_solids(operation: str, first: Operand, second: Operand):
    """'(shape, carried)': the operation by whole solids, and what each face and solid of it is in."""
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer

    first_solids, second_solids = _solids(first.shape), _solids(second.shape)
    if operation == "and":
        kept = [(solid, first) for solid in first_solids if inside(solid, second_solids)]
    else:
        kept = []
        if operation == "or":
            kept += [(solid, first) for solid in first_solids]
        else:
            kept += [(solid, first) for solid in first_solids if not inside(solid, second_solids)]
        kept += [(solid, second) for solid in second_solids if not inside(solid, first_solids)]
    carried = Carried()
    for solid, operand in kept:
        cmf_set = operand.set_of(solid, solid=True)
        if cmf_set is not None:
            carried.solids[solid] = cmf_set
        explorer = TopExp_Explorer(solid, TopAbs_FACE)
        while explorer.More():
            face = explorer.Current()
            cmf_set = operand.set_of(face, solid=False)
            if cmf_set is not None:
                carried.faces[face] = cmf_set
            explorer.Next()
    return ocp_serialize.compound_of(solid for solid, _operand in kept), carried


def process(request):
    operation = request.get("operation")
    if operation not in OPERATIONS:
        raise ValueError("The operation is one of %s, not %r" % (", ".join(OPERATIONS), operation))
    operands = request.get("operands")
    if not isinstance(operands, list) or len(operands) != 2:
        raise ValueError("A boolean takes two parts")
    first, second = Operand(operands[0], "first"), Operand(operands[1], "second")
    combine = by_whole_solids if request.get("whole") else by_volume
    shape, carried = combine(operation, first, second)
    if not _solids(shape):
        raise ValueError("The %s of the two parts is empty: it leaves no solid" % operation)
    return shape, ocp_serialize.cmf_section_for(shape, faces=carried.faces, solids=carried.solids)


if __name__ == "__main__":
    # Not decoded on the way in: the operands' CMF sections are read off their
    # payloads, which decoding throws away.
    _, request = wrapper_common.handle_input(decode=False)
    try:
        shape, section = process(request)
    except Exception as e:
        wrapper_common.handle_exception(e)
        model = {"success": False, "exception": str(e), "shape": None}
    else:
        # Validated and moved here, while it is live (see wrapper_common.finished).
        model = {"success": True, "exception": None, "shape": wrapper_common.finished(shape, cmf=section)}
    wrapper_common.handle_output(model)
