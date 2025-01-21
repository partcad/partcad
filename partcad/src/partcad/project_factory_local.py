#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.
#

import os
from . import project_factory as pf
from .sentry import instrument


class LocalImportConfiguration:
    def __init__(self):
        self.import_config_path = self.config_obj.get("path").replace("/", os.path.sep)
        self.maybe_empty = False
        if "maybeEmpty" in self.config_obj:
            self.maybe_empty = self.config_obj.get("maybeEmpty")


@instrument()
class ProjectFactoryLocal(pf.ProjectFactory, LocalImportConfiguration):
    def __init__(self, ctx, parent, config):
        pf.ProjectFactory.__init__(self, ctx, parent, config)
        LocalImportConfiguration.__init__(self)

        if not os.path.isabs(self.import_config_path) and self.config_dir != "":
            self.import_config_path = os.path.join(self.config_dir, self.import_config_path)

        self.path = self.import_config_path

        if not self.maybe_empty:
            if not os.path.exists(self.import_config_path):
                raise Exception("PartCAD config not found: %s" % self.import_config_path)

        # Complement the config object here if necessary
        self._create(config)

        # TODO(clairbee): consider installing a symlink in the parent's project

        self._save()
