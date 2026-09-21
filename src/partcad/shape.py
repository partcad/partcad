#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.

from __future__ import annotations

import asyncio
import contextlib
import copy
import os
import sys
import tempfile
import threading
import warnings
from typing import TYPE_CHECKING, Optional

from . import cae as pc_cae
from . import cam as pc_cam
from . import logging as pc_logging
from . import material as pc_material
from . import output, render_overlay
from . import runtime as pc_runtime
from . import sandbox_versions, wrapper
from .cache_hash import CacheHash
from .cache_shape import properties_key
from .shape_config import ShapeConfiguration
from .utils import resolve_resource_path, total_size

if TYPE_CHECKING:
    from partcad.context import Context
    from partcad.project import Project

# The core carries shapes as opaque BREP envelopes (see shape_envelope), never
# as live OCP objects. 'wrappers' stays on sys.path so the few code paths that
# legitimately need a live shape - the single normalization choke point in
# get_wrapped(), and convert()/show() which hand a live object to a CAD library
# - can import the OCP codec lazily.
sys.path.append(os.path.join(os.path.dirname(__file__), "wrappers"))
from . import shape_envelope, telemetry
from .process_crash import command_failure

PART_EXTENSION_MAPPING = {
    "step": "step",
    "brep": "brep",
    "stl": "stl",
    "3mf": "3mf",
    "threejs": "json",
    "obj": "obj",
    "iges": "iges",
    "gltf": "json",
    "urdf": "urdf",
    "cadquery": "py",
    "build123d": "py",
    "chili3d": "chili",
    "sdf": "py",
    "scad": "scad",
}

SKETCH_EXTENSION_MAPPING = {
    "svg": "svg",
    "dxf": "dxf",
    "cadquery": "py",
    "build123d": "py",
}

# The scene types that are file formats, and the extension each is stored in.
# The counterpart of the two mappings above for the third kind of object a file
# can hold: an arrangement rather than a shape or a drawing. It exists for the
# same reason they do -- to tell from a file name what a conversion should read
# it as.
#
# One entry, and it is the only one there can be: a scene format that belongs to
# a simulation engine is declared by that engine's plugin package (`mjcf` by
# `partcad/partcad-sim-mujoco`, `world` by `partcad/partcad-sim-gazebo`), and
# this table is consulted where there is no package graph to resolve such a name
# in. So it holds what PartCAD itself knows and nothing else -- a plugin format
# is reached by asking the graph, not by looking it up here.
#
# 'assy' is in it and is not convertible ad-hoc (see
# 'partcad.adhoc.adhoc.PACKAGE_ONLY_TYPES'): naming it is what lets the refusal
# say what the file is instead of reporting an unknown extension.
SCENE_EXTENSION_MAPPING = {
    "assy": "assy",
}

# The 2D projections '//builtin/render' implements, and the file extension each
# one writes. Deliberately kept apart from the two mappings above: those also
# enumerate the part types 'Shape.convert()' accepts, and a projection is not one
# of them (it cannot be read back in as a part or a sketch).
#
# Only 'jpeg' has an extension that differs from its name, which is what this is
# consulted first for. The other three are listed anyway so that this is the set
# of built-in projections and not a list of exceptions - 'pc adhoc render' reads
# it in reverse, to tell from an output file name which projection was asked for.
# A file type a package implements itself is not here, and is not inferable: it
# is declared in that package, and an ad-hoc render has no package.
RENDER_EXTENSION_MAPPING = {
    "svg": "svg",
    "png": "png",
    "jpeg": "jpg",
    "dxf": "dxf",
}

# The part types 'Shape.convert()' can hand back as a live in-memory CAD object
# instead of a serialized representation.
LIVE_OBJECT_PART_TYPES = frozenset({"build123d", "cadquery"})

# Part types that are named in the extension mappings above but that no exporter
# in this repository can produce. OpenSCAD is an input format for PartCAD
# (see part_factory_scad.py); nothing writes it back out.
UNEXPORTABLE_PART_TYPES = {
    "scad": "PartCAD can read OpenSCAD but cannot write it",
    "sdf": "PartCAD can read SDF scripts but cannot write them",
    "chili3d": "PartCAD can read Chili3D scripts but cannot write them",
    # URDF is exportable, but not *in memory*: the export is a .urdf file plus
    # the directory of mesh files it references, and convert() hands back a
    # single payload. Returning only the XML would quietly lose the geometry.
    "urdf": (
        "a URDF export is a .urdf file plus the mesh files it references, so it cannot be "
        "returned in memory; export it to a path instead ('pc export -t urdf')"
    ),
}

# Every part type named by the extension mappings that 'Shape.convert()' can
# serialize. Derived from the mappings rather than hand-listed, so a new format
# added to a mapping (and declared by '//builtin/export' or '//builtin/render')
# is picked up here automatically.
SERIALIZED_PART_TYPES = (
    frozenset(set(PART_EXTENSION_MAPPING) | set(SKETCH_EXTENSION_MAPPING))
    - LIVE_OBJECT_PART_TYPES
    - set(UNEXPORTABLE_PART_TYPES)
)

# Serialized part types whose output is text no matter which options are passed.
# 'stl' and 'gltf' are deliberately absent: both switch between a text and a
# binary encoding depending on the options, so both always return bytes.
TEXT_PART_TYPES = frozenset({"step", "iges", "brep", "obj", "threejs", "svg", "dxf"})

SUPPORTED_PART_TYPES = frozenset(LIVE_OBJECT_PART_TYPES | SERIALIZED_PART_TYPES)


# What a shape's configuration says about the shape to a reader, rather than
# what its geometry is made of. Everything else in the configuration is hashed
# into the cache key.
#
# A deny-list rather than an allow-list, on purpose. An allow-list has to know
# every key that can change a shape, and it cannot: a partType of kind
# 'wrapper' is a package-supplied script that reads configuration keys of its
# own invention. The ':ldraw' partType identifies its part with 'dat', which
# the previous allow-list of 'parameters'/'offset'/'scale' did not name, so
# every LDraw part hashed to the same key and whichever was meshed first was
# handed back for all the others - four different parts exported byte-identical
# geometry, and an assembly of bricks rendered as cones.
#
# The two mistakes are not symmetrical: hashing a key that turns out not to
# matter costs a rebuild, while missing one that does matter serves the wrong
# shape and says nothing. So a key this does not know about is hashed.
_NON_GEOMETRIC_CONFIG_KEYS = frozenset(
    {
        "aliases",
        "author",
        "cache",
        "cache_dependencies_ignore",
        "category",
        # How the thing is packaged for sale, not what it is. The third of the
        # (vendor, SKU, pack size) record, and the only one of the three that
        # was missing here - so the same geometry sold in bags of 25 keyed
        # differently from the same geometry sold singly, and declaring a pack
        # size rebuilt a part for a number nothing reads but a bill of
        # materials. Keying on less cannot serve the wrong shape here: nothing
        # builds anything out of it.
        "count_per_sku",
        "desc",
        "docs",
        "example",
        "images",
        "label",
        "license",
        "manufacturable",
        "manufacturing",
        # A shape's own name is not what it is made of: two parts alike but for
        # their names are one shape and share an entry. What a file-backed part
        # is built from reaches the key as the file's content, not as its name.
        "name",
        "orig_name",
        # Outputs, not inputs. A part that gains a material has not become a
        # different shape (see test_shape_properties.py).
        "properties",
        "sku",
        "summary",
        "supplier",
        "tags",
        "title",
        "url",
        "vendor",
    }
)


@telemetry.instrument(exclude=["locked"])
class Shape(ShapeConfiguration):
    name: str
    desc: str
    kind: str
    requirements: dict | list | str
    svg_path: str
    svg_url: str
    # shape: None | OCP.TopoDS.TopoDS_Solid

    errors: list[str]

    def __init__(self, project_name: str, config: dict) -> None:
        super().__init__(config)
        self.project_name = project_name
        self.errors = []
        self.lock = threading.RLock()
        self.tls = threading.local()
        self.components = []
        self.compound = None
        self.with_ports = None

        # Leave the svg path empty to get it created on demand
        self.svg_lock = asyncio.Lock()
        self.svg_path = None
        self.svg_url = None

        self.desc = config.get("desc", None)
        self.desc = self.desc.strip() if self.desc is not None else None
        self.requirements = config.get("requirements", None)
        finalized_default = config.get("type", None) != "kicad"
        self.finalized = config.get("finalized", finalized_default)

        # Cache behavior
        self.cacheable = config.get("cache", True)
        # Optional: what the environment this shape is produced in consists
        # of, for the shapes that are produced in one at all (see
        # set_environment_cache_key). None for a shape that is composed rather
        # than rendered, such as an assembly.
        self.environment_cache_key = None
        self.cache_dependencies = []
        self.cache_dependencies_broken = False
        self.cache_dependencies_ignore = self.config.get("cache_dependencies_ignore", True)

        # Memory cache
        self._wrapped = None
        self._bounding_box = None
        # Everything recorded about this shape's geometry when it was built -
        # its measurements, and whatever its source stated (see
        # 'shape_envelope.KEY_METADATA'). Learnt while building or read back
        # with the geometry, and kept here for the runs that have nowhere to
        # cache it. See 'get_metadata_async()'.
        self._metadata = None

        # Set by the factory (see ShapeFactory.prepare_async): everything that has
        # to happen before this shape's cache key means anything - 'fileFrom'
        # downloads and cross-package references - without building the shape.
        self._prepare = None
        self._prepared = False

        # Filesystem cache
        self.hash = CacheHash(f"{self.project_name}:{self.name}", cache=self.cacheable)
        self.hash.set_dependencies(self.cache_dependencies)

        # Whether this shape's cache entry is this shape's to write. False for
        # a reference that took its key from the object it points at without
        # changing anything about it (see 'take_cache_key_from'): the two share
        # one entry, and the object that owns it is the one that fills it.
        self.owns_cache_entry = True

        if self.cacheable:
            cad_config = {key: value for key, value in self.config.items() if key not in _NON_GEOMETRIC_CONFIG_KEYS}
            self.hash.add_dict(cad_config)

    def set_environment_cache_key(self, environment_cache_key: str) -> None:
        """Record the environment this shape is produced in, and cache by it.

        A shape produced by a sandbox comes from an interpreter of some version
        with dependencies of some versions, and the result belongs to that
        combination: move the package to another interpreter or another CAD
        library and the shape has to be built again rather than read back from
        what the previous one produced.

        Every kind of shape can have one. A part written as a script obviously
        does, but so does a sketch, and so does a part read from a CAD file -
        the importer that turns a STEP file into a BREP is itself a script in a
        sandbox. What does not is a shape that is composed rather than rendered,
        such as an assembly, whose pieces each carry their own.

        None of it is visible to the hash otherwise. Only 'parameters', 'offset'
        and 'scale' are taken from the configuration above, and the environment
        is not spelled out in a shape's configuration anyway - it is resolved
        from the package's settings, the shape's, and the versions PartCAD
        itself supplies.

        Set through ShapeFactory.apply_environment_cache_key() as a shape is
        created, from 'sandbox_versions.environment_cache_key()'. Must happen
        before the hash is used, which creation time guarantees.
        """
        self.environment_cache_key = environment_cache_key
        self.hash.add_string(environment_cache_key)

    def matches(self, keyword: str) -> bool:
        if not keyword:
            return False
        keyword = keyword.lower()

        # Check for a match in its configuration
        if keyword in str(self.config).lower() or keyword in self.name.lower():
            return True

        # Check for a match in other files associated with this shape
        if self.path and os.path.exists(self.path):
            with open(self.path, errors="replace") as f:
                if keyword and keyword.lower() in f.read().lower():
                    return True
        return False

    def get_cache_dependencies_broken(self) -> bool:
        if self.cache_dependencies_ignore:
            return False
        return self.cache_dependencies_broken

    def get_cacheable(self) -> bool:
        return self.cacheable and not self.get_cache_dependencies_broken()

    async def get_summary_async(self, project=None):
        # Return a manually configured summary if present, otherwise None.
        if "summary" in self.config and self.config["summary"] is not None:
            return self.config["summary"]
        return None

    def get_summary(self, project=None):
        return asyncio.run(self.get_summary_async(project))

    def get_async_lock(self) -> asyncio.Lock:
        if not hasattr(self.tls, "async_shape_locks"):
            self.tls.async_shape_locks = {}
        self_id = id(self)
        # Keyed on the loop as well as the shape, the way the runtime keys its
        # own (see runtime_python.PythonRuntime). A worker thread runs one
        # 'asyncio.run()' per instantiation, so a thread that is handed a
        # second one gets a second loop, and an asyncio.Lock that was awaited
        # under the first refuses to be awaited under the second.
        loop_id = id(asyncio.get_event_loop())
        if self_id not in self.tls.async_shape_locks or self.tls.async_shape_locks[self_id][1] != loop_id:
            self.tls.async_shape_locks[self_id] = (asyncio.Lock(), loop_id)
        return self.tls.async_shape_locks[self_id][0]

    @contextlib.asynccontextmanager
    async def locked(self):
        """Hold this shape still: nobody else instantiates it or writes its files.

        One lock for both, because they are the same question asked twice. A
        shape's files are not private to whoever asked for them: the path an
        output goes to is derived from the shape and the file type, so two
        concurrent runs over the same shape resolve to the *same* path, and
        without this the second one's work lands in the middle of the first
        one's -- deleting a model between the moment its owner wrote it and the
        moment its owner reads it back, or handing one caller the other's file.
        Instantiation has always been serialized this way; producing files was
        the half that was not.

        **Re-entrant**, and it has to be. The operations nest: 'analyze_async'
        holds this across the whole remove-run-verify sequence, and inside that
        calls 'get_wrapped' and '_run_implementation_async', each of which takes
        it in its own right. 'threading.RLock' already allows that; an
        'asyncio.Lock' does not, and a second acquisition from the task that
        already holds it waits for a release that only it can perform. So the
        owning task is remembered and passes straight through.

        The cost is real and worth stating: two *different* outputs of one shape
        no longer run at the same time, even though they write different paths.
        That is the price of one rule with no exceptions, and PartCAD's
        parallelism is across shapes rather than within one.
        """
        if not hasattr(self.tls, "async_shape_lock_owners"):
            self.tls.async_shape_lock_owners = {}
        owners = self.tls.async_shape_lock_owners
        self_id = id(self)
        # 'current_task()' is None outside a task; two such callers on one loop
        # cannot interleave at an await point anyway, so None is never treated
        # as re-entry.
        task = asyncio.current_task()
        if task is not None and owners.get(self_id) is task:
            yield
            return

        with self.lock:
            async with self.get_async_lock():
                owners[self_id] = task
                try:
                    yield
                finally:
                    owners.pop(self_id, None)

    async def get_components(self, ctx):
        if len(self.components) == 0:
            # Maybe it's empty, maybe it's not generated yet
            wrapped = await self.get_wrapped(ctx)

            # If it's a compound, we can get the components
            if len(self.components) == 0:
                self.components = [wrapped]

            if self.with_ports is not None:
                ports_list = list(await self.with_ports.get_components(ctx))
                if len(ports_list) != 0:
                    self.components.append(ports_list)

        return self.components

    def prepare(self):
        return asyncio.run(self.prepare_async())

    async def prepare_async(self):
        """Fetch everything the cache key depends on, without building the shape.

        This is what makes 'pc install' behave like 'npm install': the factory
        hook downloads whatever 'fileFrom' points at and resolves every
        cross-package reference, which loads - and so downloads - the packages
        this shape really depends on. A later build then finds it all on disk.

        Idempotent, and safe against reference cycles between assemblies: the
        flag is raised before the hook runs, so a shape that (indirectly) links
        back to itself stops here instead of recursing.
        """
        if self._prepared:
            return
        self._prepared = True
        if self._prepare is not None:
            try:
                await self._prepare(self)
            except BaseException:
                # A preparation that failed has not happened: leaving the flag
                # up would make a warm context skip it forever and then hash a
                # file that was never downloaded.
                self._prepared = False
                raise

    async def get_cache_key_async(self) -> Optional[str]:
        """Prepare this shape and return its cache key, or None if it has none.

        The key hashes the shape's configuration together with the content of
        the files it is built from, so it is only correct once those files are
        on disk - which is what 'prepare_async()' above guarantees. Shapes that
        are not cached in their own right (an alias or an enrich hashes the
        object it points at, not itself) report no key.
        """
        await self.prepare_async()
        if not self.get_cacheable():
            return None
        return self.hash.get()

    def get_cache_key(self) -> Optional[str]:
        return asyncio.run(self.get_cache_key_async())

    async def is_cached_async(self, ctx) -> bool:
        """Whether this shape can be had without building it.

        True when it is already in this process's memory, and otherwise when
        the cache holds the one entry 'get_wrapped()' materializes it from.
        One entry is the whole of it: whatever was recorded about the geometry
        travels inside that entry (see cache_shape.py), so a hit is a hit and
        there is no sibling entry that might be missing. The components beside
        it are not asked after for the same reason 'get_wrapped()' does not
        insist on them - a shape that has none is cached exactly as completely
        as one that has.

        Asked of the tiers rather than read out of them, so that answering it
        for a large assembly costs a stat() rather than the assembly. A shape
        that is not cacheable at all is never "cached" by this: it is either in
        memory or it has to be built.
        """
        if self._wrapped is not None:
            return True
        if not ctx or await self.get_cache_key_async() is None:
            return False
        present = await ctx.cache_shapes.contains_data_async(self.hash, [self.kind])
        return present.get(self.kind, False)

    async def take_cache_key_from(self, source: "Shape") -> None:
        """Key this shape on the shape it points at, plus what it adds to it.

        A reference - an alias or an enrich - is not geometry of its own: what
        it hands back is what the object it points at hands back, moved or
        scaled if it says so. A key of its own would put that geometry in the
        cache a second time, under a second key, for every copy of the
        reference; the source's key stores it once.

        A reference that adds nothing shares the source's entry outright -
        including the key, so the two are the same entry and not two copies of
        one - and leaves the writing to the source ('owns_cache_entry'). One
        that moves or scales what it points at produces different geometry and
        so keys differently: the source's key, plus what it adds, which is an
        entry of its own to fill.

        Called once the source is resolved and prepared, which is the first
        moment there is a key to take, and still before anything asks this
        shape for its own (see the alias factories' 'prepare_async').
        """
        source_key = await source.get_cache_key_async()
        if source_key is None:
            # Nothing to share: what this points at is not cached either.
            self.cacheable = False
            return

        transform = {key: self.config[key] for key in ("offset", "scale") if key in self.config}
        if not transform:
            self.hash = source.hash
            self.owns_cache_entry = False
            return

        # 'source.hash' carries everything the source is keyed on by now - the
        # call above is what hashed the files it depends on - so continuing it
        # is the source's key with this shape's own contribution after it.
        self.hash = CacheHash(f"{self.project_name}:{self.name}", hasher=source.hash.hasher, cache=True)
        self.hash.add_dict(transform)

    async def get_wrapped(self, ctx):
        async with self.locked():
            if self._wrapped is not None:
                return self._wrapped

            # Before the cache key means anything: the files this shape is
            # built from have to be on disk to be hashed, and a reference
            # has to have resolved what it points at to have a key at all
            # (see 'take_cache_key_from'). Costs one flag test once it has
            # happened.
            await self.prepare_async()

            is_cacheable = self.get_cacheable() and ctx
            if is_cacheable:
                cache_hash = self.hash
                if cache_hash:
                    cached, to_cache_in_memory = await ctx.cache_shapes.read_async(
                        cache_hash, [self.kind, "cmps"], self.get_cache_metadata()
                    )
                    # Whatever was recorded about the geometry came back inside
                    # the same entry as the geometry (see cache_shape.py), so a
                    # hit is a hit: there is no sibling entry that might be
                    # missing, and nothing to check for completeness.
                    #
                    # Set only on a hit, and to '{}' rather than None when the
                    # entry recorded nothing: None on this attribute means "not
                    # known yet" and is what sends 'get_metadata_async()' off to
                    # build the shape. A miss here has to leave it saying that.
                    if cached.get(self.kind) is not None:
                        self._metadata = shape_envelope.metadata_of(cached[self.kind]) or {}
                    if to_cache_in_memory.get(self.kind, False):
                        self._wrapped = cached[self.kind]
                    if to_cache_in_memory.get("cmps", False):
                        self.components = cached["cmps"]
                    if self.kind in cached and cached[self.kind] is not None:
                        return cached[self.kind]
                else:
                    if self.cache:
                        pc_logging.warning(f"No cache hash for shape: {self.name}")
            else:
                cache_hash = None

            shape = await self.get_shape(ctx)

            # Normalize whatever the factory produced into a BREP envelope so
            # the rest of the core - caching, offset/scale, the return value -
            # only ever handles opaque envelopes, never live OCP objects. A
            # factory that still builds a live shape in-process is encoded
            # here, at the single choke point; factories that delegate to a
            # wrapper already return an envelope and pass straight through.
            shape = self._to_envelope(shape)
            if self.components:
                self.components = [self._component_to_envelope(c) for c in self.components]

            # What the wrapper that produced this envelope recorded about it -
            # the size it measured, and whatever the source file stated (see
            # 'shape_envelope.KEY_METADATA'). Taken off here and not later
            # because 'offset'/'scale' below go through a wrapper that decodes
            # the envelope and encodes a fresh one, which cannot carry forward
            # what it was never sent.
            recorded = shape_envelope.metadata_of(shape)

            # TODO(clairbee): apply 'offset' and 'scale' during instantiation and
            #                 apply to both 'wrapped' and 'components'
            # 'offset'/'scale' are applied in a sandbox (see transform.py) so
            # the core does not have to run build123d in-process to do it.
            if shape is not None and ("offset" in self.config or "scale" in self.config):
                from . import transform

                if "offset" in self.config:
                    shape = await transform.offset(ctx, shape, self.config["offset"])
                if "scale" in self.config:
                    shape = await transform.scale(ctx, shape, self.config["scale"])

                # The transform rebuilt the geometry, so the encoder on the far
                # side measured what came out and the numbers on the way back
                # are the new ones - which is the point: a part scaled by two is
                # not the size the file it was read from would suggest. What
                # that wrapper could not know is what the *source* stated, so
                # the sections read at import are laid back under the fresh
                # measurements rather than lost with the envelope they rode in.
                #
                # The old measurements are dropped first rather than merged
                # under. They describe a shape that no longer exists, so if the
                # far side could not measure what came out, the honest answer is
                # that this shape's size is unknown - not the size it used to
                # be, which is the one answer nobody could detect as wrong.
                recorded = shape_envelope.merge_metadata(
                    shape_envelope.without_measurements(recorded),
                    shape_envelope.metadata_of(shape),
                )

            # Whatever produced the envelope - a factory, a wrapper, a
            # transform - the outer layer around it is this shape's own. It
            # is stamped here rather than left to whoever built the payload,
            # so that a shape built now and the same shape materialized from
            # the cache later carry exactly the same name and label.
            shape = shape_envelope.apply_metadata(shape, self.get_cache_metadata())

            # Kept on the object as well as cached, because the two answer for
            # different runs. A shape with 'cache: false', one that does not own
            # its entry, and a run with every tier switched off all reach here
            # having built the shape and having nowhere to store what that
            # produced - and 'pc info' should still be able to say how big it is.
            self._metadata = recorded or {}
            if recorded:
                shape = dict(shape)
                shape[shape_envelope.KEY_METADATA] = recorded

            if cache_hash:
                if is_cacheable and self.owns_cache_entry:
                    # The geometry and everything recorded about it go into the
                    # one entry, in the one write, because they were produced
                    # together and are valid together: the hash that keys the
                    # entry covers what produced the geometry, so a shape that
                    # rebuilds measures again and one that does not never needs
                    # to. Separate entries could be separately present.
                    to_cache = {self.kind: await self.get_cache_value(ctx, shape)}
                    if self.components and len(self.components) > 0:
                        to_cache["cmps"] = self.components
                    properties = self._shape_properties()
                    if properties:
                        # The one thing still kept beside the geometry rather
                        # than in it, and the reason is that it is *declared*:
                        # the hash does not cover a 'properties:' section, so
                        # editing one leaves the geometry entry valid and a copy
                        # buried inside it would go on answering with the values
                        # it happened to be written with. See
                        # 'cache_shape.properties_key()'.
                        to_cache[properties_key(self.kind)] = properties
                    to_cache_in_memory = await ctx.cache_shapes.write_async(cache_hash, to_cache)
                    do_cache_in_memory = to_cache_in_memory.get(self.kind, False)
                else:
                    do_cache_in_memory = True
                if do_cache_in_memory:
                    self._wrapped = shape
            else:
                # Let the file cache tell us if we need to cache this in memory
                self._wrapped = shape
            return shape

    def _shape_properties(self):
        """What this shape reports about itself, or None if it reports nothing.

        The 'properties:' section of the configuration - 'material', 'color' and
        'physics'. They are outputs, not inputs: 'parameters:' is what is asked
        of the object type that produces the shape, while these describe the
        shape that came out. Nothing here takes part in the cache hash, which is
        why a cached entry can be shared by objects that state different ones.

        Read as it stands, and nothing is derived here. What a shape turned out
        to be made of is written into 'properties:' by whatever instantiated it
        - a reader that found it in the file, or the part factory promoting the
        'material' its type was asked for (see
        'PartFactory.record_object_type_properties()'). By the time a shape is
        being asked what it reports, that has already happened.
        """
        if not isinstance(self.config, dict):
            return None
        properties = self.config.get(shape_envelope.KEY_PROPERTIES)
        if not isinstance(properties, dict):
            return None
        properties = {key: value for key, value in properties.items() if value not in (None, {}, [], "")}
        return properties or None

    def material_reference(self) -> Optional[str]:
        """What this shape says it is made of, as it was written, or None.

        A *name* - '//pub/std/manufacturing/material/metal:al-5052-h32', or
        ':aluminium' for one catalogued in the shape's own package - and not
        yet a thing anything can be asked of. 'get_material()' below is what
        turns it into one.
        """
        properties = self._shape_properties() or {}
        reference = properties.get("material")
        return reference if isinstance(reference, str) and reference else None

    def get_material(self, ctx, quiet: bool = True):
        """The material this shape is made of, or None if it names none.

        Resolved against the package that owns *this shape*, exactly as
        'material.physics_by_shape()' resolves it on the far side of an export:
        ':aluminium' means "in my own package", and whose package that is is a
        fact about the shape that wrote the reference rather than about the
        string. Two packages may each catalogue an 'aluminium' of their own and
        each get theirs.

        Quiet by default, because the callers are the ones that report a
        reference nobody answers to in their own way - 'shape_info()' below puts
        it in the answer rather than in the log - and because a shape with no
        material at all is the ordinary case rather than a mistake.
        """
        reference = self.material_reference()
        if reference is None or ctx is None:
            return None
        package, name = resolve_resource_path(self.project_name, reference)
        _project, found = pc_material.lookup(ctx, "%s:%s" % (package, name), quiet=quiet)
        return found

    async def get_cached_properties_async(self, ctx):
        """What the cache recorded beside this shape's geometry, or None.

        The other half of 'get_wrapped()'. The two entries are filled together,
        as the shape is instantiated, and materialized apart: the properties can
        be had without pulling a BREP out of the cache, and the BREP without
        them. A shape that has never been built, an entry written before
        properties were cached at all, and a shape that reports nothing all mean
        the same thing here - nothing recorded - which is an answer rather than
        a failure, and never a reason to build the geometry again.

        What comes back describes the geometry, which every object hashing to
        the same key shares. What identifies *this* object is its own
        'properties:' section, which is why 'get_cache_metadata()' - and so
        everything stamped onto an envelope - reads the configuration and never
        comes here.
        """
        if not ctx or await self.get_cache_key_async() is None:
            return None
        key = properties_key(self.kind)
        cached, _ = await ctx.cache_shapes.read_async(self.hash, [key])
        properties = cached.get(key)
        return properties if isinstance(properties, dict) and properties else None

    def _shape_metadata(self):
        """The (full_name, label) stamped onto this shape's envelope."""
        name = getattr(self, "name", None)
        project = getattr(self, "project_name", None)
        full_name = ("%s:%s" % (project, name)) if project and name else name
        label = self.config.get("label", name) if isinstance(self.config, dict) else name
        return full_name, label

    def _to_envelope(self, shape, name=None, label=None):
        """Normalize a factory's output into a BREP envelope dict.

        An envelope (or None) passes straight through. A live OCP shape - which
        only the in-process factories still produce - is encoded here, the one
        place in the core that touches a live shape. The OCP codec is imported
        lazily, so a workflow that only uses delegating factories never pulls
        OCP into the core process. The payload is taken as the compressed bytes,
        not the base64 the same codec produces for the pipe: this envelope stays
        in this process, and may go straight into a cache from here.
        """
        if shape is None or shape_envelope.is_shape_envelope(shape):
            return shape
        import ocp_serialize
        import shape_measure

        if name is None and label is None:
            name, label = self._shape_metadata()
        envelope = shape_envelope.make_shape(ocp_serialize.compressed_brep(shape), name=name, label=label)
        # Measured here for the same reason a wrapper's shapes are measured as
        # they are encoded: this is the moment the live object exists, and it is
        # the last one. An in-process factory is the one producer that does not
        # go through the sandbox encoder, so without this its shapes would be
        # the only ones whose size had to be computed all over again later.
        measured = shape_measure.measurements_or_none(shape)
        if measured:
            envelope[shape_envelope.KEY_METADATA] = {shape_envelope.METADATA_MEASUREMENTS: measured}
        return envelope

    def _component_to_envelope(self, component):
        """Normalize a component (or nested list of components) into envelopes."""
        if isinstance(component, list):
            return [self._component_to_envelope(item) for item in component]
        return self._to_envelope(component)

    def take_side_data_from(self, source) -> None:
        """Adopt what the object this one points at recorded about its geometry.

        A reference shares the cache entry of its source (see
        'take_cache_key_from'), so the two have to answer the same - and the
        source is what builds, and so what learns, what the geometry measures
        and what its file stated. Called once the source has been materialized,
        beside the copy of its components that happens for the same reason.
        """
        self._metadata = copy.deepcopy(getattr(source, "_metadata", None))

    async def get_cache_value(self, ctx, shape):
        """The value handed to the shape cache under 'self.kind'.

        A plain shape is a single BREP envelope; an assembly is the nested tree
        it was built as, so that the hierarchy - names, labels and
        sub-assemblies - survives caching, which a flat compound would lose.

        'shape' is already an envelope (get_wrapped normalizes it) and is passed
        on as it is: what identifies this particular shape is not cached with
        the geometry but comes from 'get_cache_metadata()' on the way out.
        """
        return shape

    def get_cache_metadata(self):
        """The outer layer to wrap around this shape's payload read from the cache.

        A cache entry is keyed on the geometry, so several shapes with identical
        geometry share one. Everything that says which shape this is therefore
        lives here rather than in the cache - see ShapeCache. That includes what
        the shape reports about itself: two parts cut from the same solid may
        well be made of different materials, and each has to get its own back.
        """
        full_name, label = self._shape_metadata()
        metadata = {"name": full_name, "label": label}
        properties = self._shape_properties()
        if properties:
            metadata[shape_envelope.KEY_PROPERTIES] = properties
        return metadata

    async def convert(self, part_type: str, ctx=None, **kwargs):
        """Convert this shape to 'part_type' and return the result in memory.

        This is the in-memory counterpart of 'render_async()': it drives the very
        same export machinery, but hands the result back instead of leaving an
        output file behind.

        Args:
            part_type: One of the supported part types (see below).
            ctx: Execution context. Optional for the live-object types, required
                for every serialized format (the exporters run in a managed
                Python runtime that only the context can provide).
            kwargs: Format-specific export options, forwarded to
                'render_async()' - e.g. 'tolerance', 'angularTolerance',
                'ascii' (stl), 'binary' (gltf), 'line_weight' and
                'viewport_origin' (svg/dxf), 'write_pcurves' and
                'precision_mode' (step/iges). 'project' may be passed to pick up
                a project's render options.

        Supported part types:
            Live objects, returned as the CAD library's own object:
                "build123d", "cadquery"
            Serialized formats:
                "3mf", "brep", "dxf", "gltf", "iges", "obj", "step", "stl",
                "svg", "threejs"

        Return type:
            The live-object types return the corresponding object. For the
            serialized formats the rule is: formats that are textual by
            definition return 'str' (UTF-8 decoded), and formats that are or can
            be binary return 'bytes'. Concretely, "step", "iges", "brep", "obj",
            "threejs", "svg" and "dxf" return 'str'; "stl", "3mf" and "gltf"
            return 'bytes', because each of those switches between a text and a
            binary encoding depending on the options. The return type therefore
            depends only on 'part_type' and never on the options passed.

        Raises:
            ValueError: 'part_type' is not supported, or a serialized format was
                requested without a context.
            RuntimeError: the exporter produced no output.
        """
        if not isinstance(part_type, str):
            raise ValueError(f"Invalid part type {part_type!r}: expected a string, got {type(part_type).__name__}")

        normalized = part_type.strip().lower()

        if normalized in LIVE_OBJECT_PART_TYPES:
            return await self._convert_to_live_object(normalized, ctx)

        if normalized in SERIALIZED_PART_TYPES:
            return await self._convert_to_serialized(normalized, ctx, **kwargs)

        supported = ", ".join(sorted(SUPPORTED_PART_TYPES))
        if normalized in UNEXPORTABLE_PART_TYPES:
            raise ValueError(
                f"Cannot convert to '{part_type}': {UNEXPORTABLE_PART_TYPES[normalized]}. "
                f"Supported part types: {supported}"
            )
        raise ValueError(f"Unknown part type '{part_type}'. Supported part types: {supported}")

    async def _convert_to_live_object(self, part_type: str, ctx):
        """Wrap this shape into a live build123d or CadQuery object."""
        if not ctx:
            pc_logging.debug(
                "No context provided to convert('%s'). Consider using Context.convert_part() instead." % part_type
            )

        # The shape may fail to instantiate, in which case 'get_wrapped()'
        # returns None. Keep handing back an object with 'wrapped' set to None
        # rather than raising: callers such as Assembly._get_shape_real() rely on
        # being able to tell that apart and report which shape went missing.
        wrapped = await self.get_wrapped(ctx)

        # 'build123d' and 'cadquery' are NOT dependencies of PartCAD: it builds
        # and exports every shape in sandboxed runtimes. Handing back a *live*
        # object of that flavour is the one thing PartCAD cannot do without the
        # library actually present in the caller's environment - so this path is
        # only for users who already have it, and OCP (which decodes the BREP)
        # comes with it. When it is missing, warn naming the expected library and
        # re-raise, rather than pointing at a PartCAD install extra.
        try:
            # get_wrapped() returns a BREP envelope; a live object is what this
            # API promises, so decode it here. This is one of the few core paths
            # that legitimately holds a live OCP shape, which is why the imports
            # stay lazy.
            live = None
            if wrapped is not None:
                import ocp_serialize

                live = ocp_serialize.decode_shape(wrapped)

            if part_type == "build123d":
                import build123d as b3d

                b3d_solid = b3d.Solid.make_box(1, 1, 1)
                b3d_solid.wrapped = live
                return b3d_solid

            import cadquery as cq

            cq_solid = cq.Solid.makeBox(1, 1, 1)
            cq_solid.wrapped = live
            return cq_solid
        except ImportError as e:
            pc_logging.warning(
                "convert('%s') needs the '%s' library, which is not installed. Install it in "
                "your project to work with PartCAD parts as live '%s' objects." % (part_type, part_type, part_type)
            )
            raise ImportError(
                "convert('%s') needs the '%s' library, which is not installed. "
                "Install '%s' to get a live %s object." % (part_type, part_type, part_type, part_type)
            ) from e

    async def _convert_to_serialized(self, part_type: str, ctx, **kwargs):
        """Export this shape to 'part_type' and return the payload in memory.

        Every exporter PartCAD ships insists on writing to a path, so the export
        goes to a temporary directory that is removed on both the success and the
        error path.
        """
        if ctx is None:
            raise ValueError(
                f"Cannot convert '{self.name}' to '{part_type}' without a context: "
                "the exporters run in a context-managed Python runtime"
            )

        # The extension is not cosmetic: some exporters pick the output format
        # from it (CadQuery's 3MF exporter, for one), so use the same mapping
        # 'render_async()' uses when it has to invent a file name.
        extension = PART_EXTENSION_MAPPING.get(part_type) or SKETCH_EXTENSION_MAPPING.get(part_type, part_type)

        with tempfile.TemporaryDirectory(prefix="partcad-convert-") as temp_dir:
            # A fixed basename keeps shape names with path separators or other
            # awkward characters out of the filesystem.
            filepath = os.path.join(temp_dir, f"shape.{extension}")

            await self.render_async(ctx, part_type, filepath=filepath, **kwargs)

            if not os.path.exists(filepath):
                raise RuntimeError(
                    f"Failed to convert {self.project_name}:{self.name} to '{part_type}': "
                    "the exporter produced no output"
                )

            with open(filepath, "rb") as f:
                data = f.read()

        if part_type in TEXT_PART_TYPES:
            return data.decode("utf-8")
        return data

    async def get_cadquery(self, ctx=None):
        """Deprecated. Use 'convert("cadquery", ctx)' instead."""
        warnings.warn(
            "Shape.get_cadquery() is deprecated, use Shape.convert('cadquery', ctx) instead",
            DeprecationWarning,
            stacklevel=2,
        )
        return await self.convert("cadquery", ctx)

    async def get_build123d(self, ctx=None):
        """Deprecated. Use 'convert("build123d", ctx)' instead."""
        warnings.warn(
            "Shape.get_build123d() is deprecated, use Shape.convert('build123d', ctx) instead",
            DeprecationWarning,
            stacklevel=2,
        )
        return await self.convert("build123d", ctx)

    async def show_async(self, ctx=None):
        # Remove this workaround when the VSCode extension is updated to pass 'ctx'
        if ctx is None:
            from .globals import _partcad_context

            ctx = _partcad_context

        with pc_logging.Action("Show", self.project_name, self.name):
            components = []
            # TODO(clairbee): consider removing this exception handler permanently
            # Comment out the below exception handler for easier troubleshooting in CLI
            try:
                components = await self.get_components(ctx)
            except Exception as e:
                pc_logging.exception(e)

            if len(components) != 0:
                # The components are BREP envelopes and stay that way here: the
                # viewer is a browser, so tessellation into glTF happens in a
                # sandbox and the core never decodes a live OCP object to show one.
                from . import viewer

                # A port is a coordinate frame with no geometry, so it cannot be
                # tessellated; it travels beside the geometry for the viewer to
                # draw a triad at.
                markers = self.with_ports.get_markers() if self.with_ports is not None else []

                await viewer.show(
                    ctx, components, name=self.name, kind=self.kind, package=self.project_name, markers=markers
                )

    def show(self, ctx=None):
        asyncio.run(self.show_async(ctx))

    def shape_info(self, ctx):
        """What 'pc info' reports of any shape, whatever kind or type it is.

        What it cost to hold, what it measured, what it is keyed and cached
        under, and the ports it carries. A factory adds what is particular to
        its type on top of this (see 'ShapeFactory.info').

        The shape is built first, and has to be: a measurement is of geometry,
        and the hash of a shape means nothing until the files it is built from
        are on disk. For a shape built before, that is a cache hit.
        """
        asyncio.run(self.get_wrapped(ctx))
        info = {}
        info["Memory"] = "%.02f KB" % ((total_size(self) + 1023.0) / 1024.0)
        info.update(asyncio.run(self._reported_async(ctx)))

        if self.with_ports is not None:
            info["Ports"] = self.with_ports.info()

        # What the shape is made of, as the facts rather than as the name. The
        # configuration printed beside this already shows the reference, and the
        # question somebody running 'pc info' on a part is asking is what that
        # reference means: the density its mass came from, the friction a
        # simulation of it used, what the substance is good and bad at.
        material_reference = self.material_reference()
        if material_reference is not None:
            material = self.get_material(ctx)
            info["Material"] = (
                material.material_info()
                if material is not None
                # A reference nothing answers to is reported as it was written
                # rather than dropped: it is the most useful thing that can be
                # said about what this is made of, and the reason no mass and no
                # friction came from it.
                else {"Name": material_reference, "Errors": ["The material is not found"]}
            )

        info["Hash"] = self.hash.get()
        if self.environment_cache_key is not None:
            # Part of that hash, and the part of it a user is most likely to be
            # asking about when a shape re-renders instead of coming from cache.
            info["Environment"] = self.environment_cache_key
        info["Dependencies"] = self.cache_dependencies
        return info

    def error(self, msg: str):
        mute = self.config.get("mute", False)
        if not mute:
            pc_logging.error(msg)
        self.errors.append(msg)

    # ------------------------------------------------------------------ #
    # Output files: 'pc export' and 'pc render'                          #
    # ------------------------------------------------------------------ #
    #
    # Neither the formats nor the implementations that write them are listed
    # here. They are declared by the packages that implement them - the ones
    # PartCAD ships, '//builtin/export' and '//builtin/render', exactly like a
    # package that implements a format itself - and resolved through 'output'.
    # What is left in this module is the part that is the same for every
    # format: gather the configuration, work out the file name, run the
    # implementation in a sandbox.

    def _output_implementor(self, ctx, format_name):
        """Split a 'package:format' file type into the type and that package.

        A bare name is left alone and answers None, which is every caller that
        has not named a package. One that has named one is asking for that
        package's implementation by its full path, the way an 'import:' type or
        a 'simulation:' plugin is named, and a package it names that is not in
        the graph is an error here rather than a file type nobody declares: the
        caller said where the implementation lives, so "not found" is about the
        package and saying anything else sends them looking in the wrong place.
        """
        format_name, package = output.split_format(self.project_name, format_name)
        if package is None:
            return format_name, None
        impl_project = ctx.get_project(package)
        if impl_project is None:
            raise Exception("The package implementing the '%s' file type is not found: %s" % (format_name, package))
        return format_name, impl_project

    def _output_section(self, ctx, format_name, project=None, options_project=None, impl_project=None) -> str:
        """Whether a file type is an 'export:' or a 'render:' one.

        A package named explicitly ('pc export -t sim-mujoco:mjcf') answers
        first: the caller said whose implementation this is, so that package's
        sections are what the file type means, even where a built-in of the same
        name would have said otherwise.

        Failing that the built-in packages decide it for the formats they
        implement. For one they do not, the package that declares it does: a
        format is an export format if it appears in an 'export:' section and a
        render format if it appears in a 'render:' one.
        """
        if impl_project is not None:
            for candidate in output.SECTIONS:
                if format_name in output.format_names(impl_project.config_obj.get(candidate)):
                    return candidate

        section = output.section_of(ctx, format_name)
        if section is not None:
            return section

        for config_obj in (self.config, *(p.config_obj for p in (project, options_project) if p is not None)):
            for candidate in output.SECTIONS:
                if format_name in output.format_names(config_obj.get(candidate)):
                    return candidate
        return output.EXPORT

    def _output_getopts(self, ctx, format_name, section, project=None, options_project=None, impl_project=None):
        """Layer every configuration of a file type, lowest priority first.

        The built-in package is the bottom layer, so a package that re-tunes a
        single parameter keeps the built-in implementation for everything else.
        Directly above it, the package a 'package:format' name pointed at, if
        the caller named one. On top of that come the package the options were
        asked to come from (the '--options-package' of 'pc export' /
        'pc render'), then the package the shape belongs to, then the shape
        itself.

        A named package goes in as a layer rather than replacing the lot -- which
        is what 'import_declaration()' does with the same spelling -- because
        this section also decides where the file goes. 'output_dir' and 'prefix'
        are the caller's business whoever writes the file, and a package asking
        somebody else's exporter for a file in its own tree would otherwise be
        told where to put it by that exporter.

        Returns the merged configuration and the output directory the sections
        asked for, if any.
        """
        layers = []
        builtin = output.builtin_project(ctx, section)
        if builtin is not None:
            layers.append((builtin.name, builtin.config_obj))
        for source in (impl_project, options_project, project):
            if source is not None:
                layers.append((source.name, source.config_obj))
        layers.append((self.project_name, self.config))

        opts = {}
        output_dir = None
        for package_name, config_obj in layers:
            for section_name in output.config_sections(section):
                section_obj = config_obj.get(section_name)
                if not isinstance(section_obj, dict):
                    continue
                if section_obj.get("output_dir"):
                    output_dir = section_obj["output_dir"]
                if format_name in section_obj:
                    layer = output.stamp(output.normalize(section_obj[format_name]), package_name)
                    opts = output.merge(opts, layer)
        return opts, output_dir

    def _output_filepath(self, opts, output_dir, extension, project=None, filepath=None, stem_suffix=""):
        """Where a file of this type goes when the caller did not say.

        'prefix' names the directory the file goes in, relative to the output
        directory or, failing that, to the package. A prefix that carries an
        extension is taken to name the file itself, which is the one way to
        give an object's output a name of its own.

        'stem_suffix' goes between the object's name and the extension, and is
        what makes an analysis write 'bracket.fea.vtu' rather than
        'bracket.vtu': the analysis is part of what the file is, and a part has
        as many analysis results as it has analyses. Empty for everything else,
        where the file type is already the extension.

        A name with a '/' in it names a file in a sub-directory of wherever the
        configuration put it -- see 'output.name_to_path()' for why, and
        'Context.ensure_dirs_for_file()' for who creates it.
        """
        if filepath is not None:
            return filepath

        filepath = opts.get("prefix") or "."
        if not os.path.isabs(filepath):
            if output_dir:
                # TODO(clairbee): consider using project.config_dir
                filepath = os.path.join(output_dir, filepath)
            elif project is not None:
                filepath = os.path.join(project.config_dir, filepath)
        filepath = os.path.normpath(filepath)

        # A directory that does not exist yet is still a directory: '--create-dirs'
        # is what creates it, and that happens once the name is known.
        if os.path.isdir(filepath) or not os.path.splitext(filepath)[1]:
            filepath = os.path.join(filepath, output.name_to_path(self.name, stem_suffix + extension))
        return filepath

    def output_getopts(self, ctx, format_name, project=None, filepath=None, options_project=None, output_dir=None):
        """Resolve one output file type: its implementation, options and path.

        This is the whole of what a format's configuration means, in one place:
        which script writes the file, what it is handed, and where the file
        lands. 'pc export' and 'pc render' differ only in which section the
        answer is read from.
        """
        format_name, impl_project = self._output_implementor(ctx, format_name)
        section = self._output_section(ctx, format_name, project, options_project, impl_project)
        opts, configured_output_dir = self._output_getopts(
            ctx, format_name, section, project, options_project, impl_project
        )
        # An explicitly requested output directory (e.g. 'pc export -O') beats
        # whatever the configuration asked for.
        output_dir = output_dir or configured_output_dir

        if filepath is not None and os.path.isdir(filepath):
            # A directory was passed where a file was expected: it names where
            # the file goes, not the file.
            output_dir, filepath = filepath, None

        impl = output.Implementation(section, format_name, opts)
        # 'jpeg' is the format's name but '.jpg' is the file's; the render-only
        # mapping is consulted first so a format whose extension differs from
        # its name keeps it even when no configuration spells 'extension' out.
        default_extension = (
            RENDER_EXTENSION_MAPPING.get(format_name)
            or PART_EXTENSION_MAPPING.get(format_name)
            or SKETCH_EXTENSION_MAPPING.get(format_name, format_name)
        )
        extension = "." + impl.extension(default_extension)
        filepath = self._output_filepath(opts, output_dir, extension, project, filepath)

        pc_logging.debug("Rendering: %s" % filepath)
        return impl, filepath

    async def _materialize_output_script(self, ctx, impl):
        """The on-disk path of the script that writes this file type.

        'output.materialize_script()' is the whole of it: nothing about finding
        an implementation's script depends on the shape it is about to be run
        for, and the simulation runner needs the very same answer for a plugin
        that writes no file at all (see 'partcad.simulation').
        """
        return await output.materialize_script(ctx, impl)

    async def _output_request(self, ctx, obj, impl, kwargs, overlay=None, ports=None):
        """What the implementation is handed.

        The shape, every parameter the layered configuration ended up with, and
        enough about the shape itself for an implementation to adapt to what it
        was given - which is how the SVG renderer knows to look at a sketch
        head-on without PartCAD having to tell it.

        'overlay'/'ports' are the overlay this file type ended up drawing (see
        render_overlay.effective) and where those ports are. They are set after
        'impl.parameters' rather than before, because the resolved overlay is
        what a file type declaring 'with_ports:' asked for plus what the command
        line asked for - the declaration has already been read.
        """
        request = {
            "wrapped": obj,
            "shape_name": self.name,
            "shape_kind": self.kind,
            "shape_type": self.config.get("type"),
            "package_name": self.project_name,
        }
        request.update(impl.parameters)
        if overlay is not None:
            request["with_ports"] = overlay.ports
            request["with_interfaces"] = overlay.interfaces
            request["ports"] = ports or []
        # An explicit argument wins over the configuration, but only when it is
        # one: 'render_async(**kwargs)' is called with a fixed set of keyword
        # arguments defaulting to None by several callers.
        request.update({key: value for key, value in kwargs.items() if value is not None})

        # 'properties: true' is left in the request as it is. What the shapes
        # report about themselves travels on the envelopes, so the index an
        # exporter looks them up in is built in the sandbox, out of the request
        # that arrives there - see wrappers/wrapper_export.py. Nothing has to be
        # collected here, and nothing has to be instantiated to collect it.
        #
        # A material is the exception, and only because it is a *name*: what a
        # shape carries is ':aluminium', and turning that into a coefficient of
        # friction means resolving it against the package that wrote it and
        # loading the package that catalogues it - neither of which the sandbox
        # can do. So the names are resolved here and the facts travel beside the
        # shapes, keyed by the shape that inherits them; the wrapper merges them
        # under what each shape said about itself. See
        # 'partcad.material.physics_by_shape()'.
        if request.get(output.PROPERTIES_KEY):
            facts = pc_material.physics_by_shape(ctx, request)
            if facts:
                request[pc_material.FACTS_KEY] = facts
        return request

    async def _overlay_ports_async(self, ctx, overlay, cache):
        """Where this shape's ports are, worked out at most once per render call.

        Two file types of one object can ask for different overlays, and what
        the answers differ in is only whether the port boundaries came along -
        so a collection that has them also answers a file type that does not.

        Failing to work it out must not cost the picture: an overlay is an
        annotation on a render, not the render. The failure is reported and the
        file is written without it - and it is *not* remembered, because what
        failed may be only the half this file type asked for. Building a port's
        boundary sketch can fail where locating the port cannot, and a cached
        "nothing" would then take the markers off the next file type too, which
        never asked for a boundary at all.
        """
        if True in cache:
            return cache[True]
        if not overlay.interfaces and False in cache:
            return cache[False]

        try:
            records = await render_overlay.collect_async(self, ctx, overlay)
        except Exception as e:
            pc_logging.error("%s:%s: failed to locate the ports to draw: %s" % (self.project_name, self.name, e))
            return []
        render_overlay.report(self, records, overlay)
        cache[overlay.interfaces] = records
        return records

    async def _run_implementation_async(self, ctx, impl, script, request, final_filepath):
        """Run one output implementation in a sandbox and read back its verdict.

        Shared by every file PartCAD produces through a script: the export and
        render formats, and the analyses of 'cae:'. What differs between them is
        what goes into the request and what is made of the answer, both of which
        belong to the caller; what is the same is the sandbox, the meta-wrapper
        and the shape of the reply, and a second copy of those is a second thing
        to keep correct.

        Returns the implementation's result dict, or None when it said nothing
        that could be read - which has already been reported by then.

        Held under 'locked()' throughout: this is the single place a shape's
        output file is written, whichever section asked for it, so it is the
        single place the rule belongs. Callers that need a wider critical
        section -- 'analyze_async' clears the path first and verifies it
        afterwards -- take the same lock around the whole of it, which nests
        because the lock is re-entrant.
        """
        async with self.locked():
            return await self._run_implementation_locked(ctx, impl, script, request, final_filepath)

    async def _run_implementation_locked(self, ctx, impl, script, request, final_filepath):
        """The body of '_run_implementation_async', with the shape held still."""
        # Whether the sandbox rebuilds the envelopes into live geometry before
        # the implementation sees them. Off for an implementation that needs what
        # the envelopes say about each node (the URDF exporter names every link
        # and places every joint from that), none of which decoding carries over
        # into the geometry it builds.
        request[output.DECODE_KEY] = impl.decode

        # Whether the file has to come out the same every time it is produced.
        # Set here rather than left to whatever the configuration happened to
        # carry, so that it is in *every* request and an implementation - one
        # PartCAD ships, or one a package published on its own - can read it
        # without first asking whether the key exists. That is the whole of what
        # makes 'reproducible' mean one thing across every implementation there
        # is; see 'output.REPRODUCIBLE_KEY'.
        #
        # What is already in the request wins, because by the time it gets here
        # it is the layered answer: the file type's declaration merged through
        # 'impl.parameters', with an explicit argument from the caller on top of
        # it. 'impl.reproducible' is the fallback for a caller that built its
        # request some other way, and the coercion is the point of reading both
        # through the same function - "false" is a string on the way in from
        # JSON-RPC and would otherwise be true.
        request[output.REPRODUCIBLE_KEY] = (
            output.as_flag(request[output.REPRODUCIBLE_KEY])
            if output.REPRODUCIBLE_KEY in request
            else impl.reproducible
        )

        request_serialized = shape_envelope.serialize(request)

        # Where this implementation runs. A container when it declared one --
        # the only sandbox that can carry what pip cannot install -- and the
        # Python sandbox otherwise, which is every implementation that ships
        # with PartCAD and most of those that do not.
        container = impl.container
        script_path = wrapper.get("export.py")
        config_dir = os.path.abspath(impl.project.config_dir)
        input_dirs = []

        if container:
            # Raises SandboxUnavailable when there is no container runtime.
            # A failure like any other, and the type is what earns the reader
            # both remedies rather than one (see 'partcad.test.cae').
            runtime = await ctx.get_container_runtime(container)
            # The wrapper and the implementing package both go in whole. Sending
            # only the files the command names would leave both unable to start:
            # the wrapper imports its siblings, and so does the implementation
            # script (see runtime.pack_directory).
            input_dirs = [os.path.dirname(script_path), config_dir]
        else:
            runtime = ctx.get_python_runtime(version=impl.python_version(), image=impl.docker_image)
            await runtime.prepare_for_package(impl.project)
            # Installed one at a time, not with asyncio.gather(): the order
            # matters, since build123d overwrites the OCP native module that
            # cadquery-ocp installs (see sandbox_versions.GUARD_INVALIDATED_BY).
            for dep in impl.python_requirements:
                await runtime.ensure_async(dep)

        with telemetry.start_as_current_span("*Shape.render_async.{runtime.run_async}"):
            # The meta-wrapper, what to write, where to run, and what to run.
            # The implementation script is an argument and not part of the
            # request because a container rewrites arguments naming a directory
            # it was sent and cannot rewrite the request, which reaches it as
            # one opaque string on standard input -- see wrapper_export.py.
            command = [
                script_path,
                final_filepath,
                config_dir,
                os.path.abspath(script),
            ]
            if container:
                # The interpreter is named rather than pathed: the container's
                # allowlist maps the name to the executable, which is what keeps
                # a caller from naming one (see PC_CONTAINER_ALLOWED_COMMANDS in
                # tools/containers/_common/pc-container-json-rpc.py).
                command.insert(0, container.get("command") or "python")
            # Only the container runtime is handed these. 'PythonRuntime' and
            # 'JavaScriptRuntime' both override 'run_async' with a narrower
            # signature -- (cmd, stdin, cwd, session, timeout) -- so the base
            # class's parameters are not a contract they honour, and passing
            # one down that path is a TypeError rather than an ignored argument.
            # What a command writes is not in the command, so a sandbox that
            # exchanges files rather than sharing them has to be told. The
            # container path knows its input directories too; the 'remote'
            # sandbox works those out from the command itself, and only the
            # output is beyond inference.
            if container:
                extra = {"input_dirs": input_dirs, "output_files": [final_filepath]}
            elif getattr(runtime, "EXCHANGES_FILES", False):
                extra = {"output_files": [final_filepath]}
            else:
                extra = {}
            exitcode, response_serialized, errors = await runtime.run_async(command, request_serialized, **extra)
            if exitcode != 0 and len(errors) == 0:
                errors = command_failure(command, exitcode)
            if errors:
                pc_logging.error(errors)
                raise Exception(errors)

        response_lines = response_serialized.strip().splitlines()
        if not response_lines:
            self.error("Empty response from the '%s' implementation: %s" % (impl.format_name, script))
            return None

        try:
            return shape_envelope.deserialize(response_lines[-1].strip())
        except Exception as e:
            self.error("Failed to deserialize response: %s" % e)
            return None

    async def _render_one_async(
        self,
        ctx,
        obj,
        format_name,
        project,
        filepath,
        options_project,
        output_dir,
        kwargs,
        overlay=None,
        ports_cache=None,
    ):
        """Produce one output file, whatever its type."""
        impl, final_filepath = self.output_getopts(ctx, format_name, project, filepath, options_project, output_dir)
        # What the file type is called from here on. The caller may have named
        # it by its full path ('sim-mujoco:mjcf'), which said where to resolve it
        # and has no business in a log line about the file.
        format_name = impl.format_name
        final_filepath = os.path.abspath(final_filepath)
        # Create the output directory for the resolved path (the incoming
        # 'filepath' is None when called from Project.render_async) using the
        # 'ctx' passed in, so direct callers without a project get
        # '--create-dirs' too. The name goes in with it: a '/' in it is a
        # sub-directory of wherever the file lands, created whether or not
        # '--create-dirs' was given.
        ctx.ensure_dirs_for_file(final_filepath, self.name)
        pc_logging.debug("Rendering: %s:%s for format '%s'" % (self.project_name, self.name, format_name))

        script = await self._materialize_output_script(ctx, impl)

        effective_overlay = render_overlay.effective(overlay, impl)
        ports = None
        if effective_overlay is not None:
            ports = await self._overlay_ports_async(
                ctx, effective_overlay, ports_cache if ports_cache is not None else {}
            )

        request = await self._output_request(ctx, obj, impl, kwargs, overlay=effective_overlay, ports=ports)
        result = await self._run_implementation_async(ctx, impl, script, request, final_filepath)
        if result is None:
            return

        if not result.get("success", False):
            self.error(
                "Render %s failed for %s:%s: %s"
                % (format_name.upper(), self.project_name, self.name, result.get("exception", "Unknown error"))
            )
        if result.get("exception"):
            pc_logging.exception("Render %s exception: %s" % (format_name.upper(), result["exception"]))

        # An implementation may report what it could not represent in the target
        # format without that being a failure (URDF, for one, cannot hold
        # everything a PartCAD assembly knows).
        for warning in result.get("warnings") or []:
            pc_logging.warning("%s:%s: %s" % (self.project_name, self.name, warning))

        # Properties PartCAD holds that the target format has no way to state.
        # Not a warning - the file is correct, it just says less than the package
        # does - but not silent either.
        unsupported = result.get("unsupported") or []
        if unsupported:
            pc_logging.info(
                "%s:%s: %s cannot state these properties, so they are not in the exported file: %s"
                % (self.project_name, self.name, format_name.upper(), ", ".join(unsupported))
            )

    async def render_async(
        self,
        ctx: Context,
        format_name: str,
        project: Optional[Project] = None,
        filepath=None,
        options_package: Optional[str] = None,
        options_project: Optional[Project] = None,
        output_dir=None,
        overlay=None,
        **kwargs,
    ) -> None:
        """Write this shape out as one output file type, or as all of them.

        Args:
            ctx: Execution context.
            format_name: The file type (e.g. "step", "svg", "png"). None
                produces every type that has a built-in implementation.
            project: The package the shape belongs to, whose 'export:' and
                'render:' sections configure the output.
            filepath: The file to write. None resolves it from the
                configuration and the object's name.
            options_package: A package to read the export/render options from
                in addition to 'project', which is how a custom implementation
                declared in one package is used from another.
            options_project: The same, as the package itself rather than its
                name, for a caller that already resolved it. Spelling a package
                one is holding and looking it up again is a round trip with one
                outcome that is not the package - so a caller with it in hand
                (`partcad.simulation`, which resolved the plugin to reach its
                'format:') hands it over instead.
            output_dir: Where the file goes when 'filepath' does not say,
                overriding whatever the configuration asked for.
            overlay: A 'render_overlay.Overlay' asking for this shape's ports
                and/or interfaces to be drawn on the projection ("pc render
                --with-ports"/"--with-interfaces"), or None. A file type that
                declares 'with_ports:'/'with_interfaces:' of its own draws them
                either way - see 'render_overlay.effective'.
            kwargs: Export parameters, overriding what the configuration says.
        """
        # A caller that names no package still gets the shape's own. Its
        # 'export:'/'render:' sections are where a package declares its file
        # types, so resolving it here is what makes a package-defined
        # implementation work through this method and not only through
        # 'Project.render_async()', which always passes the package in.
        if project is None:
            project = ctx.get_project(self.project_name)

        if options_project is None and options_package:
            options_project = ctx.get_project(options_package)
            if options_project is None:
                pc_logging.error("The options package is not found: %s" % options_package)
                return

        # The bare file type in the action name: a package path in it would make
        # one operation look like several, one per package that asked.
        action = f"Render{output.split_format(self.project_name, format_name)[0].upper()}" if format_name else "Render"
        with pc_logging.Action(action, self.project_name, self.name):
            obj = await self.get_wrapped(ctx)
            if obj is None:
                pc_logging.error(f"Cannot render '{self.name}': shape is empty")
                return

            # Shared by every file type this call writes, so that an object
            # whose ports are asked for in three formats is walked once.
            ports_cache = {}

            for fmt in [format_name] if format_name else output.all_formats(ctx):
                await self._render_one_async(
                    ctx,
                    obj,
                    fmt,
                    project,
                    filepath,
                    options_project,
                    output_dir,
                    kwargs,
                    overlay=overlay,
                    ports_cache=ports_cache,
                )

    def render(
        self,
        ctx: Context,
        format_name: str,
        project: Optional[Project] = None,
        filepath=None,
        options_package: Optional[str] = None,
        options_project: Optional[Project] = None,
        output_dir=None,
        overlay=None,
        **kwargs,
    ) -> None:
        # By keyword, every one of them. 'render_async' grew an
        # 'options_project' parameter between 'options_package' and
        # 'output_dir', and a positional forwarding here handed 'output_dir' to
        # it and 'overlay' to 'output_dir' - so a caller that named
        # 'output_dir=' got a string where '_output_getopts' reads
        # '.config_obj' off a package. Nothing in the signature above can drift
        # away from the one below while the names are what is passed.
        asyncio.run(
            self.render_async(
                ctx,
                format_name,
                project=project,
                filepath=filepath,
                options_package=options_package,
                options_project=options_project,
                output_dir=output_dir,
                overlay=overlay,
                **kwargs,
            )
        )

    # ------------------------------------------------------------------ #
    #
    # Computer-aided engineering: the third thing a script produces from a
    # shape, beside a file another tool opens ('export:') and a picture of it
    # ('render:'). It runs through exactly the same machinery - a file type
    # declared in a section, an implementation named by 'path' and 'package',
    # the same sandbox and the same meta-wrapper - and differs in two places
    # only. What goes in carries the part's boundary conditions ('fea:'/'cfd:',
    # see 'partcad.cae'), and what comes back carries findings beside the file.

    def analysis_getopts(
        self,
        ctx,
        analysis: str,
        format_name: str,
        project=None,
        filepath=None,
        options_project=None,
        output_dir=None,
    ):
        """Resolve one analysis: its implementation, options and output path.

        The counterpart of 'output_getopts' for the 'cae:' section, and different
        from it in two ways that both follow from an analysis not being a file
        type of the object:

        * The file is named after the analysis as well as the object, because a
          part has as many results as it has analyses: 'bracket.fea.vtu'.
        * There is no default extension to fall back on. Which model format an
          analysis writes is the implementation's decision - a 3D field, a 2D
          plot - so the implementation has to state it, and an implementation
          that does not is a bug in that package rather than something to guess
          at on its behalf.
        """
        opts, configured_output_dir = self._output_getopts(ctx, format_name, output.CAE, project, options_project)
        output_dir = output_dir or configured_output_dir

        if filepath is not None and os.path.isdir(filepath):
            # A directory was passed where a file was expected: it names where
            # the file goes, not the file.
            output_dir, filepath = filepath, None

        # With the implementing package, which the export path fills in later
        # (in '_materialize_output_script') because that is the first moment it
        # needs one. Here it is known already -- the caller resolved it to get
        # 'options_project' -- and something asks earlier: 'pc test' reads
        # 'container'/'dockerImage' off this to tell a machine that cannot run
        # the implementation from an implementation that does not work. Without
        # a project those read as "declared nothing", which is the same answer a
        # package that really declares nothing gives.
        impl = output.Implementation(output.CAE, format_name, opts, project=options_project)
        extension = impl.extension(None)
        if not extension:
            raise Exception(
                "The '%s' implementation does not say what file it writes: it needs an 'extension:'" % format_name
            )
        filepath = self._output_filepath(
            opts, output_dir, "." + extension, project, filepath, stem_suffix="." + analysis
        )
        return impl, filepath

    def cam_getopts(
        self,
        ctx,
        format_name: str,
        project=None,
        filepath=None,
        options_project=None,
        output_dir=None,
    ):
        """Resolve one route: its implementation, options and output path.

        The counterpart of 'analysis_getopts' for the 'cam:' section, and the
        same shape as it but for the file's name. An analysis writes
        'bracket.fea.vtu' because a part has as many results as it has analyses;
        a route writes 'bracket.nc', with no infix, because the extension
        already says what the file is and an object has one route at a time. Two
        file types that both routed the same object would collide -- and they
        cannot, because which one produces the route is a single answer resolved
        before this is called.

        There is no default extension to fall back on, for the reason the
        analysis path has none: what a controller reads is the implementation's
        decision, and an implementation that does not say is a bug in that
        package rather than something to guess at on its behalf.
        """
        opts, configured_output_dir = self._output_getopts(ctx, format_name, output.CAM, project, options_project)
        output_dir = output_dir or configured_output_dir

        if filepath is not None and os.path.isdir(filepath):
            # A directory was passed where a file was expected: it names where
            # the file goes, not the file.
            output_dir, filepath = filepath, None

        # With the implementing package, for the reason 'analysis_getopts' fills
        # it in: something asks about the implementation before it is run, and a
        # missing project answers "declared nothing" rather than failing.
        impl = output.Implementation(output.CAM, format_name, opts, project=options_project)
        extension = impl.extension(None)
        if not extension:
            raise Exception(
                "The '%s' implementation does not say what file it writes: it needs an 'extension:'" % format_name
            )
        filepath = self._output_filepath(opts, output_dir, "." + extension, project, filepath)
        return impl, filepath

    def _route_implementation(self, ctx, implementation=None, declared=None):
        """Who produces this route: the package and the file type in it.

        The very precedence '_analysis_implementation' documents, over the one
        thing that differs: the bottom of it is 'camImplementation', and unlike
        the CAE defaults that one names a package PartCAD ships. So the chain is

        * 'implementation' -- this run's answer, from 'pc cam -i'.
        * 'declared' -- the object's own, from 'implementation:' in its 'cam:'
          section. A statement about the object: the post-processor its numbers
          were written for.
        * the user configuration ('camImplementation'), which is what makes
          'pc cam' work in a package that says nothing about machines.

        A relative package name is resolved against whoever said it, which is
        why the two are handed over separately rather than picked between here.
        """
        own = False
        if not implementation:
            if declared:
                implementation, own = declared, True
            else:
                # The *context's* configuration, not the process-wide singleton:
                # a daemon builds its context from the caller's configuration,
                # and reading the singleton here would route under the daemon's
                # default. The same reason '_analysis_implementation' gives.
                implementation = ctx.user_config.cam_implementation
        implementation = str(implementation).strip()
        if not implementation:
            raise Exception("No 'cam' implementation is configured")

        package, separator, format_name = implementation.rpartition(":")
        if not separator:
            # A package on its own: the file type is 'gcode', which is what the
            # built-in package calls its only one and what a package publishing
            # one route implementation is most likely to call its own.
            package, format_name = implementation, "gcode"
        format_name = format_name or "gcode"
        package = self._resolve_implementing_package(ctx, package, own)

        options_project = ctx.get_project(package)
        if options_project is None:
            raise Exception(
                "The package implementing 'cam' is not found: %s. "
                "Add it to this package's 'dependencies:', or name another one." % package
            )
        if getattr(options_project, "broken", False):
            # A package that failed to load answers every question about itself
            # with nothing, so without this the next thing to go wrong is
            # 'cam_getopts' reporting that the implementation declared no
            # 'extension:' -- which sends the reader to look at a file that was
            # never read.
            raise Exception(
                "The package implementing 'cam' did not load: %s. "
                "The reason is reported above; a dependency that could not be fetched is the usual one."
                % options_project.name
            )
        return options_project, format_name

    def _resolve_implementing_package(self, ctx, package: str, own: bool) -> str:
        """Make a package name absolute, from the point of view of whoever said it.

        'own' is what separates a name this object declared from one a user
        typed. A user's is resolved against the current package, like every
        other name a command line carries; this object's is resolved against the
        package the object is in, because that is the package whose
        'dependencies:' the name was written against.
        """
        if not own or not self.project_name:
            return ctx.resolve_package_path(package or ".")
        if not package or package == ".":
            # The object's own package implements it, which is what a package
            # shipping a solver alongside the parts it analyses would write.
            return self.project_name
        if package.startswith("/"):
            # Already absolute; hand it over for the '/' -> '//' deprecation.
            return ctx.resolve_package_path(package)
        # The root package is named '//', so it already ends in the separator
        # and joining on another one produces '///name'. That does still
        # resolve -- 'get_project()' strips a fixed two characters and the
        # extra one lands in the part it splits -- but it is not the spelling
        # anything else uses, and a path built here is a path that can end up
        # in a message. Build the canonical one.
        base = self.project_name.rstrip("/")
        return ctx.resolve_package_path((base + "/" if base else "//") + package)

    def _analysis_implementation(
        self,
        ctx,
        analysis: str,
        implementation: Optional[str] = None,
        declared: Optional[str] = None,
    ):
        """Who runs this analysis: the package and the file type in it.

        An implementation is named as '<package>:<file type>' - the same spelling
        every other PartCAD object uses - and can be said in three places, which
        is why the precedence lives here rather than in each caller:

        * 'implementation' is this *run's* answer: 'pc cae fea -i', the IDE's
          field. It wins, because it is the most specific thing anybody said.
        * 'declared' is the object's own, from 'implementation:' in its 'fea:' or
          'cfd:' section - a statement about the part, naming the solver its
          numbers were produced with.
        * failing both, the user configuration
          ('caeFeaImplementation'/'caeCfdImplementation'), which is what makes
          'pc cae fea :bracket' work in a package that says nothing about
          solvers.

        A **relative** package name is resolved against whoever said it, and the
        three do not agree about who that is. 'pc cae fea -i calculix:fea' means
        the 'calculix' beside the user, so it resolves against the current
        package the way every other name a user types does. 'implementation:' in
        a package's own YAML means the 'calculix' that package imported, and has
        to resolve against *that* package -- otherwise the same declaration
        resolves differently depending on which directory the command was run
        from, and 'pc test -r' over a tree of packages (which runs with the tree
        root current, not each package) cannot resolve any of them.

        The file type need not be called after the analysis. What decides the
        analysis is the command that was run, because that is what says which
        section of the part holds the boundary conditions; the file type only
        says which declaration in the implementing package to read.
        """
        # 'declared' is the only one of the three that belongs to the object.
        own = False
        if not implementation:
            if declared:
                implementation, own = declared, True
            else:
                # The *context's* configuration, not the process-wide singleton.
                # A daemon builds its context from the caller's configuration
                # (see 'operations.context_create'), and its own is whatever the
                # environment held when something first started it. Reading the
                # singleton here would run the analysis under the daemon's
                # default while 'cae.defaults' -- which the IDE pre-fills its
                # field from -- reported the caller's.
                implementation = ctx.user_config.cae_implementation(analysis)
        implementation = str(implementation).strip()
        if not implementation:
            raise Exception("No '%s' implementation is configured" % analysis)

        package, separator, format_name = implementation.rpartition(":")
        if not separator:
            # A package on its own: the file type is the analysis's own name,
            # which is what a package publishing one implementation calls it.
            package, format_name = implementation, analysis
        format_name = format_name or analysis
        package = self._resolve_implementing_package(ctx, package, own)

        options_project = ctx.get_project(package)
        if options_project is None:
            raise Exception(
                "The package implementing '%s' is not found: %s. "
                "Add it to this package's 'dependencies:', or name another one." % (analysis, package)
            )
        if getattr(options_project, "broken", False):
            # A package that failed to load answers every question about itself
            # with nothing, so without this the next thing to go wrong is
            # 'analysis_getopts' reporting that the implementation declared no
            # 'extension:' -- which sends the reader to look at a file that was
            # never read. Whatever went wrong is already in the log above; what
            # is worth saying here is which package it was and that this is why
            # the analysis is not running.
            raise Exception(
                "The package implementing '%s' did not load: %s. "
                "The reason is reported above; a dependency that could not be fetched is the usual one."
                % (analysis, options_project.name)
            )
        return options_project, format_name

    async def _analysis_boundary_async(self, ctx, config):
        """Where the boundary conditions this analysis was given actually are.

        The part names interfaces; a solver needs coordinate frames. The lookup
        is the very one 'pc render --with-ports' does, so a user who cannot work
        out why a fixture did nothing can draw the same ports on a projection and
        look at them.
        """
        from .render_overlay import Overlay, collect_async

        try:
            records = await collect_async(self, ctx, Overlay(ports=True))
        except Exception as e:
            raise pc_cae.CaeConfigError(
                "Failed to locate the ports the '%s:' section names: %s" % (config.analysis, e)
            ) from e

        assigned, unmatched = pc_cae.assign_ports(config, records)
        for name, reason in unmatched:
            # A boundary condition that matched no port is silently doing
            # nothing, and a solver told to hold nothing still answers with
            # nonsense rather than with an error. The reason is carried rather
            # than assumed: a misspelt *instance* name reads very differently
            # from an interface the object never implements.
            pc_logging.warning(
                "%s:%s: '%s:' names the interface '%s', but %s"
                % (self.project_name, self.name, config.analysis, name, reason)
            )
        if not assigned:
            raise pc_cae.CaeConfigError(
                "'%s:' names no port of this object: none of the interfaces it lists is implemented here"
                % config.analysis
            )
        return assigned

    async def analyze_async(
        self,
        ctx: Context,
        analysis: str,
        implementation: Optional[str] = None,
        project: Optional[Project] = None,
        filepath=None,
        output_dir=None,
        **kwargs,
    ) -> dict:
        """Run one CAE analysis on this shape and report what it found.

        Args:
            ctx: Execution context.
            analysis: "fea" or "cfd" - which section of the object holds the
                boundary conditions, and what the output file is named after.
            implementation: '<package>:<file type>' naming who runs it,
                overriding the user configuration's default for this run.
            project: The package the object belongs to, whose 'cae:' section
                re-tunes the implementation's parameters.
            filepath: The file to write. None resolves it from the
                configuration and the object's name.
            output_dir: Where the file goes when 'filepath' does not say.
            kwargs: Analysis parameters, overriding what the configuration says.

        Returns:
            The model file that was written and the findings, as plain data.

        Raises:
            partcad.cae.CaeConfigError: the object declares no boundary
                conditions for this analysis, or declares them wrongly. Both are
                answers to the user's question rather than failures, and both
                are reported as the sentence they carry.
        """
        config = pc_cae.config_of(self, analysis)
        if config is None:
            raise pc_cae.CaeConfigError(
                "%s:%s declares no '%s:' section, so there is nothing to analyse"
                % (self.project_name, self.name, analysis)
            )

        if project is None:
            project = ctx.get_project(self.project_name)
        # '-i' first, then what the part declared, then the user configuration.
        # The part's own answer sits in the middle because it is a statement
        # about the part -- the solver it was written against -- and the two
        # things that outrank it are the two that are about this run and this
        # machine. Handed over separately rather than picked between here: the
        # two are resolved against different packages when either names one
        # relatively, and only the callee knows which it ended up using.
        options_project, format_name = self._analysis_implementation(
            ctx, analysis, implementation, declared=config.implementation
        )

        try:
            return await self._analysis_run_async(
                ctx, analysis, config, project, options_project, format_name, filepath, output_dir, kwargs
            )
        except (pc_cae.CaeConfigError, pc_runtime.SandboxUnavailable):
            # Neither is the implementation failing, and neither gets the
            # report. The first is the part's own section being wrong, which is
            # answered by editing it; the second is this machine having no
            # container runtime, so nothing was ever asked and there is nothing
            # to report about the implementation or the platform.
            raise
        except Exception as e:
            # Everything else is "asked, and no answer", and every caller says
            # so the same way. Written here rather than by each of them because
            # this is where the implementation's name is known, and because a
            # user who ran `pc cae fea` and then `pc test -f fea` must be told
            # the same thing about the same machine both times.
            raise pc_cae.CaeFailed(
                pc_cae.dysfunction_report(
                    "%s:%s" % (self.project_name, self.name),
                    analysis,
                    "%s:%s" % (options_project.name, format_name),
                    e,
                )
            ) from e

    async def _analysis_run_async(
        self,
        ctx: Context,
        analysis: str,
        config,
        project: Project,
        options_project: Project,
        format_name: str,
        filepath,
        output_dir,
        kwargs: dict,
    ) -> dict:
        """`analyze_async` once it knows what to run and who runs it.

        Split out so that the caller can say what every failure in here means
        without a ninety-line `try:` around the part that does the work. Every
        exception that leaves this is the implementation failing to deliver -
        see `analyze_async`.
        """
        with pc_logging.Action(analysis.upper(), self.project_name, self.name):
            impl, final_filepath = self.analysis_getopts(
                ctx, analysis, format_name, project, filepath, options_project, output_dir
            )
            final_filepath = os.path.abspath(final_filepath)

            # Clearing the path, writing it and reading the answer back are one
            # operation on one file, and the path is derived from the shape --
            # so a second run over the same shape resolves to the same path and
            # would otherwise interleave with this one: its 'os.remove' landing
            # between this run's write and this run's check, or its model being
            # the one handed back here. Held for all three, and the nested
            # 'get_wrapped' and '_run_implementation_async' take the same lock
            # again without waiting for it.
            #
            # What this does not make it is a snapshot. The path below is the
            # shape's model file, not this call's, and a later run of the same
            # analysis on the same shape replaces it once this one has returned
            # -- the same contract 'pc render' and 'pc export' have, and the
            # reason the IDE and the CLI can both name the file without being
            # told where it went. A caller that needs the bytes to outlive the
            # next run copies them; giving each run its own path instead would
            # take that name away from everyone who relies on it.
            async with self.locked():
                ctx.ensure_dirs_for_file(final_filepath, self.name)
                # A model is the answer to *this* run, and the path it goes to
                # is stable -- '<part>.<analysis>.<extension>', beside the
                # package. So one an earlier run left there would satisfy the
                # check below and be handed back as the new result: last week's
                # stresses under today's load, with nothing to say they are not
                # today's. Removed before the implementation is asked, which
                # makes the file's existence afterwards mean what it is read as
                # meaning.
                if os.path.exists(final_filepath):
                    os.remove(final_filepath)

                obj = await self.get_wrapped(ctx)
                if obj is None:
                    raise Exception("Cannot analyse '%s': shape is empty" % self.name)

                boundary = await self._analysis_boundary_async(ctx, config)
                script = await self._materialize_output_script(ctx, impl)

                request = await self._output_request(ctx, obj, impl, kwargs)
                request.update(config.to_data())
                # The ports each condition landed on, in the shape's own
                # coordinate system. 'fix' and 'load' above say what the user
                # wrote; this says where it goes, which is what a solver needs.
                request["boundary"] = boundary

                result = await self._run_implementation_async(ctx, impl, script, request, final_filepath)

                if result is None:
                    raise Exception("The '%s' implementation reported nothing: %s" % (format_name, script))
                if not result.get("success", False):
                    raise Exception(
                        "%s failed for %s:%s: %s"
                        % (analysis.upper(), self.project_name, self.name, result.get("exception", "Unknown error"))
                    )
                written = os.path.exists(final_filepath)

        if not written:
            # The meta-wrapper reports what the script returned and does not look
            # at the path, so "success" alone is the script's word for it. This
            # result is handed to a caller that acts on 'filepath' -- the IDE
            # reads the bytes back, the CLI prints where to find them -- so a
            # path to nothing is worse than a refusal. The same check
            # '_convert_to_serialized()' makes of an exporter, for the same
            # reason. Sound only because the path was cleared above: otherwise
            # this passes on a file the implementation never touched.
            raise Exception(
                "%s produced no model for %s:%s: %s was not written"
                % (analysis.upper(), self.project_name, self.name, final_filepath)
            )
        for warning in result.get("warnings") or []:
            pc_logging.warning("%s:%s: %s" % (self.project_name, self.name, warning))

        return {
            "object": "%s:%s" % (self.project_name, self.name),
            "analysis": analysis,
            "implementation": "%s:%s" % (options_project.name, format_name),
            "filepath": final_filepath,
            "extension": os.path.splitext(final_filepath)[1].lstrip("."),
            "findings": pc_cae.normalize_findings(result.get("findings")),
            "boundary": boundary,
        }

    def analyze(
        self,
        ctx: Context,
        analysis: str,
        implementation: Optional[str] = None,
        project: Optional[Project] = None,
        filepath=None,
        output_dir=None,
        **kwargs,
    ) -> dict:
        """`analyze_async` for a caller that has no event loop of its own."""
        return asyncio.run(self.analyze_async(ctx, analysis, implementation, project, filepath, output_dir, **kwargs))

    async def route_async(
        self,
        ctx: Context,
        implementation: Optional[str] = None,
        project: Optional[Project] = None,
        filepath=None,
        output_dir=None,
        machine: Optional[str] = None,
        **kwargs,
    ) -> dict:
        """Produce the route file this shape declares, and report what it is.

        Args:
            ctx: Execution context.
            implementation: '<package>:<file type>' naming who produces it,
                overriding the user configuration's default for this run.
            project: The package the object belongs to, whose 'cam:' section
                re-tunes the implementation's parameters.
            filepath: The file to write. None resolves it from the
                configuration and the object's name.
            output_dir: Where the file goes when 'filepath' does not say.
            kwargs: Job parameters, overriding what the configuration says.

        Returns:
            The route file that was written, what it took, and anything the
            implementation wanted said about it, as plain data.

        Raises:
            partcad.cam.CamConfigError: the object declares no 'cam:' section,
                or declares one that cannot be made sense of. Both are answers
                to the user's question rather than failures, and both are
                reported as the sentence they carry - which is what lets a run
                over a whole package tell the objects it skips from the one
                that is broken.
            partcad.cam.CamFailed: the implementation was asked and produced no
                route.
        """
        try:
            config = pc_cam.config_of(self, machine)
        except pc_cam.CamConfigError as e:
            # Named, because a run over a package reports one line per object
            # and "'cam: tool:' is not a length" against forty parts is a
            # sentence with no address on it. Done here rather than in
            # 'partcad.cam', which deliberately knows nothing about shapes.
            raise self._cam_config_error(e) from e
        if config is None:
            raise pc_cam.CamConfigError(
                "%s:%s says nothing about being cut, so there is nothing to route" % (self.project_name, self.name)
            )

        if project is None:
            project = ctx.get_project(self.project_name)
        # '-i' first, then what the object declared, then the user
        # configuration. The object's own answer sits in the middle because it
        # is a statement about the object -- the post-processor its numbers were
        # written for -- and the two things that outrank it are the two that are
        # about this run and this machine.
        try:
            options_project, format_name = self._route_implementation(
                ctx, implementation, declared=config.implementation
            )
        except pc_cam.CamConfigError as e:
            raise self._cam_config_error(e) from e
        except Exception as e:
            # Naming who should produce the route is configuration, so failing
            # to resolve that name is a 'CamConfigError' and not a plain one.
            # The type is what decides the blast radius: a package-wide run
            # gathers these, and '_route_packages_async' re-raises anything it
            # does not recognise -- so an unresolvable implementation used to
            # abort the whole request and discard the routes already produced
            # for every other object in the package.
            raise self._cam_config_error(
                pc_cam.CamConfigError("the 'cam' implementation could not be resolved: %s" % e)
            ) from e

        try:
            return await self._route_run_async(
                ctx, config, project, options_project, format_name, filepath, output_dir, kwargs, machine
            )
        except pc_cam.CamConfigError as e:
            # The same naming, for the layers underneath the object: a feed the
            # *package* wrote in a spelling nothing can read is reported against
            # every object it covers, and each of those reports has to say which
            # object could not be routed because of it.
            raise self._cam_config_error(e) from e
        except pc_runtime.SandboxUnavailable:
            # Neither is the implementation failing, and neither gets the
            # report. The first is the object's own section being wrong, which
            # is answered by editing it; the second is this machine having no
            # sandbox, so nothing was ever asked.
            raise
        except Exception as e:
            # Everything else is "asked, and no route", and every caller says so
            # the same way. Written here rather than by each of them because
            # this is where the implementation's name is known.
            raise pc_cam.CamFailed(
                pc_cam.dysfunction_report(
                    "%s:%s" % (self.project_name, self.name),
                    "%s:%s" % (options_project.name, format_name),
                    e,
                )
            ) from e

    def _route_machine_data(self, machine: Optional[str] = None) -> dict:
        """Which machine this route is written for, as the request says it.

        Empty for everything that declares no machine: an assembly, a part made
        some other way, anything with no `manufacturing:` section at all. An
        implementation that gets nothing writes what it has always written,
        which is a CNC program -- so such an object is unaffected by any of this.

        **A sketch is asked like anything else.** A drawing declares the section
        with no `method:` in it -- it is not made out of anything, it is a path a
        machine follows -- and `_read_machines` reads that case on purpose. So
        the answer has to come from what the object declared rather than from
        what class it is: a `not isinstance(self, Part)` here returned `{}` for a
        sketch that had named a `laser:`, its `machine`, `toolAxis` and `kerf`
        never reached the request, and the drawing was handed to the *router*
        emitter -- which asked it for a cutter diameter a beam does not have.

        Read from the part's own declaration rather than passed in as a job
        parameter, because the machine is not something a run gets to re-tune:
        `pc cam` on a laser-cut part produces a laser program on anybody's
        machine, and the day it does not is the day somebody sends a router
        program to a laser. What a run *may* do is choose between the machines
        the part itself named, which is what `machine` is.

        Raises:
            partcad.cam.CamConfigError: the part named a machine and the naming
                cannot be read -- a `laser:` that is not a section, a key that
                machine does not take, an axis that is not one. `route_async`
                already wraps this call's caller in a `try` that re-raises such
                an error through `_cam_config_error`, so it is raised bare here
                and named there.

        It has to *refuse* rather than fall back, and that is the whole reason
        this is not a `debug` line. `_read_machines` records such a declaration
        in `machine_error` and keeps no machine, which is indistinguishable here
        from the part that simply named none -- and a part that named none
        routes as CNC. (`cam.declared_config` refuses first for the same reason,
        which makes this the backstop; the sentence is the same either way.) So a part whose `laser:` subsection has a typo in it
        would be handed a *router* program, silently. `pc test` reporting it too
        is not enough, because nothing makes `pc cam` wait for `pc test`.
        """
        try:
            from .part_config import PartConfiguration

            manufacturing_data = PartConfiguration.get_manufacturing_data(self)
        except Exception as e:  # pylint: disable=broad-except
            raise pc_cam.CamConfigError("the 'manufacturing:' section could not be read: %s" % e) from e
        machine_error = getattr(manufacturing_data, "machine_error", None)
        if machine_error:
            # A backstop rather than the refusal a user meets: `declared_config`
            # reads the same field and raises first, on every path that reaches
            # here. Verbatim and not wrapped, so that the one fault reads as one
            # sentence whichever of the two spoke it.
            raise pc_cam.CamConfigError(machine_error)

        chosen = manufacturing_data.machine_named(machine) if machine else manufacturing_data.machine
        if chosen is None:
            # Made some other way, so there is no machine to name and nothing
            # wrong with that: an implementation handed nothing writes what it
            # has always written. A part that named several and had none chosen
            # never reaches here -- `cam.declared_config` refuses first, where
            # the sentence can name the choices.
            return {}
        return chosen.to_data()

    def _cam_config_error(self, error) -> "pc_cam.CamConfigError":
        """One `cam:` configuration error, with the object it is about in front.

        Idempotent by construction: it is applied where the error leaves
        `route_async`, which is once.
        """
        return pc_cam.CamConfigError("%s:%s: %s" % (self.project_name, self.name, error))

    async def _route_run_async(
        self,
        ctx: Context,
        config,
        project: Project,
        options_project: Project,
        format_name: str,
        filepath,
        output_dir,
        kwargs: dict,
        machine: Optional[str] = None,
    ) -> dict:
        """'route_async' once it knows what to run and who runs it.

        Split out so that the caller can say what every failure in here means
        without a ninety-line 'try:' around the part that does the work - the
        same split 'analyze_async' and '_analysis_run_async' are.
        """
        with pc_logging.Action("CAM", self.project_name, self.name):
            impl, final_filepath = self.cam_getopts(ctx, format_name, project, filepath, options_project, output_dir)
            if machine is not None and (filepath is None or os.path.isdir(filepath)):
                # 'panel.laser.nc' beside 'panel.drill.nc'. Only when a machine
                # was chosen, which only happens when the part offered more than
                # one -- so an object with a single machine keeps the name it
                # has always had, and a caller that named a path gets that path.
                #
                # A directory is not naming a path: 'cam_getopts' has just read
                # it as the *output_dir* and derived the filename from the
                # object, which is the same filename for every machine. Asking
                # the same question it asked is what keeps two alternatives from
                # resolving to one file -- where the second route deletes the
                # first before writing itself, and the run reports two.
                root, extension = os.path.splitext(final_filepath)
                final_filepath = "%s.%s%s" % (root, machine, extension)
            final_filepath = os.path.abspath(final_filepath)

            # Clearing the path, writing it and checking it afterwards are one
            # operation on one file, and the path is derived from the shape --
            # so a second run over the same shape resolves to the same path and
            # would otherwise interleave with this one. Held for all three; the
            # nested 'get_wrapped' and '_run_implementation_async' take the same
            # re-entrant lock without waiting for it.
            async with self.locked():
                ctx.ensure_dirs_for_file(final_filepath, self.name)
                # A route is the answer to *this* run, and the path it goes to
                # is stable. So one an earlier run left there would satisfy the
                # check below and be handed back as the new result: last week's
                # depths under today's tool, with nothing to say they are not
                # today's. Removed before the implementation is asked, which
                # makes the file's existence afterwards mean what it is read as
                # meaning -- the same thing 'analyze_async' does and for the
                # same reason.
                if os.path.exists(final_filepath):
                    os.remove(final_filepath)

                obj = await self.get_wrapped(ctx)
                if obj is None:
                    raise Exception("Cannot route '%s': shape is empty" % self.name)

                script = await self._materialize_output_script(ctx, impl)
                # Handed no kwargs, deliberately: '_output_request' applies them
                # before the object's own section is merged in, and the object
                # would then overwrite the very values this call was given.
                # 'route_async' promises the opposite -- an explicit parameter
                # is the most specific thing anybody said -- so they go on top,
                # below.
                request = await self._output_request(ctx, obj, impl, {})
                # The object's own job, on top of the file type's parameters:
                # only what the object actually declared, so that a package that
                # set a tool for all of its parts still answers for the ones
                # that did not name one (see 'partcad.cam.CamConfig.to_data').
                request.update(config.to_data())
                # And last, what this call was told: 'pc cam' passes none today,
                # but 'route_async(tool=...)' is the documented way to route one
                # object against another cutter without editing its section.
                request.update({key: value for key, value in kwargs.items() if value is not None})
                # And last of all, which machine this is cut on. It comes from
                # the part's 'manufacturing:' section rather than from any of
                # the three layers above, so it is applied after them and
                # cannot be overridden by a 'cam:' key: what a part is made on
                # is a property of the part, not a parameter of the route, and
                # a route written for a laser by a section that said 'machine'
                # would be a program for a machine nobody owns.
                request.update(self._route_machine_data(machine))
                # And then every layer of it converted together. The object's
                # own values are already numbers; the ones the package and
                # '//builtin/cam' contributed have never been near a parser, and
                # a '2400 mm/min' written one layer down is as much PartCAD's to
                # understand as the same words written on the object.
                request = pc_cam.normalize_job(request)

                result = await self._run_implementation_async(ctx, impl, script, request, final_filepath)

                if result is None:
                    raise Exception("The '%s' implementation reported nothing: %s" % (format_name, script))
                if not result.get("success", False):
                    raise Exception(
                        "No route for %s:%s: %s"
                        % (self.project_name, self.name, result.get("exception", "Unknown error"))
                    )
                written = os.path.exists(final_filepath)

        if not written:
            # The meta-wrapper reports what the script returned and does not look
            # at the path, so "success" alone is the script's word for it. A
            # caller acts on 'filepath' -- the CLI prints it, and whoever sends
            # it to a machine opens it -- so a path to nothing is worse than a
            # refusal. Sound only because the path was cleared above.
            raise Exception("The route for %s:%s was not written: %s" % (self.project_name, self.name, final_filepath))
        for warning in result.get("warnings") or []:
            pc_logging.warning("%s:%s: %s" % (self.project_name, self.name, warning))

        return {
            "object": "%s:%s" % (self.project_name, self.name),
            "implementation": "%s:%s" % (options_project.name, format_name),
            "filepath": final_filepath,
            "extension": os.path.splitext(final_filepath)[1].lstrip("."),
            # Whatever the implementation counted. Reported rather than
            # interpreted: what is worth knowing about a route differs between a
            # router and a wire EDM, and a fixed set of keys here would be
            # PartCAD deciding that on their behalf (see 'cam.route_report').
            "stats": result.get("stats") or {},
            "warnings": list(result.get("warnings") or []),
        }

    def route(
        self,
        ctx: Context,
        implementation: Optional[str] = None,
        project: Optional[Project] = None,
        filepath=None,
        output_dir=None,
        **kwargs,
    ) -> dict:
        """'route_async' for a caller that has no event loop of its own."""
        # By keyword, for the reason 'render' carries at length: a parameter
        # added to the middle of 'route_async' would otherwise silently
        # re-address every argument after it here.
        return asyncio.run(
            self.route_async(
                ctx,
                implementation=implementation,
                project=project,
                filepath=filepath,
                output_dir=output_dir,
                **kwargs,
            )
        )

    async def render_svg_somewhere_async(
        self,
        ctx,
        project=None,
        filepath=None,
        line_weight=None,
        viewport_origin=None,
        annotations=None,
    ):
        """Renders an SVG file somewhere, ignoring where the project wants it.

        'annotations' are 3D line segments - each a pair of points in the shape's
        own coordinate system - to draw on top of the projection. An assembly
        instruction book uses them to show the gap an exploded view introduces
        (see assembly_guide.py); they are projected together with the shape, so
        they land where the geometry they point at does.
        """
        if filepath is None:
            with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f:
                filepath = f.name

        if not annotations:
            self.svg_path = None
        await self.render_async(
            ctx,
            "svg",
            project=project,
            filepath=filepath,
            line_weight=line_weight,
            viewport_origin=viewport_origin,
            annotations=annotations,
        )
        if not annotations and os.path.exists(filepath):
            # An annotated projection is a one-off illustration, not this shape's
            # picture: remembering it here would hand it to every later caller
            # that asks for the shape's SVG.
            self.svg_path = filepath

    def render_svg_somewhere(
        self,
        ctx,
        project=None,
        filepath=None,
        line_weight=None,
        viewport_origin=None,
        annotations=None,
    ):
        asyncio.run(
            self.render_svg_somewhere_async(
                ctx,
                project=project,
                filepath=filepath,
                line_weight=line_weight,
                viewport_origin=viewport_origin,
                annotations=annotations,
            )
        )

    async def get_solidity_async(self, ctx):
        """Whether this shape is a solid OCCT will do arithmetic on.

        Returned as {"solids": n, "volume": v, "valid": bool}, with 'volume' and
        'valid' None when the shape holds no solid at all - a sketch, a shell,
        a wire - or None outright when the shape could not be built.

        A negative volume means the faces are oriented inward: the shape is
        inside out. It still builds, renders, exports and measures; only its
        arithmetic is wrong, which is why this has to be asked rather than
        noticed. Measured in a sandbox, like every other operation on geometry.
        """
        obj = await self.get_wrapped(ctx)
        if obj is None:
            return None

        with pc_logging.Action("Solidity", self.project_name, self.name):
            request_serialized = shape_envelope.serialize({"wrapped": obj})

            runtime = ctx.get_python_runtime(version="3.11")
            await runtime.ensure_async(sandbox_versions.CADQUERY_OCP)

            with tempfile.TemporaryDirectory(prefix="partcad-solidity-") as unused_dir:
                command = [wrapper.get("solidity.py"), os.path.join(unused_dir, "unused.txt")]
                exitcode, response_serialized, errors = await runtime.run_async(command, request_serialized)
            if exitcode != 0 and len(errors) == 0:
                errors = command_failure(command, exitcode)
            if errors:
                pc_logging.error(errors)
                raise Exception(errors)

            response_lines = response_serialized.strip().splitlines()
            if not response_lines:
                pc_logging.error("Empty response from wrapper: %s" % command[0])
                return None
            result = shape_envelope.deserialize(response_lines[-1].strip())

            if not result.get("success", False):
                pc_logging.error(
                    "Solidity check failed for %s:%s: %s"
                    % (self.project_name, self.name, result.get("exception", "Unknown error"))
                )
                return None
            return {
                "solids": result.get("solids", 0),
                "volume": result.get("volume"),
                "min_solid_volume": result.get("min_solid_volume"),
                "valid": result.get("valid"),
            }

    async def get_bounding_box_async(self, ctx):
        """The axis-aligned bounding box of this shape, in its own coordinates.

        Returned as '(x_min, y_min, z_min, x_max, y_max, z_max)', or 'None' when
        the shape is empty or failed to instantiate. Measured in a sandbox, like
        every other operation on geometry, and remembered afterwards: the callers
        that need a size (exploded views) ask for the same one repeatedly.
        """
        if self._bounding_box is not None:
            return self._bounding_box

        obj = await self.get_wrapped(ctx)
        if obj is None:
            return None

        with pc_logging.Action("BoundingBox", self.project_name, self.name):
            request_serialized = shape_envelope.serialize({"wrapped": obj})

            runtime = ctx.get_python_runtime(version="3.11")
            await runtime.ensure_async(sandbox_versions.CADQUERY_OCP)

            # The wrapper writes nothing, but every wrapper is invoked with an
            # output path; give it one inside a directory of our own, which is
            # removed with the call.
            with tempfile.TemporaryDirectory(prefix="partcad-bbox-") as unused_dir:
                command = [wrapper.get("bbox.py"), os.path.join(unused_dir, "unused.txt")]
                exitcode, response_serialized, errors = await runtime.run_async(command, request_serialized)
            if exitcode != 0 and len(errors) == 0:
                errors = command_failure(command, exitcode)
            if errors:
                pc_logging.error(errors)
                raise Exception(errors)

            response_lines = response_serialized.strip().splitlines()
            if not response_lines:
                pc_logging.error("Empty response from wrapper: %s" % command[0])
                return None
            result = shape_envelope.deserialize(response_lines[-1].strip())

            if not result.get("success", False):
                pc_logging.error(
                    "BoundingBox failed for %s:%s: %s"
                    % (self.project_name, self.name, result.get("exception", "Unknown error"))
                )
                return None

            box = result.get("bounding_box")
            self._bounding_box = None if box is None else tuple(box)
            return self._bounding_box

    def get_bounding_box(self, ctx):
        return asyncio.run(self.get_bounding_box_async(ctx))

    async def get_max_dimension_async(self, ctx):
        """The largest linear dimension of this shape, or 'None' if unknown."""
        box = await self.get_bounding_box_async(ctx)
        if box is None:
            return None
        return max(box[3] - box[0], box[4] - box[1], box[5] - box[2])

    def get_max_dimension(self, ctx):
        return asyncio.run(self.get_max_dimension_async(ctx))

    async def get_metadata_async(self, ctx):
        """Everything recorded about this shape when it was built, or None.

        The three sections 'shape_envelope' defines - what the geometry
        measures, what its source stated about its elements, what that source
        stated about itself - as one dict, exactly as the wrapper that built the
        shape produced them.

        Materializing the shape is what produces this, and materializing it from
        the cache is what reads it back: the metadata lives in the same cache
        entry as the geometry, so a hit carries both and there is no second
        lookup to make and no second entry to be missing. That is the whole
        reason this is cheap enough to ask for.

        'None' for a shape that recorded nothing - one that did not build, or
        one whose geometry could not be measured. A reader cannot tell those
        apart and should not: all of them mean "nothing to report".

        Internally the two *are* told apart, because they decide different
        things: 'None' on the attribute means nobody has looked yet and is what
        sends this to build the shape, while an empty dict means the shape has
        been materialized and recorded nothing. Without that an object with
        nothing to report would rebuild on every ask.
        """
        if self._metadata is None:
            await self.get_wrapped(ctx)
        return self._metadata or None

    async def get_measurements_async(self, ctx):
        """How big this shape is and how much of it there is, or None.

        ``{"bbox": [...] | None, "volume": float | None, "solids": int}`` - the
        box in the shape's own coordinates and without the gap OCCT pads one by,
        the volume in cubic millimetres, and how many solids that is the volume
        of.

        Measured as the shape was *built*, in the process that held the live
        geometry, and carried here in the envelope's metadata. Nothing is
        computed on demand: by the time anybody asks, either the shape has been
        built - in which case the numbers came back with it - or it has not, in
        which case building it is what produces them, and that is the same work
        as answering any other question about it.
        """
        metadata = await self.get_metadata_async(ctx)
        return shape_envelope.metadata_section(metadata, shape_envelope.METADATA_MEASUREMENTS)

    async def get_annotations_async(self, ctx) -> list:
        """What this shape's source said about its individual elements.

        One opaque record per element, as the importing wrapper read them. A
        DXF states these as XDATA against a line, which is where the angle and
        the radius of a sheet metal bend come from; a source that states nothing
        of the kind yields an empty list.

        The records are the source's own vocabulary and are never read into
        here. What asks the real question is a manufacturing check, and it has
        no business knowing which format answered.
        """
        metadata = await self.get_metadata_async(ctx)
        return shape_envelope.metadata_section(metadata, shape_envelope.METADATA_ANNOTATIONS) or []

    async def _reported_async(self, ctx):
        """What 'pc info' adds to a shape once the shape itself has been built.

        All of it comes out of the one metadata dict the shape was built with,
        and it is reported in two registers:

        The measurements are the generic half and are named here, because they
        are the same three numbers for every shape whatever produced it.
        ``BoundingBox`` is the measured box as ``min``/``max``/``size`` triples
        of millimetres. ``size`` is stated rather than left to be subtracted -
        it is the one of the three anybody reads out loud. ``Volume`` is in
        cubic millimetres and ``Solids`` is how many solids that is the volume
        of; both are left out for a shape holding no solid at all, because a
        volume of zero and no volume to speak of are different things. A
        negative volume is reported as it stands: the faces are oriented inward,
        which is worth seeing rather than taking the modulus of.

        Everything else is merged in **as the wrapper named it**. The sections
        are a STEP file's or a DXF drawing's own vocabulary, and the core has no
        business translating one into the other - it did not read the file and
        does not know which format answered.
        """
        info = {}

        metadata = await self.get_metadata_async(ctx)
        if not metadata:
            return info

        measured = shape_envelope.metadata_section(metadata, shape_envelope.METADATA_MEASUREMENTS)
        if measured:
            box = measured.get(shape_envelope.METADATA_BBOX)
            if box:
                info["BoundingBox"] = {
                    "min": list(box[:3]),
                    "max": list(box[3:]),
                    "size": [box[axis + 3] - box[axis] for axis in range(3)],
                }
            if measured.get(shape_envelope.METADATA_VOLUME) is not None:
                info["Volume"] = measured[shape_envelope.METADATA_VOLUME]
                info["Solids"] = measured.get(shape_envelope.METADATA_SOLIDS, 0)

        sections = shape_envelope.metadata_section(metadata, shape_envelope.METADATA_SECTIONS)
        if sections:
            info.update(sections)

        # The per-element records are deliberately *not* reported from here.
        # They are carried for 'get_annotations_async()', whose caller is a
        # manufacturing check that needs every element including the ones
        # nothing was written against. Deciding which of them are worth showing
        # a reader means reading into a record, and what a record holds is the
        # producing wrapper's vocabulary - so the wrapper reports the ones worth
        # showing under a heading of its own, in 'sections' above, and this
        # stays unable to tell a bend angle from a layer name.
        return info

    async def _run_test_async(self, ctx: Context, tests: list | None = None, use_wrapper: bool = False) -> bool:
        if not self.finalized:
            # Skip shapes that are not yet finalized
            return

        if tests is None:
            tests = ctx.get_all_tests()

        test_method = "test_log_wrapper" if use_wrapper else "test_cached"
        tasks = [asyncio.create_task(getattr(t, test_method)(tests, ctx, self)) for t in tests]

        return all(await asyncio.gather(*tasks))

    async def test_async(self, ctx, tests=None) -> bool:
        return await self._run_test_async(ctx, tests, use_wrapper=False)

    def test(self, ctx, tests=None) -> bool:
        return asyncio.run(self.test_async(ctx, tests))

    async def test_log_wrapper_async(self, ctx, tests=None) -> bool:
        return await self._run_test_async(ctx, tests, use_wrapper=True)

    def test_log_wrapper(self, ctx, tests=None) -> bool:
        return asyncio.run(self.test_log_wrapper_async(ctx, tests))
