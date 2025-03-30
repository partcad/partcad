#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-01-01
#
# Licensed under Apache License, Version 2.0.
#

import base64
import os
import pickle

from partcad import logging as pc_logging, wrapper
from partcad.part_factory.part_factory_python import PartFactoryPython
from partcad.part_factory.registry import register_factory
from partcad.part_types import PartTypes
from partcad.utils import serialize_request



BUILD123D = PartTypes.BUILD123D

@register_factory(BUILD123D.type)
class PartFactoryBuild123d(PartFactoryPython):
    def __init__(self, ctx, source_project, target_project, config, can_create=False):
        python_version = source_project.python_version or "3.11"
        if python_version in {"3.10", "3.12"}:
            pc_logging.debug("Switching Python version to 3.11 to avoid compatibility issues with build123d")
            python_version = "3.11"

        with pc_logging.Action(f"Init{BUILD123D.type.capitalize()}", target_project.name, config["name"]):
            super().__init__(
                ctx, source_project, target_project, config,
                can_create=can_create, python_version=python_version
            )
            self._create(config)

    async def instantiate(self, part):
        await super().instantiate(part)

        with pc_logging.Action(BUILD123D.type.capitalize(), part.project_name, part.name):
            if not self._is_valid_script(part.path):
                part.error(f"build123d script is empty or missing: {part.path}")
                return None

            await self.prepare_python()
            await self._prepare_runtime_dependencies()

            wrapper_path = wrapper.get(f"{BUILD123D.type}.py")
            request = self._build_request()
            cwd = os.path.join(self.project.config_dir, self.cwd or "")

            command = [
                wrapper_path,
                os.path.abspath(part.path),
                os.path.abspath(cwd),
            ]
            pc_logging.debug(f"Command: {command}")

            try:
                response_serialized, errors = await self.runtime.run_async(
                    command,
                    serialize_request(request),
                )
            except Exception as e:
                part.error(f"Wrapper execution failed: {e}")
                return None

            self._handle_errors(errors, part)

            try:
                response = pickle.loads(base64.b64decode(response_serialized))
            except Exception as e:
                part.error(f"Failed to deserialize response: {e}")
                return None

            if not response.get("success"):
                part.error(response.get("exception", "Unknown error"))
                return None

            self.ctx.stats_parts_instantiated += 1
            part.components = response.get("components", [])
            return response.get("shape")

    def _is_valid_script(self, path):
        return os.path.exists(path) and os.path.getsize(path) > 0

    async def _prepare_runtime_dependencies(self):
        for dep in wrapper.TYPE_DEPENDENCIES[BUILD123D]:
            await self.runtime.ensure_async(dep, session=self.session)

    def _build_request(self):
        request = {"build_parameters": {}}

        for param_name, param in self.config.get("parameters", {}).items():
            request["build_parameters"][param_name] = param.get("default")

        patch = {}
        if "show" in self.config:
            patch["\\Z"] = f"\nshow({self.config['show']})\n"
        if "showObject" in self.config:
            patch["\\Z"] = f"\nshow_object({self.config['showObject']})\n"
        if "patch" in self.config:
            patch.update(self.config["patch"])

        request["patch"] = patch
        return request

    def _handle_errors(self, errors: str, part):
        if not errors:
            return
        for line in errors.splitlines():
            line = line.strip()
            if line:
                part.error(line)
