#
# PartCAD, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-03-24
#
# Licensed under Apache License, Version 2.0.
#

from .project import Project


class ProjectPlugin(Project):
    def __init__(self, ctx, name, inherited_config=None):
        super().__init__(ctx, name, inherited_config=inherited_config)
        self.is_local = False
