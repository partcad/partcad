#
# PartCAD, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-04-02
#
# Licensed under Apache License, Version 2.0.
#

import os
from pathlib import Path
import ruamel.yaml

from ...user_config import user_config


def system_config_get() -> tuple[ruamel.yaml.YAML, dict]:
    """
    Get system configuration.
    """
    config_path = os.path.join(user_config.internal_state_dir, "config.yaml")

    yaml = ruamel.yaml.YAML()
    yaml.preserve_quotes = True
    if not os.path.exists(config_path):
        Path(config_path).touch()
        config = {}
    else:
        with open(config_path) as fp:
            config = yaml.load(fp)
            fp.close()

    if not config:
        config = {}

    return yaml, config


def system_config_set(yaml: ruamel.yaml.YAML, config: dict):
    """
    Set system configuration.
    """
    config_path = os.path.join(user_config.internal_state_dir, "config.yaml")

    with open(config_path, "w") as fp:
        yaml.dump(config, fp)
        fp.close()
