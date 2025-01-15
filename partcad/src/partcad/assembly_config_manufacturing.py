#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-13
#
# Licensed under Apache License, Version 2.0.
#

from . import logging as pc_logging

METHOD_NONE = None
METHOD_ASSEMBLE_PARTCAD_BASIC = 1

_METHOD_MAP = {
    "basic": METHOD_ASSEMBLE_PARTCAD_BASIC,
}


class AssemblyConfigManufacturing:
    method: int | None

    def __init__(self, final_config) -> None:
        manufacturing_config = final_config.get("manufacturing", {})
        method_string = manufacturing_config.get("method", None)
        self.method = _METHOD_MAP.get(method_string, METHOD_NONE)
        if self.method is METHOD_NONE and method_string is not None:
            pc_logging.error(
                f"Unknown manufacturing method '{method_string}'. " f"Supported methods: {list(_METHOD_MAP.keys())}."
            )

    def _method_string(self):
        if self.method == METHOD_ASSEMBLE_PARTCAD_BASIC:
            return "basic"
        if self.method == METHOD_NONE:
            return "none"
        return "unknown"

    def __str__(self) -> str:
        return f"AssemblyConfigManufacturing(method={self._method_string()})"
