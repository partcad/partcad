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
from .process_crash import command_failure
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

            self.include, self.exclude = self.filters(config)

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

        One filter at a time; 'filters()' is what resolves the pair, and what a
        caller wanting to know which layers a sketch reads should ask.
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

    @classmethod
    def filters(cls, config) -> tuple:
        """Which layers the sketch reads and which it skips, as one decision.

        The two are resolved together because they *are* one decision -- which
        layers of the drawing this sketch is -- and CadQuery's importer refuses
        to be given both ('_importDXF': "you may specify either 'include' or
        'exclude' but not both").

        So a reference setting either of them is making that decision afresh,
        and the declaration's *other* filter is not carried into it: a package
        writing 'include: [OUTLINE]' and a reference asking for 'exclude=NOTES'
        means the reference's exclusion. Carrying the declared 'include' in
        beside it would hand the importer both and refuse a reference that said
        one perfectly reasonable thing -- and it would break the rule the
        parameter exists for, which is that whoever refers to a sketch decides
        how it is read.

        Both at once is refused, whichever way they arrive. The schema states
        the rule for the two fields, but it is `pc lint` that applies it rather
        than the loader, and a reference's parameters never go near it at all.
        """
        from_reference = {}
        for name in ("include", "exclude"):
            declared = object_type_parameter(
                config,
                cls.ACCEPTED_OBJECT_TYPE_PARAMETERS,
                name,
                "sketch",
                config.get("name", ""),
            )
            if declared:
                from_reference[name] = as_list(declared)

        if len(from_reference) == 2:
            raise Exception(
                "The sketch '%s' is referred to with both 'include' (%s) and 'exclude' (%s); "
                "only one of them says which layers of the drawing to read"
                % (
                    config.get("name", ""),
                    ",".join(from_reference["include"]),
                    ",".join(from_reference["exclude"]),
                )
            )
        if from_reference:
            # The reference decided it, so the declaration's other filter goes.
            return from_reference.get("include", []), from_reference.get("exclude", [])

        include, exclude = as_list(config.get("include")), as_list(config.get("exclude"))
        if include and exclude:
            raise Exception(
                "The sketch '%s' declares both 'include' (%s) and 'exclude' (%s); "
                "only one of them says which layers of the drawing to read"
                % (config.get("name", ""), ",".join(include), ",".join(exclude))
            )
        return include, exclude

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
                    errors = command_failure(command, exitcode)

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

                # Everything the drawing said - about its own elements and
                # about itself - rides the envelope the wrapper returned, and
                # nothing here has to handle it. That is what keeps this factory
                # free of any knowledge of what a DXF states: it asks for a
                # shape and gets one, and what came with it is carried, cached
                # and reported by machinery that does not know a DXF exists.
                shape = result["shape"]
            except Exception as e:
                pc_logging.exception("Failed to import the DXF file: %s: %s" % (self.path, e))
                shape = None

            self.ctx.stats_sketches_instantiated += 1

            return shape
