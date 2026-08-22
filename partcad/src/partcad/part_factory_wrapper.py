#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Construct a part from a package-defined 'partType'.

A part whose 'type' carries a package path ('<package>:<name>', after any ':'
short form has been expanded, see factory.instantiate) is not built by a
built-in factory. Instead the referenced partType is looked up in its package
and used to construct the part. Only the default partType kind, 'wrapper', is
implemented: it runs a package-supplied Python script inside the sandbox, which
produces the shape(s) (see wrappers/wrapper_part_type.py).
"""

import base64
import os

from .part_factory import PartFactory
from .runtime_python import environment_requirements
from .utils import resolve_resource_path
from . import logging as pc_logging
from . import sandbox_versions
from . import shape_envelope
from . import telemetry
from . import transform
from . import wrapper


@telemetry.instrument()
class PartFactoryWrapper(PartFactory):
    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitWrapper", target_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config)

            # 'type' is '<package>:<partType>' by the time we get here.
            self.part_type_ref = config["type"]
            self.part_type_package, self.part_type_name = resolve_resource_path(
                target_project.name, self.part_type_ref
            )

            python_version = self.project.python_version or sandbox_versions.DEFAULT_PYTHON_VERSION
            self.runtime = self.ctx.get_python_runtime(python_version)
            self.session = self.runtime.get_session(source_project.name)

            self._create(config)

    def environment_cache_key(self) -> str | None:
        """The interpreter and the dependency versions this part renders with.

        Deliberately partial: the partType's own 'pythonRequirements' come from
        a package that is only resolved when the part is instantiated, so they
        cannot be read here. The interpreter and the pinned stack can be, and
        they are what a stack upgrade moves, so keying on them is worth having
        even though a partType changing its own requirements does not move the
        key - no more than a partType changing its wrapper script does today.
        """
        return sandbox_versions.environment_cache_key(
            "python", self.runtime.version, environment_requirements(self.project, self.config)
        )

    async def _materialize_wrapper_script(self, pt_project, script_rel):
        """Return the on-disk path of the partType's wrapper script.

        For a local package the script is a file in the package. For a
        plugin-backed package it is fetched from the plugin (like a file-backed
        object) and written into the package's cache directory.
        """
        script_abs = os.path.join(pt_project.config_dir, script_rel)
        if os.path.exists(script_abs):
            return script_abs

        get_data_async = getattr(pt_project, "get_data_async", None)
        if get_data_async is None:
            raise Exception("partType wrapper script not found: %s" % script_abs)

        data = await get_data_async("files/" + script_rel)
        if data is None:
            raise Exception("The repository did not provide the partType wrapper: %s" % script_rel)
        content = base64.b64decode(data) if isinstance(data, str) else bytes(data)

        dirs = os.path.dirname(script_abs)
        if dirs and not os.path.exists(dirs):
            os.makedirs(dirs, exist_ok=True)
        with open(script_abs, "wb") as f:
            f.write(content)
        return script_abs

    async def instantiate(self, part):
        with pc_logging.Action("Wrapper", part.project_name, part.name):
            pt_project = self.ctx.get_project(self.part_type_package)
            if pt_project is None:
                part.error("partType package not found: %s" % self.part_type_package)
                return None

            pt_config = pt_project.get_part_type_config(self.part_type_name)
            if pt_config is None:
                part.error(
                    "partType '%s' not found in '%s'" % (self.part_type_name, self.part_type_package)
                )
                return None

            kind = pt_config.get("kind", "wrapper")
            if kind != "wrapper":
                part.error("Unsupported partType kind '%s' (only 'wrapper' is implemented)" % kind)
                return None

            # The wrapper script: 'path' or, by default, '<name>.py'.
            script_rel = pt_config.get("path", self.part_type_name + ".py")
            try:
                script_abs = await self._materialize_wrapper_script(pt_project, script_rel)
            except Exception as e:
                part.error(str(e))
                return None

            # Prepare the sandbox: the partType's package dependencies, then
            # whatever the partType itself declares, then the geometry stack.
            await self.runtime.prepare_for_package(pt_project, session=self.session)
            await self.runtime.prepare_for_shape(self.config, session=self.session)
            for req in pt_config.get("pythonRequirements", []) or []:
                await self.runtime.ensure_async(req, session=self.session)

            # The geometry stack the sandbox needs so a wrapper can build and
            # serialize shapes. The versions come from sandbox_versions: a
            # session v-env is shared by every part of a package, so a factory
            # that pins its own version corrupts it for all the others. The
            # core itself never imports OCP - shapes cross the boundary as
            # BREP envelopes (see shape_envelope).
            await self.runtime.ensure_async(sandbox_versions.OCP_TESSELLATE, session=self.session)
            await self.runtime.ensure_async(sandbox_versions.TYPING_EXTENSIONS, session=self.session)
            await self.runtime.ensure_async(sandbox_versions.OCPSVG, session=self.session)
            await self.runtime.ensure_async(sandbox_versions.BUILD123D, session=self.session)
            # Last: re-asserts the VTK-enabled OCP that build123d's
            # 'cadquery-ocp-novtk' dependency has just replaced.
            await self.runtime.ensure_async(sandbox_versions.CADQUERY_OCP, session=self.session)

            # The request handed to the wrapper script.
            request = {
                "name": "%s:%s" % (part.project_name, part.name),
                "label": part.name,
                "orig_name": self.orig_name,
                "config": self.config,
                "parameters": {},
            }
            for param_name, param in (self.config.get("parameters") or {}).items():
                request["parameters"][param_name] = param.get("default") if isinstance(param, dict) else param
            request_serialized = shape_envelope.serialize(request)

            meta_wrapper = wrapper.get("part_type.py")
            exitcode, response_serialized, errors = await self.runtime.run_async(
                [meta_wrapper, os.path.abspath(script_abs), os.path.abspath(pt_project.config_dir)],
                request_serialized,
                session=self.session,
            )
            if exitcode != 0 and not errors:
                errors = "%s: %s: partType wrapper failed (exit code %s)" % (
                    part.project_name,
                    part.name,
                    exitcode,
                )
            if errors:
                for line in errors.split("\n"):
                    line = line.strip()
                    if line:
                        pc_logging.debug("%s: %s" % (part.name, line))

            try:
                response = shape_envelope.deserialize(response_serialized)
            except Exception as e:
                part.error("Deserialization error: %s" % e)
                return None

            if not response.get("success"):
                part.error(str(response.get("exception")))
                return None

            shapes = response.get("shapes", [])
            if not shapes:
                part.error("The partType wrapper produced no shape")
                return None
            self.ctx.stats_parts_instantiated += 1
            if len(shapes) == 1:
                return shapes[0]

            # Compounding runs in the sandbox (transform.compound), so the core
            # never touches OCP. Keep the contract: report via part.error() and
            # return None instead of raising.
            try:
                return await transform.compound(self.ctx, shapes)
            except Exception as e:
                part.error("Failed to compound wrapper shapes: %s" % e)
                return None
