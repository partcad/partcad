#
# PartCAD, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-03-24
#
# Licensed under Apache License, Version 2.0.
#

from jinja2 import Environment, FileSystemLoader, ChoiceLoader
import json
import math
import os
import yaml

from .project import Project
from . import logging as pc_logging
from . import telemetry

DEFAULT_CONFIG_FILENAME = "partcad.yaml"


@telemetry.instrument()
class ProjectLocal(Project):
    def __init__(self, ctx, name, path, include_paths=None, inherited_config=None):
        self.is_local = True

        if os.path.isdir(path):
            self.config_dir = path
            self.config_path = os.path.join(path, DEFAULT_CONFIG_FILENAME)
        else:
            self.config_dir = os.path.dirname(os.path.abspath(path))
            self.config_path = path

        if not os.path.isfile(self.config_path):
            pc_logging.error("PartCAD configuration file is not found: '%s'" % self.config_path)
            self.broken = True
            return

        # Read the body of the configuration file
        fp = open(self.config_path, "r", encoding="utf-8")
        config = fp.read()
        fp.close()

        # Resolve Jinja templates
        loaders = [FileSystemLoader(self.config_dir + os.path.sep)]
        # TODO(clairbee): mark the build as non-hermetic if includePaths is used
        for include_path in include_paths:
            include_path = os.path.join(self.config_dir, include_path) + os.path.sep
            loaders.append(FileSystemLoader(include_path))
        loader = ChoiceLoader(loaders)
        template = Environment(loader=loader).from_string(config)
        config = template.render(
            {
                "package_name": name,
                "M_PI": math.pi,
                "PI": math.pi,
                "SQRT_2": math.sqrt(2),
                "SQRT_3": math.sqrt(3),
                "SQRT_5": math.sqrt(5),
                "INCH": 25.4,
                "INCHES": 25.4,
                "FOOT": 304.8,
                "FEET": 304.8,
                "get_from_config": lambda: None,
            }
        )

        # Parse the config
        if self.config_path.endswith(".yaml"):
            self.config_obj = yaml.safe_load(config)
        if self.config_path.endswith(".json"):
            self.config_obj = json.load(config)

        # Recover from a broken or missing configuration
        # TODO(clairbee): add better error and exception handling (consider if it is needed)
        if self.config_obj is None:
            self.config_obj = {}

        # The 'path' parameter is the config filename or the directory
        # where 'partcad.yaml' is present.
        # 'self.path' has to be set to the directory name.
        dir_name = path
        if not os.path.isdir(dir_name):
            dir_name = os.path.dirname(os.path.abspath(dir_name))
        self.config_path = path
        self.path = dir_name

        super().__init__(ctx, name, inherited_config=inherited_config)
