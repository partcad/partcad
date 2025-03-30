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
import copy
import os
import pickle
import shutil
import sys
import tempfile
import threading
from typing import Optional

from .cache_hash import CacheHash
from .render import *
from .shape_config import ShapeConfiguration
from .utils import deserialize_response, serialize_request, total_size
from . import exception
from . import logging as pc_logging
from .sync_threads import threadpool_manager
from . import wrapper
from .part_types import Format, PartTypes

if TYPE_CHECKING:
    from partcad.context import Context
    from partcad.project import Project

sys.path.append(os.path.join(os.path.dirname(__file__), "wrappers"))
from ocp_serialize import register as register_ocp_helper


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
            return
            cad_config = {}
            for key in ["parameters", "offset", "scale"]:
                if key in self.config:
                    cad_config[key] = self.config[key]
            self.hash.add_dict(cad_config)

    def get_cache_dependencies_broken(self) -> bool:
        if self.cache_dependencies_ignore:
            return False
        return self.cache_dependencies_broken

    def get_cacheable(self) -> bool:
        return self.cacheable and not self.get_cache_dependencies_broken()

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

                # TODO(clairbee): apply 'offset' and 'scale' during instantiation and
                #                 apply to both 'wrapped' and 'components'
                if "offset" in self.config:
                    import build123d as b3d

                    b3d_solid = b3d.Solid.make_box(1, 1, 1)
                    b3d_solid.wrapped = shape
                    b3d_solid.relocate(b3d.Location(*self.config["offset"]))
                    shape = b3d_solid.wrapped
                if "scale" in self.config:
                    import build123d as b3d

                    b3d_solid = b3d.Solid.make_box(1, 1, 1)
                    b3d_solid.wrapped = shape
                    b3d_solid = b3d_solid.scale(self.config["scale"])
                    shape = b3d_solid.wrapped

                if cache_hash:
                    if is_cacheable:
                        to_cache = {self.kind: shape}
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

    async def get_cadquery(self, ctx=None):
        import cadquery as cq

        if not ctx:
            pc_logging.debug("No context provided to get_cadquery(). Consider using get_part_cadquery() instead.")

        cq_solid = cq.Solid.makeBox(1, 1, 1)
        cq_solid.wrapped = await self.get_wrapped(ctx)
        return cq_solid

    async def get_build123d(self, ctx=None):
        import build123d as b3d

        if not ctx:
            pc_logging.debug("No context provided to get_build123d(). Consider using get_part_build123d() instead.")

        b3d_solid = b3d.Solid.make_box(1, 1, 1)
        b3d_solid.wrapped = await self.get_wrapped(ctx)
        return b3d_solid

    def regenerate(self):
        """Regenerates the shape generated by AI. Config remains the same."""
        if hasattr(self, "generate"):
            # Invalidate the shape
            self._wrapped = None

            # # Truncate the source code file
            # # This will trigger the regeneration of the file on instantiation
            # p = pathlib.Path(self.path)
            # p.unlink(missing_ok=True)
            # p.touch()
            self.do_regenerate(self.path)
        else:
            pc_logging.error("No generation function found")

    def do_change(self, change=None):
        if hasattr(self, "change"):
            self.change(self.path, change)
        else:
            pc_logging.error("No change function found")

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
                        # ocp_vscode.config.status()
                        pc_logging.info('Visualizing in "OCP CAD Viewer"...')
                        # pc_logging.debug(self.shape)
                        ocp_vscode.show(
                            *components,
                            progress=None,
                            # TODO(clairbee): make showing (and the connection
                            # to ocp_vscode) a part of the context, and memorize
                            # which part was displayed last. Keep the camera
                            # if the part has not changed.
                            # reset_camera=ocp_vscode.Camera.KEEP,
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
        if mute:
            self.errors.append(msg)
        else:
            pc_logging.error(msg)

    async def render_svg_somewhere(
        self,
        ctx,
        project=None,
        filepath=None,
        line_weight=None,
        viewport_origin=None,
    ):
        """Renders an SVG file somewhere and ignore the project settings"""
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

        wrapper_path = wrapper.get_render("svg.py")
        request = {
            "wrapped": obj,
            "line_weight": line_weight,
            "viewport_origin": viewport_origin,
        }
        register_ocp_helper()

        # We don't care about customer preferences much here
        # as this is expected to be hermetic.
        # Stick to the version where CadQuery and build123d are known to work.
        runtime = ctx.get_python_runtime(version="3.11")
        await runtime.ensure_async("cadquery-ocp==7.7.2")
        await runtime.ensure_async("ocpsvg==0.3.4")
        await runtime.ensure_async("build123d==0.8.0")
        response_serialized, errors = await runtime.run_async(
            [
                wrapper_path,
                os.path.abspath(filepath),
            ],
            serialize_request(request),
        )
        sys.stderr.write(errors)

        response = base64.b64decode(response_serialized)
        result = pickle.loads(response)
        if not result["success"]:
            pc_logging.error("RenderSVG failed: %s:%s: %s" % (self.project_name, self.name, result["exception"]))
        if "exception" in result and not result["exception"] is None:
            pc_logging.exception("RenderSVG exception: %s" % result["exception"])

        self.svg_path = filepath

    async def _get_svg_path(self, ctx, project):
        async with self.svg_lock:
            if self.svg_path is None:
                await self.render_svg_somewhere(ctx=ctx, project=project)
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

    @staticmethod
    async def _ensure_dependencies(runtime, fmt: Format):
        deps = wrapper.TYPE_DEPENDENCIES.get(fmt, [])
        if not deps:
            pc_logging.warn(f"No dependencies for {fmt.value}")
        await asyncio.gather(*(runtime.ensure_async(dep) for dep in deps))

    def _build_render_request(self, fmt: Format, obj, kwargs: dict, opts: dict) -> dict:
        args = {
            "wrapped": obj,
        }

        if fmt in {PartTypes.SVG, PartTypes.PNG}:
            args.update(
                {
                    "viewport_origin": kwargs.get("viewport_origin", [100, -100, 100]),
                    "line_weight": kwargs.get("line_weight", 1.0),
                }
            )
            if fmt == PartTypes.PNG:
                args.update(
                    {
                        "width": kwargs.get("width", 512),
                        "height": kwargs.get("height", 512),
                    }
                )

        if fmt in {
            PartTypes.STL,
            PartTypes.OBJ,
            PartTypes.THREEJS,
            PartTypes.GLTF,
            PartTypes.THREE_MF,
        }:
            args.update(
                {
                    "tolerance": kwargs.get("tolerance", opts.get("tolerance", 0.1)),
                    "angularTolerance": kwargs.get("angularTolerance", opts.get("angularTolerance", 0.1)),
                    "ascii": kwargs.get("ascii", opts.get("ascii", False)) if fmt == PartTypes.STL else False,
                    "binary": (kwargs.get("binary", opts.get("binary", False)) if fmt == PartTypes.GLTF else False),
                }
            )

        if fmt == PartTypes.STEP:
            args.update(
                {
                    "write_pcurves": kwargs.get("write_pcurves", opts.get("write_pcurves", True)),
                    "precision_mode": kwargs.get("precision_mode", opts.get("precision_mode", 0)),
                }
            )

        return args

    @staticmethod
    def _resolve_format_enum(format_name: str) -> Format:
        for enum_cls in PartTypes.export:
            try:
                return enum_cls(format_name)
            except ValueError:
                continue
        raise ValueError(f"Unsupported format: {format_name}")

    async def render_async(
        self, ctx: Context, format_name: str, project: Optional[Project] = None, filepath=None, **kwargs
    ) -> None:
        """
        Centralized method to render shape via external wrapper.
        Args:
            ctx: Execution context.
            format_name: Render format (e.g., "png", "svg").
            project: Optional project object.
            filepath: Target file path for output.
            kwargs: Additional options (width, height, etc.).
        """
        pc_logging.info(f"[Render] Starting render for '{self.name}' as '{format_name}'")

        format = PartTypes.convert_output.get_format(format_name)
        if not format:
            pc_logging.error(f"Unsupported format: {format_name}")
            return

        if filepath and os.path.isdir(filepath):
            self.config_obj.setdefault("render", {})["output_dir"] = filepath
            pc_logging.info(f"[Render] Using output directory: {filepath}")

        with pc_logging.Action(f"Render{format.type.upper()}", self.project_name, self.name):
            obj = await self.get_build123d(ctx) if format == PartTypes.GLTF else await self.get_wrapped(ctx)

            if obj is None:
                pc_logging.error(f"Cannot render '{self.name}': shape is empty")
                return

            pc_logging.info("[Render] Shape successfully retrieved.")

            if project is not None:
                project.ctx.ensure_dirs_for_file(filepath)

            runtime = ctx.get_python_runtime(version="3.11")
            pc_logging.info("[Render] Ensuring dependencies...")
            await self._ensure_dependencies(runtime, format.type)

            wrapper_path = wrapper.get_render(f"{format.type}.py")
            pc_logging.info(f"[Render] Wrapper path: {wrapper_path}")

            render_opts, final_filepath = self.render_getopts(format.type, f".{format.ext}", project, filepath)
            pc_logging.info(f"[Render] Final output file: {final_filepath}")

            request = self._build_render_request(format, obj, kwargs, render_opts)
            pc_logging.debug(f"[Render] Render request built: {request}")

            register_ocp_helper()
            pc_logging.info("[Render] Running external render subprocess...")

            response_serialized, errors = await runtime.run_async(
                [wrapper_path, os.path.abspath(final_filepath)],
                serialize_request(request),
            )

            sys.stderr.write(errors)
            if errors:
                pc_logging.error(f"Wrapper {format.type.upper()} stderr:\n{errors}")

            response_lines = response_serialized.strip().splitlines()
            if not response_lines:
                pc_logging.error(f"Empty response from wrapper: {wrapper_path}")
                return

            cleaned_response = response_lines[-1].strip()
            pc_logging.debug(f"[Render] Cleaned response: {cleaned_response[:80]}...")

            try:
                result = deserialize_response(cleaned_response)
                pc_logging.info(f"[Render] Deserialization successful: success={result.get('success')}")
            except Exception as e:
                pc_logging.error(f"Failed to deserialize response: {e}")
                return

            if not result.get("success", False):
                pc_logging.error(f"Render {format.type.upper()} failed: {result.get('exception')}")
            if result.get("exception"):
                pc_logging.exception(f"Render exception: {result['exception']}")

    def render(
        self,
        ctx: Context,
        format_name: str,
        project: Optional[Project] = None,
        filepath=None,
    ) -> None:
        asyncio.run(self.render_async(ctx, format_name, project, filepath))
