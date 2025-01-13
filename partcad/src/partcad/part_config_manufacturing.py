#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-13
#
# Licensed under Apache License, Version 2.0.
#

METHOD_NONE = None
METHOD_ADDITIVE = 1


class PartConfigManufacturing:
    method: int | None

    def __init__(self, final_config):
        manufacturing_config = final_config.get("manufacturing", {})
        method_string = manufacturing_config.get("method", None)
        if method_string == "additive":
            self.method = METHOD_ADDITIVE
        else:
            self.method = METHOD_NONE

    def _method_string(self):
        if self.method == METHOD_ADDITIVE:
            return "additive"

        if self.method == METHOD_NONE:
            return "none"

        return "unknown"

    def __str__(self):
        return f"PartConfigManufacturing(method={self._method_string()})"
