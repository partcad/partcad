#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-09-07
#
# Licensed under Apache License, Version 2.0.
#

import os
import sys

from . import shape_envelope

from .plugin import Plugin
from .plugin_factory_file import PluginFactoryFile
from .runtime_python import PythonRuntime

from . import wrapper
from . import logging as pc_logging
from . import sandbox_versions
from . import telemetry


@telemetry.instrument()
class PluginFactoryPython(PluginFactoryFile):
    runtime: PythonRuntime
    cwd: str

    def __init__(
        self,
        ctx,
        source_project,
        target_project,
        config,
        can_create=False,
        python_version=None,
        extension=".py",
    ):
        super().__init__(
            ctx,
            source_project,
            target_project,
            config,
            extension=extension,
            can_create=can_create,
        )
        self.cwd = config.get("cwd", None)

        if python_version is None:
            # TODO(clairbee): stick to a default constant or configured version
            python_version = self.project.python_version
        if python_version is None:
            # Stay one step ahead of the minimum required Python version
            python_version = sandbox_versions.DEFAULT_PYTHON_VERSION
        # A provider script may use either CadQuery or build123d, so it takes
        # the stricter of the two floors.
        python_version = sandbox_versions.at_least(python_version, sandbox_versions.MIN_PYTHON_VERSION_CADQUERY)

        self.runtime = self.ctx.get_python_runtime(python_version)
        self.session = self.runtime.get_session(source_project.name)

    def info(self, plugin: Plugin):
        return {
            "sandbox_version": self.runtime.version,
            "sandbox_path": self.runtime.path,
        }

    async def prepare_script(self, plugin) -> bool:
        """
        Finish initialization of PythonRuntime
        which was too expensive to do in the constructor
        """

        # Install dependencies of this package
        await self.runtime.prepare_for_package(self.project, session=self.session)
        await self.runtime.prepare_for_shape(self.config, session=self.session)

        return await super().prepare_script(plugin)

    async def query_script(self, plugin: Plugin, script_name: str, request):
        extra = ""
        if script_name == "avail":
            vendor = request.get("vendor", None)
            sku = request.get("sku", None)
            if not vendor and not sku:
                extra = request["name"]
            else:
                if not vendor:
                    vendor = "None"
                if not sku:
                    sku = "None"
                extra = vendor + ":" + sku
        with pc_logging.Action(
            script_name.capitalize(),
            plugin.project_name,
            plugin.name,
            extra,
        ):
            prepared = await self.prepare_script(plugin)
            if not prepared:
                pc_logging.error("Failed to prepare %s of %s" % (script_name, plugin.name))
                return None

            # Get the path to the wrapper script
            # which needs to be executed
            wrapper_path = wrapper.get("plugin.py")

            # Build the request
            request["partcad_version"] = sys.modules["partcad"].__version__
            request["verbose"] = pc_logging.getLevel() <= pc_logging.DEBUG
            request["api"] = script_name
            request["user"] = self.ctx.user_config.pii_config.to_dict()
            request["parameters"] = {}
            if "parameters" in self.config:
                for param_name, param in self.config["parameters"].items():
                    # Check if this parameter has a value set
                    if "default" in param:
                        request["parameters"][param_name] = param["default"]

            # TODO(clairbee): Add support for patching. Copy files or drop runpy
            # patch = {}
            # if "patch" in self.config:
            #     patch.update(self.config["patch"])
            # request["patch"] = patch

            # Serialize the request
            request_serialized = shape_envelope.serialize(request)

            # TODO-199: Use a requirements.txt or pyproject.toml for version specifications
            # TODO-200: Create a version resolution mechanism that can handle dependency conflicts
            # TODO-201: Implement a version update strategy for security patches
            await self.runtime.ensure_async(
                sandbox_versions.OCP_TESSELLATE,
                session=self.session,
            )
            await self.runtime.ensure_async(
                sandbox_versions.NLOPT,
                session=self.session,
            )
            await self.runtime.ensure_async(
                sandbox_versions.CADQUERY,
                session=self.session,
            )
            await self.runtime.ensure_async(
                sandbox_versions.NUMPY,
                session=self.session,
            )
            await self.runtime.ensure_async(
                sandbox_versions.TYPING_EXTENSIONS,
                session=self.session,
            )
            await self.runtime.ensure_async(
                sandbox_versions.CADQUERY_OCP,
                session=self.session,
            )
            cwd = self.project.config_dir
            if self.cwd is not None:
                cwd = os.path.join(self.project.config_dir, self.cwd)
            command = [
                wrapper_path,
                os.path.abspath(self.path),
                os.path.abspath(cwd),
            ]
            exitcode, response_serialized, errors = await self.runtime.run_async(
                command,
                request_serialized,
                session=self.session,
            )

            if exitcode != 0 and len(errors) == 0:
                errors = "%s: %s: Failed to instantiate" % (self.project.name, plugin.name)
                pc_logging.debug(
                    "%s: %s: Failed to execute command: '%s' with exitcode %s"
                    % (plugin.project_name, plugin.name, " ".join(command), exitcode)
                )

            if len(errors) > 0:
                error_lines = errors.split("\n")
                for error_line in error_lines:
                    plugin.error("%s: %s" % (plugin.name, error_line))

            try:
                result = shape_envelope.deserialize(response_serialized)
            except Exception as e:
                plugin.error("Exception while deserializing %s: %s" % (plugin.name, e))
                return None

            if "exception" in result:
                plugin.error("%s: %s" % (plugin.name, result["exception"]))
                return None

            self.ctx.stats_plugin_queries += 1

            return result
