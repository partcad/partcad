#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Construct a sketch from a package-defined 'sketchType'.

The sketch counterpart of 'PartFactoryWrapper': a sketch whose 'type' is
':<name>' or '<package>:<name>' is built by the 'sketchTypes:' entry it names,
whose script runs in the sandbox and hands back the sketch's faces, wires and
edges (see wrappers/wrapper_part_type.py for the contract, and
docs/source/plugins/sketch_types.rst). Resolving the type, reading a file for
a type with an ``extension``, keying and running the script are the partType's
own, in 'partcad.type_wrapper'; what is a sketch's is what the answer is made
into: one compound of the 2D geometry, with its components.

There is no ``requireSolid`` counterpart. No sketch type of PartCAD's holds its
sketches to being closed or planar -- a DXF of bend lines is open, a sweep path
is a wire -- so a type that could declare it would be the only one judged by
it, and what a consumer needs (an extrusion wants faces) is the consumer's to
say.
"""

from . import logging as pc_logging
from . import output, telemetry
from .sketch_factory import SketchFactory
from .type_wrapper import TYPE_WRAPPER, TypeWrapperFactory


@telemetry.instrument()
class SketchFactoryWrapper(TypeWrapperFactory, SketchFactory):
    WRAPPERS = (TYPE_WRAPPER,)
    TYPE_KIND = "sketchType"
    OBJECT_KIND = "sketch"

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitWrapper", target_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config)
            self.init_type(ctx, source_project, target_project, config)
            self._create(config)

    def _type_config(self, project, name):
        return project.get_sketch_type_config(name)

    def _builtin_type_package(self, ctx, name):
        return output.builtin_sketch_type(ctx, name)

    def shape_object(self):
        return self.sketch

    def post_create(self) -> None:
        self.post_create_type()
        super().post_create()

    async def prepare_async(self, sketch) -> None:
        """Key the sketch on its type (see 'TypeWrapperFactory.prepare_type_async')."""
        await super().prepare_async(sketch)
        await self.prepare_type_async(sketch)
        await self._key_on_reported_async(sketch)

    def info(self, sketch):
        info: dict[str, object] = sketch.shape_info(self.ctx)
        if self.runtime is not None:
            info.update({"sandbox_version": self.runtime.version, "sandbox_path": self.runtime.path})
        elif self.container is not None:
            info.update({"container": self.container["image"]})
        return info

    async def instantiate(self, sketch):
        with pc_logging.Action("Wrapper", sketch.project_name, sketch.name):
            resolved = self.resolve_type(sketch)
            if resolved is None:
                return None
            response = await self.run_type_async(sketch, *resolved)
            if response is None:
                return None

            # The wrapper compounded the script's edges, wires and faces and
            # split out the components, as it does for a build123d sketch (see
            # wrapper_common.combine); the factory forwards the envelope.
            components = response.get("components") or []
            if not _has_component(components) or response.get("shape") is None:
                sketch.error("The sketchType wrapper produced no edge, wire or face")
                return None
            await self.record_reported_async(sketch, response)
            self.ctx.stats_sketches_instantiated += 1
            sketch.components = components
            return response["shape"]


def _has_component(components) -> bool:
    """Whether a tree of components (lists may nest) holds any component at all."""
    return any(_has_component(item) if isinstance(item, list) else item is not None for item in components)
