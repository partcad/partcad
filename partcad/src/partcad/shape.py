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
import base64
import os
import sys
import tempfile
import threading
import warnings
from typing import Optional

from .cache_hash import CacheHash
from . import output
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
    "sdf": "py",
    "scad": "scad",
}

SKETCH_EXTENSION_MAPPING = {
    "svg": "svg",
    "dxf": "dxf",
    "cadquery": "py",
    "build123d": "py",
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
        self.cache_dependencies = []
        self.cache_dependencies_broken = False
        self.cache_dependencies_ignore = self.config.get("cache_dependencies_ignore", True)

        # Memory cache
        self._wrapped = None

        # Filesystem cache
        self.hash = CacheHash(f"{self.project_name}:{self.name}", cache=self.cacheable)
        self.hash.set_dependencies(self.cache_dependencies)

        if self.cacheable:
            cad_config = {}
            for key in ["parameters", "offset", "scale"]:
                if key in self.config:
                    cad_config[key] = self.config[key]
            self.hash.add_dict(cad_config)

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
                        cached, to_cache_in_memory = await ctx.cache_shapes.read_async(cache_hash, keys_to_read)
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
        OCP into the core process.
        """
        if shape is None or shape_envelope.is_shape_envelope(shape):
            return shape
        import ocp_serialize

        if name is None and label is None:
            name, label = self._shape_metadata()
        return ocp_serialize.encode_shape(shape, name=name, label=label)

    def _component_to_envelope(self, component):
        """Normalize a component (or nested list of components) into envelopes."""
        if isinstance(component, list):
            return [self._component_to_envelope(item) for item in component]
        return self._to_envelope(component)

    async def get_cache_value(self, ctx, shape):
        """The value stored in the shape cache under 'self.kind'.

        A plain shape is stored as a single {"name", "label", "brep"} object.
        Assembly overrides this to store its nested tree so that the hierarchy -
        names, labels and sub-assemblies - survives caching, which a flat
        compound would lose.

        'shape' is already a BREP envelope (get_wrapped normalizes it), so this
        only restamps the cache's canonical name/label onto it.
        """
        if shape is None:
            return None
        full_name, label = self._shape_metadata()
        return shape_envelope.with_metadata(shape, name=full_name, label=label)

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

    def _output_section(self, ctx, format_name, project=None, options_project=None) -> str:
        """Whether a file type is an 'export:' or a 'render:' one.

        The built-in packages decide it for the formats they implement. For one
        they do not, the package that declares it does: a format is an export
        format if it appears in an 'export:' section and a render format if it
        appears in a 'render:' one.
        """
        section = output.section_of(ctx, format_name)
        if section is not None:
            return section

        for config_obj in (self.config, *(p.config_obj for p in (project, options_project) if p is not None)):
            for candidate in output.SECTIONS:
                if format_name in output.format_names(config_obj.get(candidate)):
                    return candidate
        return output.EXPORT

    def _output_getopts(self, ctx, format_name, section, project=None, options_project=None):
        """Layer every configuration of a file type, lowest priority first.

        The built-in package is the bottom layer, so a package that re-tunes a
        single parameter keeps the built-in implementation for everything else.
        On top of it come the package the options were asked to come from (the
        '--options-package' of 'pc export' / 'pc render'), then the package the
        shape belongs to, then the shape itself.

        Returns the merged configuration and the output directory the sections
        asked for, if any.
        """
        layers = []
        builtin = output.builtin_project(ctx, section)
        if builtin is not None:
            layers.append((builtin.name, builtin.config_obj))
        for source in (options_project, project):
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

    def _output_filepath(self, opts, output_dir, extension, project=None, filepath=None):
        """Where a file of this type goes when the caller did not say.

        'prefix' names the directory the file goes in, relative to the output
        directory or, failing that, to the package. A prefix that carries an
        extension is taken to name the file itself, which is the one way to
        give an object's output a name of its own.
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
            filepath = os.path.join(filepath, self.name + extension)
        return filepath

    def output_getopts(self, ctx, format_name, project=None, filepath=None, options_project=None, output_dir=None):
        """Resolve one output file type: its implementation, options and path.

        This is the whole of what a format's configuration means, in one place:
        which script writes the file, what it is handed, and where the file
        lands. 'pc export' and 'pc render' differ only in which section the
        answer is read from.
        """
        section = self._output_section(ctx, format_name, project, options_project)
        opts, configured_output_dir = self._output_getopts(ctx, format_name, section, project, options_project)
        # An explicitly requested output directory (e.g. 'pc export -O') beats
        # whatever the configuration asked for.
        output_dir = output_dir or configured_output_dir

        if filepath is not None and os.path.isdir(filepath):
            # A directory was passed where a file was expected: it names where
            # the file goes, not the file.
            output_dir, filepath = filepath, None

        impl = output.Implementation(section, format_name, opts)
        default_extension = PART_EXTENSION_MAPPING.get(format_name) or SKETCH_EXTENSION_MAPPING.get(
            format_name, format_name
        )
        extension = "." + impl.extension(default_extension)
        filepath = self._output_filepath(opts, output_dir, extension, project, filepath)

        pc_logging.debug("Rendering: %s" % filepath)
        return impl, filepath

    async def _materialize_output_script(self, ctx, impl):
        """The on-disk path of the script that writes this file type.

        For a local package - which the built-in ones are - that is a file in
        the package. For a plugin-backed package it is fetched from the plugin
        (like a file-backed object) and written into the package's cache
        directory, the same way a partType's wrapper script is.
        """
        if not impl.script:
            raise Exception(
                "No implementation of '%s' is declared: neither %s nor this package provides a 'path'"
                % (impl.format_name, output.BUILTIN_PACKAGES[impl.section])
            )

        package_name = impl.config.get("package") or output.BUILTIN_PACKAGES[impl.section]
        project = ctx.get_project(package_name)
        if project is None:
            raise Exception("The package implementing '%s' is not found: %s" % (impl.format_name, package_name))
        impl.project = project

        # The script is named by the package's own configuration and is about to
        # be executed, so it has to come from inside that package: a 'path' of
        # '../../..' would otherwise both read and, for a plugin-backed package,
        # write outside it.
        config_dir = os.path.abspath(project.config_dir)
        script_abs = os.path.abspath(os.path.join(config_dir, impl.script))
        if os.path.commonpath([config_dir, script_abs]) != config_dir:
            raise Exception("The implementation of '%s' is outside its package: %s" % (impl.format_name, impl.script))
        if os.path.exists(script_abs):
            return script_abs

        get_data_async = getattr(project, "get_data_async", None)
        if get_data_async is None:
            raise Exception("The implementation of '%s' is not found: %s" % (impl.format_name, script_abs))

        data = await get_data_async("files/" + impl.script)
        if data is None:
            raise Exception(
                "The repository did not provide the implementation of '%s': %s" % (impl.format_name, impl.script)
            )
        content = base64.b64decode(data) if isinstance(data, str) else bytes(data)
        dirs = os.path.dirname(script_abs)
        if dirs and not os.path.exists(dirs):
            os.makedirs(dirs, exist_ok=True)
        with open(script_abs, "wb") as f:
            f.write(content)
        return script_abs

    def _output_request(self, obj, impl, kwargs):
        """What the implementation is handed.

        The shape, every parameter the layered configuration ended up with, and
        enough about the shape itself for an implementation to adapt to what it
        was given - which is how the SVG renderer knows to look at a sketch
        head-on without PartCAD having to tell it.
        """
        request = {
            "wrapped": obj,
            "shape_name": self.name,
            "shape_kind": self.kind,
            "shape_type": self.config.get("type"),
            "package_name": self.project_name,
        }
        request.update(impl.parameters)
        # An explicit argument wins over the configuration, but only when it is
        # one: 'render_async(**kwargs)' is called with a fixed set of keyword
        # arguments defaulting to None by several callers.
        request.update({key: value for key, value in kwargs.items() if value is not None})
        return request

    async def _render_one_async(self, ctx, obj, format_name, project, filepath, options_project, output_dir, kwargs):
        """Produce one output file, whatever its type."""
        impl, final_filepath = self.output_getopts(ctx, format_name, project, filepath, options_project, output_dir)
        final_filepath = os.path.abspath(final_filepath)
        # Create the output directory for the resolved path (the incoming
        # 'filepath' is None when called from Project.render_async) using the
        # 'ctx' passed in, so direct callers without a project get
        # '--create-dirs' too.
        ctx.ensure_dirs_for_file(final_filepath)
        pc_logging.debug("Rendering: %s:%s for format '%s'" % (self.project_name, self.name, format_name))

        script = await self._materialize_output_script(ctx, impl)

        request = self._output_request(obj, impl, kwargs)
        request[output.SCRIPT_KEY] = os.path.abspath(script)
        request_serialized = shape_envelope.serialize(request)

        runtime = ctx.get_python_runtime(version=impl.python_version())
        await runtime.prepare_for_package(impl.project)
        # Installed one at a time, not with asyncio.gather(): the order
        # matters, since build123d overwrites the OCP native module that
        # cadquery-ocp installs (see sandbox_versions.GUARD_INVALIDATED_BY).
        for dep in impl.python_requirements:
            await runtime.ensure_async(dep)

        with telemetry.start_as_current_span("*Shape.render_async.{runtime.run_async}"):
            command = [
                wrapper.get("export.py"),
                final_filepath,
                os.path.abspath(impl.project.config_dir),
            ]
            exitcode, response_serialized, errors = await runtime.run_async(command, request_serialized)
            if exitcode != 0 and len(errors) == 0:
                errors = "Failed to execute command '%s' with exit code %s" % (" ".join(command), exitcode)
            if errors:
                pc_logging.error(errors)
                raise Exception(errors)

        response_lines = response_serialized.strip().splitlines()
        if not response_lines:
            self.error("Empty response from the '%s' implementation: %s" % (format_name, script))
            return

        try:
            result = shape_envelope.deserialize(response_lines[-1].strip())
        except Exception as e:
            self.error("Failed to deserialize response: %s" % e)
            return

        if not result.get("success", False):
            self.error(
                "Render %s failed for %s:%s: %s"
                % (format_name.upper(), self.project_name, self.name, result.get("exception", "Unknown error"))
            )
        if result.get("exception"):
            pc_logging.exception("Render %s exception: %s" % (format_name.upper(), result["exception"]))

    async def render_async(
        self,
        ctx: Context,
        format_name: str,
        project: Optional[Project] = None,
        filepath=None,
        options_package: Optional[str] = None,
        output_dir=None,
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
            output_dir: Where the file goes when 'filepath' does not say,
                overriding whatever the configuration asked for.
            kwargs: Export parameters, overriding what the configuration says.
        """
        # A caller that names no package still gets the shape's own. Its
        # 'export:'/'render:' sections are where a package declares its file
        # types, so resolving it here is what makes a package-defined
        # implementation work through this method and not only through
        # 'Project.render_async()', which always passes the package in.
        if project is None:
            project = ctx.get_project(self.project_name)

        options_project = ctx.get_project(options_package) if options_package else None
        if options_package and options_project is None:
            pc_logging.error("The options package is not found: %s" % options_package)
            return

        action = f"Render{format_name.upper()}" if format_name else "Render"
        with pc_logging.Action(action, self.project_name, self.name):
            obj = await self.get_wrapped(ctx)
            if obj is None:
                pc_logging.error(f"Cannot render '{self.name}': shape is empty")
                return

            for fmt in [format_name] if format_name else output.all_formats(ctx):
                await self._render_one_async(ctx, obj, fmt, project, filepath, options_project, output_dir, kwargs)

    def render(
        self,
        ctx: Context,
        format_name: str,
        project: Optional[Project] = None,
        filepath=None,
        options_package: Optional[str] = None,
        output_dir=None,
        **kwargs,
    ) -> None:
        asyncio.run(self.render_async(ctx, format_name, project, filepath, options_package, output_dir, **kwargs))

    async def render_svg_somewhere_async(
        self,
        ctx,
        project=None,
        filepath=None,
        line_weight=None,
        viewport_origin=None,
    ):
        """Renders an SVG file somewhere, ignoring where the project wants it."""
        if filepath is None:
            with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f:
                filepath = f.name

        self.svg_path = None
        await self.render_async(
            ctx,
            "svg",
            project=project,
            filepath=filepath,
            line_weight=line_weight,
            viewport_origin=viewport_origin,
        )
        if os.path.exists(filepath):
            self.svg_path = filepath

    def render_svg_somewhere(
        self,
        ctx,
        project=None,
        filepath=None,
        line_weight=None,
        viewport_origin=None,
    ):
        asyncio.run(self.render_svg_somewhere_async(ctx, project, filepath, line_weight, viewport_origin))

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
