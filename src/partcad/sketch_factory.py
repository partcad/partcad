#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-04-20
#
# Licensed under Apache License, Version 2.0.
#

import typing

from . import factory, telemetry
from .shape_factory import ShapeFactory
from .sketch import Sketch


@telemetry.instrument()
class SketchFactory(ShapeFactory):
    # TODO(clairbee): Make the next line work for part_factory_file only
    path: typing.Optional[str] = None
    sketch: Sketch
    name: str
    orig_name: str

    # Object-type parameters, the same mechanism the part factories have (see
    # 'PartFactory', where the reasoning for the two class attributes is
    # written out in full). A sketch has its own registry because the names are
    # its own: what a *drawing* contributes is which of its layers are read,
    # and neither name means anything on a part.
    #
    # POLICED_OBJECT_TYPE_PARAMETERS is the registry of names policed at all.
    # Only a name in here may ever be rejected; every other parameter name stays
    # the sketch author's own invention, forever.
    POLICED_OBJECT_TYPE_PARAMETERS: typing.FrozenSet[str] = frozenset({"include", "exclude"})

    # ...and what *this* factory accepts of them, mapped to the default each
    # reads back as when nothing declares it. Empty here, so "does not accept"
    # is the default and a type opts in by widening the mapping (see
    # 'SketchFactoryDxf'): a layer is a thing a DXF has, and a sketch built by a
    # script has no layers to filter.
    ACCEPTED_OBJECT_TYPE_PARAMETERS: typing.Dict[str, typing.Any] = {}

    def __init__(
        self,
        ctx,
        source_project,
        target_project,
        config: object,
    ):
        super().__init__(ctx, source_project, config)
        self.target_project = target_project
        self.name = config["name"]
        self.orig_name = config["orig_name"]

        self._validate_object_type_parameters(config)

    def _validate_object_type_parameters(self, config: object) -> None:
        """Reject an object-type parameter this sketch type does not accept.

        Runs from the constructor rather than from 'post_create()', for the
        reason spelled out in 'PartFactory._validate_object_type_parameters':
        '_create()' registers the sketch before 'post_create()' is called, so
        raising from there would report the rejection and go on holding a fully
        registered sketch under the same name. Nothing is registered yet here,
        so the failure is the per-object failure an unknown type produces.
        """
        parameters = config.get("parameters") or {}
        if not isinstance(parameters, dict):
            # Malformed; the schema has its own say about that.
            return
        for name in sorted(parameters):
            if name not in self.POLICED_OBJECT_TYPE_PARAMETERS:
                continue
            if name in self.ACCEPTED_OBJECT_TYPE_PARAMETERS:
                continue
            raise factory.ObjectTypeParameterException(
                "sketch",
                config.get("type"),
                config.get("name"),
                name,
            )

    def _create_sketch(self, config: object) -> Sketch:
        sketch = Sketch(self.target_project.name, config)
        # What this sketch's type contributes, so that reading an object-type
        # parameter off the sketch applies the type's default without the
        # reader having to know which factory made it (see
        # 'ShapeConfiguration.get_object_type_parameter').
        sketch.object_type_parameters = self.ACCEPTED_OBJECT_TYPE_PARAMETERS
        sketch.instantiate = lambda sketch_self: self.instantiate(sketch_self)
        sketch._prepare = lambda shape_self: self.prepare_async(shape_self)
        sketch.info = lambda: self.info(sketch)
        sketch.with_ports = self.with_ports
        return sketch

    def _create(self, config: object) -> None:
        self.sketch = self._create_sketch(config)
        self.target_project.register_object("sketch", self.name, self.sketch)

        self.apply_environment_cache_key(self.sketch)
        self.post_create()

    def post_create(self) -> None:
        # This is a base class catch-all method
        pass
