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

        # The 'path' parameter is either the configuration filename or the
        # directory where 'partcad.yaml' is present. 'self.path' (passed to the
        # base class below) has to be the directory, while 'self.config_path'
        # has to point at the configuration file itself.
        if os.path.isdir(path):
            config_dir = path
            config_path = os.path.join(path, DEFAULT_CONFIG_FILENAME)
        else:
            config_dir = os.path.dirname(os.path.abspath(path))
            config_path = path
        self.config_path = config_path

        if not os.path.isfile(config_path):
            pc_logging.error("PartCAD configuration file is not found: '%s'" % config_path)
            # Initialize the base classes anyway. Otherwise this object is left
            # without a name, a path or a config object, none of which the
            # handling of broken packages can do without - see
            # 'ProjectFactory._create()' and 'Context.import_project()'.
            super().__init__(ctx, name, config_dir, config_obj={}, inherited_config=inherited_config)
            self.broken = True
            return

        # Read the body of the configuration file
        fp = open(config_path, "r", encoding="utf-8")
        config = fp.read()
        fp.close()

        # Resolve Jinja templates
        loaders = [FileSystemLoader(config_dir + os.path.sep)]
        # TODO(clairbee): mark the build as non-hermetic if includePaths is used
        for include_path in include_paths or []:
            include_path = os.path.join(config_dir, include_path) + os.path.sep
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
        config_obj = None
        if config_path.endswith(".yaml"):
            config_obj = yaml.safe_load(config)
        if config_path.endswith(".json"):
            # 'config' is the rendered text, not a file object, hence 'loads'
            config_obj = json.loads(config)

        # Recover from a broken or missing configuration
        # TODO(clairbee): add better error and exception handling (consider if it is needed)
        if config_obj is None:
            config_obj = {}

        super().__init__(ctx, name, config_dir, config_obj=config_obj, inherited_config=inherited_config)
