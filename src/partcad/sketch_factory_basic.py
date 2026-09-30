#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-04-20
#
# Licensed under Apache License, Version 2.0.
#

import copy

from . import config as pc_config
from . import expr
from . import logging as pc_logging
from . import sandbox_versions, shape_envelope, telemetry, wrapper
from .process_crash import describe_exit_code
from .sketch_factory import SketchFactory


# TODO(clairbee): distinguish between inner and outer wires?
#                 see Face::_make_from_wires in build123d/topology.py
@telemetry.instrument()
class SketchFactoryBasic(SketchFactory):
    PYTHON_SANDBOX_VERSION = sandbox_versions.DEFAULT_PYTHON_VERSION

    def __init__(self, ctx, source_project, target_project, config):
        super().__init__(
            ctx,
            source_project,
            target_project,
            config,
        )

        # The shape parameters that define this sketch (circle/square/rectangle/slot
        # outlines and inner cut-outs). They are forwarded verbatim to the
        # wrapper, which turns them into an OCCT face, and folded into the cache
        # hash here.
        #
        # "Verbatim" after the expressions in them have been resolved: a basic
        # sketch has no script to hand its parameters to, so a '%...%' over them
        # is the only way it can be parametric at all - and it is what lets one
        # 'm' sketch serve every port of a parametrized interface instead of one
        # pre-generated sketch per size. The resolved values are what goes into
        # the hash, which is what makes two sizes two cache entries.
        values = pc_config.parameter_values(config.get("parameters"))
        self.basic_config = {}
        for key in ("circle", "square", "rectangle", "slot", "inner"):
            if key in config:
                value = config[key]
                if values:
                    value = expr.resolve(value, values, "%s:%s" % (target_project.name, config["name"]))
                self.basic_config[key] = value

        self._create(config)
        self.sketch.hash.add_dict(self.basic_config)

    def info(self, sketch):
        """The outline this sketch is built from, beside the usual shape info.

        Reported because it is not what the declaration says any more once the
        outline is written as an expression: 'circle: "%size / 2%"' of the
        instance 'm;size=4' is a circle of radius 2, and that is the number
        worth seeing.
        """
        info: dict = super().info(sketch)
        # Deep, because the outline nests ("slot: {length, width}") and this is
        # handed out: a caller that edits it would otherwise be editing the
        # configuration this factory builds from, under a hash that no longer
        # describes it.
        info["outline"] = copy.deepcopy(self.basic_config)
        return info

    async def instantiate(self, sketch):
        with pc_logging.Action("Basic", sketch.project_name, sketch.name):
            try:
                # Building the face (OCCT wires + BRepBuilderAPI_MakeFace) runs
                # in a sandbox, so the core process never touches a live OCP
                # object; only the shape parameters and the resulting BREP
                # envelope cross the boundary.
                runtime = self.ctx.get_python_runtime(version=self.PYTHON_SANDBOX_VERSION)
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
                    errors = "%s: %s: basic sketch failed: %s" % (
                        sketch.project_name,
                        sketch.name,
                        describe_exit_code(exitcode),
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
