import base64
import os
import pickle

from partcad import logging as pc_logging, wrapper
from partcad.exception import PartFactoryError
from partcad.part_factory.part_factory_file import PartFactoryFile
from partcad.part_factory.registry import register_factory
from partcad.part_types import PartTypes
from partcad.utils import serialize_request


OBJ = PartTypes.OBJ

@register_factory(OBJ.type)
class PartFactoryObj(PartFactoryFile):
    PYTHON_RUNTIME_VERSION = "3.11"

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitOBJ", target_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config, extension=f".{OBJ.ext}", can_create=False)
            self._create(config)
            self.runtime = None  # Lazy initialization

    async def instantiate(self, part):
        await super().instantiate(part)

        with pc_logging.Action("OBJ", part.project_name, part.name):
            if self.runtime is None:
                pc_logging.debug("Initializing subprocess runtime...")
                self.runtime = self.ctx.get_python_runtime(self.PYTHON_RUNTIME_VERSION)
                if self.runtime is None:
                    raise RuntimeError("Failed to initialize runtime for subprocess execution.")
                pc_logging.debug(f"Subprocess runtime initialized: {self.runtime}")

            wrapper_path = wrapper.get(f"{OBJ.type}.py")
            request = {"build_parameters": {}}

            try:
                response_serialized, errors = await self.runtime.run_async(
                    [
                        wrapper_path,
                        os.path.abspath(self.path),
                        os.path.abspath(self.project.config_dir),
                    ],
                    serialize_request(request),
                )
            except Exception as e:
                pc_logging.error(f"OBJ wrapper execution failed: {e}")
                raise

            if errors:
                for line in errors.splitlines():
                    part.error(line.strip())

            try:
                response = pickle.loads(base64.b64decode(response_serialized))
            except Exception as e:
                raise PartFactoryError(f"Deserialization failed: {e}")

            if not response.get("success", False):
                raise PartFactoryError(response.get("exception", "Unknown error"))

            self.ctx.stats_parts_instantiated += 1
            part.components = response.get("components", [])

            return response["shape"]
