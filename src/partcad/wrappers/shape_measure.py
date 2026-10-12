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
"""


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


def _solid_properties(shape):
    """The volume properties of each solid in 'shape', as OCCT integrates them."""
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    found = []
    explorer = TopExp_Explorer(shape, TopAbs_SOLID)
    while explorer.More():
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(explorer.Current(), props)
        found.append(props)
        explorer.Next()
    return found


def volumes(shape):
    """The volume of each solid in 'shape', largest first.

    Per solid rather than summed, for the reason wrapper_solidity gives: a
    compound holding one inverted solid and a larger correct one adds up to a
    positive number, and the inversion disappears into the total. The caller
    adds them up knowing how many there were.
    """
    return sorted((props.Mass() for props in _solid_properties(shape)), reverse=True)


def distribution(solids):
    """Where the solids' volume is and how it is spread: (centroid, unit inertia).

    The centroid in millimetres, and the inertia tensor about it as a 3x3 list,
    taken at a density of one in the shape's own units - mm^5. It is the half of
    a mass, a centre of mass and an inertia that the geometry decides; the other
    half is one number, a density, which the geometry knows nothing about and
    the core multiplies in (see 'mass_properties.of_solid()'). Splitting them
    there is what lets this half be measured once, as the shape is built, and
    cached with the geometry it describes, while a material's density can be
    edited without rebuilding anything.

    OCCT's MatrixOfInertia() is already the tensor about the centre of mass, and
    with its products of inertia already negated - the tensor itself rather
    than the integrals - which is the form URDF, SDFormat and MJCF all state.
    Adding the solids up with GProp_GProps.Add() moves each one's tensor to the
    common centroid, so a compound of several is one distribution.

    (None, None) unless every solid encloses a positive volume. A solid with its
    faces turned inward integrates to a negative mass, and a centre of mass
    worked out with one in the sum is a number with no meaning - the volume is
    reported as it stands, and that is where the defect shows.
    """
    from OCP.GProp import GProp_GProps

    if not solids or any(props.Mass() <= 0.0 for props in solids):
        return None, None
    total = GProp_GProps()
    for props in solids:
        total.Add(props)
    centre = total.CentreOfMass()
    matrix = total.MatrixOfInertia()
    # Row/column indices in OCCT's gp_Mat are 1-based.
    tensor = [[matrix.Value(row, col) for col in (1, 2, 3)] for row in (1, 2, 3)]
    return [centre.X(), centre.Y(), centre.Z()], tensor


def measurements(shape):
    """Everything generic that is worth knowing about a shape's size.

    ``{"bbox": [...] | None, "volume": float | None, "solids": int,
    "centroid": [x, y, z] | None, "unitInertia": [[...], [...], [...]] | None}``.

    'volume' is None - rather than 0.0 - for a shape holding no solid at all: a
    sketch, a shell, a wire. A shape that encloses nothing and a shape that is
    not the kind of thing that encloses anything are different answers, and only
    the first of them is a defect.

    A negative volume is returned as it stands: it means the faces are oriented
    inward, which is worth seeing rather than taking the modulus of.

    'centroid' and 'unitInertia' are what a mass is worked out from - see
    'distribution()'. They are taken in the same pass over the solids as the
    volume, so a shape that is measured at all is measured for its mass too.
    """
    solids = _solid_properties(shape)
    found = sorted((props.Mass() for props in solids), reverse=True)
    centroid, unit_inertia = distribution(solids)
    measured = {
        "bbox": bbox(shape),
        "volume": sum(found) if found else None,
        "solids": len(found),
    }
    if centroid is not None:
        measured["centroid"] = centroid
        measured["unitInertia"] = unit_inertia
    return measured


def measurements_or_none(shape):
    """'measurements()', or None if the shape cannot be measured at all.

    Measuring happens on the way past - inside the encoder, as a shape a wrapper
    just built is serialized - so it is never the answer the caller asked for.
    A shape whose geometry is too broken to bound or to integrate still has a
    BREP worth returning, and returning it is what was asked; the size is the
    extra. So a failure here costs the measurement and nothing else.
    """
    try:
        return measurements(shape)
    except Exception:  # pylint: disable=broad-except
        return None
