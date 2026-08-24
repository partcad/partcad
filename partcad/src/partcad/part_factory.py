#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.
#

import typing

from . import factory
from .part import Part
from .shape_factory import ShapeFactory
from . import telemetry


@telemetry.instrument()
class PartFactory(ShapeFactory):
    # TODO(clairbee): Make the next line work for part_factory_file only
    path: typing.Optional[str] = None
    part: Part
    name: str
    orig_name: str

    # Object-type parameters: the parameters an object *type* contributes to
    # the parameter list, rather than the author of the part declaring them
    # from nothing. They are told apart from the rest here, in the factory
    # layer, because that is the only layer that knows what type produced the
    # part: the schema accepts any parameter name matching its pattern and has
    # no per-part-type branching at all.
    #
    # Two class-level sets, so the mechanism is not welded to the one parameter
    # that exists today.
    #
    # POLICED_OBJECT_TYPE_PARAMETERS is the registry of names policed at all,
    # and stays a plain set of names: whether a name is policed is a property
    # of the name, the same everywhere. Only a name in here may ever be
    # rejected. Parameters are otherwise arbitrary - a script may call its own
    # whatever it likes - so a name that is not in this registry must stay free
    # on every type, forever.
    #
    # A name, not a shape of declaration: a parameter *named* 'color' is
    # policed, while the 'color:' and 'material:' fields a parameter of any
    # name may carry inside its own definition (see 'shape-parameter' in the
    # schema, and 'features/lint.feature') are a different thing entirely and
    # are never looked at here.
    POLICED_OBJECT_TYPE_PARAMETERS: typing.FrozenSet[str] = frozenset({"material", "color", "tolerance"})

    # ACCEPTED_OBJECT_TYPE_PARAMETERS is what *this* factory accepts of the
    # policed names, mapped to the default each reads back as when nothing
    # declares it. 'NO_DEFAULT' means absent stays absent. Empty here, which
    # makes "does not accept" the default: a type opts in by mixing in a class
    # that widens the mapping (see 'PartFactoryHomogen'). The types that have
    # not opted in are deliberate, not an oversight - whether each of them
    # should accept these has not been decided, and will be settled case by
    # case. Defaulting to "no" is what leaves that decision open; defaulting to
    # "yes" would silently make it.
    #
    # Only what is *accepted* carries defaults, which is why this is a mapping
    # and the registry above is not. A default is what a type promises about a
    # parameter it honours, and a type that rejects a parameter promises
    # nothing about it.
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
        """Reject an object-type parameter this part type does not accept.

        Runs from the constructor rather than from 'post_create()', the base
        class catch-all that would otherwise be the natural hook, because
        '_create()' registers the part in 'target_project.parts' *before* it
        calls 'post_create()'. Raising from there would have the package record
        the object as broken and go on holding a fully registered, buildable
        part under the same name: the rejection would be reported and not
        enforced. Nothing is registered yet at this point, so the failure is
        the same per-object failure an unknown type produces - caught by
        'Project.init_objects()' / 'Project.get_object()' and filed against
        this one object by 'Project.record_broken_object()', which logs it as
        an error and so sets the CLI's error state, while the rest of the
        package loads and builds.
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
                "part",
                config.get("type"),
                config.get("name"),
                name,
            )

    def object_type_parameter_names(self) -> list:
        """The object-type parameter names this part's type contributes.

        Put into the request a script-running wrapper is handed, so the wrapper
        learns them from the type instead of carrying a copy of the list. A
        wrapper that runs a CadQuery/build123d script is otherwise strict about
        build parameters the script does not declare - rightly, since such a
        name is usually a typo - but a part may be obliged to declare an
        object-type parameter its script has no use for ('pc test' requires a
        manufactured part to state a tolerance). Those names, and only those,
        are dropped there when the script does not want them; see
        'wrappers/custom_cqgi.filter_optional_params'.

        Sorted, so the request is stable and two identical parts serialize
        identically.
        """
        return sorted(self.ACCEPTED_OBJECT_TYPE_PARAMETERS)

    def _create_part(self, config: object) -> Part:
        part = Part(self.target_project.name, config)
        # What this part's type contributes, so that reading an object-type
        # parameter off the part applies the type's default without the reader
        # having to know which factory made it (see
        # 'ShapeConfiguration.get_object_type_parameter').
        part.object_type_parameters = self.ACCEPTED_OBJECT_TYPE_PARAMETERS
        part.instantiate = lambda part_self: self.instantiate(part_self)
        part._prepare = lambda shape_self: self.prepare_async(shape_self)
        part.info = lambda: self.info(part)
        part.with_ports = self.with_ports
        return part

    def _create(self, config: object) -> None:
        self.part = self._create_part(config)
        self.target_project.parts[self.name] = self.part

        self.apply_environment_cache_key(self.part)
        self.post_create()

        self.ctx.stats_parts += 1

    def post_create(self) -> None:
        # This is a base class catch-all method
        pass
