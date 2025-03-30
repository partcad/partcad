import base64
import os
import pickle

from partcad import logging as pc_logging, wrapper
from partcad.exception import PartFactoryError
from partcad.part_factory.part_factory import PartFactory
from partcad.part_factory.registry import register_factory
from partcad.part_types import ExtraOps, PartTypes
from partcad.utils import resolve_resource_path

EXTRUDE = PartTypes.EXTRUDE
# EXTRUDE = ExtraOps.EXTRUDE


@register_factory(EXTRUDE.type)
class PartFactoryExtrude(PartFactory):
    PYTHON_SANDBOX_VERSION = "3.11"

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitExtrude", target_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config)

            self.depth = float(config["depth"])

            self.source_sketch_name = config.get("sketch", "sketch")
            if "project" in config:
                self.source_project_name = config["project"] or source_project.name
            elif ":" in self.source_sketch_name:
                self.source_project_name, self.source_sketch_name = resolve_resource_path(
                    source_project.name,
                    self.source_sketch_name,
                )
            else:
                self.source_project_name = source_project.name

            self.source_sketch_spec = f"{self.source_project_name}:{self.source_sketch_name}"

            self._create(config)
            self.part.hash.add_string(str(self.depth))
            self.part.cache_dependencies_broken = True  # TODO(PC-313)

            self.runtime = None  # Lazy init

    async def instantiate(self, part):
        with pc_logging.Action("Extrude", part.project_name, part.name):
            shape = await self._process_extrude_subprocess()
            self.ctx.stats_parts_instantiated += 1
            return shape

    async def _process_extrude_subprocess(self):
        if self.runtime is None:
            pc_logging.debug("Initializing subprocess runtime...")
            self.runtime = self.ctx.get_python_runtime(self.PYTHON_SANDBOX_VERSION)
            if self.runtime is None:
                raise RuntimeError("Failed to initialize runtime for subprocess execution.")
            pc_logging.debug(f"Subprocess runtime initialized: {self.runtime}")

        sketch = self.ctx.get_sketch(self.source_sketch_spec)
        sketch_shape = await sketch.get_wrapped(self.ctx)

        wrapper_path = wrapper.get(f"{EXTRUDE.type}.py")
        request = {
            "depth": self.depth,
            "sketch_shape": sketch_shape,
        }
        request_serialized = base64.b64encode(pickle.dumps(request)).decode()

        try:
            response_serialized, errors = await self.runtime.run_async(
                [
                    wrapper_path,
                    "-",
                    os.path.abspath(self.project.config_dir),
                ],
                request_serialized,
            )
            if errors:
                for line in errors.splitlines():
                    if line.strip():
                        pc_logging.error(line.strip())

            result = pickle.loads(base64.b64decode(response_serialized))
            if not result.get("success"):
                pc_logging.error(result.get("exception", "Unknown error"))
                raise PartFactoryError(result.get("exception", "Unknown error"))

            return result["shape"]
        except Exception as e:
            pc_logging.error(f"Subprocess execution failed: {e}")
            raise
