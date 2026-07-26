#
# OpenVMP, 2024
#
# Licensed under Apache License, Version 2.0.
#

import importlib
from types import ModuleType


class AiProviderDependencyError(ImportError):
    """Raised when an AI provider is used without its optional SDK installed."""


# The import name of an optional SDK is not always the name of the distribution
# that provides it, so the error message would otherwise suggest a package that
# cannot be installed. Longest matching prefix wins.
_DISTRIBUTION_BY_MODULE = {
    "google.genai": "google-genai",
    "PIL": "Pillow",
    "openai": "openai",
    "ollama": "ollama",
    "httpx": "httpx",
}


def distribution_for(module_name: str) -> str:
    """Return the pip distribution name that provides `module_name`."""
    for candidate in sorted(_DISTRIBUTION_BY_MODULE, key=len, reverse=True):
        if module_name == candidate or module_name.startswith(candidate + "."):
            return _DISTRIBUTION_BY_MODULE[candidate]
    return module_name


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
        missing = e.name or ""
        # Treat this as a missing optional extra only when the module that failed
        # to import IS the requested module or an ANCESTOR package of it. If a
        # deeper submodule of an otherwise-installed SDK failed to import (same
        # root, but not an ancestor of what we asked for), that is genuine
        # breakage inside the SDK, so re-raise the original error untouched.
        requested_from_missing = missing == module_name or module_name.startswith(missing + ".")
        if not requested_from_missing:
            raise
        raise AiProviderDependencyError(
            f"The {provider} provider requires an optional dependency "
            f"('{module_name}', provided by the '{distribution_for(module_name)}' package) "
            f"that is not installed. "
            f"Install it with: pip install 'partcad[{extra}]' "
            f"(or 'partcad-cli[{extra}]' when using the command line interface)."
        ) from e
