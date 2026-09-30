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
from . import logging as pc_logging
from . import shape_envelope, telemetry
from .part import Part
from .shape_config import is_a_length
from .shape_factory import ShapeFactory


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

    # Whether a part of this type may carry a 'tolerance:' field of its own, and
    # which format's reader is used to see whether its file states one.
    #
    # A second way for a part to say what the 'tolerance' object-type parameter
    # above says, for the types that cannot say it that way. A 'step' part
    # rejects the object-type parameters because a STEP file may hold many
    # solids and already states what each of them is (see 'PartFactoryHomogen'),
    # and for 'material' and 'color' that is the end of it: the file answers. For
    # 'tolerance' it is not, because plenty of STEP files carry no GD&T at all,
    # and a part read from one of those has no way left to say how precisely it
    # has to be made - which is what 'pc test' demands of anything that is going
    # to be manufactured.
    #
    # So the field. It is a field rather than a parameter because it is not a
    # request made of the type that produces the shape - nothing is built
    # differently for it, and the file is read the same way either way - and
    # because the parameter of that name stays rejected for the reason it always
    # was.
    #
    # The two attributes are separate because they answer separate questions. A
    # type could gain a file format that states a tolerance without gaining a
    # field (the file would always answer), or a field without a format (nothing
    # to read). Today one type sets both.
    ACCEPTS_TOLERANCE_FIELD: bool = False
    TOLERANCE_FILE_FORMAT: typing.Optional[str] = None

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
        self._validate_tolerance_field(config)

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

    def _validate_tolerance_field(self, config: object) -> None:
        """Reject a 'tolerance:' field on a part type that does not accept one.

        The same shape of failure, raised from the same place and for the same
        reason, as '_validate_object_type_parameters()' above: the schema takes
        the field on any part because it has no per-part-type branching to hang
        this on, so the factory layer - the one layer that knows what type is
        being created - is what says no.

        Policed rather than ignored because a part type that neither accepts the
        field nor reads a tolerance out of its file would silently make no use of
        it, and a part its author believed was tolerated would go to a
        manufacturer without a tolerance. A homogeneous type is told to declare
        the parameter instead, which is what it already accepts.
        """
        if not isinstance(config, dict) or "tolerance" not in config:
            return
        if self.ACCEPTS_TOLERANCE_FIELD:
            return
        if config.get("type") in ("alias", "enrich"):
            # A second name for another object, which is the object that is
            # made: what it is made to is the source's business, and such a
            # declaration already ignores everything that says how its source is
            # built (see 'enrich.ENRICH_IGNORED_PROPERTIES', which lists this
            # field and warns about it). Refusing it here would report one
            # mistake twice and contradict that warning while doing it.
            return
        raise factory.ObjectTypeParameterException(
            "part",
            config.get("type"),
            config.get("name"),
            "tolerance",
            noun="field",
        )

    def declared_tolerance(self, config: object) -> typing.Optional[float]:
        """The 'tolerance:' the declaration carried, as a number, or None.

        None means nothing was declared, which is what leaves the file - and
        after it the type's own default - to answer. A value that is not one is
        reported and treated as absent, the way
        'ShapeConfiguration.get_object_type_parameter()' treats a non-numeric
        parameter: the declaration is wrong, not the part.

        What counts as one is what the schema says: a finite number, not
        negative. 'float()' is wider than that in four ways YAML can reach, and
        each of them would declare its way past the manufacturability check:

        * '.nan' is the answer that means "the file tolerances this feature by
          feature", which 'pc test' accepts. NaN is
          'tolerance_inspect.reduce()'s to produce, and nothing else's.
        * '.inf' and '-.inf' are neither zero nor NaN, so they pass as though
          they were a real tolerance.
        * A negative number is the same, and the schema has said 'minimum: 0'
          all along - it is simply not enforced while a package is loaded.
        * 'true' is an int in Python and reads back as one millimetre. YAML
          makes that one easy to write by accident, because 'yes' is 'True'
          rather than the word, and a millimetre is plausible enough to go
          unnoticed while quietly outranking what the file states.

        None of the four is a tolerance anybody can be asked to hold, and
        'shape_config.is_a_length()' is the one statement of that - the
        'tolerance' object-type parameter of the homogeneous types is read
        through it too, so the two ways a part can state one cannot come to
        disagree about what one is.
        """
        if not isinstance(config, dict):
            return None
        value = config.get("tolerance")
        if value is None:
            return None
        if isinstance(value, bool):
            # Tested before 'float()' rather than after, because by then it is
            # an ordinary 1.0 and indistinguishable from a declared one.
            pc_logging.error("Part '%s' has a 'tolerance' that is not a length: %r" % (config.get("name"), value))
            return None
        try:
            tolerance = float(value)
        except (TypeError, ValueError):
            pc_logging.error("Part '%s' has a non-numeric 'tolerance': %r" % (config.get("name"), value))
            return None
        if not is_a_length(tolerance):
            pc_logging.error("Part '%s' has a 'tolerance' that is not a length: %r" % (config.get("name"), value))
            return None
        return tolerance

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

    # Object-type parameters that are also something the shape reports about
    # itself, mapped to the 'properties:' key each becomes.
    #
    # The two sections are not two spellings of one thing: 'parameters:' is what
    # was *asked of* the type that produces the shape, and 'properties:' is what
    # the shape *turned out to be* - which is why a 'step' part, whose file
    # already states a material per solid, does not accept the parameter at all
    # (see 'PartFactoryHomogen'). But for a type that does accept it, the answer
    # to "what did this turn out to be made of" is exactly what was asked for,
    # and nothing else is going to say so: a CadQuery script does not report a
    # material.
    #
    # 'color' is deliberately absent. The parameter is free-form text ("red")
    # and the property is '#RRGGBB', so promoting one would need a conversion,
    # and inventing one here would write a colour nobody stated.
    OBJECT_TYPE_PARAMETER_PROPERTIES = {"material": "material"}

    def record_object_type_properties(self, config: object) -> None:
        """Write what this part was asked to be into what it reports being.

        The one place a *user* declaration becomes a 'properties:' entry, and it
        is instantiation code doing it - which is the rule for that section:
        'properties:' is filled in by whatever built the shape (a URDF reader
        naming a link's material, a STEP reader reading one out of the file),
        never written by hand in a package.

        Only for the parameters this type accepts, so a type that rejects
        'material' cannot acquire one by the back door, and only where nothing
        has been recorded already - a reader that found the real answer in the
        file outranks what the declaration asked for.
        """
        if not isinstance(config, dict):
            return
        parameters = config.get("parameters")
        if not isinstance(parameters, dict):
            return
        for name, key in self.OBJECT_TYPE_PARAMETER_PROPERTIES.items():
            if name not in self.ACCEPTED_OBJECT_TYPE_PARAMETERS:
                continue
            declared = parameters.get(name)
            if not isinstance(declared, dict):
                continue
            value = declared.get("default")
            if not isinstance(value, str) or not value:
                continue
            properties = config.get(shape_envelope.KEY_PROPERTIES)
            if not isinstance(properties, dict):
                properties = {}
                config[shape_envelope.KEY_PROPERTIES] = properties
            properties.setdefault(key, value)

    def _create_part(self, config: object) -> Part:
        self.record_object_type_properties(config)
        part = Part(self.target_project.name, config)
        # What this part's type contributes, so that reading an object-type
        # parameter off the part applies the type's default without the reader
        # having to know which factory made it (see
        # 'ShapeConfiguration.get_object_type_parameter').
        part.object_type_parameters = self.ACCEPTED_OBJECT_TYPE_PARAMETERS
        # ...and the same for the tolerance the declaration may state itself and
        # the file it is read from may state instead (see 'get_tolerance()').
        part.tolerance_field_accepted = self.ACCEPTS_TOLERANCE_FIELD
        part.tolerance_file_format = self.TOLERANCE_FILE_FORMAT
        # Only where the type takes the field. An alias and an enrich may carry
        # it and ignore it (see '_validate_tolerance_field'), and reading it
        # here would be the one place it was not ignored.
        part._tolerance = self.declared_tolerance(config) if self.ACCEPTS_TOLERANCE_FIELD else None
        part.instantiate = lambda part_self: self.instantiate(part_self)
        part._prepare = lambda shape_self: self.prepare_async(shape_self)
        part.info = lambda: self.info(part)
        part.with_ports = self.with_ports
        return part

    def _create(self, config: object) -> None:
        self.part = self._create_part(config)
        self.target_project.register_object("part", self.name, self.part)

        self.apply_environment_cache_key(self.part)
        self.post_create()

    def post_create(self) -> None:
        # This is a base class catch-all method
        pass
