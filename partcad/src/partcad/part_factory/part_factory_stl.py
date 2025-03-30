import base64
import os
import pickle

from partcad import logging as pc_logging, wrapper
from partcad.exception import PartFactoryError
from partcad.part_factory.part_factory_file import PartFactoryFile
from partcad.part_factory.registry import register_factory
from partcad.part_types import PartTypes
from partcad.utils import serialize_request


STL = PartTypes.STL

@register_factory(STL.type)
class PartFactoryStl(PartFactoryFile):
    PYTHON_SANDBOX_VERSION = "3.11"

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitSTL", target_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config, extension=f".{STL.ext}")
            self._create(config)
            self.runtime = None  # Lazy initialization

    async def instantiate(self, part):
        await super().instantiate(part)

        with pc_logging.Action("STL", part.project_name, part.name):
            if self.runtime is None:
                self.runtime = self.ctx.get_python_runtime(self.PYTHON_SANDBOX_VERSION)
                if self.runtime is None:
                    raise RuntimeError("Failed to initialize runtime for subprocess execution.")

            wrapper_path = wrapper.get(f"{STL.type}.py")
            request = {"build_parameters": {}}
            request_serialized = serialize_request(request)

            try:
                response_serialized, errors = await self.runtime.run_async(
                    [wrapper_path, os.path.abspath(self.path)],
                    request_serialized,
                )
            except Exception as e:
                pc_logging.error(f"Wrapper execution failed: {e}")
                raise

            if errors:
                for line in errors.splitlines():
                    part.error(line.strip())

            try:
                result = pickle.loads(base64.b64decode(response_serialized))
            except Exception as e:
                pc_logging.error(f"Failed to deserialize STL wrapper response: {e}")
                raise

            if not result.get("success", False):
                raise PartFactoryError(result.get("exception", "Unknown error"))

            self.ctx.stats_parts_instantiated += 1
            part.components = result.get("components", [])
            return result["shape"]
