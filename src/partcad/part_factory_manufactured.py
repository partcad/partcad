#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A part whose geometry is what its manufacturing makes (see 'part_config_manufacturing.implied_type').

    stand:
      manufacturing:
        method: additive
        source: stand-design
        fff: {infill: 10%}

A part like this states no file: it is what the printer deposits by following
the route `pc cam` writes for its design -- or what a router leaves of its
stock, or what a mold gives back of its cavity. `pc cam --materialize` writes
that into the part's file, `<name>.brep` unless the part says `type: step` or
`type: sdf` or names a `path:`; from then on the file is what the part is, read
by that type's own factory, and the `materialize` check says whether it is
still what the machine would make.

Until then the part is made on demand (`PartFactoryManufactured`): the same
`pc cam` implementation is asked for the route and for what it makes, in a
sandbox, and the answer is the part -- cached like any other, under a key that
covers what it is made from and how, which the part's own key does not
('manufacturing:' is left out of every shape's hash). A part that says `type:
sdf` is kept as an SDF instead: the implementation writes a script whose
distance field is the route's deposit, bead by bead, and the `sdf` part type
meshes it (`PartFactoryManufacturedSdf`).
"""

import copy
import hashlib
import json
import os
import typing

from . import cmf
from . import logging as pc_logging
from . import part_factory as pf
from . import telemetry
from .part_config_manufacturing import (
    IMPLIED_TYPE_KEY,
    MACHINE_MOLD,
    MATERIALIZED_FORMATS,
    METHOD_ADDITIVE,
    METHOD_SUBTRACTIVE,
    PartConfigManufacturing,
)
from .part_factory_alias import _SourcePorts
from .part_factory_brep import PartFactoryBrep
from .part_factory_homogen import PartFactoryHomogen
from .part_factory_sdf import PartFactorySdf
from .part_factory_step import PartFactoryStep
from .utils import format_parameterized_name, parse_parameterized_name, resolve_resource_path

# What a part that is what its machine makes is lent by what it is made from,
# where it says nothing itself: what it is made of, what it looks like, and how
# precisely it has to be made. A print is made of its filament, which is what its
# design says it is made of, and is held to its design's tolerance; a cut part
# to its stock's.
LENT_CMF = ("material", "color", "finish")
LENT_NUMBERS = ("tolerance",)

# The parameter the SDF of a print is meshed at, in mm: half a layer unless the
# part says, so that every bead is crossed twice (see docs/design/additive.md,
# section 7.3, for what coarser costs in accuracy).
SDF_STEP = "step"


def materialized_format(config) -> str:
    """The format a manufactured part's own geometry is kept in: 'brep', 'step' or 'sdf'."""
    value = config.get(IMPLIED_TYPE_KEY) if isinstance(config, dict) else None
    return value if value in MATERIALIZED_FORMATS else "brep"


def materialized_path(project, config) -> str:
    """Where a manufactured part's own geometry is kept: its 'path:', else its name with the format's extension."""
    relative = (
        config.get("path")
        or (config.get("orig_name") or config["name"]) + MATERIALIZED_FORMATS[materialized_format(config)]
    )
    return os.path.join(project.config_dir, relative)


def create(ctx, source_project, target_project, config):
    """The factory of a manufactured part: its file's own type where it has been materialized, made otherwise."""
    # Lent whichever way it is read: a materialized print is as much its
    # design's material as one made on demand.
    _lend_cmf(ctx, source_project, config)
    fmt = materialized_format(config)
    path = materialized_path(source_project, config)
    if os.path.isfile(path):
        # Materialized, or written by hand: the file is what the part is, and
        # the type that reads it is the one it says.
        config["type"] = fmt
        config.setdefault("path", os.path.relpath(path, source_project.config_dir))
        if fmt == "sdf":
            _declare_sdf_step(config)
        made = _MATERIALIZED[fmt](ctx, source_project, target_project, config)
    elif fmt == "sdf":
        made = PartFactoryManufacturedSdf(ctx, source_project, target_project, config)
    else:
        made = PartFactoryManufactured(ctx, source_project, target_project, config)
    _lend_ports(ctx, made.part, source_project, config)
    return made


def design_of(config):
    """The design a part is the product of, where its outside is the design's: a print's, an unshrunk molding's.

    None for a cut part, whose source is its stock, and for a molding whose mold
    shrinks it, which the design's ports and size no longer fit.
    """
    data = PartConfigManufacturing(config)
    if not data.design:
        return None
    if data.method != METHOD_ADDITIVE:
        mold = data.machines.get(MACHINE_MOLD)
        if mold is not None and mold.get("shrinkage"):
            return None
    return data.design


def _lend_ports(ctx, part, project, config) -> None:
    """Give the part its design's ports, as an alias has its source's, unless it says where it connects itself.

    A print is its design on the outside -- a hole in the design is a hole in
    the print, where the design put it -- so it connects where the design does.
    """
    if any(key in config for key in ("implements", "ports", "map")):
        return
    design = design_of(config)
    if design is None:
        return
    base, parameters = parse_parameterized_name(design.strip())
    package, name = resolve_resource_path(project.name, base)
    part.with_ports = _DesignPorts(
        ctx, format_parameterized_name("%s:%s" % (package, name), parameters), project.name, part.name
    )


class _DesignPorts(_SourcePorts):
    """The ports of a part's design; none where the design is not there, since building the part says so."""

    def __init__(self, ctx, source: str, referrer: str, name: str):
        super().__init__(ctx, source, referrer)
        self._name = name

    def _target(self):
        try:
            return super()._target()
        except Exception as e:  # pylint: disable=broad-except
            pc_logging.debug("%s: no ports of its design: %s" % (self._name, e))
            if self._empty is None:
                from .port import WithPorts

                self._empty = WithPorts(self._name, self._ctx.get_project(self._referrer), {})
            return self._empty


def _declare_sdf_step(config) -> None:
    """Give an SDF print the meshing step its beads need, where it declares none."""
    parameters = config.setdefault("parameters", {})
    if SDF_STEP in parameters:
        return
    data = PartConfigManufacturing(config)
    layer = None
    if data.machine is not None:
        layer = data.machine.settings().get("layerHeight")
    parameters[SDF_STEP] = {"type": "float", "default": float(layer or 0.2) / 2.0}


def _references(config) -> list:
    """What the part is made from and after, as written: the design or the stock, and the instructions."""
    data = PartConfigManufacturing(config)
    names = [data.source]
    if data.method == METHOD_SUBTRACTIVE and data.instructions:
        names.append(data.instructions)
    return [name for name in names if isinstance(name, str) and name.strip()]


def _lend_cmf(ctx, project, config) -> None:
    """Fill the CMF parameters the part leaves unset from what it is made from.

    Written into the declaration's parameters, spelled in full against the
    package that declared them, so that the core applies them as if the part
    had declared them itself (see 'cmf.apply_declared') and weighs it at the
    material's density.
    """
    source = PartConfigManufacturing(config).source
    if not isinstance(source, str) or not source.strip() or ctx is None:
        return
    base, _ = parse_parameterized_name(source.strip())
    package, name = resolve_resource_path(project.name, base)
    owner = ctx.get_project(package)
    if owner is None:
        return
    try:
        source_config = owner.get_part_config(name) or {}
    except Exception as e:  # pylint: disable=broad-except
        pc_logging.debug("%s: nothing lent by '%s': %s" % (config.get("name"), source, e))
        return
    lent = source_config.get("parameters") or {}
    parameters = config.setdefault("parameters", {})
    for key in LENT_CMF + LENT_NUMBERS:
        if key in parameters:
            continue
        declared = lent.get(key)
        value = declared.get("default") if isinstance(declared, dict) else declared
        if key in LENT_NUMBERS:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                parameters[key] = {"type": "float", "default": float(value)}
            continue
        if not isinstance(value, str) or not value.strip():
            continue
        parameters[key] = {"type": "string", "default": cmf.canonical(ctx, key, value, owner.name, quiet=True)}


def _hash_declaration(part, config, fmt) -> None:
    """Key the part on what it is made from and how: its key is seeded with neither."""
    data = PartConfigManufacturing(config)
    section = config.get("manufacturing") or {}
    part.hash.add_string("manufactured:%s" % fmt)
    part.hash.add_string(json.dumps(section, sort_keys=True, default=str))
    for kind in data.machine_choices():
        part.hash.add_string(data.machines[kind].key())


async def _add_reference_keys(ctx, part, config) -> bool:
    """Fold the cache keys of what the part is made from into its own; False where one has none."""
    from .qual.basic.manufacturability_reference import resolve_reference

    data = PartConfigManufacturing(config)
    complete = True
    for name in _references(config):
        kind = "sketch" if name == data.instructions and ctx.get_sketch(name) is not None else "part"
        found = await resolve_reference(ctx, part, name, kind)
        if found is None:
            complete = False
            continue
        if not await part.add_cache_key_of(found):
            complete = False
    return complete


# The factories a materialized file is read by: its format's own, taking the
# 'tolerance' parameter a 'brep' or a 'step' part otherwise refuses. Those refuse
# it because their file may hold many bodies, each stating what it is; a file
# PartCAD wrote from what one machine made of one design is one body of one
# material, which is what 'PartFactoryHomogen' is for.
@telemetry.instrument()
class PartFactoryMaterializedBrep(PartFactoryHomogen, PartFactoryBrep):
    pass


@telemetry.instrument()
class PartFactoryMaterializedStep(PartFactoryHomogen, PartFactoryStep):
    pass


_MATERIALIZED = {"brep": PartFactoryMaterializedBrep, "step": PartFactoryMaterializedStep, "sdf": PartFactorySdf}


def maker_parts(ctx, config) -> list:
    """The code that makes the part, as the strings a cache key is made of.

    The part is what that code makes, so a change to it is another part: a print
    built by an older route is not this route's print. Keyed without loading any
    package -- resolving the implementation's package from inside a preparation
    is what it must not do (loading it waits for what is waiting for this) -- so
    on the implementation's name as the part's route resolves it ('pc cam -i'
    aside, which the part is never made with), and for PartCAD's own
    '//builtin/cam' on its sources as they are on disk, with the wrappers that
    run them. Another package's code is keyed by its name, and moves with the
    revision its dependency is pinned at.
    """
    data = PartConfigManufacturing(config)
    return _maker_parts_of(ctx, data.machine.get("implementation") if data.machine is not None else None)


def _maker_parts_of(ctx, declared) -> list:
    """'maker_parts' for a machine declaring 'declared' as its implementation (None: it declares none)."""
    from . import source_key

    implementation = str(declared or ctx.user_config.cam_implementation or "").strip()
    parts = ["maker:%s" % implementation]
    if implementation.split(":")[0] in ("", "//builtin/cam") or implementation.startswith("//builtin/cam:"):
        directory = os.path.join(os.path.dirname(os.path.abspath(__file__)), "builtin", "cam")
        parts.append("maker-sources:%s" % source_key.directory_key(directory))
    parts.append("wrappers:%s" % source_key.wrappers_key())
    return parts


def _add_maker_key(ctx, part, config) -> bool:
    """Fold in the code that makes the part ('maker_parts'), as a route's cached answer is keyed on its implementation."""
    for piece in maker_parts(ctx, config):
        part.hash.add_string(piece)
    return True


async def _referenced_key(ctx, part, reference, kind) -> typing.Optional[str]:
    """What a reference the product is made from contributes to its key; None where that object keeps no key.

    One that resolves to nothing keys as missing ('kind:name@'), which is an
    answer like any other and stops being one the moment the object is added.
    One that resolves to an object with no key -- 'cache: false', say -- leaves
    nothing to tell an edit of it by, so nothing made from it may be kept.
    """
    from .qual.basic.manufacturability_reference import resolve_reference

    if not reference:
        return "%s@" % kind
    found = await resolve_reference(ctx, part, reference, kind)
    if found is None:
        return "%s:%s@" % (kind, reference)
    try:
        key = await found.get_cache_key_async()
    except Exception as e:  # pylint: disable=broad-except
        pc_logging.debug("No key for '%s', which %s:%s is made from: %s" % (reference, part.project_name, part.name, e))
        key = None
    if key is None:
        return None
    return "%s:%s@%s" % (kind, reference, key)


async def product_key_async(ctx, part) -> typing.Optional[str]:
    """What a part's product is made from and how, as one key: everything about it the part's own key leaves out.

    The keys of what it is made from -- its 'source:', and its 'instructions:',
    a part or a drawing, resolved the way the route resolves them
    ('Shape._route_subject_async') -- every machine's subsection as written and
    the job they share, the implementation's options as every layer of them
    reaches the route ('_layered_options'), and the code that makes it
    ('maker_parts'). None of
    those moves the key of a part with a geometry of its own: 'manufacturing:'
    is left out of a shape's hash, and an edited design is another object. So
    whatever keeps an answer about the product of such a part -- the
    'materialize' check's verdict, the CAM tab's drawing -- keys on this too.

    None where something it is made from keeps no key ('_referenced_key'): an
    answer about it is not to be kept at all.
    """
    from .part_config import PartConfiguration
    from .qual.basic.manufacturability_reference import resolve_reference

    data = PartConfiguration.get_manufacturing_data(part)
    declared = [await _referenced_key(ctx, part, data.source, "part")]
    if data.instructions:
        found = await resolve_reference(ctx, part, data.instructions, "part")
        kind = "part" if found is not None else "sketch"
        declared.append(await _referenced_key(ctx, part, data.instructions, kind))
    if any(key is None for key in declared):
        return None
    for kind in data.machine_choices():
        machine = data.machines[kind]
        declared.append("%s:%s:%s" % (kind, machine.key(), json.dumps(machine.options, sort_keys=True, default=str)))
    declared.append("job:%s" % json.dumps(data.job, sort_keys=True, default=str))
    declared.append("error:%s" % (data.machine_error or ""))
    # Every machine the part could be made on, each with the implementation it
    # declares: which of them a run is asked for is the caller's to say, and a
    # key covering all of them is right for whichever it is.
    for kind in data.machine_choices() or [None]:
        implementation = data.machines[kind].get("implementation") if kind is not None else None
        declared.append("%s:%s" % (kind, _layered_options(ctx, part, implementation)))
        declared += _maker_parts_of(ctx, implementation)
    return hashlib.sha256(";".join(declared).encode()).hexdigest()[:16]


def _layered_options(ctx, part, declared) -> str:
    """The options of the 'pc cam' implementation a machine declaring 'declared' routes with, every layer of them.

    What the part does not state is filled from the package's 'cam:' section
    and the implementing package's defaults ('Shape._output_getopts') -- a
    tool's diameter, say -- and those move what the machine makes as much as
    the part's own settings do. Keyed as the 'cam' check keys them.
    """
    from . import output

    try:
        options_project, format_name = part._route_implementation(ctx, declared=declared)
        options, _output_dir = part._output_getopts(
            ctx, format_name, output.CAM, ctx.get_project(part.project_name), options_project
        )
        return "options:%s:%s:%s" % (
            options_project.name,
            format_name,
            json.dumps(options, sort_keys=True, default=str),
        )
    except Exception as e:  # pylint: disable=broad-except
        # Not resolved: an answer of its own (the product cannot be made), and
        # keyed as one rather than as a run that did resolve.
        return "options-unresolved:%s" % e


@telemetry.instrument()
class PartFactoryManufactured(PartFactoryHomogen, pf.PartFactory):
    """A part made on demand by following its manufacturing, until it is materialized into its file."""

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitManufactured", target_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config)
            self._create(config)
            self.format = materialized_format(config)
            _hash_declaration(self.part, config, self.format)
            self.part.cache_dependencies_broken = True
            if not self.part.desc:
                data = PartConfigManufacturing(config)
                self.part.desc = "%s, as %s makes it" % (data.source, _maker(data))

    async def prepare_async(self, part) -> None:
        """Key the part on what it is made from, once that is resolved, and on the code that makes it."""
        if await _add_reference_keys(self.ctx, part, self.config) and _add_maker_key(self.ctx, part, self.config):
            part.cache_dependencies_broken = False
        else:
            part.cacheable = False

    async def instantiate(self, part):
        with pc_logging.Action("Manufactured", part.project_name, part.name):
            try:
                made = await part.materialize_async(self.ctx)
            except Exception as e:  # pylint: disable=broad-except
                part.error(str(e))
                return None
            self.ctx.stats_parts_instantiated += 1
            return made.get("product")


@telemetry.instrument()
class PartFactoryManufacturedSdf(PartFactorySdf):
    """A print kept as an SDF: the route's deposit as a distance field, meshed by the 'sdf' part type.

    The script is written by the 'pc cam' implementation into the package's
    cache rather than beside the package, which is what materializing it does.
    It is written as the part is built, so the part is not keyed on it as a file
    part is keyed on its file -- the one on disk may be another setting's, or not
    there yet -- but on what it is a function of: the declaration, what the
    print is made from and the code that makes it, as 'PartFactoryManufactured'
    is. So the mesh and every verdict reached on it are remembered.
    """

    def __init__(self, ctx, source_project, target_project, config):
        config = config if isinstance(config, dict) else {}
        _declare_sdf_step(config)
        from . import output

        cache = os.path.join(output.package_cache_dir(ctx, source_project), "manufactured")
        os.makedirs(cache, exist_ok=True)
        declared_path = config.get("path")
        # Relative to the package, as a declared 'path:' is: the declaration is
        # part of the key, and the package's own '.cache' is where it is
        # wherever the package is.
        config["path"] = os.path.relpath(
            os.path.join(cache, (config.get("orig_name") or config["name"]) + ".py"), source_project.config_dir
        )
        super().__init__(ctx, source_project, target_project, config, can_create=True)
        script = os.path.abspath(self.path)
        if declared_path is not None:
            config["path"] = declared_path
        else:
            config.pop("path", None)
        # The list the part's hash reads its files from, changed where it is.
        self.part.cache_dependencies[:] = [
            path for path in self.part.cache_dependencies if os.path.abspath(path) != script
        ]
        _hash_declaration(self.part, config, "sdf")
        self.part.cache_dependencies_broken = True

    async def prepare_async(self, part) -> None:
        """Key the part on what it is made from and on the code that makes it, as 'PartFactoryManufactured' does."""
        await super().prepare_async(part)
        if await _add_reference_keys(self.ctx, part, self.config) and _add_maker_key(self.ctx, part, self.config):
            part.cache_dependencies_broken = False
        else:
            part.cacheable = False

    async def instantiate(self, part):
        with pc_logging.Action("ManufacturedSdf", part.project_name, part.name):
            try:
                made = await part.materialize_async(self.ctx, representation="sdf")
            except Exception as e:  # pylint: disable=broad-except
                part.error(str(e))
                return None
            script = made.get("sdf_script")
            if not script:
                part.error("the 'pc cam' implementation wrote no SDF")
                return None
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(script)
            part.path = self.path
            return await super().instantiate(part)


def _maker(data) -> str:
    """The machine a part is made on, as the description says it."""
    kinds = data.machine_choices()
    if kinds:
        return "a '%s'" % kinds[0]
    return {"additive": "a printer", "subtractive": "a router", "forming": "a mold"}.get(
        data._method_string(), "its machine"
    )


# What the dispatcher contributes: the CMF parameters every part type takes, and
# the tolerance one homogeneous body takes.
create.ACCEPTED_OBJECT_TYPE_PARAMETERS = copy.copy(PartFactoryManufactured.ACCEPTED_OBJECT_TYPE_PARAMETERS)
