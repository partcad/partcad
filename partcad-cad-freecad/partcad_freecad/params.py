#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The parameter model behind the import dialog.

An object's ``parameters`` section is already normalized by the time it reaches a
client (see ``partcad.config.Configuration.normalize``): every entry is a dict
with a ``type`` -- ``string``, ``int``, ``float``, ``bool`` or ``array`` -- and
usually a ``default``. This module turns that into a list of :class:`ParamSpec`
the dialog renders one control per, and converts what the user typed back into
the JSON types the service expects.

Keeping the conversion here, rather than in the Qt code, is what makes it
testable without FreeCAD.
"""

import json
from typing import Any, Optional

TYPE_STRING = "string"
TYPE_INT = "int"
TYPE_FLOAT = "float"
TYPE_BOOL = "bool"
TYPE_ARRAY = "array"

# A parameter declared as a bare mapping with no explicit type is a float
# (normalize() applies the same rule), so that is the fallback here too.
DEFAULT_TYPE = TYPE_FLOAT

_TRUE = ("true", "yes", "on", "1")
_FALSE = ("false", "no", "off", "0")


class ParamSpec:
    """One parameter: what to render, and how to read the value back."""

    def __init__(
        self,
        name: str,
        type: str = DEFAULT_TYPE,  # pylint: disable=redefined-builtin
        default: Any = None,
        enum: Optional[list] = None,
        desc: str = "",
        min: Any = None,  # pylint: disable=redefined-builtin
        max: Any = None,  # pylint: disable=redefined-builtin
    ):
        self.name = name
        self.type = type or DEFAULT_TYPE
        self.default = default
        self.enum = list(enum) if enum else None
        self.desc = desc or ""
        self.min = min
        self.max = max

    @property
    def is_enum(self) -> bool:
        return bool(self.enum)

    def coerce(self, value: Any) -> Any:
        """Convert a value from a control into what the service expects.

        Raises ``ValueError`` with a message naming the parameter, which the
        dialog shows next to the offending field.
        """
        try:
            return self._check_bounds(self._coerce(value))
        except (TypeError, ValueError) as e:
            raise ValueError("%s: %s" % (self.name, e)) from e

    def _check_bounds(self, value: Any) -> Any:
        """Reject a number outside a declared ``min``/``max``.

        A spin box clamps an int to the range on its own, but a float is typed
        into a line edit whose validator accepts an out-of-range value as
        "intermediate" -- so without this the bound would hold for one type and
        not the other, and the export would run with a value the dialog showed
        as illegal.
        """
        if self.type not in (TYPE_INT, TYPE_FLOAT):
            return value
        # Compared as floats so a fractional bound on an int parameter is not
        # truncated into a bound that lets the value through.
        number = float(value)
        if self.min is not None and number < float(self.min):
            raise ValueError("%s is below the minimum of %s" % (value, self.min))
        if self.max is not None and number > float(self.max):
            raise ValueError("%s is above the maximum of %s" % (value, self.max))
        return value

    def _coerce(self, value: Any) -> Any:
        if self.type == TYPE_BOOL:
            if isinstance(value, bool):
                return value
            text = str(value).strip().lower()
            if text in _TRUE:
                return True
            if text in _FALSE:
                return False
            raise ValueError("expected a boolean, got '%s'" % value)
        if self.type == TYPE_INT:
            if isinstance(value, bool):
                return int(value)
            if isinstance(value, int):
                return value
            return int(str(value).strip())
        if self.type == TYPE_FLOAT:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
            # A decimal comma is what a user on a European locale types, and
            # FreeCAD's own inputs accept it; PartCAD's floats do not.
            return float(str(value).strip().replace(",", "."))
        if self.type == TYPE_ARRAY:
            if isinstance(value, (list, tuple)):
                return list(value)
            text = str(value).strip()
            if not text:
                return []
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                # Fall back to the shorthand a user is more likely to type.
                return [element.strip() for element in text.split(",") if element.strip()]
            return list(parsed) if isinstance(parsed, (list, tuple)) else [parsed]
        return str(value)

    def format_default(self) -> str:
        """The default rendered for a text control."""
        return format_value(self.type, self.default)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "ParamSpec(%s, %s, default=%r)" % (self.name, self.type, self.default)


def format_value(type_name: str, value: Any) -> str:
    """Render a parameter value as the text a control starts out with."""
    if value is None:
        return "" if type_name != TYPE_FLOAT else "0.0"
    if type_name == TYPE_BOOL:
        return "true" if value else "false"
    if type_name == TYPE_FLOAT:
        number = float(value)
        # Keep floats looking like floats, as the VS Code inspector does: a
        # bare "10" in a float field invites an int-shaped edit.
        return "%.1f" % number if number.is_integer() else repr(number)
    if type_name == TYPE_ARRAY:
        return json.dumps(list(value)) if isinstance(value, (list, tuple)) else str(value)
    return str(value)


def parse_parameters(config: dict) -> list:
    """The parameters of an object's config, in declaration order."""
    parameters = (config or {}).get("parameters") or {}
    specs = []
    for name, param in parameters.items():
        if not isinstance(param, dict):
            # Defensive: an un-normalized short form (``width: 10.0``) would
            # otherwise crash the dialog. Infer the type the way normalize does.
            specs.append(ParamSpec(name, _infer_type(param), param))
            continue
        specs.append(
            ParamSpec(
                name,
                param.get("type") or DEFAULT_TYPE,
                param.get("default"),
                param.get("enum"),
                param.get("desc") or "",
                param.get("min"),
                param.get("max"),
            )
        )
    return specs


def _infer_type(value: Any) -> str:
    if isinstance(value, bool):
        return TYPE_BOOL
    if isinstance(value, float):
        return TYPE_FLOAT
    if isinstance(value, int):
        return TYPE_INT
    if isinstance(value, (list, tuple)):
        return TYPE_ARRAY
    return TYPE_STRING


def collect(specs: list, raw_values: dict) -> dict:
    """Coerce every raw control value; return the parameter dict to send.

    Every parameter is sent, not only the edited ones: the service instantiates
    a parameterized object keyed by the values it is given, and sending the
    defaults explicitly makes that key -- and the resulting STEP -- exactly what
    the dialog showed.
    """
    values = {}
    for spec in specs:
        if spec.name not in raw_values:
            continue
        values[spec.name] = spec.coerce(raw_values[spec.name])
    return values


def instance_suffix(values: dict) -> str:
    """PartCAD's own naming for a parameterized instance (``;w=1,h=2``).

    Used for labels, so an imported object says which variant it is. The format
    matches ``Project.get_object``'s ``result_name``.
    """
    if not values:
        return ""
    return ";" + ",".join("%s=%s" % (name, values[name]) for name in sorted(values))
