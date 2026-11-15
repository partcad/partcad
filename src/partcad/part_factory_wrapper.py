#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Construct a part from a package-defined 'partType'.

A part whose 'type' carries a package path ('<package>:<name>', after any ':'
short form has been expanded, see factory.instantiate) is not built by a
built-in factory. Instead the referenced partType is looked up in its package
and used to construct the part. Only the default partType kind, 'wrapper', is
implemented: it runs a package-supplied Python script inside the sandbox, which
produces the shape(s) (see wrappers/wrapper_part_type.py).

How a type is resolved, read from a file, keyed and run is shared with
'sketchTypes' and lives in 'partcad.type_wrapper', which says what a
file-backed type (one with an ``extension``) and a type that
``reportsDependencies`` are. What is a part's own is here: ``requireSolid``,
and that the script's shapes are one part.
"""

from . import logging as pc_logging
from . import output, shape_envelope, telemetry, transform
from .part_factory import PartFactory
from .type_wrapper import TYPE_WRAPPER, TypeWrapperFactory


@telemetry.instrument()
class PartFactoryWrapper(TypeWrapperFactory, PartFactory):
    WRAPPERS = (TYPE_WRAPPER, "transform.py")
    TYPE_KIND = "partType"
    OBJECT_KIND = "part"

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitWrapper", target_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config)
            self.init_type(ctx, source_project, target_project, config)
            self._create(config)

    def _type_config(self, project, name):
        return project.get_part_type_config(name)

    def _builtin_type_package(self, ctx, name):
        return output.builtin_part_type(ctx, name)

    def shape_object(self):
        return self.part

    def post_create(self) -> None:
        self.post_create_type()
        super().post_create()

    async def prepare_async(self, part) -> None:
        """Key the part on its type (see 'TypeWrapperFactory.prepare_type_async') and on 'requireSolid'."""
        await super().prepare_async(part)
        await self.prepare_type_async(part)
        # And on what the part is judged by, which is part of what it is: read
        # here as well as in 'instantiate()', because the cache is read before
        # anything is instantiated (see 'Shape.key_on_required_solid').
        required = self._type_flag(output.REQUIRE_SOLID_KEY)
        if required is None:
            # A value that is not a flag. Keyed as no requirement, the part
            # would be read back from whatever was cached before the value was
            # written, and 'instantiate()', which fails the part for it, would
            # never run. So it is not read from the cache at all.
            part.cacheable = False
        elif required:
            part.key_on_required_solid()
        await self._key_on_reported_async(part)

    def type_request(self, shape, type_project) -> dict:
        request = super().type_request(shape, type_project)
        # Validated and moved by the wrapper, while the shape is live (see 'Shape.finish_request').
        request[shape_envelope.KEY_FINISH] = shape.finish_request()
        return request

    async def instantiate(self, part):
        with pc_logging.Action("Wrapper", part.project_name, part.name):
            resolved = self.resolve_type(part)
            if resolved is None:
                return None
            pt_project, pt_config = resolved

            # A type that builds solids and nothing else says so, and then what
            # every part is judged by fails one of its parts instead of being
            # reported beside it (see 'Shape._accepted_as_solid'). Read here,
            # where the declaration is always resolved, and before the shape
            # comes back to be judged.
            try:
                part.solid_required = output.as_flag(pt_config.get(output.REQUIRE_SOLID_KEY), output.REQUIRE_SOLID_KEY)
            except ValueError as e:
                part.error("partType '%s': %s" % (self.type_name, e))
                return None

            response = await self.run_type_async(part, pt_project, pt_config)
            if response is None:
                return None

            shapes = response.get("shapes", [])
            if not shapes:
                part.error("The partType wrapper produced no shape")
                return None
            await self.record_reported_async(part, response)
            self.ctx.stats_parts_instantiated += 1
            # One shape, which is what the wrapper hands back for a part however
            # many the script made: it compounds them itself, while they are
            # live (see 'wrapper_common.finished_shapes').
            if len(shapes) == 1:
                return shapes[0]

            # Several only from a wrapper that could not compound them - an
            # answer holding something no shape is made of, which it leaves
            # for the codec to refuse. Compounding runs in a sandbox
            # (transform.compound), so the core never touches OCP. Keep the
            # contract: report via part.error() and return None instead of
            # raising.
            try:
                return await transform.compound(self.ctx, shapes)
            except Exception as e:
                part.error("Failed to compound wrapper shapes: %s" % e)
                return None
