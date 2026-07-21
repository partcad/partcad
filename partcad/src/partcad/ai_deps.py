#
# OpenVMP, 2024
#
# Licensed under Apache License, Version 2.0.
#

import importlib
from types import ModuleType


class AiProviderDependencyError(ImportError):
    """Raised when an AI provider is used without its optional SDK installed."""


def import_optional(module_name: str, provider: str, extra: str) -> ModuleType:
    """Import an AI provider SDK that PartCAD only declares as an optional extra.

    Raises AiProviderDependencyError, naming the exact install command, when the
    SDK itself is missing. Any other ModuleNotFoundError raised from inside the
    SDK is left alone, so genuine breakage inside an installed SDK is not
    misreported as a missing extra.
    """
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as e:
        missing_root = (e.name or "").split(".")[0]
        if missing_root != module_name.split(".")[0]:
            raise
        raise AiProviderDependencyError(
            f"The {provider} provider requires an optional dependency "
            f"('{module_name}') that is not installed. "
            f"Install it with: pip install 'partcad[{extra}]' "
            f"(or 'partcad-cli[{extra}]' when using the command line interface)."
        ) from e
