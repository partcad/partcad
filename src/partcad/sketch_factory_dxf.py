#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-04-20
#
# Licensed under Apache License, Version 2.0.
#

import os

from . import logging as pc_logging
from . import sandbox_versions, shape_envelope, telemetry, wrapper
from .shape_config import as_list, object_type_parameter
from .sketch_factory_python import SketchFactoryPython


@telemetry.instrument()
class SketchFactoryDxf(SketchFactoryPython):
    tolerance = 0.000001
    include = []
    exclude = []

    # Which layers of the drawing are read is an object-type parameter (see
    # 'SketchFactory'), not merely a field of the declaration, and that is the
    # whole point: a parameter can be set by whoever *refers* to the sketch.
    # One DXF holding an outline and its bend lines is then one sketch, read as
    # many ways as there are references to it -
    # 'bends;include=BEND_UP,BEND_DOWN' - instead of one declaration per
    # combination of layers somebody might want.
    #
    # The defaults are empty lists, which is what "every layer" has always been
    # spelled as here.
    ACCEPTED_OBJECT_TYPE_PARAMETERS = {
        **SketchFactoryPython.ACCEPTED_OBJECT_TYPE_PARAMETERS,
        "include": [],
        "exclude": [],
    }

    def __init__(self, ctx, source_project, target_project, config, can_create=False):
        with pc_logging.Action("InitDXF", target_project.name, config["name"]):
            python_version = source_project.python_version
            if python_version is None:
                # Stay one step ahead of the minimum required Python version
                python_version = sandbox_versions.DEFAULT_PYTHON_VERSION
            # CadQuery has no release for Python 3.10, so a package that asks
            # for it still gets rendered on the oldest interpreter it supports.
            python_version = sandbox_versions.at_least(python_version, sandbox_versions.MIN_PYTHON_VERSION_CADQUERY)
            super().__init__(
                ctx,
                source_project,
                target_project,
                config,
                can_create=can_create,
                python_version=python_version,
                extension=".dxf",
            )

            if "tolerance" in config:
                self.tolerance = float(config["tolerance"])

            self.include = self.layers(config, "include")
            self.exclude = self.layers(config, "exclude")

            self._create(config)

    @classmethod
    def layers(cls, config, name: str) -> list:
        """The layer names one of the two filters was given, as a list.

        Two spellings, and they are the same parameter: the top-level field
        ('include: [BEND_UP]') is how a DXF sketch has always declared this and
        goes on being what a package writes, while the parameter of the same
        name is what a reference can set. The parameter wins where it is
        declared, because whoever refers to a sketch is the outer of the two -
        which is how every other parameter override already behaves.
        """
        declared = object_type_parameter(
            config,
            cls.ACCEPTED_OBJECT_TYPE_PARAMETERS,
            name,
            "sketch",
            config.get("name", ""),
        )
        if declared:
            return declared
        return as_list(config.get(name))

    async def instantiate(self, sketch):
        await super().instantiate(sketch)

        with pc_logging.Action("DXF", sketch.project_name, sketch.name):
            try:
                wrapper_path = wrapper.get("import_dxf.py")

                request = {
                    "path": self.path,
                    "tolerance": self.tolerance,
                    "include": self.include,
                    "exclude": self.exclude,
                }
                request["name"] = "%s:%s" % (sketch.project_name, sketch.name)
                request["label"] = sketch.name
                request_serialized = shape_envelope.serialize(request)

                await self.runtime.ensure_async(sandbox_versions.CADQUERY_OCP)
                await self.runtime.ensure_async(sandbox_versions.CADQUERY)
                command = [
                    wrapper_path,
                    os.path.abspath(self.path),
                    os.path.abspath(self.project.config_dir),
                ]
                exitcode, response_serialized, errors = await self.runtime.run_async(
                    command,
                    request_serialized,
                )
                if exitcode != 0 and len(errors) == 0:
                    errors = f"Failed to execute command '{' '.join(command)}' with exit code {exitcode}"

                if errors:
                    pc_logging.error(errors)
                    raise Exception(errors)

                result = shape_envelope.deserialize(response_serialized)

                if not result["success"]:
                    pc_logging.error(result["exception"])
                    raise Exception(result["exception"])

                if result.get("warning"):
                    # Not an error - the sketch was produced - but not silent
                    # either: it says the drawing did not close into a face,
                    # which is what a drawing of bend lines is meant to do and
                    # what an outline with a gap in it is not.
                    pc_logging.warning("%s: %s" % (self.path, result["warning"]))

                shape = result["shape"]
                # What the drawing said about its own elements, which the
                # geometry cannot carry (see 'Sketch.get_annotations'). Set on
                # the sketch rather than returned, because the return value is
                # the shape; 'Shape.get_wrapped' caches this beside it.
                sketch.annotations = result.get("annotations") or []
            except Exception as e:
                pc_logging.exception("Failed to import the DXF file: %s: %s" % (self.path, e))
                shape = None

            self.ctx.stats_sketches_instantiated += 1

            return shape
