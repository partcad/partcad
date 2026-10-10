#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The arithmetic of mass, centre of mass and inertia - PartCAD's one copy of it.

Imported by the core, which works out what each part weighs (see
'partcad.physics'), and by every exporter that writes a body's inertia: the
URDF one in '//builtin/export', and the MJCF and SDFormat ones the simulation
plugins carry. A plugin runs in a sandbox with this directory on its path, so
it imports this module the way it imports 'urdf_common' and 'ocp_serialize',
and does none of this arithmetic itself. Three exporters with a copy each is
three ways to place an inertia, and a URDF and an MJCF of the same robot that
disagree about where it balances.

Deliberately free of every dependency but 'urdf_common', which is free of every
dependency: no OCP, so the core can import it without loading a CAD kernel,
and the exporters can do this without one too. The geometry's share of a mass
is measured once, by OCCT, as the shape is built (see
'shape_measure.distribution()'), and everything after that is a handful of
3x3 matrices.

The currency is a PartCAD ``physics`` dict - the names and the units a part
states its own under, so that what a part states and what is worked out for it
are the same kind of thing and one can stand in for the other:

    mass                kg
    centerOfMass        [x, y, z] mm, in the frame the dict is stated in
    inertia             {"ixx", "ixy", "ixz", "iyy", "iyz", "izz"} kg*m^2,
                        about 'centerOfMass'
    inertiaOrientation  [roll, pitch, yaw] degrees, optional: the frame
                        'inertia' is stated in, relative to the dict's own

A dict this module produces states its inertia in its own frame and so never
carries an 'inertiaOrientation'. One it is handed may, and is read as stated.
Keys other than these four are neither read nor carried: friction and contact
are not mass properties, and have nothing to add up.

Two more keys are read, by 'volume_of()' and 'displacement_of()' alone:

    volume              mm^3, what the solid encloses - measured, never stated
    centerOfVolume      [x, y, z] mm, the centroid of that volume, in the frame
                        the dict is stated in - measured, never stated

Neither is a mass property, and neither is carried into what 'placed()' and
'combined()' return: what a body's volume is, and where its middle is, have
nothing to do with how its mass is spread. They are what the body displaces of
the fluid a scene is filled with, and where the fluid pushes it up from - the
two facts buoyancy needs that a mass and a density cannot give. A sealed float
states its mass and still pushes aside the whole of its solid, and a hull with a
lead keel balances low while the water lifts it from its middle; the distance
between those two points is what rights it.

The products of inertia are the tensor's own entries, not the integrals they
are the negatives of - the convention URDF, SDFormat and MJCF all state, and
OCCT's MatrixOfInertia() already follows.
"""

import math

import urdf_common

# Millimetres per metre: a centre of mass is stated in millimetres, an inertia
# in kg*m^2, so the one place they meet - the parallel-axis term - converts.
MM_PER_M = urdf_common.MM_PER_M

# Cubic metres per cubic millimetre: a volume is measured in mm^3 and a density
# is stated in kg/m^3, so this is the whole of turning the one into a mass.
M3_PER_MM3 = 1.0e-9

# m^5 per mm^5: the second moment OCCT integrates at unit density is length^5,
# and this is what makes it kg*m^2 once the density (kg/m^3) is applied.
M5_PER_MM5 = 1.0e-15

INERTIA_KEYS = ("ixx", "ixy", "ixz", "iyy", "iyz", "izz")

MASS_KEYS = ("mass", "centerOfMass", "inertia", "inertiaOrientation")

VOLUME_KEY = "volume"

CENTER_OF_VOLUME_KEY = "centerOfVolume"

_ZERO = ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))


def mass_of(volume_mm3, density_kg_m3):
    """The mass in kilograms of 'volume_mm3' cubic millimetres at 'density_kg_m3'.

    The one place a volume and a density become a mass. A density is in kg/m^3
    everywhere in PartCAD - a material's, a part's, an export's - and a volume
    in mm^3, so this is one multiplication, and it is here so that nobody
    writes it with the exponent the wrong way round.
    """
    return float(volume_mm3) * M3_PER_MM3 * float(density_kg_m3)


def of_solid(volume_mm3, centroid_mm, unit_inertia_mm5, density_kg_m3):
    """The mass properties of a homogeneous solid, as a physics dict.

    'centroid_mm' and 'unit_inertia_mm5' are what the solid measured as it was
    built - its centroid, and its inertia tensor about it at a density of one
    (see 'shape_measure.distribution()'). The density scales the volume into a
    mass and the second moment into an inertia, and moves nothing: a
    homogeneous solid balances at its centroid whatever it is made of.
    """
    density = float(density_kg_m3)
    factor = density * M5_PER_MM5
    return {
        "mass": mass_of(volume_mm3, density),
        "centerOfMass": [float(v) for v in centroid_mm],
        "inertia": inertia_of([[float(value) * factor for value in row] for row in unit_inertia_mm5]),
    }


def tensor_of(physics):
    """The inertia tensor a physics dict states, as a 3x3 list in the dict's own frame.

    An 'inertiaOrientation' is folded in: the stated tensor is in a frame turned
    by it, and is turned back. None when the dict states no inertia.
    """
    inertia = (physics or {}).get("inertia")
    if not isinstance(inertia, dict) or not inertia:
        return None
    value = {key: float(inertia.get(key, 0.0) or 0.0) for key in INERTIA_KEYS}
    tensor = [
        [value["ixx"], value["ixy"], value["ixz"]],
        [value["ixy"], value["iyy"], value["iyz"]],
        [value["ixz"], value["iyz"], value["izz"]],
    ]
    orientation = physics.get("inertiaOrientation")
    if orientation and any(float(v) for v in orientation):
        rotation = urdf_common.rpy_to_quat([math.radians(float(v)) for v in orientation])
        tensor = _rotated(tensor, rotation)
    return tensor


def inertia_of(tensor):
    """A 3x3 tensor as the six-key 'inertia' dict a physics dict states it as."""
    return {
        "ixx": tensor[0][0],
        "ixy": tensor[0][1],
        "ixz": tensor[0][2],
        "iyy": tensor[1][1],
        "iyz": tensor[1][2],
        "izz": tensor[2][2],
    }


def with_mass(physics, mass):
    """'physics' at another mass: the same centre, the inertia scaled to match.

    What a part that states its mass and not its inertia gets. Its solid says
    how the mass is spread and the statement says how much of it there is, and
    a homogeneous body's inertia is proportional to its mass - so the derived
    tensor is scaled rather than thrown away, and a part weighed on the bench is
    not left turning as if it were a point.
    """
    result = {key: physics[key] for key in ("centerOfMass", "inertia", "inertiaOrientation") if key in physics}
    result["mass"] = float(mass)
    own = float(physics.get("mass") or 0.0)
    tensor = tensor_of(physics)
    if tensor is not None and own > 0.0:
        ratio = float(mass) / own
        result["inertia"] = inertia_of([[value * ratio for value in row] for row in tensor])
        result.pop("inertiaOrientation", None)
    return result


def placed(physics, location):
    """'physics' as seen from the frame a shape is placed in.

    'location' is the placement - PartCAD's packed ``[[tx, ty, tz], [ax, ay,
    az], angle]``, or None for none. The centre of mass moves with the shape and
    the tensor turns with it (R I R^T); it stays about the centre of mass, so
    no parallel-axis term belongs here - that is 'combined()'s, where there is
    a common centre to move to. A dict with no mass comes back as None, because
    there is nothing to place.
    """
    if not weighs(physics):
        return None
    centre = [float(v) for v in (physics.get("centerOfMass") or (0.0, 0.0, 0.0))]
    tensor = tensor_of(physics)
    if location is not None:
        rotation, translation = urdf_common.from_packed(location)
        moved = urdf_common.rotate_vec(rotation, centre)
        centre = [moved[axis] + translation[axis] for axis in range(3)]
        if tensor is not None:
            tensor = _rotated(tensor, rotation)
    result = {"mass": float(physics["mass"]), "centerOfMass": centre}
    if tensor is not None:
        result["inertia"] = inertia_of(tensor)
    return result


def combined(parts):
    """The mass properties of several physics dicts held rigidly together.

    Every dict is stated in the same frame (see 'placed()'). The masses add,
    the centre of mass is their weighted mean, and each part's tensor is moved
    from its own centre to the common one by the parallel-axis theorem before
    the tensors are added. A part that states a mass and no inertia counts as a
    point mass, which is what URDF and SDFormat make of one too.

    A part with no mass - an open shell, a mesh nobody weighed - adds nothing,
    exactly as it adds nothing to an integral. None when nothing in 'parts'
    has a mass, so that a body made of nothing weighable is written with no
    inertia rather than with an invented one.
    """
    weighed = [part for part in parts if weighs(part)]
    if not weighed:
        return None
    total = sum(float(part["mass"]) for part in weighed)
    centres = [[float(v) for v in (part.get("centerOfMass") or (0.0, 0.0, 0.0))] for part in weighed]
    centre = [sum(float(part["mass"]) * c[axis] for part, c in zip(weighed, centres)) / total for axis in range(3)]

    any_inertia = False
    tensor = [[0.0] * 3 for _ in range(3)]
    for part, own_centre in zip(weighed, centres):
        mass = float(part["mass"])
        own = tensor_of(part)
        if own is None:
            own = _ZERO
        else:
            any_inertia = True
        offset = [(own_centre[axis] - centre[axis]) / MM_PER_M for axis in range(3)]
        square = sum(v * v for v in offset)
        for row in range(3):
            for col in range(3):
                shift = mass * ((square if row == col else 0.0) - offset[row] * offset[col])
                tensor[row][col] += own[row][col] + shift

    result = {"mass": total, "centerOfMass": centre}
    # Point masses all of them, and only one: a single point has no inertia to
    # speak of, and a zero tensor written out would claim one.
    if any_inertia or len(weighed) > 1:
        result["inertia"] = inertia_of(tensor)
    return result


def of_body(parts, own=None):
    """The mass properties of one rigid body - a URDF link, an MJCF body.

    'parts' is the (physics, placement) pairs the body is made of, each
    placement in the body's frame or None. 'own' is what the body states about
    itself when it is not simply one of its parts: a sub-assembly that is one
    link of several shapes, and that states its own mass, is taken at its word
    - a measured link beats the sum of its pieces.

    A body that is one part, unplaced, *is* that part, and comes back exactly as
    the part states it - inertiaOrientation and all - so that what was read from
    a file goes back into one unchanged. Anything else is 'combined()'.

    None when nothing here has a mass.
    """
    if own and weighs(own):
        return own
    parts = list(parts)
    if len(parts) == 1 and parts[0][1] is None:
        physics = parts[0][0]
        return physics if weighs(physics) else None
    return combined([placed(physics, location) for physics, location in parts if physics])


def volume_of(parts):
    """The volume one rigid body encloses, in mm^3, or None if any part of it is not known.

    'parts' is the same (physics, placement) pairs 'of_body()' takes, so that an
    exporter hands both functions one list and the body's volume and its mass
    are of the same shapes. The placements are not needed - a volume is the
    same wherever the shape is put - and are taken only so the two agree.

    The sum of what each part encloses, which is the body's as long as its
    parts do not overlap, as the parts of one body do not. None, rather than the
    sum of the rest, when a part's volume is not known (an open mesh, a shell):
    a body buoyed by part of what it displaces floats wrongly, and nothing
    downstream could tell. None for a body of no parts, too.
    """
    total = 0.0
    counted = 0
    for physics, _location in parts:
        try:
            volume = float((physics or {}).get(VOLUME_KEY))
        except (TypeError, ValueError):
            return None
        if not math.isfinite(volume) or volume <= 0.0:
            return None
        total += volume
        counted += 1
    return total if counted else None


def displacement_of(parts):
    """What one rigid body displaces, as {'volume': mm^3, 'centerOfVolume': [x, y, z] mm}, or None.

    'parts' is the same (physics, placement) pairs 'of_body()' and
    'volume_of()' take. The centre of volume is the volume-weighted mean of
    each part's own, each moved to where the body holds it - the centre of
    buoyancy of the body when it is wholly submerged, which is where a fluid's
    lift acts. Unlike the centre of mass it does not care what anything is made
    of: a hull and its keel are weighed by their materials and buoyed by their
    shapes.

    None when any part's volume or centre of volume is not known, for the reason
    'volume_of()' gives.
    """
    total = volume_of(parts)
    if total is None:
        return None
    centre = [0.0, 0.0, 0.0]
    for physics, location in parts:
        own = (physics or {}).get(CENTER_OF_VOLUME_KEY)
        if not own or len(own) != 3:
            return None
        point = [float(v) for v in own]
        if location is not None:
            rotation, translation = urdf_common.from_packed(location)
            moved = urdf_common.rotate_vec(rotation, point)
            point = [moved[axis] + translation[axis] for axis in range(3)]
        weight = float(physics[VOLUME_KEY]) / total
        for axis in range(3):
            centre[axis] += weight * point[axis]
    return {VOLUME_KEY: total, CENTER_OF_VOLUME_KEY: centre}


def weighs(physics):
    """Whether a physics dict states a mass worth adding up."""
    if not physics or "mass" not in physics:
        return False
    try:
        mass = float(physics["mass"])
    except (TypeError, ValueError):
        return False
    return math.isfinite(mass) and mass > 0.0


def _rotated(tensor, rotation):
    """R T R^T, for the rotation quaternion 'rotation'."""
    # The columns of R are the images of the basis vectors.
    columns = [urdf_common.rotate_vec(rotation, axis) for axis in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))]
    matrix = [[columns[col][row] for col in range(3)] for row in range(3)]
    left = [[sum(matrix[row][k] * tensor[k][col] for k in range(3)) for col in range(3)] for row in range(3)]
    return [[sum(left[row][k] * matrix[col][k] for k in range(3)) for col in range(3)] for row in range(3)]
