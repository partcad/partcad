#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-01-26
#
# Licensed under Apache License, Version 2.0.
#

import asyncio
import math
import os
import random
import string
import typing

from partcad.shape_config_store import ShapeConfigStore

from . import logging as pc_logging
from . import tolerance_inspect


class _NoDefault:
    """Sentinel: an object-type parameter that has no default.

    For such a parameter, absent means absent - 'material' and 'color' either
    were declared or were not, and there is nothing sensible to invent for
    them. A parameter whose default is a real value (a 'tolerance' of 0.0)
    reads back as that value when nothing declared it.
    """

    def __repr__(self) -> str:
        return "NO_DEFAULT"


NO_DEFAULT = _NoDefault()


class _NotRead:
    """Sentinel: a file that has not been read for what it states yet.

    Distinct from None, which is the answer of a file that has been read and
    states nothing.
    """

    def __repr__(self) -> str:
        return "NOT_READ"


_NOT_READ = _NotRead()


def is_a_length(value) -> bool:
    """Whether a number is one a manufacturing tolerance can be stated as.

    Finite, not negative, and not a boolean - which is what the schema says
    ('number', 'minimum: 0') and what nothing enforced while a package was
    loaded. The three ways past it are all reachable from YAML and all pass
    'float()': '.nan' and '.inf' convert, and 'True' is an int in Python and
    converts to 1.0.

    NaN is the one that has to be kept out rather than merely tidied away.
    'ManufacturabilityTest.tolerance_failure()' takes a NaN to mean "the file
    tolerances this part feature by feature" and passes it - so a NaN a
    *declaration* produced would be reported as something no file ever said. Whatever states a
    tolerance goes through here first, and NaN stays
    'tolerance_inspect.reduce()'s alone to produce.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value) and value >= 0.0


def final_config(obj) -> dict:
    """The declaration an object resolves to, defensively.

    'get_final_config()' rather than 'config', so that an alias and an enrich
    answer for what they point at: neither says where a file comes from or what
    software it ships with, and reading their own configuration would find
    nothing and quietly conclude there is nothing to find.

    Module-level and duck-typed because the callers are not all looking at a
    'ShapeConfiguration' - a bill of materials walks whatever an assembly holds
    - and because two copies of this would be two answers to one question.
    """
    get_final_config = getattr(obj, "get_final_config", None)
    if get_final_config is None:
        return obj.config
    try:
        return get_final_config()
    except Exception as e:  # pylint: disable=broad-except
        pc_logging.debug("Failed to resolve the configuration of %s: %s" % (getattr(obj, "name", obj), e))
        return obj.config


def object_type_parameter(config: dict, accepted: dict, name: str, kind: str = "object", object_name: str = ""):
    """The value of one object-type parameter, with the type's default applied.

    'accepted' is what the type that produces the shape contributes, mapped to
    the default each reads back as when nothing declares it (see
    'PartFactory.ACCEPTED_OBJECT_TYPE_PARAMETERS').

    The default is applied *here*, on the way out, and is deliberately never
    written into 'config["parameters"]'. 'Shape.__init__' hashes that dictionary
    into the shape's cache key, so injecting a default would move the key of
    every homogeneous part that never mentioned a tolerance - a mass
    invalidation of existing cache entries for a value nobody set. Read this
    way, an undeclared tolerance stays out of the hash entirely, while a
    tolerance somebody did declare keys the cache like any other input, because
    it is one.

    The default doubles as the parameter's type witness:

    * a numeric default means the parameter is numeric, so a declared value is
      coerced to a number;
    * a list default means the parameter is a list, and a value that arrived as
      text is split on commas - which is how it arrives from a reference, where
      everything after the ';' is one string by the time the name has been read
      ('bends;include=BEND_UP,BEND_DOWN').

    A value that will not coerce is reported and the default is used instead,
    which is how 'PartConfigManufacturing' treats a manufacturing method it does
    not recognize.

    Reads the configuration it is handed rather than the resolved final one, the
    same as 'get_mcftt()' does, so an alias reports what the alias itself
    declares. That is a pre-existing property of that reader, not something
    decided here.
    """
    if name not in accepted:
        # Not a parameter this type contributes at all.
        return None
    default = accepted[name]
    fallback = None if isinstance(default, _NoDefault) else default

    parameters = (config or {}).get("parameters") or {}
    declared = parameters.get(name) if isinstance(parameters, dict) else None
    if not isinstance(declared, dict) or "default" not in declared:
        return fallback

    value = declared["default"]
    if isinstance(default, float):
        # Before 'float()' rather than after: by then 'True' is an ordinary 1.0
        # and nothing can tell it from a number somebody wrote. Said here, of
        # numeric object-type parameters in general, because a boolean is not a
        # number for any of them.
        if isinstance(value, bool):
            pc_logging.error("%s '%s' has a non-numeric '%s': %r" % (kind.capitalize(), object_name, name, value))
            return fallback
        try:
            return float(value)
        except (TypeError, ValueError):
            pc_logging.error("%s '%s' has a non-numeric '%s': %r" % (kind.capitalize(), object_name, name, value))
            return fallback
    if isinstance(default, list):
        return as_list(value)
    return value


def as_list(value) -> list:
    """A list-valued parameter, however it was written.

    A list stays one; text is the spelling a reference has to use, because the
    whole parameter section of a name is text, so it is split on commas. Empty
    entries are dropped rather than kept as empty names: a trailing comma is a
    typo, not a layer called ''.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple)):
        return [item for item in value if item not in (None, "")]
    return [value]


class ShapeConfiguration:
    is_manufacturable: bool = False

    # The object-type parameters the type that produces this shape accepts,
    # mapped to their defaults (see 'PartFactory.ACCEPTED_OBJECT_TYPE_PARAMETERS',
    # which is what a part factory stamps here as the part is created). Empty
    # for every shape whose type contributes none - which today is every shape
    # that is not a part.
    object_type_parameters: dict = {}

    # The manufacturing tolerance this object's declaration stated, as a number,
    # or None if it stated none. Private because nothing may read it directly:
    # what a declaration wrote down is one of three answers to "how precisely is
    # this to be made", and 'get_tolerance()' is the one place that knows which
    # of them applies. Stamped on by the factory that created the object, like
    # the two below (see 'PartFactory._create_part').
    _tolerance: typing.Optional[float] = None

    # Whether the type that produces this shape takes a 'tolerance:' field at
    # all, and which file format's stated tolerance its file is to be read for.
    # Both are False/None for every type that does neither, which today is every
    # type but 'step' and the 'kicad' that inherits it.
    tolerance_field_accepted: bool = False
    tolerance_file_format: typing.Optional[str] = None

    # What the file turned out to say, once it has been read, and the sentinel
    # for "not read yet". A file is read at most once per object: it does not
    # change under a loaded package, and a STEP file large enough to be worth
    # caring about is large enough not to want scanned twice.
    _tolerance_from_file: typing.Any = _NOT_READ

    def __init__(self, config: dict) -> None:
        self.config = config

        if "name" in config:
            self.name = config["name"]
        else:
            name = "part" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
            self.name = name
            self.config["name"] = name

        self.is_manufacturable = bool(config.get("manufacturable", True))

    @staticmethod
    def normalize(name, config):
        # Handle the case of the part being declared in the config
        # but not defined (a one liner like "part_name:").
        # TODO(clairbee): Revisit whether it's a bug or a feature
        #                 that this code allows to load undeclared scripts
        if config is None:
            config = {}

        # Instead of passing the name as a parameter,
        # enrich the configuration object
        # TODO(clairbee): reconsider passing the name as a parameter
        config["name"] = name
        config["orig_name"] = name

        return config

    def get_final_config(self) -> dict:
        """Return the final configuration (once all "alias" and "enrich" directives are resolved)."""
        return self.config

    def get_store_data(self) -> ShapeConfigStore:
        final_config = self.get_final_config()
        return ShapeConfigStore(final_config)

    async def get_mcftt(self, property: str):
        """Get the material, color, finish, texture or tolerance of the object."""

        store_data = self.get_store_data()

        if not store_data.is_purchasable and (
            "parameters" not in self.config or property not in self.config["parameters"]
        ):
            # shape = await self.get_wrapped()
            # TODO(clairbee): derive the property from the model

            if property == "finish":
                # By default, the finish is set to "none"
                value = "none"
            else:
                # By default, the parameter is not set
                value = None

            if value is None:
                kind = getattr(self, "kind", "object").capitalize()
                pc_logging.warning(f"{kind} '{self.name}' has no '{property}'")

            # Answered on the way out and never written into
            # 'config["parameters"]', for the same two reasons
            # 'object_type_parameter()' above gives - and this one had a third.
            #
            # That dictionary is what the factories hand to the wrapper as the
            # model's build parameters, one name per declared parameter. A
            # 'finish' synthesized here is not a parameter of the model, so the
            # next build of that object was rejected outright:
            #
            #     Cannot set value 'finish': not a parameter of the model.
            #
            # Which build that was depended on timing. 'pc test' runs an
            # object's checks concurrently, so the manufacturability check
            # asking for the finish raced the CAD check building the shape, and
            # the write landed first only sometimes. It also moved the shape's
            # cache key ('Shape.__init__' hashes this dictionary), so the answer
            # to "has this already been built" changed underneath an object that
            # nobody had re-declared.
            return value

        if (
            "parameters" not in self.config
            or property not in self.config["parameters"]
            or "default" not in self.config["parameters"][property]
        ):
            return None
        return self.config["parameters"][property]["default"]

    async def get_tolerance(self):
        """How precisely this object has to be made, or None if it cannot say.

        The one reader of the manufacturing tolerance. There are three places
        the answer can come from and they are not interchangeable, so nothing
        outside this reads any of them directly:

        1. The 'tolerance:' field of the declaration, for the types that take
           one. An author who wrote it down meant it, and it outranks the file:
           it is written precisely because the file did not say, and a file that
           later starts saying something else is a change to argue about rather
           than one to silently adopt.
        2. What the file itself states, for the types whose format can state it.
           A STEP file carrying GD&T already says how precisely each feature has
           to be made, in more detail than one number holds - so a file that
           tolerances several features differently answers NaN, which means
           "tolerated, feature by feature" and not "unknown". See
           'tolerance_inspect.reduce()'.
        3. The 'tolerance' object-type parameter, for the homogeneous types that
           accept it, which reads back as its type's default of 0.0 when nothing
           declared one.

        None is reserved for the object that has no way to answer at all: a type
        that takes neither the field nor the parameter, and whose file states
        nothing. It is not the same as 0.0, which is what "nobody said" reads as
        on a type that could have said - and the manufacturability test reports
        the two differently, because one is a declaration to fix and the other a
        part type to think again about.

        Asynchronous because of case 2, which reads a file, and because an
        object whose file is not there yet ('kicad' builds its STEP, a part with
        'fileFrom' downloads it) has to be free to answer without one.
        """
        if self._tolerance is not None:
            return self._tolerance

        stated = await self._get_file_tolerance()
        if stated is not None:
            return stated

        declared = self.get_object_type_parameter("tolerance")
        if declared is not None:
            if not is_a_length(declared):
                # An infinite or negative parameter, which the coercion above
                # has no opinion about: 'tolerance' is the one numeric
                # object-type parameter that is a length, so the rule about what
                # a length may be lives here rather than there.
                kind = getattr(self, "kind", "object").capitalize()
                pc_logging.error(f"{kind} '{self.name}' has a 'tolerance' that is not a length: {declared!r}")
                return 0.0
            return declared

        # A type that takes the field and whose file said nothing has said
        # nothing, which is 0.0 - the same "nobody said" the parameter's default
        # is, reached the other way.
        if self.tolerance_field_accepted:
            return 0.0
        return None

    async def _get_file_tolerance(self):
        """What this object's file states about its tolerance, read once.

        The file is prepared first, where the object has a way to prepare one.
        'Shape.prepare_async()' is "everything that has to happen before this
        shape's cache key means anything", and a 'fileFrom' download is the
        whole of it for a file-backed part: without this, a STEP file fetched
        from a URL would be read before it was there, report that it states
        nothing, and have the answer cached against a hash of a file that had
        never been downloaded. It is idempotent and costs nothing for a file the
        package carries.

        It does not make a 'kicad' part's STEP file appear - that is generated
        while the part is built, not while it is prepared - and it is not meant
        to. What kicad-cli writes carries no GD&T for this to find, so the field
        is that type's answer and the absent file is the right "nothing".
        """
        if self.tolerance_file_format is None:
            return None
        if self._tolerance_from_file is not _NOT_READ:
            return self._tolerance_from_file

        prepare = getattr(self, "prepare_async", None)
        if prepare is not None:
            try:
                await prepare()
            except Exception as e:  # pylint: disable=broad-except
                # Not this reader's to report: a file that cannot be fetched
                # fails the object wherever it is next needed, with the reason.
                # Here it is simply a file that is not there.
                pc_logging.debug("Could not prepare %s to read its tolerance: %s" % (self.name, e))

        path = getattr(self, "path", None)
        value = await asyncio.to_thread(tolerance_inspect.of_file, self.tolerance_file_format, path)
        # Only a file that was there gave an answer worth keeping. A 'kicad'
        # part's STEP file does not exist until the part is built, and
        # remembering the "nothing" read before that would outlive the reason
        # for it.
        if value is not None or (path and os.path.isfile(path)):
            self._tolerance_from_file = value
        return value

    def get_object_type_parameter(self, name: str):
        """The value of an object-type parameter, with the type's default applied.

        The counterpart of 'get_mcftt()' for the parameters a type contributes
        rather than the object invents. It reads the same place - the object's
        own 'parameters:' - and differs in what happens when nothing is
        declared: the default comes from the type that produces the shape, not
        from here.

        The rules are 'object_type_parameter()' above, which is module-level
        because a factory has to read the same answer out of a configuration
        before there is an object to ask it of (see 'SketchFactoryDxf', which
        needs its layer filters while it is still deciding what to build).
        """
        return object_type_parameter(
            self.config,
            self.object_type_parameters,
            name,
            getattr(self, "kind", "object"),
            self.name,
        )
