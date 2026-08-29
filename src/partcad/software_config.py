#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

from .config import Configuration
from .software import DEFAULT_TYPE


class SoftwareConfiguration:
    def __init__(self, name, config):
        super().__init__(name, config)

    @staticmethod
    def normalize(name, config, object_name):
        if config is None:
            config = {}

        if isinstance(config, str):
            # The short form: the value is the path of the file.
            config = {"path": config}

        # Every software object has a type, and a declaration that names none
        # gets 'raw' - the file handed over as it is. Applied here rather than
        # in the factory dispatch so that everything downstream (the schema
        # linting aside, which reads the file) sees a config that says what it
        # is, including 'pc info' and the bill of materials.
        if "type" not in config or config["type"] is None:
            config["type"] = DEFAULT_TYPE

        return Configuration.normalize(name, config, object_name)
