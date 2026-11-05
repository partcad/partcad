#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Parts that are one primitive solid - a cuboid or a cylinder - given by a few numbers.

The twin of 'SketchFactoryBasic': nothing to read and nothing to run, only the
dimensions in the declaration, so the solid is written out by 'basic_shapes' in
this process rather than built by a CAD kernel in a sandbox.
"""

import copy

from . import basic_shapes
from . import config as pc_config
from . import expr
from . import logging as pc_logging
from . import telemetry
from .part_factory_homogen import PartFactoryHomogen


# Homogeneous: a primitive is one solid, so one 'material:', one colour and one
# tolerance are true of the whole of it.
@telemetry.instrument()
class PartFactoryBasic(PartFactoryHomogen):
    # No wrapper, no sandbox, no cache and no action in the log, for the reasons
    # 'SketchFactoryBasic' gives.
    WRAPPERS = ()
    PYTHON_SANDBOX_VERSION = None
    CODE_VERSIONS = ((basic_shapes.CODE_NAME, basic_shapes.CACHE_VERSION),)

    def __init__(self, ctx, source_project, target_project, config):
        super().__init__(ctx, source_project, target_project, config)

        # The dimensions, with their expressions worked out, as a basic
        # sketch's are: the only way a part with no script can take a
        # parameter is to be written in terms of it ('cuboid: "%side%"'), and
        # the resolved numbers are what is hashed, so two sizes are two keys.
        values = pc_config.parameter_values(config.get("parameters"))
        self.basic_config = {}
        for key in basic_shapes.PART_KEYS:
            if key in config:
                value = config[key]
                if values:
                    value = expr.resolve(value, values, "%s:%s" % (target_project.name, config["name"]))
                self.basic_config[key] = value

        self._create(config)
        self.part.built_in_place = True
        self.part.hash.add_dict(self.basic_config)

    def info(self, part):
        """The primitive this part is, with its dimensions as they were resolved."""
        info: dict = super().info(part)
        info["primitive"] = copy.deepcopy(self.basic_config)
        return info

    async def instantiate(self, part):
        try:
            # Validated, moved and scaled as it is built, as a wrapper would do
            # it (see 'Shape.finish_request'), and said so.
            payload, measurements, claim = basic_shapes.part(self.basic_config, part.finish_request())
        except ValueError as e:
            part.error("%s: %s" % (part.name, e))
            return None
        except Exception as e:
            pc_logging.exception("Failed to create a basic part: %s" % e)
            return None

        self.ctx.stats_parts_instantiated += 1
        name, label = part._shape_metadata()
        return basic_shapes.envelope(payload, measurements, name=name, label=label, claim=claim)
