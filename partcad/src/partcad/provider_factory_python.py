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
from ocp_serialize import register as register_ocp_helper

from .user_config import user_config
from .provider_factory_file import ProviderFactoryFile
from .runtime_python import PythonRuntime

from . import wrapper
from . import logging as pc_logging
from . import telemetry


@telemetry.instrument()
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
            python_version = "3.11"
        if python_version == "3.12" or python_version == "3.10":
            pc_logging.debug("Downgrading Python version to 3.11 to minimize compatibility issues")
            python_version = "3.11"

        self.runtime = self.ctx.get_python_runtime(python_version)
        self.session = self.runtime.get_session(source_project.name)

    def info(self, provider):
        info: dict[str, object] = provider.shape_info(self.ctx)
        info.update(
            {
                "sandbox_version": self.runtime.version,
                "sandbox_path": self.runtime.path,
            }
        )
        return info

    async def prepare_script(self, provider) -> bool:
        """
        Finish initialization of PythonRuntime
        which was too expensive to do in the constructor
        """

        # Install dependencies of this package
        await self.runtime.prepare_for_package(self.project, session=self.session)
        await self.runtime.prepare_for_shape(self.config, session=self.session)

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
                pc_logging.error("Failed to prepare %s of %s" % (script_name, provider.name))
                return None

            # Get the path to the wrapper script
            # which needs to be executed
            wrapper_path = wrapper.get("provider.py")

            # Build the request
            request["partcad_version"] = sys.modules["partcad"].__version__
            request["verbose"] = pc_logging.getLevel() <= pc_logging.DEBUG
            request["api"] = script_name
            request["user"] = user_config.pii_config.to_dict()
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
            register_ocp_helper()
            picklestring = pickle.dumps(request)
            request_serialized = base64.b64encode(picklestring).decode()

            # TODO-199: Use a requirements.txt or pyproject.toml for version specifications
            # TODO-200: Create a version resolution mechanism that can handle dependency conflicts
            # TODO-201: Implement a version update strategy for security patches
            await self.runtime.ensure_async(
                "ocp-tessellate==3.0.9",
                session=self.session,
            )
            await self.runtime.ensure_async(
                "nlopt==2.9.1",
                session=self.session,
            )
            await self.runtime.ensure_async(
                "cadquery==2.5.2",
                session=self.session,
            )
            await self.runtime.ensure_async(
                "numpy==2.2.1",
                session=self.session,
            )
            await self.runtime.ensure_async(
                "typing_extensions==4.12.2",
                session=self.session,
            )
            await self.runtime.ensure_async(
                "cadquery-ocp==7.7.2",
                session=self.session,
            )
            cwd = self.project.config_dir
            if self.cwd is not None:
                cwd = os.path.join(self.project.config_dir, self.cwd)
            response_serialized, errors = await self.runtime.run_async(
                [
                    wrapper_path,
                    os.path.abspath(self.path),
                    os.path.abspath(cwd),
                ],
                request_serialized,
                session=self.session,
            )
            if len(errors) > 0:
                error_lines = errors.split("\n")
                for error_line in error_lines:
                    provider.error("%s: %s" % (provider.name, error_line))

            try:
                response = base64.b64decode(response_serialized)
                register_ocp_helper()
                result = pickle.loads(response)
            except Exception as e:
                provider.error("Exception while deserializing %s: %s" % (provider.name, e))
                return None

            if "exception" in result:
                provider.error("%s: %s" % (provider.name, result["exception"]))
                return None

            self.ctx.stats_provider_queries += 1

            return result
