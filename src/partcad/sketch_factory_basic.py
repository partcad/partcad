#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-04-20
#
# Licensed under Apache License, Version 2.0.
#

import copy

from . import basic_shapes
from . import config as pc_config
from . import expr
from . import logging as pc_logging
from . import telemetry
from .sketch_factory import SketchFactory


# TODO(clairbee): distinguish between inner and outer wires?
#                 see Face::_make_from_wires in build123d/topology.py
@telemetry.instrument()
class SketchFactoryBasic(SketchFactory):
    # Built in this process, by 'basic_shapes', and never in a sandbox: the
    # face is lines and circles on a plane, which needs no CAD kernel to write
    # down. So no wrapper is run and no environment is keyed on - the sketch is
    # the same whatever Python the package asks for - and what is keyed instead
    # is the version of the code that writes the geometry.
    WRAPPERS = ()
    PYTHON_SANDBOX_VERSION = None
    CODE_VERSIONS = ((basic_shapes.CODE_NAME, basic_shapes.CACHE_VERSION),)

    def __init__(self, ctx, source_project, target_project, config):
        super().__init__(
            ctx,
            source_project,
            target_project,
            config,
        )

        # The shape parameters that define this sketch (circle/square/rectangle/slot
        # outlines and inner cut-outs). They are what 'basic_shapes.sketch' builds
        # the face from, and folded into the cache hash here.
        #
        # After the expressions in them have been resolved: a basic sketch has
        # no script to hand its parameters to, so a '%...%' over them is the
        # only way it can be parametric at all - and it is what lets one 'm'
        # sketch serve every port of a parametrized interface instead of one
        # pre-generated sketch per size. The resolved values are what goes into
        # the hash, which is what makes two sizes two cache entries.
        values = pc_config.parameter_values(config.get("parameters"))
        self.basic_config = {}
        for key in basic_shapes.SKETCH_KEYS:
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
                payload, measurements = basic_shapes.sketch(self.basic_config)
            except ValueError as e:
                # What is wrong with the declaration, in its own words.
                sketch.error("%s: %s" % (sketch.name, e))
                return None
            except Exception as e:
                pc_logging.exception("Failed to create a basic sketch: %s" % e)
                return None

            self.ctx.stats_sketches_instantiated += 1
            name, label = sketch._shape_metadata()
            return basic_shapes.envelope(payload, measurements, name=name, label=label)
