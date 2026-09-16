#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.
#

import os
import threading

from . import logging as pc_logging
from . import shape_envelope, telemetry, wrapper
from .part_factory_file import PartFactoryFile


@telemetry.instrument()
class PartFactoryStep(PartFactoryFile):
    PYTHON_SANDBOX_VERSION = "3.11"

    # A STEP file is where a manufacturing tolerance belongs when the file
    # states one: AP242 carries the whole of GD&T, and a part read from a file
    # that tolerances its features is better described by the file than by
    # anything a package could write beside it. So this type is read for it (see
    # 'tolerance_inspect'), and - because plenty of STEP files carry no GD&T at
    # all, and a part read from one of those would otherwise have no way left to
    # say how precisely it has to be made - it accepts a 'tolerance:' field for
    # the declaration to answer with when the file does not.
    #
    # 'kicad' inherits both by inheriting this factory, which is right in both
    # directions: what it builds is a STEP file, so it is read like one, and a
    # board fabricated to a tolerance nothing in the KiCad project states has
    # the same need of a field.
    ACCEPTS_TOLERANCE_FIELD = True
    TOLERANCE_FILE_FORMAT = "step"

    lock = threading.Lock()

    def __init__(self, ctx, source_project, target_project, config, can_create=False):
        with pc_logging.Action("InitSTEP", target_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config, extension=".step", can_create=can_create)
            self._create(config)

            self.runtime = self.ctx.get_python_runtime(self.PYTHON_SANDBOX_VERSION)

    async def instantiate(self, part):
        await super().instantiate(part)
        with pc_logging.Action("STEP", part.project_name, part.name):
            wrapper_path = wrapper.get("step.py")
            request = {"build_parameters": {}}
            with telemetry.start_as_current_span("*PartFactoryStep.instantiate.{shape_envelope.serialize}"):
                request["name"] = "%s:%s" % (part.project_name, part.name)
                request["label"] = part.name
                request_serialized = shape_envelope.serialize(request)

            with telemetry.start_as_current_span("*PartFactoryStep.instantiate.{runtime.run_async}"):
                command = [wrapper_path, os.path.abspath(part.path), os.path.abspath(self.project.config_dir)]
                exitcode, response_serialized, errors = await self.runtime.run_async(
                    command,
                    request_serialized,
                )
                if exitcode != 0 and len(errors) == 0:
                    errors = f"Failed to execute command '{' '.join(command)}' with exit code {exitcode}"

                if errors:
                    pc_logging.error(errors)
                    raise Exception(errors)

            with telemetry.start_as_current_span("*PartFactoryStep.instantiate.{shape_envelope.deserialize}"):
                result = shape_envelope.deserialize(response_serialized)
            if not result["success"]:
                pc_logging.error(result["exception"])
                raise Exception(result["exception"])
            shape = result["shape"]

            self.ctx.stats_parts_instantiated += 1
            return shape
