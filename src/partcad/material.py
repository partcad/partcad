#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The 'material' a part is made of.

A part's ``material`` parameter is one of the MCFT parameters: it does not
describe the shape, it says what the shape is to be made out of. Until now it
was a plain string, matched against whatever a manufacturing provider happened
to call the same substance, and the packages that catalogued materials
(``//pub/std/manufacturing/material/...``) declared them in a section PartCAD
did not read. This module is the object that string now points at.

A 'Material' is deliberately **not** a 'Shape', for the same reason 'Software'
is not: there is nothing to tessellate, render, export or measure. PLA is not a
thing with geometry, it is a set of facts about a substance - what it is
formally called, how dense it is, how well it grips, what it is good and bad at
- that the things with geometry refer to. Density and friction are the two of
those facts PartCAD computes with (mass = volume x density; 'mu' is what decides
whether a stack of them stands up), and it is why both are carried in the units
the rest of PartCAD works in rather than the ones a datasheet prints.

Both reach a simulation. Whether two blocks stay stacked is not a property of
their geometry at all: squarely stacked 20 mm cubes stay put at mu = 0.2 and
scatter at mu = 0.0, and nothing about the arrangement changes in between. And
what they weigh, where they balance and how they turn are the solid plus the
density, and nothing else. A part that says what it is made of therefore says
whether it stands up and what it weighs, and 'PHYSICS_FROM_MATERIAL' below is
where that stops being a fact nobody reads. See docs/source/simulation.rst.

Materials are addressed like every other object, as '<package>:<name>', so a
part in one package names a material catalogued in another exactly as it names
an interface or a sketch. That is the whole point: 'lookup()' here is what turns
'//pub/std/manufacturing/material/plastic:pla' from a string nobody resolves
into the object a provider, a bill of materials or a mass calculation can ask
questions of.
"""

import typing

from . import cmf, telemetry

# What a material contributes to the physics of a shape made of it: the
# 'Material' attribute, and the PartCAD property it fills in where the shape
# states none.
#
# 'mu' decides whether a stack of these stands up. 'density' is what they weigh:
# a part's mass, centre of mass and inertia are its solid at this one number,
# so the three agree with each other and with what the part is made of (see
# 'partcad.physics'). Both are lent under the names and in the units a part
# would state them in itself - a density in kg/m^3, the one unit PartCAD has for
# one - so lending is a copy and not a conversion.
#
# A part that states a value of its own keeps it: a part weighed on the bench
# beats the substance it is made of.
PHYSICS_FROM_MATERIAL = {"mu": "friction", "density": "density"}

# What a material contributes to an analysis of a shape made of it: the
# 'Material' attribute, and the parameter of an analysis implementation it
# fills in where neither the package, nor the object, nor the run states one
# (see 'partcad.cae_material'). In SI, as every physical quantity here is: a
# stiffness and a strength in Pa, which is what '//pub/feature/cae/calculix'
# takes them in, a conductivity in W/(m*K) and a viscosity in Pa*s.
#
# The parameter is named as the implementations in the index already name it,
# which is not always the material's own name for it: every thermal analysis
# there ('//pub/feature/cae/code_aster:thermal', and Elmer's and MOOSE's) takes
# a 'conductivity', and a material says which conductivity it means.
#
# 'viscosity' is what only a fluid states, and a fluid only reaches an
# analysis of a fluid: see 'partcad.cae_material.FLUID_ANALYSES'.
ANALYSIS_FROM_MATERIAL = {
    "youngs_modulus": "youngs_modulus",
    "poissons_ratio": "poissons_ratio",
    "yield_strength": "yield_strength",
    "density": "density",
    "thermal_conductivity": "conductivity",
    "viscosity": "viscosity",
}


# The numbers a material states, by the key it states each under, and the range
# each has to lie in - the same keywords, with the same bounds, the schema
# gives the plain number ('partcad_utils/schema/partcad.json', where a test
# holds the two together). A material may compute any of them from its
# parameters ('density: "%1040 + 100 * butadiene%"', see 'partcad.cmf'), and
# what the expression comes to is held to the same range a number written out
# is: a parametric declaration whose 'max' a catalogue got wrong would
# otherwise hand an analysis a negative stiffness.
NUMBERS = {
    "density": {"exclusiveMinimum": 0},
    "viscosity": {"exclusiveMinimum": 0},
    "youngsModulus": {"exclusiveMinimum": 0},
    "poissonsRatio": {"minimum": 0, "exclusiveMaximum": 0.5},
    "yieldStrength": {"exclusiveMinimum": 0},
    "thermalConductivity": {"exclusiveMinimum": 0},
    "mu": {"minimum": 0},
}

_RANGE_WORDS = {
    "minimum": ("at least", lambda value, bound: value >= bound),
    "exclusiveMinimum": ("above", lambda value, bound: value > bound),
    "maximum": ("at most", lambda value, bound: value <= bound),
    "exclusiveMaximum": ("below", lambda value, bound: value < bound),
}


def _spells_a_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def number_problems(config: dict) -> list:
    """What is wrong with the numbers a material's declaration states, once rendered, as clauses.

    Each has to be a number - an expression that could not be evaluated is
    still the text it was written as (see 'partcad.expr.resolve'), and a
    string where a density belongs is the fault, not something to read a
    number out of later - in the range 'NUMBERS' gives it.
    """
    problems = []
    for key, bounds in NUMBERS.items():
        value = config.get(key)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            hint = ""
            if isinstance(value, str) and "%" not in value and _spells_a_number(value):
                # YAML 1.1 reads '69e9' as text: a number written with an
                # exponent is one only with a point and a signed exponent.
                hint = ": YAML reads a number with an exponent only when it has a point and a sign, as '69.0e+9'"
            problems.append("its '%s' is %r, which is text and not a number%s" % (key, value, hint))
            continue
        for keyword, bound in bounds.items():
            words, holds = _RANGE_WORDS[keyword]
            if not holds(value, bound):
                problems.append("its '%s' is %s, and has to be %s %s" % (key, "%g" % value, words, "%g" % bound))
    return problems


@telemetry.instrument()
class Material(cmf.Declaration):
    """One material of a package: a CMF declaration with the physical facts of a substance.

    'density' is in kg/m^3, the unit every density in PartCAD is in - a part's
    'physics', an export's 'density' parameter, and every simulation format a
    part is written into. One unit is what keeps a mass from being off by a
    factor nobody notices: a datasheet's 1.32 g/cm^3 is 1320 here, and there is
    no second spelling of it anywhere for that number to be mistaken for.
    """

    kind: str = "material"

    @property
    def color_claim(self) -> typing.Optional[str]:
        """The colour the material claims for its natural surface, as written, or None.

        A reference to a colour declaration: an unpainted aluminium part is
        whatever colour aluminium is, and a part made of it that states no colour
        of its own is that colour (see docs/design/cmf.md).
        """
        claim = self.config.get("color")
        return claim if isinstance(claim, str) and claim.strip() else None

    @property
    def formal(self) -> typing.Optional[str]:
        """The short formal name ('PLA'), or None.

        Falls back to nothing rather than to 'name': the object's own name is
        the address it is reached at, which a package is free to spell however
        it likes, and reporting it as though the package had stated a formal
        name would be inventing one.
        """
        return self.config.get("formal")

    @property
    def full(self) -> typing.Optional[str]:
        """The full name of the substance ('Polylactic Acid'), or None."""
        return self.config.get("full")

    @property
    def url(self) -> typing.Optional[str]:
        return self.config.get("url")

    @property
    def density(self) -> typing.Optional[float]:
        """Density in kg/m^3, or None if the package did not state one."""
        value = self.config.get("density")
        return None if value is None else float(value)

    @property
    def youngs_modulus(self) -> typing.Optional[float]:
        """Young's modulus in Pa, or None if the package did not state one.

        How stiff the substance is in tension: what an analysis of a part made
        of it deflects by. In Pa rather than the GPa a datasheet prints, for the
        reason a density is in kg/m^3: one unit, so that no number is off by a
        factor nobody notices (PLA is about 3.5e9, steel about 2.0e11).
        """
        value = self.config.get("youngsModulus")
        return None if value is None else float(value)

    @property
    def poissons_ratio(self) -> typing.Optional[float]:
        """Poisson's ratio, dimensionless, or None if the package did not state one."""
        value = self.config.get("poissonsRatio")
        return None if value is None else float(value)

    @property
    def yield_strength(self) -> typing.Optional[float]:
        """The stress in Pa past which the substance stops springing back, or None if none was stated.

        What an analysis holds a part made of it to: a part whose peak stress
        exceeds it is one that bends for good, or breaks.
        """
        value = self.config.get("yieldStrength")
        return None if value is None else float(value)

    @property
    def thermal_conductivity(self) -> typing.Optional[float]:
        """Thermal conductivity in W/(m*K), or None if the package did not state one.

        How readily heat crosses the substance: what a steady heat conduction
        analysis of a part made of it is solved with. Near room temperature, as
        a datasheet tabulates it; a conductivity that changes much with
        temperature is a different material at the other temperature, the way a
        fluid at another temperature is.
        """
        value = self.config.get("thermalConductivity")
        return None if value is None else float(value)

    @property
    def is_fluid(self) -> bool:
        """Whether this is a fluid: a substance that states a viscosity.

        What a scene is filled with, and what a fluid-dynamics analysis meshes
        a part as -- never what a stress, a mode or a conduction analysis of a
        part made of it is solved with (see 'partcad.cae_material').
        """
        return self.viscosity is not None

    @property
    def viscosity(self) -> typing.Optional[float]:
        """Dynamic viscosity in Pa*s, or None if the package did not state one.

        What makes a substance a *fluid* worth filling a scene with (see
        'Scene.get_medium()'): how hard it resists being sheared, which is what
        a simulator's drag on a body moving through it is made of. Dynamic
        rather than kinematic viscosity, because that is what MuJoCo states and
        what a datasheet tabulates first; the kinematic one is this divided by
        'density', and stating both would be two numbers that can disagree.

        In SI, as every physical quantity PartCAD states is (only lengths and
        angles are millimetres and degrees), so that it goes into a simulation
        format as it was written: water at 15 degrees C is 0.001138 here, on its
        datasheet and in MuJoCo's '<option viscosity>' alike.
        """
        value = self.config.get("viscosity")
        return None if value is None else float(value)

    @property
    def mu(self) -> typing.Optional[float]:
        """The coefficient of sliding friction, or None if none was stated.

        Dimensionless, and the same number all three simulation formats state:
        SDFormat's ``<surface><friction><ode><mu>``, URDF's ``<gazebo><mu1>``
        and MJCF's first ``friction`` component. PartCAD calls it 'friction' as
        a shape property and 'mu' here, because that is what a datasheet and
        every one of those formats calls it.

        It is a property of a *pair* of surfaces in reality and of one surface
        in every simulator, which is the approximation all three formats make
        and this makes with them: what is stated is this material against a
        typical counterface, and the simulator combines the two sides its own
        way.
        """
        value = self.config.get("mu")
        return None if value is None else float(value)

    @property
    def tags(self) -> list[str]:
        """What the material is good at, as the package chose to say it.

        Free-form on purpose. There is no controlled vocabulary of material
        properties that survives contact with real catalogues, and inventing one
        here would only mean packages could not say what they mean.
        """
        tags = self.config.get("tags")
        if not tags:
            return []
        if isinstance(tags, str):
            return [tags]
        return [str(tag) for tag in tags]

    def mass(self, volume: float) -> typing.Optional[float]:
        """The mass in kilograms of 'volume' mm^3 of this material.

        A volume is measured in mm^3 and a density is stated in kg/m^3, and
        'mass_properties.mass_of()' is the one place the two meet - the same
        function every part's derived mass goes through, so this answer and the
        one 'pc info' gives for a part cannot disagree.

        None when the material does not state a density: a made-up mass is
        worse than no mass, because nothing downstream can tell it apart from a
        measured one.
        """
        density = self.density
        if density is None:
            return None
        from .physics import mass_properties

        return mass_properties.mass_of(volume, density)

    def material_info(self) -> dict:
        """What this object is, as the '<label>: <value>' pairs 'pc info' prints.

        Named the way 'Software.software_info()' and 'Shape.shape_info()' are,
        and for the same reason: 'info' is the attribute a factory replaces, so
        the object's own half of the answer needs a name of its own.
        """
        info = self.cmf_info()
        info.pop("Errors", None)
        if self.color_claim:
            info["Color"] = self.color_claim
        if self.formal:
            info["Formal"] = self.formal
        if self.full:
            info["Full"] = self.full
        if self.desc:
            info["Desc"] = self.desc
        if self.density is not None:
            info["Density"] = "%g kg/m^3" % self.density
        if self.viscosity is not None:
            info["Viscosity"] = "%g Pa*s" % self.viscosity
        if self.youngs_modulus is not None:
            info["Youngs modulus"] = "%g Pa" % self.youngs_modulus
        if self.poissons_ratio is not None:
            info["Poissons ratio"] = "%g" % self.poissons_ratio
        if self.yield_strength is not None:
            info["Yield strength"] = "%g Pa" % self.yield_strength
        if self.thermal_conductivity is not None:
            info["Thermal conductivity"] = "%g W/(m*K)" % self.thermal_conductivity
        if self.mu is not None:
            info["Mu"] = "%g" % self.mu
        if self.tags:
            info["Tags"] = ", ".join(self.tags)
        if self.url:
            info["Url"] = self.url
        if self.errors:
            info["Errors"] = list(self.errors)
        return info

    def info(self) -> dict:
        return self.material_info()


def lookup(ctx, ref: str, quiet: bool = False):
    """The (package, material) a fully qualified reference points at.

    Both are None when the reference resolves to nothing. Reported here, once,
    rather than by each caller: a mass calculation and a manufacturing quote ask
    the same question, and a reference that does not resolve is the same mistake
    either way.

    'quiet' is for the callers that are not the ones to report it - a provider
    deciding whether it can make something out of what was asked for, which asks
    the same question moments before the caller that *will* report it.

    Shaped exactly like 'software.lookup()', because a caller resolving a
    reference should not have to learn a second way of doing it per kind.
    """
    found = cmf.lookup(ctx, "material", ref, quiet=quiet)
    if found is None:
        # 'cmf.lookup' has already said why, unless it was asked not to. The
        # package is still answered where there is one.
        package_name, _name = cmf._split(ref, "")
        return (ctx.get_project(package_name) if ctx is not None else None), None
    return ctx.get_project(found.project_name), found


def analysis_of(material) -> dict:
    """What a material says about an analysis of anything made of it, under the implementation's names."""
    facts = {}
    for field, parameter in ANALYSIS_FROM_MATERIAL.items():
        value = getattr(material, field, None)
        if value is not None:
            facts[parameter] = value
    return facts


def physics_of(material) -> dict:
    """What a material says about the physics of anything made of it.

    Only the facts 'PHYSICS_FROM_MATERIAL' maps, under the PartCAD property
    names a shape would have stated them under itself - so that what arrives
    from a material and what a shape declares are the same vocabulary, and
    merging them is one dictionary update rather than a translation.
    """
    facts = {}
    for field, prop in PHYSICS_FROM_MATERIAL.items():
        value = getattr(material, field, None)
        if value is not None:
            facts[prop] = value
    return facts
