#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-04
#
# Licensed under Apache License, Version 2.0.
#

from .part_factory import PartFactory
from .sketch import Sketch
from . import logging as pc_logging
from . import wrapper
from . import shape_envelope
from . import sandbox_versions


class PartFactorySweep(PartFactory):
    PYTHON_SANDBOX_VERSION = sandbox_versions.DEFAULT_PYTHON_VERSION

    depth: float
    source_project_name: str
    source_sketch_name: str
    source_sketch_spec: str
    sketch: Sketch

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitSweep", target_project.name, config["name"]):
            super().__init__(
                ctx,
                source_project,
                target_project,
                config,
            )

            if "axis" in config:
                self.axis = config["axis"]
                self.accumulate = True
            else:
                self.axis = config["axisCoords"]
                self.accumulate = False

            self.ratio = config.get("ratio", None)

            self.source_sketch_name = config.get("sketch", "sketch")
            if "project" in config:
                self.source_project_name = config["project"]
                if self.source_project_name == "this" or self.source_project_name == "":
                    self.source_project_name = source_project.name
            else:
                if ":" in self.source_sketch_name:
                    self.source_project_name, self.source_sketch_name = source_project.resolve(
                        self.source_sketch_name,
                    )
                else:
                    self.source_project_name = source_project.name
            self.source_sketch_spec = self.source_project_name + ":" + self.source_sketch_name

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

    async def instantiate(self, part):
        with pc_logging.Action("Sweep", part.project_name, part.name):
            try:
                self.sketch = self.project.ctx.get_sketch(self.source_sketch_spec)
                sketch_env = await self.sketch.get_wrapped(self.ctx)
                if sketch_env is None:
                    part.error("%s: %s: the source sketch produced no shape" % (part.project_name, part.name))
                    return None

                # The sweep (Bezier path plus OCCT BRepOffsetAPI_MakePipe) runs in
                # a sandbox: the source sketch and the swept solid cross as BREP
                # envelopes and the path is plain data, so the core never touches
                # a live OCP object.
                runtime = self.ctx.get_python_runtime(version=self.PYTHON_SANDBOX_VERSION)
                await runtime.ensure_async(sandbox_versions.CADQUERY_OCP)

                wrapper_path = wrapper.get("sweep.py")
                request = {
                    "sketch": sketch_env,
                    "axis": self.axis,
                    "ratio": self.ratio,
                    "accumulate": self.accumulate,
                    "name": "%s:%s" % (part.project_name, part.name),
                    "label": part.name,
                }
                request_serialized = shape_envelope.serialize(request)
                exitcode, response_serialized, errors = await runtime.run_async(
                    [wrapper_path, "sweep"], request_serialized
                )
                if exitcode != 0 and not errors:
                    errors = "%s: %s: sweep failed with exit code %s" % (part.project_name, part.name, exitcode)
                if errors:
                    pc_logging.error(errors)
                    raise Exception(errors)

                result = shape_envelope.deserialize(response_serialized)
                if not result["success"]:
                    part.error("%s: %s" % (part.name, result["exception"]))
                    return None

                self.ctx.stats_parts_instantiated += 1
                return result["shape"]
            except Exception as e:
                part.error("%s: %s: failed to create a swept part: %s" % (part.project_name, part.name, e))
                pc_logging.exception(f"Failed to create a swept part: {e}")
                return None
