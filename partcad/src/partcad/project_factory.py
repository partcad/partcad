#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.
#

from . import project as p
from . import telemetry


class ImportConfiguration:
    def __init__(self, config_obj: dict = {}, parent: p.Project | None = None):
        self.config_obj = config_obj
        self.name = config_obj.get("name")
        if not "type" in config_obj:
            if "url" in config_obj:
                if config_obj["url"].endswith(".tar.gz"):
                    config_obj["type"] = "tar"
                else:
                    config_obj["type"] = "git"
            elif "path" in config_obj:
                config_obj["type"] = "local"
            else:
                raise ValueError("Import configuration type is not set")
        self.import_config_type = config_obj.get("type")
        self.import_config_is_root = config_obj.get("isRoot", False)
        self.import_config_url = config_obj.get("url")
        self.include_paths = self.config_obj.get("includePaths", [])
        self.inherited_config = config_obj.get("inheritedConfig", {})
        if parent and not self.inherited_config:
            self.inherited_config = {"manufacturable": parent.is_manufacturable}


@telemetry.instrument()
class ProjectFactory(ImportConfiguration):
    def __init__(self, ctx, parent, import_config_obj):
        super().__init__(import_config_obj, parent)
        self.ctx = ctx
        self.parent = parent

        if parent is None:
            self.config_path = ctx.config_path
            self.config_dir = ctx.config_dir
        else:
            self.config_path = parent.config_path
            self.config_dir = parent.config_dir

        # Continue initializing the config object here if necessary

    def _create(self, config):
        # Finalize the config object here if necessary

        self.project = p.Project(
            self.ctx,
            self.name,
            self.path,
            include_paths=self.include_paths,
            inherited_config=self.inherited_config,
        )
        # Make the project config inherit some properties of the import config
        self.project.config_obj["type"] = self.import_config_type
        self.project.config_obj["isRoot"] = self.import_config_is_root
        self.project.config_obj["importUrl"] = self.import_config_url

    def _save(self):
        self.ctx.projects[self.name] = self.project
