#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-13
#
# Licensed under Apache License, Version 2.0.
#

METHOD_NONE: None = None
# Note: The assigned numbers are used in APIs and must never change unless the old method is deprecated.
METHOD_ADDITIVE: int = 100
METHOD_SUBTRACTIVE: int = 200
METHOD_FORMING: int = 300


class PartConfigManufacturing:
    method: int | None

    def __init__(self, final_config):
        manufacturing_config = final_config.get("manufacturing", {})
        method_string = manufacturing_config.get("method", None)
        if method_string == "additive":
            self.method = METHOD_ADDITIVE
        elif method_string == "subtractive":
            self.method = METHOD_SUBTRACTIVE
        elif method_string == "forming":
            self.method = METHOD_FORMING
        else:
            self.method = METHOD_NONE

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

    def __str__(self):
        return f"PartConfigManufacturing(method={self._method_string()})"
