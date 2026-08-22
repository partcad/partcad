#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.

from __future__ import annotations
from typing import TYPE_CHECKING

import asyncio
import copy
import os
import sys
import tempfile
import threading
import warnings
from typing import Optional

from .cache_hash import CacheHash
from .render import *
from .shape_config import ShapeConfiguration
from .utils import total_size
from . import logging as pc_logging
from .sync_threads import threadpool_manager
from . import wrapper

if TYPE_CHECKING:
    from partcad.context import Context
    from partcad.project import Project

# The core carries shapes as opaque BREP envelopes (see shape_envelope), never
# as live OCP objects. 'wrappers' stays on sys.path so the few code paths that
# legitimately need a live shape - the single normalization choke point in
# get_wrapped(), and convert()/show() which hand a live object to a CAD library
# - can import the OCP codec lazily.
sys.path.append(os.path.join(os.path.dirname(__file__), "wrappers"))
from . import shape_envelope

from . import sandbox_versions
from . import telemetry

PART_EXTENSION_MAPPING = {
    "step": "step",
    "brep": "brep",
    "stl": "stl",
    "3mf": "3mf",
    "threejs": "json",
    "obj": "obj",
    "iges": "iges",
    "gltf": "json",
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

# File extensions for the render formats whose name is not their extension.
# Deliberately kept apart from the two mappings above: those also enumerate the
# part types 'Shape.convert()' accepts, and a rasterized projection is not one
# of them (it cannot be read back in as a part).
RENDER_EXTENSION_MAPPING = {
    "jpeg": "jpg",
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
}

# Every part type named by the extension mappings that 'Shape.convert()' can
# serialize. Derived from the mappings rather than hand-listed, so a new format
# added to a mapping (with a matching 'wrapper_render_<format>.py') is picked up
# here automatically.
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

previously_displayed_shape = None


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

        # Set by the factory (see ShapeFactory.prepare_async): everything that has
        # to happen before this shape's cache key means anything - 'fileFrom'
        # downloads and cross-package references - without building the shape.
        self._prepare = None
        self._prepared = False

        # Filesystem cache
        self.hash = CacheHash(f"{self.project_name}:{self.name}", cache=self.cacheable)
        self.hash.set_dependencies(self.cache_dependencies)

        if self.cacheable:
            cad_config = {}
            for key in ["parameters", "offset", "scale"]:
                if key in self.config:
                    cad_config[key] = self.config[key]
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
            with open(self.path, errors='replace') as f:
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
        if self_id not in self.tls.async_shape_locks:
            self.tls.async_shape_locks[self_id] = asyncio.Lock()
        return self.tls.async_shape_locks[self_id]

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

    async def get_wrapped(self, ctx):
        with self.lock:
            async with self.get_async_lock():
                if self._wrapped is not None:
                    return self._wrapped

                is_cacheable = self.get_cacheable() and ctx
                if is_cacheable:
                    cache_hash = self.hash
                    if cache_hash:
                        keys_to_read = [self.kind, "cmps"]
                        cached, to_cache_in_memory = await ctx.cache_shapes.read_async(
                            cache_hash, keys_to_read, self.get_cache_metadata()
                        )
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

                # Whatever produced the envelope - a factory, a wrapper, a
                # transform - the outer layer around it is this shape's own. It
                # is stamped here rather than left to whoever built the payload,
                # so that a shape built now and the same shape materialized from
                # the cache later carry exactly the same name and label.
                shape = shape_envelope.apply_metadata(shape, self.get_cache_metadata())

                if cache_hash:
                    if is_cacheable:
                        to_cache = {self.kind: await self.get_cache_value(ctx, shape)}
                        if self.components and len(self.components) > 0:
                            to_cache["cmps"] = self.components
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

        if name is None and label is None:
            name, label = self._shape_metadata()
        return shape_envelope.make_shape(ocp_serialize.compressed_brep(shape), name=name, label=label)

    def _component_to_envelope(self, component):
        """Normalize a component (or nested list of components) into envelopes."""
        if isinstance(component, list):
            return [self._component_to_envelope(item) for item in component]
        return self._to_envelope(component)

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
        lives here rather than in the cache - see ShapeCache.
        """
        full_name, label = self._shape_metadata()
        return {"name": full_name, "label": label}

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
                import importlib

                ocp_vscode = importlib.import_module("ocp_vscode")
                if ocp_vscode is None:
                    pc_logging.warning('Failed to load "ocp_vscode". Giving up on connection to VS Code.')
                else:
                    try:
                        global previously_displayed_shape

                        show_kwargs = {}
                        if previously_displayed_shape == self.name:
                            show_kwargs["reset_camera"] = ocp_vscode.Camera.KEEP
                        else:
                            previously_displayed_shape = self.name

                        # ocp_vscode.config.status()
                        pc_logging.info('Visualizing in "OCP CAD Viewer"...')
                        # pc_logging.debug(self.shape)
                        # The viewer needs live OCP objects; get_components()
                        # returns BREP envelopes, so decode them here (lazily -
                        # ocp_vscode already brings OCP with it).
                        import ocp_serialize

                        def _to_live(component):
                            if isinstance(component, list):
                                return [_to_live(item) for item in component]
                            if shape_envelope.is_shape_envelope(component):
                                return ocp_serialize.decode_shape(component)
                            return component

                        ocp_vscode.show(
                            *[_to_live(component) for component in components],
                            progress=None,
                            **show_kwargs,
                        )
                    except Exception as e:
                        pc_logging.warning(e)
                        pc_logging.warning('No VS Code or "OCP CAD Viewer" extension detected.')

    def show(self, ctx=None):
        asyncio.run(self.show_async(ctx))

    def shape_info(self, ctx):
        asyncio.run(self.get_wrapped(ctx))
        info = {}
        info["Memory"] = "%.02f KB" % ((total_size(self) + 1023.0) / 1024.0)

        if self.with_ports is not None:
            info["Ports"] = self.with_ports.info()

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

    async def render_svg_somewhere_async(
        self,
        ctx,
        project=None,
        filepath=None,
        line_weight=None,
        viewport_origin=None,
        annotations=None,
    ):
        """Renders an SVG file somewhere and ignore the project settings

        'annotations' are 3D line segments - each a pair of points in the shape's
        own coordinate system - to draw on top of the projection. An assembly
        instruction book uses them to show the gap an exploded view introduces
        (see assembly_guide.py); they are projected together with the shape, so
        they land where the geometry they point at does.
        """
        if filepath is None:
            filepath = tempfile.mktemp(".svg")

        obj = await self.get_wrapped(ctx)
        if obj is None:
            # pc_logging.error("The shape failed to instantiate")
            self.svg_path = None
            return

        svg_opts, _ = self.render_getopts("svg", ".svg", project, filepath)

        if line_weight is None:
            if "lineWeight" in svg_opts and not svg_opts["lineWeight"] is None:
                line_weight = svg_opts["lineWeight"]
            else:
                line_weight = 1.0

        if viewport_origin is None:
            if "viewportOrigin" in svg_opts and not svg_opts["viewportOrigin"] is None:
                viewport_origin = svg_opts["viewportOrigin"]
            else:
                viewport_origin = [100, -100, 100]

        wrapper_path = wrapper.get("render_svg.py")
        request = {
            "wrapped": obj,
            "line_weight": line_weight,
            "viewport_origin": viewport_origin,
        }
        if annotations:
            request["annotations"] = annotations
        with telemetry.start_as_current_span("*Shape.render_svg_somewhere_async.{shape_envelope.serialize}"):
            request_serialized = shape_envelope.serialize(request)

        # We don't care about customer preferences much here
        # as this is expected to be hermetic.
        # Stick to the version where CadQuery and build123d are known to work.
        runtime = ctx.get_python_runtime(version="3.11")
        await runtime.ensure_async(sandbox_versions.OCPSVG)
        await runtime.ensure_async(sandbox_versions.BUILD123D)
        # Last: re-asserts the VTK-enabled OCP that build123d's
        # 'cadquery-ocp-novtk' dependency has just replaced.
        await runtime.ensure_async(sandbox_versions.CADQUERY_OCP)

        command = [wrapper_path, os.path.abspath(filepath)]
        exitcode, response_serialized, errors = await runtime.run_async(
            command,
            request_serialized,
        )
        if exitcode != 0 and len(errors) == 0:
            errors = f"Failed to execute command '{' '.join(command)}' with exit code {exitcode}"

        if errors:
            pc_logging.error(errors)
            raise Exception(errors)

        result = shape_envelope.deserialize(response_serialized)
        if not result["success"]:
            pc_logging.error("RenderSVG failed: %s:%s: %s" % (self.project_name, self.name, result["exception"]))
        if "exception" in result and not result["exception"] is None:
            pc_logging.exception("RenderSVG exception: %s" % result["exception"])

        if not annotations:
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
        return asyncio.run(
            self.render_svg_somewhere_async(
                ctx,
                project=project,
                filepath=filepath,
                line_weight=line_weight,
                viewport_origin=viewport_origin,
                annotations=annotations,
            )
        )

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
                errors = f"Failed to execute command '{' '.join(command)}' with exit code {exitcode}"
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

    async def _get_svg_path(self, ctx, project):
        async with self.svg_lock:
            if self.svg_path is None:
                await self.render_svg_somewhere_async(ctx=ctx, project=project)
            return self.svg_path

    def render_getopts(
        self,
        kind,
        extension,
        project=None,
        filepath=None,
    ):
        if not project is None and "render" in project.config_obj:
            render_opts = copy.copy(project.config_obj["render"])
        else:
            render_opts = {}

        if kind in render_opts and not render_opts[kind] is None:
            if isinstance(render_opts[kind], str):
                opts = {"prefix": render_opts[kind]}
            else:
                opts = copy.copy(render_opts[kind])
        else:
            opts = {}

        if (
            "render" in self.config
            and not self.config["render"] is None
            and kind in self.config["render"]
            and not self.config["render"][kind] is None
        ):
            shape_opts = copy.copy(self.config["render"][kind])
            if isinstance(shape_opts, str):
                shape_opts = {"prefix": shape_opts}
            opts = render_cfg_merge(opts, shape_opts)

        # Using the project's config defaults if any
        if filepath is None:
            if "path" in opts and not opts["path"] is None:
                filepath = opts["path"]
            elif "prefix" in opts and not opts["prefix"] is None:
                filepath = opts["prefix"]
            else:
                filepath = "."

            # Check if the format specific section of the config (e.g. "png")
            # provides a relative path and there is output dir in cmd line or
            # the generic section of rendering options in the config.
            if not os.path.isabs(filepath):
                if "output_dir" in render_opts:
                    # TODO(clairbee): consider using project.config_dir
                    # filepath = os.path.join(
                    #     project.config_dir, render_opts["output_dir"], filepath
                    # )
                    filepath = os.path.join(render_opts["output_dir"], filepath)
                elif not project is None:
                    filepath = os.path.join(project.config_dir, filepath)

            if os.path.isdir(filepath):
                filepath = os.path.join(filepath, self.name + extension)

        pc_logging.debug("Rendering: %s" % filepath)

        return opts, filepath

    async def render_async(
        self, ctx: Context, format_name: str, project: Optional[Project] = None, filepath=None, **kwargs
    ) -> None:
        """
        Centralized method to render shape via external wrapper.
        Args:
            ctx: Execution context.
            format_name: Render format (e.g., "png", "svg", "dxf").
            project: Optional project object.
            filepath: Target file path for output.
            kwargs: Additional options (width, height, etc.).
        """
        WRAPPER_FORMATS = {
            # NOTE: cadquery-ocp comes last in every list that also has
            # build123d. build123d pulls 'cadquery-ocp-novtk', which replaces
            # the OCP native module with a VTK-less build; re-asserting
            # cadquery-ocp afterwards puts the right one back.
            "svg": [
                sandbox_versions.OCPSVG,
                sandbox_versions.BUILD123D,
                sandbox_versions.CADQUERY_OCP,
            ],
            # JPEG rasterizes through the very same stack as PNG (see
            # wrappers/wrapper_render_raster.py): reportlab's renderPM hands the
            # image to Pillow, which reportlab already depends on, so supporting
            # both formats costs no additional package in the sandbox.
            "png": [
                sandbox_versions.OCPSVG,
                sandbox_versions.BUILD123D,
                sandbox_versions.SVGLIB,
                sandbox_versions.REPORTLAB,
                sandbox_versions.RLPYCAIRO,
                sandbox_versions.CADQUERY_OCP,
            ],
            "jpeg": [
                sandbox_versions.OCPSVG,
                sandbox_versions.BUILD123D,
                sandbox_versions.SVGLIB,
                sandbox_versions.REPORTLAB,
                sandbox_versions.RLPYCAIRO,
                sandbox_versions.CADQUERY_OCP,
            ],
            "dxf": [
                sandbox_versions.OCPSVG,
                sandbox_versions.BUILD123D,
                sandbox_versions.SVGPATHTOOLS,
                sandbox_versions.EZDXF,
                sandbox_versions.CADQUERY_OCP,
            ],
            "brep": [sandbox_versions.CADQUERY_OCP],
            "step": [sandbox_versions.CADQUERY_OCP],
            "stl": [sandbox_versions.CADQUERY_OCP],
            "obj": [sandbox_versions.CADQUERY_OCP],
            "3mf": [sandbox_versions.CADQUERY_OCP, sandbox_versions.CADQUERY],
            "gltf": [sandbox_versions.BUILD123D, sandbox_versions.CADQUERY_OCP],
            "iges": [sandbox_versions.CADQUERY_OCP],
            "threejs": [sandbox_versions.CADQUERY_OCP],
        }

        with pc_logging.Action(f"Render{format_name.upper()}", self.project_name, self.name):

            if filepath and os.path.isdir(filepath):
                self.config_obj.setdefault("render", {})["output_dir"] = filepath

            # The wire format carries OCCT geometry, not build123d objects, so glTF
            # is handed the raw shape too and the wrapper rebuilds the build123d
            # wrapper it needs on the far side.
            obj = await self.get_wrapped(ctx)

            if obj is None:
                pc_logging.error(f"Cannot render '{self.name}': shape is empty")
                return

            formats_to_render = [format_name] if format_name else list(WRAPPER_FORMATS.keys())

            for format in formats_to_render:
                file_extension = RENDER_EXTENSION_MAPPING.get(format) or PART_EXTENSION_MAPPING.get(format, format)
                render_opts, final_filepath = self.render_getopts(format, f".{file_extension}", project, filepath)
                final_filepath = os.path.abspath(final_filepath)
                # Create the output directory for the resolved path. Use
                # 'final_filepath' (the incoming 'filepath' is None when called
                # from Project.render_async, which broke '--create-dirs' with a
                # TypeError) and the 'ctx' passed in, so direct callers without a
                # project still get '--create-dirs'.
                ctx.ensure_dirs_for_file(final_filepath)
                pc_logging.debug(f"Rendering: {self.project_name}:{self.name} for format '{format}'")

                wrapper_path = wrapper.get(f"render_{format}.py")

                request = {"wrapped": obj}

                # Common defaults
                line_weight = kwargs.get("line_weight", 1.0)
                viewport_origin = kwargs.get("viewport_origin")
                viewport_up = kwargs.get("viewport_up")

                # 2D formats
                if format in ["svg", "png", "jpeg"]:
                    request["viewport_origin"] = viewport_origin or (
                        [0, 0, 100] if self.kind == "sketch" else [100, -100, 100]
                    )
                    if self.kind == "sketch":
                        request["viewport_up"] = viewport_up or [0, 1, 0]
                    request["line_weight"] = line_weight

                    # SDF parts are meshes: the wrapped shape is a triangulation
                    # with no edges to project, so ask the render runtime to
                    # normalize it first (see wrapper_render_svg._normalize_mesh).
                    if self.config.get("type") == "sdf":
                        request["normalize_mesh"] = True

                    # Raster formats
                    if format in ["png", "jpeg"]:
                        request["width"] = kwargs.get("width", render_opts.get("width", 512))
                        request["height"] = kwargs.get("height", render_opts.get("height", 512))

                    if format == "jpeg":
                        # JPEG has no alpha channel, so the transparent SVG
                        # background has to be flattened onto some color.
                        request["background"] = kwargs.get("background", render_opts.get("background", "#ffffff"))
                        request["quality"] = kwargs.get("quality", render_opts.get("quality", 85))
                        request["progressive"] = kwargs.get("progressive", render_opts.get("progressive", False))
                        request["optimize"] = kwargs.get("optimize", render_opts.get("optimize", False))
                        # A projection is line art: 4:2:0 chroma subsampling
                        # (what Pillow picks below quality 95) smears color
                        # across the one-pixel-wide edges, so keep full chroma
                        # unless the package asks for something smaller.
                        request["subsampling"] = kwargs.get("subsampling", render_opts.get("subsampling", "4:4:4"))

                # DXF
                elif format == "dxf":
                    request["line_weight"] = line_weight
                    request["viewport_origin"] = viewport_origin or [0, 0, 100]
                    request["viewport_up"] = viewport_up or [0, 1, 0]

                # Mesh formats
                elif format in ["3mf", "obj", "gltf", "stl", "threejs"]:
                    request["tolerance"] = kwargs.get("tolerance", render_opts.get("tolerance", 0.1))
                    request["angularTolerance"] = kwargs.get(
                        "angularTolerance", render_opts.get("angularTolerance", 0.1)
                    )

                    if format == "stl":
                        request["ascii"] = kwargs.get("ascii", render_opts.get("ascii", False))
                    elif format == "gltf":
                        request["binary"] = kwargs.get("binary", render_opts.get("binary", False))

                # CAD formats
                elif format in ["step", "iges"]:
                    request["write_pcurves"] = kwargs.get("write_pcurves", render_opts.get("write_pcurves", True))
                    request["precision_mode"] = kwargs.get("precision_mode", render_opts.get("precision_mode", 0))

                request_serialized = shape_envelope.serialize(request)

                runtime = ctx.get_python_runtime(version="3.11")

                dependencies = WRAPPER_FORMATS[format_name]
                # Installed one at a time, not with asyncio.gather(): the
                # order matters, since build123d overwrites the OCP native
                # module that cadquery-ocp installs (see the note above).
                for dep in dependencies:
                    await runtime.ensure_async(dep)

                # Run wrapper
                with telemetry.start_as_current_span("*Shape.render_async.{runtime.run_async}"):
                    command = [wrapper_path, os.path.abspath(final_filepath)]
                    exitcode, response_serialized, errors = await runtime.run_async(
                        command,
                        request_serialized,
                    )
                    if exitcode != 0 and len(errors) == 0:
                        errors = f"Failed to execute command '{' '.join(command)}' with exit code {exitcode}"

                    if errors:
                        pc_logging.error(errors)
                        raise Exception(errors)

                if errors:
                    pc_logging.error(f"Wrapper {format_name} stderr:\n{errors}")

                response_lines = response_serialized.strip().splitlines()
                if not response_lines:
                    pc_logging.error(f"Empty response from wrapper: {wrapper_path}")
                    return

                cleaned_response = response_lines[-1].strip()

                # Handle response
                result = {}
                try:
                    result = shape_envelope.deserialize(cleaned_response)
                except Exception as e:
                    pc_logging.error(f"Failed to deserialize response: {e}")

                if not result.get("success", False):
                    pc_logging.error(
                        f"Render {format_name.upper()} failed for {self.project_name}:{self.name}: {result.get('exception', 'Unknown error')}"
                    )
                if "exception" in result and result["exception"]:
                    pc_logging.exception(f"Render {format_name.upper()} exception: {result['exception']}")

    def render(
        self,
        ctx: Context,
        format_name: str,
        project: Optional[Project] = None,
        filepath=None,
    ) -> None:
        asyncio.run(self.render_async(ctx, format_name, project, filepath))

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
