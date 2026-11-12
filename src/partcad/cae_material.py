#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What an analysis is asked of a part: the geometry it meshes, and what the part is made of.

An analysis implementation takes the substance as parameters of its own -- the
CalculiX FEA (`//pub/feature/cae/calculix:fea`) takes `youngs_modulus`,
`poissons_ratio`, `yield_strength` and `density`, defaulting to steel -- and a
package or an object re-tunes them in its `cae:` section. Until this module, that
was the only way: a part made of PLA was analysed as steel unless somebody wrote
PLA's numbers into its `cae:` section by hand, beside a `material:` that already
said PLA.

**The material fills what nobody stated.** A parameter of the implementation that
the material states (`partcad.material.ANALYSIS_FROM_MATERIAL`) is the material's,
unless the package, the object, the scenario or the run states it: those are
statements about this analysis, and the material is a statement about every
part made of it. The implementation's own default is what is left when neither
says.

**A print is analysed as its design, at the print's density.** A part that is
what its printer makes (`part_config_manufacturing.implied_type`) is, as
geometry, tens of thousands of prisms that touch without sharing a node -- a
mesher makes as many bodies of them, and a solver a singular stiffness matrix;
at the scale of a bead a part the size of a hand is millions of elements. So
what is meshed is the design, and what it is made of is the material
homogenized at the print's density: the volume the printer deposits (walls,
skins and infill together) over the design's. Stiffness, strength and density
are each scaled by that fraction -- the rule of mixtures, which is exact for
the weight and an upper bound for the stiffness of a lattice. A print's walls
carry more than their share of a bending load, and the average does not credit
them with it, which errs on the side of the part failing.

A part that has a geometry of its own -- an as-printed scan, a model somebody
drew -- is analysed as that geometry, at its material's full properties: it is
what it is, and it says nothing about its inside that a mesh would not see.
"""

import typing

from . import logging as pc_logging
from .material import analysis_of

# The parameters a print's density scales: what a homogenized lattice of the
# same substance is, per unit of the design's volume. Poisson's ratio is a
# ratio of strains and is left as it is.
SCALED = ("youngs_modulus", "yield_strength", "density")


class Subject(typing.NamedTuple):
    """What an analysis of a part meshes, and at what fraction of its material."""

    # The shape whose geometry is meshed and whose ports the conditions land on.
    shape: typing.Any
    # The fraction of the design a print deposits, or None for a part that is
    # its own geometry.
    fraction: typing.Optional[float] = None
    # Said in the log: why the design is meshed rather than the part.
    note: typing.Optional[str] = None


def _volume(envelope) -> typing.Optional[float]:
    from . import shape_envelope

    if not isinstance(envelope, dict):
        return None
    metadata = envelope.get(shape_envelope.KEY_METADATA)
    measurements = shape_envelope.metadata_section(metadata, shape_envelope.METADATA_MEASUREMENTS) or {}
    value = measurements.get(shape_envelope.METADATA_VOLUME)
    return float(value) if isinstance(value, (int, float)) and value > 0 else None


async def subject_async(ctx, shape) -> Subject:
    """What 'shape' is meshed as: itself, or -- for a print -- its design, with the fraction it deposits."""
    from .part_config_manufacturing import IMPLIED_TYPE_KEY, METHOD_ADDITIVE, PartConfigManufacturing
    from .qual.basic.manufacturability_reference import resolve_reference

    config = getattr(shape, "config", None)
    if getattr(shape, "kind", None) != "part" or not isinstance(config, dict) or not config.get(IMPLIED_TYPE_KEY):
        return Subject(shape)
    data = PartConfigManufacturing(config)
    if data.method != METHOD_ADDITIVE or not data.design:
        # A cut part and a molding are solids: what the machine leaves of the
        # stock, the cavity shrunk. They mesh as they are.
        return Subject(shape)
    design = await resolve_reference(ctx, shape, data.design, "part")
    if design is None:
        raise Exception("it is printed from '%s', which is not found" % data.design)

    printed = _volume(await shape.get_wrapped(ctx))
    designed = _volume(await design.get_wrapped(ctx))
    if printed is None or designed is None:
        pc_logging.warning(
            "%s:%s: the print or its design recorded no volume, so it is analysed at its material's full density"
            % (shape.project_name, shape.name)
        )
        return Subject(design, None, "analysed as its design, '%s'" % data.design)
    fraction = min(1.0, printed / designed)
    return Subject(
        design,
        fraction,
        "analysed as its design, '%s', at the %.0f%% of it the printer deposits" % (data.design, fraction * 100.0),
    )


def fill(request: dict, material, stated: typing.Iterable[str], fraction: typing.Optional[float]) -> dict:
    """Put what 'material' says into 'request' where nothing 'stated' it; scale by a print's 'fraction'.

    Only a parameter the implementation takes is filled: one it does not
    declare would be a key it ignores, and the request is part of the
    analysis's cache key. Returns what was filled, as it went into the request.
    """
    stated = set(stated)
    facts = analysis_of(material) if material is not None else {}
    filled = {}
    for key, value in facts.items():
        if key in stated or key not in request:
            continue
        filled[key] = value
    if fraction is not None:
        # The print's density applies to whatever the substance is said to be,
        # including the implementation's own default where the material states
        # nothing: a lattice of steel is as much lighter than steel.
        for key in SCALED:
            if key in stated or key not in request:
                continue
            base = filled.get(key, request.get(key))
            if isinstance(base, (int, float)) and not isinstance(base, bool):
                filled[key] = float(base) * fraction
    request.update(filled)
    return filled
