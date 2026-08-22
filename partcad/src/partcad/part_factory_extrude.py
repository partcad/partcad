#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-04-20
#
# Licensed under Apache License, Version 2.0.
#

from .part_factory import PartFactory
from .sketch import Sketch
from . import logging as pc_logging
from . import wrapper
from . import shape_envelope
from . import sandbox_versions
from . import telemetry


@telemetry.instrument()
class PartFactoryExtrude(PartFactory):
    PYTHON_SANDBOX_VERSION = sandbox_versions.DEFAULT_PYTHON_VERSION

    depth: float
    source_project_name: str
    source_sketch_name: str
    source_sketch_spec: str
    sketch: Sketch

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("IniExtrude", target_project.name, config["name"]):
            super().__init__(
                ctx,
                source_project,
                target_project,
                config,
            )

            self.depth = float(config["depth"])

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
            self.part.hash.add_string(str(self.depth))
            # TODO(clairbee): add dependency tracking for Extrude (PC-313)
            self.part.cache_dependencies_broken = True

    async def instantiate(self, part):
        with pc_logging.Action("Extrude", part.project_name, part.name):
            try:
                self.sketch = self.ctx.get_sketch(self.source_sketch_spec)
                sketch_env = await self.sketch.get_wrapped(self.ctx)
                if sketch_env is None:
                    part.error("%s: %s: the source sketch produced no shape" % (part.project_name, part.name))
                    return None

                # The extrusion (OCCT BRepPrimAPI) runs in a sandbox: the source
                # sketch and the resulting solid cross as BREP envelopes, so the
                # core process never touches a live OCP object.
                runtime = self.ctx.get_python_runtime(version=self.PYTHON_SANDBOX_VERSION)
                await runtime.ensure_async(sandbox_versions.CADQUERY_OCP)

                wrapper_path = wrapper.get("extrude.py")
                request = {
                    "sketch": sketch_env,
                    "depth": self.depth,
                    "name": "%s:%s" % (part.project_name, part.name),
                    "label": part.name,
                }
                request_serialized = shape_envelope.serialize(request)
                exitcode, response_serialized, errors = await runtime.run_async(
                    [wrapper_path, "extrude"], request_serialized
                )
                if exitcode != 0 and not errors:
                    errors = "%s: %s: extrude failed with exit code %s" % (part.project_name, part.name, exitcode)
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
                part.error("%s: %s: failed to create an extruded part: %s" % (part.project_name, part.name, e))
                pc_logging.exception("Failed to create an extruded part: %s" % e)
                return None
