#
# OpenVMP, 2023
#
# Author: PartCAD Inc. <support@partcad.org>
# Created: 2024-01-26
#
# Licensed under Apache License, Version 2.0.
#

from .shape_config import ShapeConfiguration


class AssemblyConfiguration(ShapeConfiguration):
    def __init__(self, name, config=None):
        super().__init__(name, config)

    @staticmethod
    def normalize(name, config):
        if isinstance(config, str):
            # This is a short form alias
            config = {"type": "alias", "source": config}

        return ShapeConfiguration.normalize(name, config)
