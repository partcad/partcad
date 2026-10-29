#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a shape measures, taken where the shape is live.

Separate from both of its callers because it has exactly two, and they are in
different processes:

  * 'ocp_serialize.encode_shape()' calls it as it encodes a shape a wrapper
    produced, which is what puts a part's size into the envelope - and so into
    the cache entry - at the moment the part is built.
  * 'wrapper_measure.py' calls it for the one caller that measures something it
    did not build: 'measure.bbox()', which re-measures a shape in a *port's*
    frame rather than its own.

Two copies of "how big is it" would be two answers to it, and the one in the
cache would be the one nobody re-derived. Hence one module, imported by both.

Nothing here imports OCP at module scope: the core process imports
'ocp_serialize' to encode the shapes its in-process factories still build, and
it pulls the kernel in lazily so that a workflow using only delegating
factories never loads it at all.

**A shape is measured once, however often it is met** (see 'Measurer'). What
costs is integrating a solid's volume - OCCT's 'VolumeProperties', which on
curved geometry takes longer than writing the BREP does - and the same solid
used to be integrated again and again: once inside the compound a script
returned, once more as the component it also returned, and once per placement
when one solid is placed many times. Now a solid is integrated once per
'TShape', its numbers are moved to wherever else it is placed, and a
compound's numbers are worked out from its children's rather than by
integrating them all over again.
"""

import mass_properties


def bbox(shape):
    """The axis-aligned bounding box of 'shape' as [xmin, ymin, zmin, xmax, ymax, zmax].

    The shape is measured exactly as it is handed over - already placed, if the
    caller placed it - so the box is in whatever frame the caller meant. 'None'
    for a shape that bounds nothing, which has no box to speak of.
    """
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    if box.IsVoid():
        return None
    # Bnd_Box.Get() reports the box grown by its gap; drop the gap so that the
    # numbers are the shape's own extent. Without this a 10 mm block measures
    # 10.0000002, which every other caller of a bounding box wants - an exploded
    # view that overlapped by a tolerance would be wrong - and no reader of a
    # reported size does.
    box.SetGap(0.0)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    return [xmin, ymin, zmin, xmax, ymax, zmax]


def _united(box, other):
    """The smallest box holding two boxes, either of which may be None (holding nothing)."""
    if box is None:
        return other
    if other is None:
        return box
    return [min(box[axis], other[axis]) for axis in range(3)] + [max(box[axis], other[axis]) for axis in range(3, 6)]


def _hash(shape):
    """A hash of 'shape' for finding it again in a 'Measurer', or None where the OCP build has none.

    OCP hashes a shape by its 'TShape' and its location, and compares two with
    'IsEqual()', which adds the orientation. Without a hash nothing is found
    again, and everything is measured as it is met - slower, and the same
    numbers.
    """
    try:
        return hash(shape)
    except TypeError:
        return None


def _integrated(solid):
    """'(volume, centroid, unit inertia)' of one solid, as OCCT integrates it where it stands.

    OCCT's MatrixOfInertia() is already the tensor about the centre of mass, and
    with its products of inertia already negated - the tensor itself rather
    than the integrals - which is the form URDF, SDFormat and MJCF all state.
    """
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(solid, props)
    centre = props.CentreOfMass()
    matrix = props.MatrixOfInertia()
    # Row/column indices in OCCT's gp_Mat are 1-based.
    tensor = [[matrix.Value(row, col) for col in (1, 2, 3)] for row in (1, 2, 3)]
    return props.Mass(), [centre.X(), centre.Y(), centre.Z()], tensor


def _moved(measured, transformation):
    """'measured' for the same solid moved by 'transformation' (a gp_Trsf), or None.

    A rigid motion moves the centroid and turns the tensor about it (R I R^T,
    'mass_properties.turned()'), and leaves the volume as it was - which is what
    lets a solid placed a hundred times be integrated once. Anything else - a
    scale, a mirror - changes what there is to integrate, so None, and the
    caller integrates it where it stands.
    """
    from OCP.gp import gp_Pnt

    if abs(transformation.ScaleFactor() - 1.0) > 1e-12 or transformation.IsNegative():
        return None
    volume, centre, tensor = measured
    point = gp_Pnt(*centre).Transformed(transformation)
    rotation = [[transformation.Value(row, col) for col in (1, 2, 3)] for row in (1, 2, 3)]
    return volume, [point.X(), point.Y(), point.Z()], mass_properties.turned(tensor, rotation)


class Measurer:
    """Measures shapes, taking each solid and each shape it is handed once.

    One per document being encoded ('ocp_serialize.encode()' makes one for
    everything it encodes), and never kept beyond it: it holds on to every
    shape it has measured, which is what lets it recognise one again, and a
    process encoding shapes for as long as it runs would hold all of them.

    Two things are remembered, and neither changes a number:

      * A shape - a compound, a solid, a face - by its 'TShape', its location
        and its orientation. Met again, it is the same geometry in the same
        place, so its measurements are what they were. That is what a
        script's components are: the very shapes the compound beside them
        holds, encoded again on their own.
      * A solid by its 'TShape' and orientation alone. Met again somewhere
        else, its volume is the same, and its centroid and its inertia are
        moved there rather than integrated again ('_moved()').

    A compound is measured as its children are: its solids are theirs, in the
    order OCCT's explorer would visit them, and its box is the union of theirs -
    which is exactly the box OCCT draws round the compound, because that box is
    the union of the boxes of the faces, edges and vertices in it, child by
    child. So measuring a compound and then each of its children costs no more
    than measuring the compound.
    """

    def __init__(self):
        self._shapes = {}
        self._solids = {}

    def measurements(self, shape):
        """'measurements(shape)', taking what this measurer has already measured as known."""
        solids, box = self._measured(shape)
        found = sorted((volume for volume, _centre, _tensor in solids), reverse=True)
        centroid, unit_inertia = distribution(solids)
        measured = {
            "bbox": None if box is None else list(box),
            "volume": sum(found) if found else None,
            "solids": len(found),
            # Counted afresh for every shape rather than from its children's:
            # a walk of its containers alone, a step per solid and shell, and a
            # shell two children share is one shell (see 'free_shells()').
            "freeShells": free_shells(shape),
        }
        if centroid is not None:
            measured["centroid"] = centroid
            measured["unitInertia"] = unit_inertia
        return measured

    def measurements_or_none(self, shape):
        """'measurements_or_none(shape)', taking what this measurer has already measured as known."""
        try:
            return self.measurements(shape)
        except Exception:  # pylint: disable=broad-except
            return None

    def _measured(self, shape):
        """'(solids, box)' of 'shape': each solid's '(volume, centroid, unit inertia)', and its box."""
        from OCP.TopAbs import TopAbs_COMPOUND, TopAbs_SOLID
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopoDS import TopoDS_Iterator

        if shape.IsNull():
            # Asked of a null shape, OCCT's ShapeType() does not raise: it
            # crashes the process. A null shape holds nothing, and that is the
            # answer measuring it whole always gave.
            return [], None
        key = _hash(shape)
        if key is not None:
            for known, measured in self._shapes.get(key, ()):
                if known.IsEqual(shape):
                    return measured

        if shape.ShapeType() == TopAbs_COMPOUND:
            solids = []
            box = None
            # Cumulative, as TopExp_Explorer is: each child comes out placed
            # and oriented the way the compound holds it.
            children = TopoDS_Iterator(shape)
            while children.More():
                child_solids, child_box = self._measured(children.Value())
                solids.extend(child_solids)
                box = _united(box, child_box)
                children.Next()
        else:
            solids = []
            explorer = TopExp_Explorer(shape, TopAbs_SOLID)
            while explorer.More():
                solids.append(self._solid(explorer.Current()))
                explorer.Next()
            box = bbox(shape)

        measured = (solids, box)
        if key is not None:
            self._shapes.setdefault(key, []).append((shape, measured))
        return measured

    def _solid(self, solid):
        """'(volume, centroid, unit inertia)' of one solid, integrated once per 'TShape'."""
        from OCP.TopLoc import TopLoc_Location

        location = solid.Location()
        local = solid.Located(TopLoc_Location())
        key = _hash(local)
        known = self._solids.get(key, ()) if key is not None else ()
        for other, where, measured in known:
            if other.IsEqual(local):
                if where.IsEqual(location):
                    return measured
                moved = _moved(measured, location.Transformation().Multiplied(where.Transformation().Inverted()))
                if moved is not None:
                    return moved
                break

        measured = _integrated(solid)
        if key is not None:
            self._solids.setdefault(key, []).append((local, location, measured))
        return measured


def volumes(shape):
    """The volume of each solid in 'shape', largest first.

    Per solid rather than summed, for the reason wrapper_solidity gives: a
    compound holding one inverted solid and a larger correct one adds up to a
    positive number, and the inversion disappears into the total. The caller
    adds them up knowing how many there were.
    """
    solids, _box = Measurer()._measured(shape)
    return sorted((volume for volume, _centre, _tensor in solids), reverse=True)


def free_shells(shape):
    """How many shells in 'shape' no solid bounds itself with.

    A shell no solid owns is a skin rather than a body - the shape itself, or a
    piece of the compound it is - and it is what the 'shell' check fails a part
    for. That check runs in the core, which has no kernel, and used to read the
    answer off the ASCII payload (see 'partcad.brep_inspect'); a payload is
    binary now, so the answer is counted here, as the shape is encoded, and
    travels in the measurements.

    By the rule the payload scan applies, so the two agree: every distinct
    shell, less the ones a solid is made of. Distinct by what the shell *is*
    and not by where it is placed, since a payload records each sub-shape once
    however often it is placed. Only containers are walked - compounds,
    compsolids, solids - so this costs a step per solid and shell rather than
    one per face.
    """
    from OCP.TopAbs import TopAbs_COMPOUND, TopAbs_COMPSOLID, TopAbs_SHELL, TopAbs_SOLID
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS_Iterator
    from OCP.TopTools import TopTools_MapOfShape

    if shape is None or shape.IsNull():
        return 0
    containers = (TopAbs_COMPOUND, TopAbs_COMPSOLID, TopAbs_SOLID)
    unplaced = TopLoc_Location()
    shells = []
    seen = TopTools_MapOfShape()
    bounding = TopTools_MapOfShape()
    pending = [shape]
    while pending:
        current = pending.pop()
        kind = current.ShapeType()
        if kind == TopAbs_SHELL:
            shell = current.Located(unplaced)
            if seen.Add(shell):
                shells.append(shell)
        elif kind in containers:
            children = TopoDS_Iterator(current)
            while children.More():
                child = children.Value()
                if kind == TopAbs_SOLID and child.ShapeType() == TopAbs_SHELL:
                    bounding.Add(child.Located(unplaced))
                pending.append(child)
                children.Next()
    return sum(1 for shell in shells if not bounding.Contains(shell))


def distribution(solids):
    """Where the solids' volume is and how it is spread: (centroid, unit inertia).

    'solids' is each solid's '(volume, centroid, unit inertia)' as OCCT
    integrated it ('_integrated()'), in one frame.

    The centroid in millimetres, and the inertia tensor about it as a 3x3 list,
    taken at a density of one in the shape's own units - mm^5. It is the half of
    a mass, a centre of mass and an inertia that the geometry decides; the other
    half is one number, a density, which the geometry knows nothing about and
    the core multiplies in (see 'mass_properties.of_solid()'). Splitting them
    there is what lets this half be measured once, as the shape is built, and
    cached with the geometry it describes, while a material's density can be
    edited without rebuilding anything.

    Several solids are added up into one distribution by the parallel-axis
    theorem, with 'mass_properties.added_up()' - the arithmetic every body an
    exporter writes is added up with - so a compound of several is one
    distribution. One solid is its own.

    (None, None) unless every solid encloses a positive volume. A solid with its
    faces turned inward integrates to a negative mass, and a centre of mass
    worked out with one in the sum is a number with no meaning - the volume is
    reported as it stands, and that is where the defect shows.
    """
    if not solids or any(volume <= 0.0 for volume, _centre, _tensor in solids):
        return None, None
    if len(solids) == 1:
        _volume, centre, tensor = solids[0]
        return list(centre), [list(row) for row in tensor]
    _total, centre, tensor = mass_properties.added_up(solids, length_unit=1.0)
    return centre, tensor


def measurements(shape):
    """Everything generic that is worth knowing about a shape's size.

    ``{"bbox": [...] | None, "volume": float | None, "solids": int,
    "freeShells": int, "centroid": [x, y, z] | None,
    "unitInertia": [[...], [...], [...]] | None}``.

    'volume' is None - rather than 0.0 - for a shape holding no solid at all: a
    sketch, a shell, a wire. A shape that encloses nothing and a shape that is
    not the kind of thing that encloses anything are different answers, and only
    the first of them is a defect.

    A negative volume is returned as it stands: it means the faces are oriented
    inward, which is worth seeing rather than taking the modulus of.

    'centroid' and 'unitInertia' are what a mass is worked out from - see
    'distribution()'. They are taken in the same pass over the solids as the
    volume, so a shape that is measured at all is measured for its mass too.

    'freeShells' is how many shells no solid bounds itself with - see
    'free_shells()', and the 'shell' check it is recorded for.

    A shape measured on its own; to measure several that share solids, measure
    them with one 'Measurer'.
    """
    return Measurer().measurements(shape)


def measurements_or_none(shape):
    """'measurements()', or None if the shape cannot be measured at all.

    Measuring happens on the way past - inside the encoder, as a shape a wrapper
    just built is serialized - so it is never the answer the caller asked for.
    A shape whose geometry is too broken to bound or to integrate still has a
    BREP worth returning, and returning it is what was asked; the size is the
    extra. So a failure here costs the measurement and nothing else.
    """
    return Measurer().measurements_or_none(shape)
