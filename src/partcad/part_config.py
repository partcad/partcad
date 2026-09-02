#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-01-26
#
# Licensed under Apache License, Version 2.0.
#

from .config import Configuration
from .shape_config import ShapeConfiguration
from .part_config_manufacturing import PartConfigManufacturing


class PartConfiguration(Configuration, ShapeConfiguration):
    def __init__(self, name, config):
        super().__init__(name, config)

    @staticmethod
    def normalize(name, config, object_name):
        if isinstance(config, str):
            # This is a short form alias
            config = {"type": "alias", "source": config}

        config = Configuration.normalize(name, config, object_name)
        return ShapeConfiguration.normalize(name, config)

    @staticmethod
    def get_manufacturing_data(part) -> PartConfigManufacturing:
        """How this part is made, as its own configuration states it.

        The part is passed rather than only its configuration because the
        section names things - a tool - relative to the package that declared
        them, and because what it says has to be reported against the object it
        was declared on.
        """
        final_config = part.get_final_config()
        return PartConfigManufacturing(
            final_config,
            project_name=getattr(part, "project_name", "") or "",
            where="%s:%s" % (getattr(part, "project_name", ""), getattr(part, "name", "")),
        )
