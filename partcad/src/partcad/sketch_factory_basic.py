#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-04-20
#
# Licensed under Apache License, Version 2.0.
#

from .sketch_factory import SketchFactory
from . import logging as pc_logging
from . import wrapper
from . import shape_envelope
from . import sandbox_versions
from . import telemetry


# TODO(clairbee): distinguish between inner and outer wires?
#                 see Face::_make_from_wires in build123d/topology.py
@telemetry.instrument()
class SketchFactoryBasic(SketchFactory):
    def __init__(self, ctx, source_project, target_project, config):
        super().__init__(
            ctx,
            source_project,
            target_project,
            config,
        )

        # The shape parameters that define this sketch (circle/square/rectangle
        # outlines and inner cut-outs). They are forwarded verbatim to the
        # wrapper, which turns them into an OCCT face, and folded into the cache
        # hash here.
        self.basic_config = {}
        for key in ("circle", "square", "rectangle", "inner"):
            if key in config:
                self.basic_config[key] = config[key]

        self._create(config)
        self.sketch.hash.add_dict(self.basic_config)

    async def instantiate(self, sketch):
        with pc_logging.Action("Basic", sketch.project_name, sketch.name):
            try:
                # Building the face (OCCT wires + BRepBuilderAPI_MakeFace) runs
                # in a sandbox, so the core process never touches a live OCP
                # object; only the shape parameters and the resulting BREP
                # envelope cross the boundary.
                runtime = self.ctx.get_python_runtime(version=sandbox_versions.DEFAULT_PYTHON_VERSION)
                await runtime.ensure_async(sandbox_versions.CADQUERY_OCP)

                wrapper_path = wrapper.get("sketch_basic.py")
                request = {
                    "config": self.basic_config,
                    "name": "%s:%s" % (sketch.project_name, sketch.name),
                    "label": sketch.name,
                }
                request_serialized = shape_envelope.serialize(request)
                exitcode, response_serialized, errors = await runtime.run_async(
                    [wrapper_path, "sketch_basic"], request_serialized
                )
                if exitcode != 0 and not errors:
                    errors = "%s: %s: basic sketch failed with exit code %s" % (
                        sketch.project_name,
                        sketch.name,
                        exitcode,
                    )
                if errors:
                    pc_logging.error(errors)
                    raise Exception(errors)

                result = shape_envelope.deserialize(response_serialized)
                if not result["success"]:
                    sketch.error("%s: %s" % (sketch.name, result["exception"]))
                    return None

                self.ctx.stats_sketches_instantiated += 1
                return result["shape"]
            except Exception as e:
                pc_logging.exception("Failed to create a basic sketch: %s" % e)
                return None
