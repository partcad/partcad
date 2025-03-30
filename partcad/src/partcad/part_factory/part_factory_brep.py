import base64
import os
import pickle
import sys

from partcad import logging as pc_logging, wrapper
from partcad.exception import PartFactoryError
from partcad.part_factory.part_factory_file import PartFactoryFile
from partcad.part_factory.registry import register_factory
from partcad.part_types import PartTypes


sys.path.append(os.path.join(os.path.dirname(__file__), "wrappers"))

BREP = PartTypes.BREP

@register_factory(BREP.type)
class PartFactoryBrep(PartFactoryFile):
    PYTHON_SANDBOX_VERSION = "3.11"

    def __init__(self, ctx, source_project, target_project, config, can_create=False):
        with pc_logging.Action(f"Init{BREP.type.upper()}", target_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config, extension=f".{BREP.ext}", can_create=can_create)
            self._create(config)

            self.runtime = None  # Lazy init

    async def instantiate(self, part):
        await super().instantiate(part)

        with pc_logging.Action(BREP.type.upper(), part.project_name, part.name):
            shape = await self._process_brep_subprocess()
            self.ctx.stats_parts_instantiated += 1
            return shape

    async def _process_brep_subprocess(self):
        if self.runtime is None:
            pc_logging.debug("Initializing subprocess runtime...")
            self.runtime = self.ctx.get_python_runtime(self.PYTHON_SANDBOX_VERSION)
            if self.runtime is None:
                raise RuntimeError("Failed to initialize runtime for subprocess execution.")
            pc_logging.debug(f"Subprocess runtime initialized: {self.runtime}")

        wrapper_path = wrapper.get(f"{BREP.type}.py")
        request = {"build_parameters": {}}
        request_serialized = base64.b64encode(pickle.dumps(request)).decode()

        try:
            response_serialized, errors = await self.runtime.run_async(
                [
                    wrapper_path,
                    os.path.abspath(self.path),
                    os.path.abspath(self.project.config_dir),
                ],
                request_serialized,
            )
            if errors:
                sys.stderr.write(errors)

            response = pickle.loads(base64.b64decode(response_serialized))
            if not response.get("success", False):
                pc_logging.error(response["exception"])
                raise PartFactoryError(response["exception"])

            return response["shape"]
        except Exception as e:
            pc_logging.error(f"Subprocess execution failed: {e}")
            raise
