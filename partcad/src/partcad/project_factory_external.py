#
# PartCAD, 2025
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.
#

import os
import hashlib

from . import project_factory as pf
from .project import Project
from .project_plugin import ProjectPlugin
from .utils import normalize_resource_path
from . import logging as pc_logging
from . import telemetry


class ExternalImportConfiguration:
    def __init__(self):
        self.plugin = self.config_obj.get("plugin", ":plugin")


@telemetry.instrument()
class ProjectFactoryExternal(pf.ProjectFactory, ExternalImportConfiguration):
    def __init__(self, ctx, parent: Project, config):
        pf.ProjectFactory.__init__(self, ctx, parent, config)
        ExternalImportConfiguration.__init__(self)

        # If needed, turn the relative path into an absolute one to make it usable in other places
        self.plugin = normalize_resource_path(parent.path, self.plugin)

        # Find a place to store all temporary artifacts if any
        repo_hash = hashlib.sha256(self.plugin.encode()).hexdigest()[:16]
        self.path = os.path.join(ctx.user_config.internal_state_dir, "external", repo_hash)

        pc_logging.info(f"External project path: {self.path}")

        # Complement the config object here if necessary
        self._create(config)

        self._save()

    def _create_project(self, config):
        return ProjectPlugin(
            self.ctx,
            self.name,
            inherited_config=self.inherited_config,
        )
