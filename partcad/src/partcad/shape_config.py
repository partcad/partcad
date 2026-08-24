#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-01-26
#
# Licensed under Apache License, Version 2.0.
#

import random
import string

from partcad.shape_config_store import ShapeConfigStore
from . import logging as pc_logging


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


class ShapeConfiguration:
    is_manufacturable: bool = False

    # The object-type parameters the type that produces this shape accepts,
    # mapped to their defaults (see 'PartFactory.ACCEPTED_OBJECT_TYPE_PARAMETERS',
    # which is what a part factory stamps here as the part is created). Empty
    # for every shape whose type contributes none - which today is every shape
    # that is not a part.
    object_type_parameters: dict = {}

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

            if value:
                if "parameters" not in self.config:
                    self.config["parameters"] = {}
                self.config["parameters"][property] = {
                    "type": "string",
                    "enum": [value],
                    "default": value,
                }
            else:
                kind = getattr(self, "kind", "object").capitalize()
                pc_logging.warning(f"{kind} '{self.name}' has no '{property}'")

            return value

        if (
            "parameters" not in self.config
            or property not in self.config["parameters"]
            or "default" not in self.config["parameters"][property]
        ):
            return None
        return self.config["parameters"][property]["default"]

    def get_object_type_parameter(self, name: str):
        """The value of an object-type parameter, with the type's default applied.

        The counterpart of 'get_mcftt()' for the parameters a type contributes
        rather than the object invents. It reads the same place - the object's
        own 'parameters:' - and differs in what happens when nothing is
        declared: the default comes from the type that produces the shape, not
        from here.

        The default is applied *here*, on the way out, and is deliberately never
        written into 'config["parameters"]'. 'Shape.__init__' hashes that
        dictionary into the shape's cache key, so injecting a default would move
        the key of every homogeneous part that never mentioned a tolerance - a
        mass invalidation of existing cache entries for a value nobody set. Read
        this way, an undeclared tolerance stays out of the hash entirely, while a
        tolerance somebody did declare keys the cache like any other input,
        because it is one.

        The default doubles as the parameter's type witness: a numeric default
        means the parameter is numeric, so a declared value is coerced to a
        number. A value that will not coerce is reported and the default is used
        instead, which is how 'PartConfigManufacturing' treats a manufacturing
        method it does not recognize.

        Reads 'self.config' rather than the resolved final configuration, the
        same as 'get_mcftt()' does, so an alias reports what the alias itself
        declares. That is a pre-existing property of both readers, not something
        decided here.
        """
        accepted = self.object_type_parameters
        if name not in accepted:
            # Not a parameter this type contributes at all.
            return None
        default = accepted[name]
        fallback = None if isinstance(default, _NoDefault) else default

        parameters = self.config.get("parameters") or {}
        declared = parameters.get(name) if isinstance(parameters, dict) else None
        if not isinstance(declared, dict) or "default" not in declared:
            return fallback

        value = declared["default"]
        if isinstance(default, float):
            try:
                return float(value)
            except (TypeError, ValueError):
                kind = getattr(self, "kind", "object").capitalize()
                pc_logging.error(f"{kind} '{self.name}' has a non-numeric '{name}': {value!r}")
                return fallback
        return value
