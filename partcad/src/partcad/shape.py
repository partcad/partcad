#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.

import contextlib
import build123d as b3d

import asyncio
import base64
import copy
import os
import pickle
import shutil
import sys
import tempfile
import threading

from .render import *
from .plugins import *
from .shape_config import ShapeConfiguration
from .utils import total_size
from . import logging as pc_logging
from . import sync_threads as pc_thread
from . import wrapper

sys.path.append(os.path.join(os.path.dirname(__file__), "wrappers"))
from ocp_serialize import register as register_ocp_helper


class Shape(ShapeConfiguration):
    name: str
    desc: str
    requirements: dict | list | str
    svg_path: str
    svg_url: str
    # shape: None | OCP.TopoDS.TopoDS_Solid

    errors: list[str]

    def __init__(self, config):
        super().__init__(config)
        self.errors = []
        self._lock = threading.Lock()
        self.shape = None
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

    @contextlib.asynccontextmanager
    async def locked(self):
        """Multi-threading lock for coroutines"""
        await pc_thread.run_detached(self._lock.acquire)
        try:
            yield
        finally:
            self._lock.release()

    async def get_components(self):
        if len(self.components) == 0:
            # Maybe it's empty, maybe it's not generated yet
            wrapped = await self.get_wrapped()

            # If it's a compound, we can get the components
            if len(self.components) == 0:
                self.components = [wrapped]

            if self.with_ports is not None:
                ports_list = list(await self.with_ports.get_components())
                if len(ports_list) != 0:
                    self.components.append(ports_list)

        return self.components

    async def get_wrapped(self):
        shape = await self.get_shape()

        # TODO(clairbee): apply 'offset' and 'scale' during instantiation and
        #                 apply to both 'wrapped' and 'components'
        if "offset" in self.config:
            b3d_solid = b3d.Solid.make_box(1, 1, 1)
            b3d_solid.wrapped = shape
            b3d_solid.relocate(b3d.Location(*self.config["offset"]))
            shape = b3d_solid.wrapped
        if "scale" in self.config:
            b3d_solid = b3d.Solid.make_box(1, 1, 1)
            b3d_solid.wrapped = shape
            b3d_solid = b3d_solid.scale(self.config["scale"])
            shape = b3d_solid.wrapped
        return shape

    async def get_cadquery(self):
        import cadquery as cq

        cq_solid = cq.Solid.makeBox(1, 1, 1)
        cq_solid.wrapped = await self.get_wrapped()
        return cq_solid

    async def get_build123d(self) -> b3d.Solid:
        b3d_solid = b3d.Solid.make_box(1, 1, 1)
        b3d_solid.wrapped = await self.get_wrapped()
        return b3d_solid

    def regenerate(self):
        """Regenerates the shape generated by AI. Config remains the same."""
        if hasattr(self, "generate"):
            # Invalidate the shape
            # async with self.locked():
            self.shape = None

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

    async def show_async(self, show_object=None):
        with pc_logging.Action("Show", self.project_name, self.name):
            if show_object is None:
                components = []
                # TODO(clairbee): consider removing this exception handler permanently
                # Comment out the below exception handler for easier troubleshooting in CLI
                try:
                    components = await self.get_components()
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

            if show_object is not None:
                try:
                    shape = await self.get_shape()
                except Exception as e:
                    pc_logging.error(e)
                if shape is not None:
                    show_object(
                        shape,
                        options={},
                    )

    async def test_async(self):
        return await self.get_wrapped()

    def test(self):
        _ = asyncio.run(self.test_async())

    def show(self, show_object=None):
        asyncio.run(self.show_async(show_object))

    def shape_info(self):
        asyncio.run(self.get_wrapped())
        info = {}
        info["Memory"] = "%.02f KB" % ((total_size(self) + 1023.0) / 1024.0)

        if self.with_ports is not None:
            info["Ports"] = self.with_ports.info()

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

        obj = await self.get_wrapped()
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
        register_ocp_helper()
        picklestring = pickle.dumps(request)
        request_serialized = base64.b64encode(picklestring).decode()

        # We don't care about customer preferences much here
        # as this is expected to be hermetic.
        # Stick to the version where CadQuery and build123d are known to work.
        runtime = ctx.get_python_runtime(version="3.10")
        await runtime.ensure_async("cadquery-ocp==7.7.2")
        await runtime.ensure_async("build123d==0.7.0")
        response_serialized, errors = await runtime.run_async(
            [
                wrapper_path,
                os.path.abspath(filepath),
            ],
            request_serialized,
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

    async def render_svg_async(
        self,
        ctx,
        project=None,
        filepath=None,
    ):
        with pc_logging.Action("RenderSVG", self.project_name, self.name):
            _, filepath = self.render_getopts("svg", ".svg", project, filepath)

            # This creates a temporary file, but it allows to reuse the file
            # with other consumers of self._get_svg_path()
            svg_path = await self._get_svg_path(ctx=ctx, project=project)
            if not svg_path is None and svg_path != filepath:
                if os.path.exists(svg_path):
                    shutil.copyfile(svg_path, filepath)
                else:
                    pc_logging.error("SVG file was not created by the wrapper")

    def render_svg(
        self,
        ctx,
        project=None,
        filepath=None,
    ):
        asyncio.run(self.render_svg_async(ctx, project, filepath))

    async def render_png_async(
        self,
        ctx,
        project=None,
        filepath=None,
        width=None,
        height=None,
    ):
        with pc_logging.Action("RenderPNG", self.project_name, self.name):
            if not plugins.export_png.is_supported():
                pc_logging.error("Export to PNG is not supported")
                return

            png_opts, filepath = self.render_getopts("png", ".png", project, filepath)

            if width is None:
                if "width" in png_opts and not png_opts["width"] is None:
                    width = png_opts["width"]
                else:
                    width = DEFAULT_RENDER_WIDTH
            if height is None:
                if "height" in png_opts and not png_opts["height"] is None:
                    height = png_opts["height"]
                else:
                    height = DEFAULT_RENDER_HEIGHT

            # Render the vector image
            svg_path = await self._get_svg_path(ctx=ctx, project=project)

            def do_render_png():
                nonlocal project, svg_path, width, height, filepath
                plugins.export_png.export(project, svg_path, width, height, filepath)

            await pc_thread.run(do_render_png)

    def render_png(
        self,
        ctx,
        project=None,
        filepath=None,
        width=None,
        height=None,
    ):
        asyncio.run(self.render_png_async(ctx, project, filepath, width, height))

    async def render_step_async(
        self,
        ctx,
        project=None,
        filepath=None,
    ):
        with pc_logging.Action("RenderSTEP", self.project_name, self.name):
            step_opts, filepath = self.render_getopts("step", ".step", project, filepath)

            obj = await self.get_wrapped()

            def do_render_step():
                nonlocal project, filepath, obj
                from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
                from OCP.Interface import Interface_Static

                if not project is None:
                    project.ctx.ensure_dirs_for_file(filepath)

                pcurves = 1
                if "write_pcurves" in step_opts and not step_opts["write_pcurves"]:
                    pcurves = 0
                precision_mode = step_opts.get("precision_mode", 0)

                writer = STEPControl_Writer()
                Interface_Static.SetIVal_s("write.surfacecurve.mode", pcurves)
                Interface_Static.SetIVal_s("write.precision.mode", precision_mode)
                writer.Transfer(obj, STEPControl_AsIs)
                writer.Write(filepath)

            await pc_thread.run(do_render_step)

    def render_step(
        self,
        ctx,
        project=None,
        filepath=None,
    ):
        asyncio.run(self.render_step_async(ctx, project, filepath))

    async def render_stl_async(
        self,
        ctx,
        project=None,
        filepath=None,
        tolerance=None,
        angularTolerance=None,
        ascii=None,
    ):
        with pc_logging.Action("RenderSTL", self.project_name, self.name):
            stl_opts, filepath = self.render_getopts("stl", ".stl", project, filepath)

            if tolerance is None:
                if "tolerance" in stl_opts and not stl_opts["tolerance"] is None:
                    tolerance = float(stl_opts["tolerance"])
                else:
                    tolerance = 0.1

            if angularTolerance is None:
                if "angularTolerance" in stl_opts and not stl_opts["angularTolerance"] is None:
                    angularTolerance = float(stl_opts["angularTolerance"])
                else:
                    angularTolerance = 0.1

            if ascii is None:
                if "ascii" in stl_opts and not stl_opts["ascii"] is None:
                    ascii = bool(stl_opts["ascii"])
                else:
                    ascii = False

            obj = await self.get_wrapped()

            def do_render_stl():
                nonlocal obj, project, filepath, tolerance, angularTolerance, ascii
                from OCP.BRepMesh import BRepMesh_IncrementalMesh
                from OCP.StlAPI import StlAPI_Writer

                if not project is None:
                    project.ctx.ensure_dirs_for_file(filepath)

                BRepMesh_IncrementalMesh(
                    obj,
                    theLinDeflection=tolerance,
                    isRelative=True,
                    theAngDeflection=angularTolerance,
                    isInParallel=True,
                )

                writer = StlAPI_Writer()
                writer.ASCIIMode = ascii
                writer.Write(obj, filepath)

            await pc_thread.run(do_render_stl)

    def render_stl(
        self,
        ctx,
        project=None,
        filepath=None,
        tolerance=None,
        angularTolerance=None,
    ):
        asyncio.run(self.render_stl_async(ctx, project, filepath, tolerance, angularTolerance))

    async def render_3mf_async(
        self,
        ctx,
        project=None,
        filepath=None,
        tolerance=None,
        angularTolerance=None,
    ):
        with pc_logging.Action("Render3MF", self.project_name, self.name):
            threemf_opts, filepath = self.render_getopts("3mf", ".3mf", project, filepath)

            if tolerance is None:
                if "tolerance" in threemf_opts and not threemf_opts["tolerance"] is None:
                    tolerance = threemf_opts["tolerance"]
                else:
                    tolerance = 0.1

            if angularTolerance is None:
                if "angularTolerance" in threemf_opts and not threemf_opts["angularTolerance"] is None:
                    angularTolerance = threemf_opts["angularTolerance"]
                else:
                    angularTolerance = 0.1

            obj = await self.get_wrapped()

            if not project is None:
                project.ctx.ensure_dirs_for_file(filepath)

            wrapper_path = wrapper.get("render_3mf.py")
            request = {
                "wrapped": obj,
                "tolerance": tolerance,
                "angularTolerance": angularTolerance,
            }
            register_ocp_helper()
            picklestring = pickle.dumps(request)
            request_serialized = base64.b64encode(picklestring).decode()

            # We don't care about customer preferences much here
            # as this is expected to be hermetic.
            # Stick to the version where CadQuery and build123d are known to work.
            runtime = ctx.get_python_runtime(version="3.10")
            await runtime.ensure_async("cadquery-ocp==7.7.2")
            await runtime.ensure_async("cadquery==2.4.0")
            response_serialized, errors = await runtime.run_async(
                [
                    wrapper_path,
                    os.path.abspath(filepath),
                ],
                request_serialized,
            )
            sys.stderr.write(errors)

            response = base64.b64decode(response_serialized)
            result = pickle.loads(response)

            if not result["success"]:
                pc_logging.error("Render3MF failed: %s: %s" % (self.name, result["exception"]))
            if "exception" in result and not result["exception"] is None:
                pc_logging.exception(result["exception"])

    def render_3mf(
        self,
        ctx,
        project=None,
        filepath=None,
        tolerance=None,
        angularTolerance=None,
    ):
        asyncio.run(self.render_3mf_async(ctx, project, filepath, tolerance, angularTolerance))

    async def render_threejs_async(
        self,
        ctx,
        project=None,
        filepath=None,
        tolerance=None,
        angularTolerance=None,
    ):
        with pc_logging.Action("RenderThreeJS", self.project_name, self.name):
            threejs_opts, filepath = self.render_getopts("threejs", ".json", project, filepath)

            if tolerance is None:
                if "tolerance" in threejs_opts and not threejs_opts["tolerance"] is None:
                    tolerance = threejs_opts["tolerance"]
                else:
                    tolerance = 0.1

            if angularTolerance is None:
                if "angularTolerance" in threejs_opts and not threejs_opts["angularTolerance"] is None:
                    angularTolerance = threejs_opts["angularTolerance"]
                else:
                    angularTolerance = 0.1

            obj = await self.get_wrapped()
            wrapper_path = wrapper.get("render_threejs.py")
            request = {
                "wrapped": obj,
                "tolerance": tolerance,
                "angularTolerance": angularTolerance,
            }
            register_ocp_helper()
            picklestring = pickle.dumps(request)
            request_serialized = base64.b64encode(picklestring).decode()

            # We don't care about customer preferences much here
            # as this is expected to be hermetic.
            # Stick to the version where CadQuery and build123d are known to work.
            runtime = ctx.get_python_runtime(version="3.10")
            await runtime.ensure_async("cadquery-ocp==7.7.2")
            response_serialized, errors = await runtime.run_async(
                [
                    wrapper_path,
                    os.path.abspath(filepath),
                ],
                request_serialized,
            )
            sys.stderr.write(errors)

            response = base64.b64decode(response_serialized)
            result = pickle.loads(response)

            if not result["success"]:
                pc_logging.error("RenderThreeJS failed: %s: %s" % (self.name, result["exception"]))
            if "exception" in result and not result["exception"] is None:
                pc_logging.exception(result["exception"])

    def render_threejs(
        self,
        ctx,
        project=None,
        filepath=None,
        tolerance=None,
        angularTolerance=None,
    ):
        asyncio.run(self.render_threejs_async(ctx, project, filepath, tolerance, angularTolerance))

    async def render_obj_async(
        self,
        ctx,
        project=None,
        filepath=None,
        tolerance=None,
        angularTolerance=None,
    ):
        with pc_logging.Action("RenderOBJ", self.project_name, self.name):
            obj_opts, filepath = self.render_getopts("obj", ".obj", project, filepath)

            if tolerance is None:
                if "tolerance" in obj_opts and not obj_opts["tolerance"] is None:
                    tolerance = obj_opts["tolerance"]
                else:
                    tolerance = 0.1

            if angularTolerance is None:
                if "angularTolerance" in obj_opts and not obj_opts["angularTolerance"] is None:
                    angularTolerance = obj_opts["angularTolerance"]
                else:
                    angularTolerance = 0.1

            obj = await self.get_wrapped()
            wrapper_path = wrapper.get("render_obj.py")
            request = {
                "wrapped": obj,
                "tolerance": tolerance,
                "angularTolerance": angularTolerance,
            }
            register_ocp_helper()
            picklestring = pickle.dumps(request)
            request_serialized = base64.b64encode(picklestring).decode()

            # We don't care about customer preferences much here
            # as this is expected to be hermetic.
            # Stick to the version where CadQuery and build123d are known to work.
            runtime = ctx.get_python_runtime(version="3.10")
            await runtime.ensure_async("cadquery-ocp==7.7.2")
            response_serialized, errors = await runtime.run_async(
                [
                    wrapper_path,
                    os.path.abspath(filepath),
                ],
                request_serialized,
            )
            sys.stderr.write(errors)

            response = base64.b64decode(response_serialized)
            result = pickle.loads(response)

            if not result["success"]:
                pc_logging.error("RenderOBJ failed: %s: %s" % (self.name, result["exception"]))
            if "exception" in result and not result["exception"] is None:
                pc_logging.exception(result["exception"])

    def render_obj(
        self,
        ctx,
        project=None,
        filepath=None,
        tolerance=None,
        angularTolerance=None,
    ):
        asyncio.run(self.render_obj_async(ctx, project, filepath, tolerance, angularTolerance))

    async def render_gltf_async(
        self,
        ctx,
        project=None,
        filepath=None,
        binary=None,
        tolerance=None,
        angularTolerance=None,
    ):
        with pc_logging.Action("RenderGLTF", self.project_name, self.name):
            gltf_opts, filepath = self.render_getopts("gltf", ".json", project, filepath)

            if tolerance is None:
                if "tolerance" in gltf_opts and not gltf_opts["tolerance"] is None:
                    tolerance = gltf_opts["tolerance"]
                else:
                    tolerance = 0.1

            if angularTolerance is None:
                if "angularTolerance" in gltf_opts and not gltf_opts["angularTolerance"] is None:
                    angularTolerance = gltf_opts["angularTolerance"]
                else:
                    angularTolerance = 0.1

            if binary is None:
                if "binary" in gltf_opts and not gltf_opts["binary"] is None:
                    binary = gltf_opts["binary"]
                else:
                    binary = False

            b3d_obj = await self.get_build123d()

            def do_render_gltf():
                nonlocal b3d_obj, project, filepath, tolerance, angularTolerance
                b3d.export_gltf(
                    b3d_obj,
                    filepath,
                    binary=binary,
                    linear_deflection=tolerance,
                    angular_deflection=angularTolerance,
                )

            await pc_thread.run(do_render_gltf)

    def render_gltf(
        self,
        ctx,
        project=None,
        filepath=None,
        tolerance=None,
        angularTolerance=None,
    ):
        asyncio.run(self.render_gltf_async(ctx, project, filepath, tolerance, angularTolerance))

    async def render_txt_async(self, ctx, project=None, filepath=None):
        with pc_logging.Action("RenderTXT", self.project_name, self.name):
            if filepath is None:
                filepath = self.path + "/bom.txt"

            if not project is None:
                project.ctx.ensure_dirs_for_file(filepath)
            file = open(filepath, "w+")
            file.write("BoM:\n")
            await self._render_txt_real(file)
            file.close()

    def render_txt(self, ctx, project=None, filepath=None):
        asyncio.run(self.render_txt_async(ctx, project, filepath))

    async def render_markdown_async(self, ctx, project=None, filepath=None):
        with pc_logging.Action("RenderMD", self.project_name, self.name):
            if filepath is None:
                filepath = self.path + "/README.md"

            bom_file = open(filepath, "w+")
            bom_file.write(
                "# "
                + self.name
                + "\n"
                + "## Bill of Materials\n"
                + "| Part | Count* | Vendor | SKU | Preview |\n"
                + "| -- | -- | -- | -- | -- |\n"
            )
            self._render_markdown_real(bom_file)
            bom_file.write(
                """
(\\*) The `Count` field is the number of SKUs to be ordered.
It already takes into account the number of items per SKU.
            """
            )
            bom_file.close()

    def render_markdown(self, ctx, project=None, filepath=None):
        asyncio.run(self.render_markdown_async(ctx, project, filepath))

    async def get_summary_async(self, project=None):
        if "summary" in self.config and not self.config["summary"] is None:
            return self.config["summary"]
        return None

    def get_summary(self, project=None):
        asyncio.run(self.get_summary_async(project))
