#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-09-07
#
# Licensed under Apache License, Version 2.0.
#

import base64
import os
import pickle
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "wrappers"))
from cq_serialize import register as register_cq_helper

from .provider_factory_file import ProviderFactoryFile
from .runtime_python import PythonRuntime

from . import wrapper
from . import logging as pc_logging


class ProviderFactoryPython(ProviderFactoryFile):
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
    ):
        super().__init__(
            ctx,
            source_project,
            target_project,
            config,
            extension=".py",
            can_create=can_create,
        )
        self.cwd = config.get("cwd", None)

        if python_version is None:
            # TODO(clairbee): stick to a default constant or configured version
            python_version = self.project.python_version
        if python_version is None:
            # Stay one step ahead of the minimum required Python version
            python_version = "3.10"
        if python_version == "3.12" or python_version == "3.11":
            pc_logging.debug(
                "Downgrading Python version to 3.10 to minimize compatibility issues"
            )
            python_version = "3.10"

        self.runtime = self.ctx.get_python_runtime(python_version)

    def info(self, provider):
        info: dict[str, object] = provider.shape_info()
        info.update(
            {
                "runtime_version": self.runtime.version,
                "runtime_path": self.runtime.path,
            }
        )
        return info

    async def prepare_script(self, provider) -> bool:
        """
        Finish initialization of PythonRuntime
        which was too expensive to do in the constructor
        """

        # Install dependencies of this package
        await self.runtime.prepare_for_package(self.project)
        await self.runtime.prepare_for_shape(self.config)

        return await super().prepare_script(provider)

    async def query_script(self, provider, script_name, request):
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
            provider.project_name,
            provider.name,
            extra,
        ):
            prepared = await self.prepare_script(provider)
            if not prepared:
                pc_logging.error(
                    "Failed to prepare %s of %s" % (script_name, provider.name)
                )
                return None

            # Get the path to the wrapper script
            # which needs to be executed
            wrapper_path = wrapper.get("provider.py")

            # Build the request
            request["partcad_version"] = sys.modules["partcad"].__version__
            request["verbose"] = pc_logging.getLevel() <= pc_logging.DEBUG
            request["api"] = script_name
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
            register_cq_helper()
            picklestring = pickle.dumps(request)
            request_serialized = base64.b64encode(picklestring).decode()

            await self.runtime.ensure("ocp-tessellate")
            await self.runtime.ensure("numpy==1.24.1")
            await self.runtime.ensure("numpy-quaternion==2023.0.4")
            await self.runtime.ensure("nptyping==1.4.4")
            await self.runtime.ensure("typing_extensions>=4.6.0,<5")
            await self.runtime.ensure("cadquery")
            cwd = self.project.config_dir
            if self.cwd is not None:
                cwd = os.path.join(self.project.config_dir, self.cwd)
            response_serialized, errors = await self.runtime.run(
                [
                    wrapper_path,
                    os.path.abspath(self.path),
                    os.path.abspath(cwd),
                ],
                request_serialized,
            )
            if len(errors) > 0:
                error_lines = errors.split("\n")
                for error_line in error_lines:
                    provider.error("%s: %s" % (provider.name, error_line))

            try:
                response = base64.b64decode(response_serialized)
                register_cq_helper()
                result = pickle.loads(response)
            except Exception as e:
                provider.error(
                    "Exception while deserializing %s: %s" % (provider.name, e)
                )
                return None

            if "exception" in result:
                provider.error("%s: %s" % (provider.name, result["exception"]))
                return None

            self.ctx.stats_provider_queries += 1

            return result
