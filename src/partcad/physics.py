#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a shape's physics turns out to be: stated, lent by its material, or derived.

A part's ``properties: physics:`` is what somebody *stated* about it - a mass
weighed on the bench, an inertia read out of a URDF. Most parts state nothing,
and still have a mass: the solid they are, at the density of what they are made
of. This module is where the two meet, once, for every reader:

  * 'pc info', which shows each value and says where it came from;
  * an export that asks for its shapes' properties, which is handed every
    shape's values already resolved - so the URDF exporter here and the MJCF
    and SDFormat ones in the simulation plugins write a mass, and never work
    one out;
  * the IDE's Build vs Buy table, which shows what a part weighs.

One order, for every value, and the same everywhere:

  density        stated, else the material's, else - for an export only - the
                 export's ``density`` parameter, else DEFAULT_EXPORT_DENSITY
  mass           stated, else the volume at that density
  centerOfMass   stated, else the centroid of the solid
  inertia        stated, else the solid's, scaled to the mass above - so a part
                 that states its mass and nothing else turns the way its solid
                 says it does, at the weight it says it is
  friction       stated, else the material's 'mu'
  volume         measured, never stated: what the solid encloses, in mm^3. Not a
                 property any format writes - it is what a body displaces of
                 the fluid a scene is filled with, which is how a simulation
                 buoys it (see 'partcad.scene_world') - and it is handed over
                 so that no exporter has to measure the geometry to find it

Every density is in kg/m^3: a material's, a part's and an export's are one unit,
so nothing here converts one. The arithmetic - a volume and a density into a
mass, a tensor moved or added up - is 'wrappers/mass_properties.py', which the
exporters in the sandbox import too, so there is one copy of that as well.

**What a part weighs is cached, and goes stale exactly when it should.** Its
volume, mass, centre of mass and inertia are stored as one entry of the shape
cache (DERIVED_KEY) under a key of their own: the part's own cache key - so an
edit to the CAD is a new key - and everything the derivation reads that the
part's key does not cover. That is the density it was weighed at and where the
density came from (a stated one, the material that lent it, or an export's
fallback) and every value the part states that a derived one would otherwise
fill in. So an edit to a material's density, or to a stated mass, is a new key
as well; and nothing else is - a material's description, or a part's friction,
does not touch what the part weighs. A hit answers without the geometry: 'pc
info', an export and the IDE read the same entry, and none of them measures a
thing it was not asked to build. See '_derived_async()'.

A miss derives the values from what the shape measured as it was built - its
volume, and its centroid and its inertia at unit density, which OCCT works out
in the encoder and the geometry's own entry carries (see
'shape_measure.distribution()').
"""

import math
import os
import sys

from . import logging as pc_logging
from . import material as pc_material
from . import shape_envelope
from .utils import resolve_resource_path

# The wrappers directory is on the path for anything that imports 'partcad'
# (see 'shape.py'); said again here so that this module stands on its own.
_WRAPPERS = os.path.join(os.path.dirname(__file__), "wrappers")
if _WRAPPERS not in sys.path:
    sys.path.append(_WRAPPERS)
import mass_properties  # noqa: E402

from .cache_hash import CacheHash  # noqa: E402

# The request key the resolved physics of every shape travels to a sandbox
# under, keyed by the shape's full name. 'wrappers/wrapper_export.PHYSICS_KEY'
# is its twin, spelled out there because a sandbox cannot import 'partcad'.
FACTS_KEY = "__physics__"

# What an export weighs a part at that states no density and is made of
# nothing that does, in kg/m^3. Aluminium: a middle-of-the-road value for a
# machined part, and one whose provenance is obvious in the output rather than
# looking like a measurement. Overridden by the export's own 'density'
# parameter, and never used by 'pc info', which says it does not know instead -
# a made-up mass is worse than none where somebody reads it, and a simulator
# that is handed a body with no mass makes one up anyway.
DEFAULT_EXPORT_DENSITY = 2700.0

# The export parameter that overrides DEFAULT_EXPORT_DENSITY, in kg/m^3.
DENSITY_PARAMETER = "density"

# How many significant digits 'pc info' shows a value to. The arithmetic is
# done in full; this is only what a reader sees, so that a 20 mm cube is
# 8000 mm^3 rather than 7999.999999999998.
_SHOWN = 9

STATED = "stated"

# The shape-cache key what a part weighs is stored under. The entry's hash is
# not the part's own but one derived from it (see '_derived_hash()'), so the
# file is '<that hash>.mass' and sits beside nothing it could be mistaken for.
DERIVED_KEY = "mass"

# The shape of what is stored under DERIVED_KEY. It is hashed into the key, so
# that changing what an entry holds moves every entry to a new key rather than
# reading an old one back under new rules - the same arrangement as
# 'cache_hash.VERSION', for an entry that version does not describe.
#
#   1: mass, centre of mass and inertia.
#   2: and the 'volume' the solid encloses, which a simulation buoys it by. An
#      entry written under 1 has none, and read back would buoy nothing.
_DERIVED_FORMAT = 2

# What a derivation reads besides the geometry: the density it weighs the solid
# at, and every stated value that stands in for a derived one. Each goes into
# the key with where it came from - a density of 2700 lent by aluminium and a
# density of 2700 stated by the part are two different reasons for one number,
# and 'pc info' says which.
_DERIVATION_INPUTS = ("density", "mass", "centerOfMass", "inertia", "inertiaOrientation")


def _positive(value):
    """'value' as a positive finite float, or None."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0.0 else None


def _shown(value, floor=0.0):
    """'value' to _SHOWN significant digits, with anything below 'floor' shown as nought.

    The floor is for what integration leaves behind where the answer is zero: a
    cube's centre at 1e-17 mm, a product of inertia of 1e-25 next to moments of
    1e-6. Both are the arithmetic's noise rather than the part's, and printing
    them would have a reader wondering what they mean.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = float(value)
        if abs(value) < floor:
            return 0.0
        return float("%.*g" % (_SHOWN, value))
    if isinstance(value, (list, tuple)):
        return [_shown(v, floor) for v in value]
    if isinstance(value, dict):
        return {key: _shown(v, floor) for key, v in value.items()}
    return value


def _noise_floor(key, value):
    """Below what a value of property 'key' is shown as nought: see '_shown()'."""
    if key == "centerOfMass":
        # A nanometre, which no part is drawn to.
        return 1e-6
    if key == "inertia" and isinstance(value, dict):
        try:
            largest = max((abs(float(v)) for v in value.values()), default=0.0)
        except (TypeError, ValueError):
            return 0.0
        return largest * 10.0**-_SHOWN
    return 0.0


def resolve(stated=None, material=None, material_name=None, measurements=None, fallback=None):
    """A shape's physics, every value with where it came from: (physics, sources).

    'stated' is the shape's own 'physics'. 'material' is the Material it is made
    of, if any, and 'material_name' what to call it in a source. 'measurements'
    is what the shape measured as it was built (see 'shape_envelope'), which is
    what a mass, a centre of mass and an inertia are derived from. 'fallback' is
    the density an export weighs a part at that has none of its own, as a
    (value, source) pair; None for every reader that should rather say it does
    not know.

    'physics' is a PartCAD physics dict - the stated values as they were stated,
    and what was lent or derived under the same names and in the same units.
    'sources' says, per name, "stated", which material lent it, or how it was
    derived. A value that could not be had is in neither.

    The arithmetic, with nothing cached: what every reader that has a shape to
    ask goes through instead is '_derived_async()', which keeps the derived half
    of this in the cache.
    """
    physics, sources = _declared(stated, material, material_name, fallback)
    derived, derived_sources, _volume = _derive(physics, measurements)
    physics.update(derived)
    sources.update(derived_sources)
    return physics, sources


def _declared(stated, material, material_name, fallback):
    """What a shape's physics is before anything is derived: (physics, sources).

    What it states, what its material lends, and an export's fallback density.
    All of it is read off declarations, so it needs no geometry - which is what
    lets the key of a cached derivation be worked out before the geometry is
    asked for (see '_derived_hash()').
    """
    physics = {}
    sources = {}
    for key, value in (stated or {}).items():
        physics[key] = value
        sources[key] = STATED

    if "density" in physics and _positive(physics["density"]) is None:
        # The schema refuses one, and 'pc lint' says so; a package loaded
        # without linting can still carry it, and a density that weighs nothing
        # is not one to weigh a part at.
        pc_logging.warning("Ignoring the stated density %r, which is not a positive number" % (physics["density"],))
        del physics["density"]
        del sources["density"]

    if material is not None:
        lent = "the material %s" % (material_name or material.name)
        for prop, value in pc_material.physics_of(material).items():
            if prop not in physics and (prop != "density" or _positive(value) is not None):
                physics[prop] = value
                sources[prop] = lent

    if "density" not in physics and fallback is not None:
        value, source = fallback
        if _positive(value) is not None:
            physics["density"] = float(value)
            sources["density"] = source
    return physics, sources


def _derive(physics, measurements):
    """What the solid adds to 'physics': (derived, sources, volume).

    Only the values 'physics' does not already state - a mass at its density,
    the centroid, and the solid's inertia at the density its mass implies, so
    that a stated mass and a derived inertia agree. 'volume' is the solid's, or
    None for a shape that encloses nothing.
    """
    derived = {}
    sources = {}
    measured = measurements or {}
    volume = _positive(measured.get(shape_envelope.METADATA_VOLUME))
    centroid = measured.get(shape_envelope.METADATA_CENTROID)
    unit_inertia = measured.get(shape_envelope.METADATA_UNIT_INERTIA)
    if volume is None:
        return derived, sources, None
    # What the solid displaces, whatever it weighs: a float states its mass and
    # still pushes aside its whole volume of water. Measured, so never one a
    # part states, and never derived from a mass and a density, which for a
    # part that states its mass would be the volume of something else.
    derived[mass_properties.VOLUME_KEY] = volume
    sources[mass_properties.VOLUME_KEY] = "measured"

    density = _positive(physics.get("density"))
    if "mass" not in physics and density is not None:
        derived["mass"] = mass_properties.mass_of(volume, density)
        sources["mass"] = "derived: %.9g mm^3 at %.9g kg/m^3" % (volume, density)
    if centroid is None or unit_inertia is None:
        return derived, sources, volume

    if "centerOfMass" not in physics:
        derived["centerOfMass"] = [float(v) for v in centroid]
        sources["centerOfMass"] = "derived: the centroid of the solid"
    mass = _positive(physics["mass"] if "mass" in physics else derived.get("mass"))
    if "inertia" not in physics and mass is not None:
        # At the density that makes the solid weigh what the part does: the
        # material's, or - for a part that states its mass - the one that mass
        # implies. Either way the mass and the inertia agree.
        at = mass / (volume * mass_properties.M3_PER_MM3)
        derived["inertia"] = mass_properties.of_solid(volume, centroid, unit_inertia, at)["inertia"]
        sources["inertia"] = (
            "derived: the solid at %.9g kg/m^3" % at
            if "mass" in derived
            else "derived: the solid, scaled to the stated mass"
        )
    return derived, sources, volume


def _derived_hash(shape_key, physics, sources):
    """The key a shape's derived values are cached under.

    The shape's own key, which moves with every edit to the CAD, and what
    '_declared()' worked out that a derivation reads: the density and every
    stated value that stands in for a derived one, each with where it came from.
    Nothing else - so a material's description, a part's friction or its colour
    can change without a part being weighed again.
    """
    inputs = {name: [physics[name], sources.get(name)] for name in _DERIVATION_INPUTS if name in physics}
    derived_hash = CacheHash("mass properties", cache=True)
    derived_hash.add_string(shape_key)
    derived_hash.add_dict({"format": _DERIVED_FORMAT, "inputs": inputs})
    return derived_hash


async def _derived_async(ctx, shape, physics, sources, measure):
    """What the solid adds to 'physics', from the cache where it can be: (derived, sources, volume).

    The one place a derivation is cached and read back, for 'pc info', for every
    export and for the IDE. 'shape' is the object the values belong to and is
    what keys them (see '_derived_hash()'); 'measure' is a coroutine function
    returning what the shape measured, called only on a miss - a hit needs no
    geometry at all.

    Nothing is cached for a shape with no key of its own (one that is not
    cached, or that hashes another), and nothing for one whose measurements
    could not be had: a shape that failed to build has no weight to remember,
    and remembering that it had none would outlast whatever made it fail.
    """
    entry_hash = None
    cache = getattr(ctx, "cache_shapes", None) if ctx is not None else None
    if shape is not None and cache is not None:
        try:
            shape_key = await shape.get_cache_key_async()
        except Exception as e:  # pylint: disable=broad-except
            pc_logging.debug("No cache key to weigh %s under: %s" % (getattr(shape, "name", shape), e))
            shape_key = None
        if shape_key:
            entry_hash = _derived_hash(shape_key, physics, sources)
            cached, _ = await cache.read_async(entry_hash, [DERIVED_KEY])
            entry = cached.get(DERIVED_KEY)
            if isinstance(entry, dict) and isinstance(entry.get("physics"), dict):
                return entry["physics"], entry.get("sources") or {}, entry.get("volume")

    measurements = await measure()
    derived, derived_sources, volume = _derive(physics, measurements)
    if entry_hash is not None and measurements:
        entry = {"physics": derived, "sources": derived_sources, "volume": volume}
        await cache.write_async(entry_hash, {DERIVED_KEY: entry})
    return derived, derived_sources, volume


class _Materials:
    """Material references - and the parts behind a tree's leaves - resolved once per walk."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.found = {}
        self.parts = {}
        self.leaves = {}

    async def part(self, name):
        """The part a leaf of a tree is named after, or None.

        What a leaf's derived values are cached under is that part's key, and a
        tree carries the part's name but not its key. Looked up quietly: a leaf
        whose part cannot be found is still weighed, just not remembered.
        """
        if name not in self.parts:
            found = None
            if self.ctx is not None and name and ":" in name:
                # Split at the first ':' - a package path has none, and a
                # parameter value may.
                package, object_name = name.split(":", 1)
                try:
                    project = self.ctx.get_project(package)
                    if project is not None:
                        found = await project.get_part_async(object_name, quiet=True)
                except Exception as e:  # pylint: disable=broad-except
                    pc_logging.debug("No part behind %s to weigh it by: %s" % (name, e))
            self.parts[name] = found
        return self.parts[name]

    def get(self, owner, reference):
        """(Material or None, its full name) for 'reference' as written in 'owner'."""
        key = (owner, reference)
        if key not in self.found:
            package, name = resolve_resource_path(owner, reference)
            full = "%s:%s" % (package, name)
            _project, found = pc_material.lookup(self.ctx, full, quiet=False)
            self.found[key] = (found, full)
        return self.found[key]


def _node_inputs(node, materials):
    """(stated, material, material_name, measurements) of one envelope of a tree."""
    properties = node.get(shape_envelope.KEY_PROPERTIES) or {}
    if not isinstance(properties, dict):
        properties = {}
    material, material_name = None, None
    reference = properties.get("material")
    name = node.get("name")
    if isinstance(reference, str) and reference and name and materials.ctx is not None:
        material, material_name = materials.get(owner_package(name), reference)
    metadata = node.get(shape_envelope.KEY_METADATA)
    measurements = shape_envelope.metadata_section(metadata, shape_envelope.METADATA_MEASUREMENTS)
    stated = properties.get("physics") if isinstance(properties.get("physics"), dict) else None
    return stated, material, material_name, measurements


def _of_node(node, materials, fallback=None):
    """resolve() for one envelope of a tree, with its material looked up by its owner."""
    stated, material, material_name, measurements = _node_inputs(node, materials)
    return resolve(stated, material, material_name, measurements, fallback)


async def _leaf_async(node, materials, fallback=None):
    """(physics, sources, volume) of one leaf of a tree, its derived share cached.

    Keyed on the part the leaf is named after, so that a part weighed by 'pc
    info' is not weighed again by an export of an assembly holding it, nor the
    other way round. What is measured on a miss is what the leaf carries - the
    tree was built, so its geometry is already in hand.
    """
    name = node.get("name")
    memo = (name, fallback)
    if name and memo in materials.leaves:
        physics, sources, volume = materials.leaves[memo]
        return dict(physics), dict(sources), volume
    stated, material, material_name, measurements = _node_inputs(node, materials)
    physics, sources = _declared(stated, material, material_name, fallback)

    async def measure():
        return measurements

    derived, derived_sources, volume = await _derived_async(
        materials.ctx, await materials.part(name), physics, sources, measure
    )
    physics.update(derived)
    sources.update(derived_sources)
    if name:
        materials.leaves[memo] = (dict(physics), dict(sources), volume)
    return physics, sources, volume


def _envelopes(request):
    """Every named envelope of a request, depth first, as (node, is_shape) pairs."""
    found = []

    def walk(obj):
        if isinstance(obj, list):
            for item in obj:
                walk(item)
            return
        if not isinstance(obj, dict):
            return
        is_shape = shape_envelope.KEY_BREP in obj
        if is_shape or shape_envelope.KEY_ASSEMBLY in obj:
            if obj.get("name"):
                found.append((obj, is_shape))
            for child in obj.get(shape_envelope.KEY_ASSEMBLY) or []:
                walk(child)
            return
        for key, value in obj.items():
            if key not in (shape_envelope.KEY_PROPERTIES, FACTS_KEY):
                walk(value)

    walk(request)
    return found


def physics_by_shape(ctx, request, fallback=None):
    """The resolved physics of every shape an export request holds, by full name.

    What the export wrapper merges into the properties index it hands the
    implementation (see 'wrappers/wrapper_export.properties_index()'), so that
    an exporter reads 'mass', 'centerOfMass', 'inertia', 'density' and
    'friction' off each shape and never learns that materials, densities or
    derivations exist. A leaf of the tree - a shape with geometry - gets
    everything 'resolve()' can say about it, at 'fallback' where it has no
    density of its own; an assembly node gets what it states and what its
    material lends, and nothing derived: what a body of several shapes weighs
    is the exporter's to add up, with 'mass_properties.of_body()', because only
    the exporter knows which nodes it makes one body of.

    Keyed by *shape* rather than by material reference, which is what lets a
    reference be relative. A material is named the way every other object is, so
    ':aluminium' means "in my own package" -- and whose package that is is a
    fact about the shape that wrote it, not about the string. Two packages in
    one tree may each catalogue an 'aluminium' of their own and each get theirs.

    A reference that does not resolve is reported once, by 'material.lookup()',
    and lends nothing: a part whose material is a typo is weighed at the
    fallback, and gets the simulator's friction, which is what it got before
    anyone declared a material at all.

    This one caches nothing, for a caller with no loop to read a cache on; an
    export goes through 'physics_by_shape_async()', which is this walk with
    every leaf's derived values read from the cache and written back to it.
    """
    materials = _Materials(ctx)
    facts = {}
    for node, is_shape in _envelopes(request):
        resolved, _sources = _of_node(node, materials, fallback if is_shape else None)
        if resolved:
            facts[node["name"]] = resolved
    return facts


async def physics_by_shape_async(ctx, request, fallback=None):
    """'physics_by_shape()', with every leaf's derived values cached (see '_derived_async()').

    What an export is handed, so that it reads the very values 'pc info'
    reports for the same parts, from the same cache entries.
    """
    materials = _Materials(ctx)
    facts = {}
    for node, is_shape in _envelopes(request):
        if is_shape:
            resolved, _sources, _volume = await _leaf_async(node, materials, fallback)
        else:
            resolved, _sources = _of_node(node, materials)
        if resolved:
            facts[node["name"]] = resolved
    return facts


def export_fallback(request):
    """The (density, source) an export weighs a part at that has none of its own."""
    stated = _positive(request.get(DENSITY_PARAMETER))
    if stated is not None:
        return stated, "the export's 'density' parameter"
    return DEFAULT_EXPORT_DENSITY, "the export default, for a part made of nothing that states a density"


async def _tree_async(node, materials):
    """(physics, sources, volume, parts, unweighed) of one node of a tree, in its own frame.

    'parts' counts the shapes under the node and 'unweighed' names those with no
    mass, so that a total that is not one can say so. Each part's own values
    come from the cache, under that part's key (see '_leaf_async()'); the sum is
    worked out again on every read, because it is the placements that decide
    it, and those are the tree's rather than any one part's.
    """
    if shape_envelope.KEY_BREP in node:
        physics, sources, volume = await _leaf_async(node, materials)
        unweighed = [] if mass_properties.weighs(physics) else [node.get("name") or node.get("label") or "?"]
        return physics, sources, volume or 0.0, 1, unweighed

    placed, volume, parts, unweighed = [], 0.0, 0, []
    for child in node.get(shape_envelope.KEY_ASSEMBLY) or []:
        physics, _sources, child_volume, child_parts, child_unweighed = await _tree_async(child, materials)
        volume += child_volume
        parts += child_parts
        unweighed += child_unweighed
        placed.append(mass_properties.placed(physics, child.get(shape_envelope.KEY_LOCATION)))
    derived = mass_properties.combined([p for p in placed if p]) or {}
    sources = {}
    weighed = parts - len(unweighed)
    if derived:
        noun = "part" if weighed == 1 else "parts"
        sources["mass"] = "the sum of %d %s" % (weighed, noun)
        sources["centerOfMass"] = "combined from %d %s" % (weighed, noun)
        if "inertia" in derived:
            sources["inertia"] = "combined from %d %s, about the combined centre of mass" % (weighed, noun)

    properties = node.get(shape_envelope.KEY_PROPERTIES) or {}
    stated = properties.get("physics") if isinstance(properties, dict) else None
    if stated and _positive(stated.get("mass")) is not None:
        # An assembly that states what it weighs is taken at its word, and what
        # its parts add up to says only how that weight is spread.
        physics = mass_properties.with_mass(derived, stated["mass"]) if derived else {}
        physics.update(stated)
        if "inertia" in physics and "inertia" not in stated:
            sources["inertia"] = "combined from its parts, scaled to the stated mass"
        sources.update({key: STATED for key in stated})
        return physics, sources, volume, parts, []
    physics = dict(derived)
    for key, value in (stated or {}).items():
        physics[key] = value
        sources[key] = STATED
    return physics, sources, volume, parts, unweighed


_UNITS = {
    "volume": "mm^3",
    "density": "kg/m^3",
    "mass": "kg",
    "centerOfMass": "mm",
    "inertia": "kg*m^2, about centerOfMass",
    "inertiaOrientation": "degrees",
}


def _report(physics, sources, volume, volume_source, missing=None):
    """What 'pc info' prints: each value, its unit, and where it came from."""
    report = {}
    if volume:
        report["volume"] = {"value": _shown(float(volume)), "unit": _UNITS["volume"], "source": volume_source}
    for key in ("density", "mass", "centerOfMass", "inertia", "inertiaOrientation"):
        if key in physics:
            shown = _shown(physics[key], _noise_floor(key, physics[key]))
            report[key] = {"value": shown, "unit": _UNITS[key], "source": sources.get(key, STATED)}
    if "mass" not in report and missing:
        report["mass"] = {"value": None, "unit": _UNITS["mass"], "source": missing}
    return report


async def mass_properties_async(ctx, shape):
    """What 'pc info' says a part or an assembly weighs, and how it knows; None if nothing.

    A part: its volume, its density, and the mass, centre of mass and inertia
    'resolve()' derives from them or the part states, in the part's own frame.
    No export fallback: a part that states no density and is made of nothing
    that does is reported as having no known mass, with the reason.

    An assembly: the same values for the whole of it, in its own frame - the
    masses of its parts added up, their centres combined, their tensors moved to
    the combined centre by the parallel-axis theorem and added. Worked out from
    the tree the assembly was built as, which carries every part's measurements
    and properties, so nothing is built twice and nothing is instantiated part by
    part. A part with no mass adds nothing, and the total says which they were:
    it is the mass of what could be weighed, not a guess at the rest.
    """
    kind = getattr(shape, "kind", None)
    if kind == "assembly":
        tree = await shape.get_wrapped(ctx)
        if not isinstance(tree, dict):
            return None
        physics, sources, volume, parts, unweighed = await _tree_async(tree, _Materials(ctx))
        if not parts:
            return None
        if unweighed and "mass" in physics:
            names = ", ".join(unweighed[:5]) + (", ..." if len(unweighed) > 5 else "")
            sources["mass"] = "%s; %d without a mass: %s" % (sources.get("mass", STATED), len(unweighed), names)
        missing = None
        if unweighed and "mass" not in physics:
            missing = "not known: no part states a mass or is made of anything that states a density"
        noun = "part" if parts == 1 else "parts"
        report = _report(physics, sources, volume, "the sum of %d %s" % (parts, noun), missing)
        return report or None

    if kind != "part":
        return None
    physics, sources, volume, material, material_name = await _part_async(ctx, shape)
    if not volume and "mass" not in physics:
        return None
    missing = None
    if "mass" not in physics:
        missing = (
            "not known: the material %s states no density" % material_name
            if material is not None
            else "not known: the part states no density and names no material"
        )
    return _report(physics, sources, volume, "measured", missing) or None


async def _part_async(ctx, shape):
    """A part's physics, its derived share cached: (physics, sources, volume, material, material_name)."""
    material = shape.get_material(ctx)
    material_name = None
    if material is not None:
        package, name = resolve_resource_path(shape.project_name, shape.material_reference())
        material_name = "%s:%s" % (package, name)
    stated = ((shape._shape_properties() or {}).get("physics")) or None
    physics, sources = _declared(stated, material, material_name, None)

    async def measure():
        return await shape.get_measurements_async(ctx)

    derived, derived_sources, volume = await _derived_async(ctx, shape, physics, sources, measure)
    physics.update(derived)
    sources.update(derived_sources)
    return physics, sources, volume, material, material_name


async def part_mass_async(ctx, shape):
    """What a part weighs in kilograms, stated or derived; None if that is not known.

    The mass 'pc info' reports, for a caller that wants the number and not the
    account of it - the IDE's Build vs Buy table.
    """
    if getattr(shape, "kind", None) != "part":
        return None
    physics, _sources, _volume, _material, _name = await _part_async(ctx, shape)
    return _positive(physics.get("mass"))


def owner_package(shape_name: str) -> str:
    """The package a shape's full name ("//pkg:part") belongs to.

    Split at the first ':': a package path is full of '/' and starts with '//'
    but carries no ':', while what follows it may - a parameter value naming
    another object (";material=//pkg:steel"), or the container an ASSY file
    holds ("//pkg:arm:wrist"). A name with no ':' is a package with nothing
    after it, which is what an assembly with no name of its own carries.
    """
    return shape_name.split(":", 1)[0] if ":" in shape_name else shape_name
