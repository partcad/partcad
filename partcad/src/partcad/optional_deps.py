#
# OpenVMP, 2024
#
# Licensed under Apache License, Version 2.0.
#

import importlib
from types import ModuleType


class OptionalDependencyError(ImportError):
    """Raised when a feature is used without the optional dependency it needs."""


def import_optional(module_name: str, feature: str, extra: str) -> ModuleType:
    """Import a module that PartCAD only declares as an optional extra.

    'feature' names whatever needed it, phrased to read as the subject of a
    sentence (for example "The Google AI provider" or "Python linting").

    Raises OptionalDependencyError, naming the exact install command, when the
    module itself is missing. Any other ModuleNotFoundError raised from inside an
    installed module is left alone, so genuine breakage in a package that IS
    installed is not misreported as a missing extra.
    """
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as e:
        missing_root = (e.name or "").split(".")[0]
        if missing_root != module_name.split(".")[0]:
            raise
        raise OptionalDependencyError(
            f"{feature} requires an optional dependency "
            f"('{module_name}') that is not installed. "
            f"Install it with: pip install 'partcad[{extra}]' "
            f"(or 'partcad-cli[{extra}]' when using the command line interface)."
        ) from e
