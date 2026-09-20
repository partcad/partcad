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


def volumes(shape):
    """The volume of each solid in 'shape', largest first.

    Per solid rather than summed, for the reason wrapper_solidity gives: a
    compound holding one inverted solid and a larger correct one adds up to a
    positive number, and the inversion disappears into the total. The caller
    adds them up knowing how many there were.
    """
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    found = []
    explorer = TopExp_Explorer(shape, TopAbs_SOLID)
    while explorer.More():
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(explorer.Current(), props)
        found.append(props.Mass())
        explorer.Next()
    return sorted(found, reverse=True)


def measurements(shape):
    """Everything generic that is worth knowing about a shape's size.

    ``{"bbox": [...] | None, "volume": float | None, "solids": int}``.

    'volume' is None - rather than 0.0 - for a shape holding no solid at all: a
    sketch, a shell, a wire. A shape that encloses nothing and a shape that is
    not the kind of thing that encloses anything are different answers, and only
    the first of them is a defect.

    A negative volume is returned as it stands: it means the faces are oriented
    inward, which is worth seeing rather than taking the modulus of.
    """
    found = volumes(shape)
    return {
        "bbox": bbox(shape),
        "volume": sum(found) if found else None,
        "solids": len(found),
    }


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
