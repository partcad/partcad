#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""One reading of a boolean that arrived as text.

A boolean option reaches PartCAD as a string more often than as a boolean: the
environment can carry nothing else, and the VS Code extension spells several of
its settings as ``"true"``/``"false"`` enums. Every place that turns such a
string into a boolean has to agree, or the same ``PC_*`` variable means one
thing to ``pc`` and the opposite to the daemon it launches.

This module deliberately imports nothing. ``partcad_service_json_rpc.core.session``
is imported by the daemon launcher that every ``pc`` command runs, and the rest
of ``partcad_utils`` costs ~150ms to import (sentry, opentelemetry, psutil),
which that hot path must not pay for a five-line helper.
"""

# Spelled out rather than left to ``bool(str)``, which is true for every
# non-empty string -- "0" and "off" among them. Both sets are lowercase; the
# value is normalized before it is looked up.
_TRUE = frozenset(("1", "true", "yes", "y", "on", "t"))
_FALSE = frozenset(("0", "false", "no", "n", "off", "f", ""))


def to_bool(value, default: bool = False) -> bool:
    """Interpret 'value' as a boolean, however it was written.

    A boolean is itself and a number is false only when it is zero, which is
    what a YAML configuration file produces for ``develIndex: false`` and
    ``develIndex: 0``. A string is matched against the spellings above, ignoring
    case and surrounding space, so the environment can say ``0``, ``no`` or
    ``off`` and be believed.

    Anything else that is not empty is true. That is the rule a flag-like
    variable is expected to follow -- setting it to something means turning it
    on -- and it keeps an unrecognized value on the side it has always been on,
    so this reading only ever changes the answer for a value that was meant to
    be false in the first place.

    'default' is the answer for a value that is absent (``None``), which is not
    the same question as a value that is present and empty: ``PC_OFFLINE=``
    unsets the flag rather than leaving it at its default.
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in _FALSE:
        return False
    if text in _TRUE:
        return True
    return True
