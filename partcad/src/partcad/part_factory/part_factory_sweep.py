import base64
import os
import pickle

from partcad import logging as pc_logging, wrapper
from partcad.part_factory.part_factory import PartFactory
from partcad.part_factory.registry import register_factory
from partcad.part_types import PartTypes
from partcad.utils import resolve_resource_path


SWEEP = PartTypes.SWEEP

@register_factory(SWEEP.type)
class PartFactorySweep(PartFactory):
    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitSweep", target_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config)

            if "axis" in config:
                self.axis = config["axis"]
                self.accumulate = True
            else:
                self.axis = config["axisCoords"]
                self.accumulate = False

            self.ratio = config.get("ratio", None)

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

            sweep_config = {}
            if "axis" in config:
                sweep_config["axis"] = self.axis
            if "axisCoords" in config:
                sweep_config["axisCoords"] = self.axis
            if "ratio" in config:
                sweep_config["ratio"] = self.ratio
            self.part.hash.add_dict(sweep_config)

            # TODO(clairbee): add dependency tracking for Sweep (PC-313)
            self.part.cache_dependencies_broken = True

            self.runtime = None  # Lazy init

    async def instantiate(self, part):
        with pc_logging.Action("Sweep", part.project_name, part.name):
            try:
                sketch = self.ctx.get_sketch(self.source_sketch_spec)
                sketch_shape = await sketch.get_wrapped(self.ctx)

                if self.runtime is None:
                    self.runtime = self.ctx.get_python_runtime("3.11")

                wrapper_path = wrapper.get(f"{SWEEP.type}.py")
                request = {
                    "axis": self.axis,
                    "accumulate": self.accumulate,
                    "ratio": self.ratio,
                    "sketch_shape": sketch_shape,
                }
                request_serialized = base64.b64encode(pickle.dumps(request)).decode()

                response_serialized, errors = await self.runtime.run_async(
                    [wrapper_path, "-", "-"],
                    request_serialized,
                )

                if errors:
                    for line in errors.splitlines():
                        part.error(line.strip())

                result = pickle.loads(base64.b64decode(response_serialized))

                if not result.get("success", False):
                    raise Exception(result.get("exception", "Unknown error"))

                self.ctx.stats_parts_instantiated += 1
                part.components = result.get("components", [])
                return result["shape"]

            except Exception as e:
                pc_logging.exception(f"Failed to create a swept part: {e}")
                return None
