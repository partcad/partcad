#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a scene says about the world it is, beside where things are in it.

A scene states where things are (see 'partcad.scene'). A *simulation* scene has
to state two more things, because a simulation of the same arrangement comes
out differently without them: which way, and how hard, things fall -- and what
they fall *through*. A block dropped on the Moon and the same block dropped in a
tank of seawater are the same scene in every other respect.

    gravity     the acceleration of gravity, as a vector [x, y, z] in the
                scene's own frame, in **m/s^2**.
    medium      the fluid the scene is filled with, as a reference to a
                **material** -- '//pub/std/manufacturing/material/fluid:water',
                or ':brine' for one the scene's own package catalogues. What a
                simulator needs of it is the material's 'density' and
                'viscosity'; its name is only carried along to say what they are.

Both are optional, and both defaults are what every scene has meant until now,
so that no existing result changes:

  * **No gravity** leaves it to the engine, and every engine's default is
    Earth's along -Z -- MuJoCo writes 9.81, SDFormat 9.8. PartCAD does not
    restate a number of its own: a third value for "standard" would move every
    existing simulation by a fraction of a percent for nothing.
  * **No medium** is vacuum, which is what every engine assumes: nothing drags
    and nothing floats.

**Why m/s^2.** Every physical quantity PartCAD states is SI except lengths and
angles, which are millimetres and degrees: a density is kg/m^3, a viscosity
Pa*s, a mass kg, an inertia kg*m^2, a force N (see the 'how:' section of an
ASSY file, which has always said so). An acceleration is not a length, so it is
m/s^2 -- and that is also the unit of the other place a gravity is stated, which
it has to be compared with. A 'simulate:' may pass its plugin a 'gravity' of
its own in 'params', and both simulation plugins have always taken that in
m/s^2, because both engines do; two numbers where one replaces the other must
not be a thousand apart for the same acceleration. It is the number everybody
knows, too: 9.81, 1.62 and 3.72 are Earth, the Moon and Mars to anybody who
reads the file, and 9806.65 is not recognisable as anything.

The mistake the choice invites -- writing -9806.65 in a file that means m/s^2
-- is the one that is easy to catch, because it is a thousand g: anything above
'IMPLAUSIBLE_GRAVITY' is reported. The mistake the other choice would have
invited -- -9.81 in a file that means mm/s^2 -- is a thousandth of a g, which
looks like a plausible slow simulation and is caught by nothing.

Unit-suffixed strings ("9.81 m/s^2") are deliberately not accepted. PartCAD has
no unit-aware scalar yet (item 10 of docs/source/simulation.rst), and a parser
for one field would be a third dialect beside the ones 'partcad.cam' and
'partcad.cae' already speak. A bare number in a documented unit is checked by
the schema; a string would be checked by nothing until it was read here.

The medium's two facts arrive as the material states them, in kg/m^3 and Pa*s,
which is what both engines state them in too: nothing converts them on the way.

This module is what 'Scene' asks and what 'Shape._output_request()' catches;
it is separate from 'partcad.scene' because that module is an 'Assembly' and
'partcad.shape' cannot import it.
"""

from __future__ import annotations

import math
import typing

from . import logging as pc_logging
from . import material as pc_material
from .utils import resolve_resource_path

# The two keys of a scene's declaration.
GRAVITY_KEY = "gravity"
MEDIUM_KEY = "medium"

# Above this many m/s^2 a gravity is almost certainly a vector in mm/s^2 written
# into a field that is in m/s^2. A hundred g: nothing a package would simulate a
# part standing in -- the surface of the Sun is 274 -- and well short of the
# thousand g the mistake actually produces.
IMPLAUSIBLE_GRAVITY = 1000.0


class WorldError(ValueError):
    """A scene whose gravity or medium cannot be made sense of.

    A ValueError, because that is what it is: the declaration says something
    that is not a vector, or names a material nothing answers to. Raised rather
    than logged and defaulted, because the default is a different physics: a
    scene that said it was under water and is simulated in a vacuum answers a
    different question with the same confidence.
    """


def gravity_of(config: dict, where: str) -> typing.Optional[list]:
    """The gravity a scene's declaration states, in m/s^2, or None.

    Raises:
        WorldError: what is there is not three finite numbers. A boolean is not
            one, although YAML's 'true' converts to 1.0 without complaint.
    """
    value = (config or {}).get(GRAVITY_KEY)
    if value is None:
        return None
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)) or len(value) != 3:
        raise WorldError(
            "%s: 'gravity' is a vector of three numbers in m/s^2, such as [0, 0, -9.81]; got %r" % (where, value)
        )
    vector = []
    for component in value:
        if isinstance(component, bool) or not isinstance(component, (int, float)) or not math.isfinite(component):
            raise WorldError("%s: 'gravity' is a vector of three numbers in m/s^2; %r is not one" % (where, component))
        vector.append(float(component))
    return vector


def medium_reference_of(config: dict) -> typing.Optional[str]:
    """The material a scene's declaration says it is filled with, as written, or None."""
    reference = (config or {}).get(MEDIUM_KEY)
    return reference if isinstance(reference, str) and reference else None


def resolve_medium(ctx, project_name: str, reference: str, where: str):
    """The material 'reference' names, resolved against the scene's own package.

    The way 'Shape.get_material()' resolves what a part is made of: ':water'
    means "in the package that declared this scene", and a full path means
    exactly that package.

    Raises:
        WorldError: nothing answers to it. Reported here, with the scene that
            asked, rather than by 'material.lookup()', which would only know the
            reference.
    """
    if reference.count(":") > 1:
        raise WorldError("%s: the medium '%s' is not a material reference" % (where, reference))
    package, name = resolve_resource_path(project_name, reference)
    _project, found = pc_material.lookup(ctx, "%s:%s" % (package, name), quiet=True)
    if found is None:
        raise WorldError(
            "%s: the scene is filled with '%s:%s', and no material answers to that name" % (where, package, name)
        )
    return found


def facts(ctx, project_name: str, config: dict, where: str) -> typing.Optional[dict]:
    """What an implementation is handed about a scene's world, or None.

    None when the scene states neither, which is what keeps every export of a
    scene that predates this exactly what it was. Otherwise a dictionary with
    whichever of the two it states:

        {
          "gravity": [0.0, 0.0, -1.62],                  # m/s^2
          "medium": {
            "material": "//pub/std/manufacturing/material/fluid:seawater",
            "density": 1026.0,                           # kg/m^3, when stated
            "viscosity": 0.00122,                        # Pa*s, when stated
          },
        }

    A medium whose material states neither fact is still carried -- the name
    says what the scene meant -- and is reported, since an engine handed it can
    do nothing with it and the package probably meant something.
    """
    world = {}

    gravity = gravity_of(config, where)
    if gravity is not None:
        magnitude = math.sqrt(sum(component * component for component in gravity))
        if magnitude > IMPLAUSIBLE_GRAVITY:
            pc_logging.warning(
                "%s: 'gravity' is %g m/s^2, which is %.0f g. It is stated in m/s^2: Earth is [0, 0, -9.81]"
                % (where, magnitude, magnitude / 9.80665)
            )
        world[GRAVITY_KEY] = gravity

    reference = medium_reference_of(config)
    if reference is not None:
        material = resolve_medium(ctx, project_name, reference, where)
        medium = {"material": "%s:%s" % (material.project_name, material.name)}
        if material.density is not None:
            medium["density"] = material.density
        if material.viscosity is not None:
            medium["viscosity"] = material.viscosity
        if len(medium) == 1:
            pc_logging.warning(
                "%s: the medium '%s' states no 'density' and no 'viscosity', so a simulation has nothing to "
                "drag or buoy anything with" % (where, medium["material"])
            )
        world[MEDIUM_KEY] = medium

    return world or None
