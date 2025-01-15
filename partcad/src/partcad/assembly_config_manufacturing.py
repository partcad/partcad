#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-13
#
# Licensed under Apache License, Version 2.0.
#

METHOD_NONE = None
METHOD_ASSEMBLE_PARTCAD_BASIC = 1


class AssemblyConfigManufacturing:
    method: int | None

    def __init__(self, final_config):
        manufacturing_config = final_config.get("manufacturing", {})
        method_string = manufacturing_config.get("method", None)
        if method_string == "basic":
            self.method = METHOD_ASSEMBLE_PARTCAD_BASIC
        else:
            self.method = METHOD_NONE
