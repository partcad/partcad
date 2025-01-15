#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-13
#
# Licensed under Apache License, Version 2.0.
#

from . import logging as pc_logging

METHOD_NONE: None = None
# Note: The assigned numbers are used in APIs and must never change unless the old method is deprecated.
METHOD_ADDITIVE: int = 100
METHOD_SUBTRACTIVE: int = 200
METHOD_FORMING: int = 300

_METHOD_MAP = {
    "additive": METHOD_ADDITIVE,
    "subtractive": METHOD_SUBTRACTIVE,
    "forming": METHOD_FORMING,
}


class PartConfigManufacturing:
    method: int | None

    def __init__(self, final_config: dict) -> None:
        manufacturing_config = final_config.get("manufacturing", {})
        method_string = manufacturing_config.get("method", None)
        self.method = _METHOD_MAP.get(method_string, METHOD_NONE)
        if self.method == METHOD_NONE and method_string is not None:
            pc_logging.error(
                f"Unknown manufacturing method '{method_string}'. " f"Supported methods: {list(_METHOD_MAP.keys())}."
            )

    def _method_string(self):
        if self.method == METHOD_ADDITIVE:
            return "additive"
        if self.method == METHOD_SUBTRACTIVE:
            return "subtractive"
        if self.method == METHOD_FORMING:
            return "forming"
        if self.method == METHOD_NONE:
            return "none"
        return "unknown"

    def __str__(self) -> str:
        return f"PartConfigManufacturing(method={self._method_string()})"
