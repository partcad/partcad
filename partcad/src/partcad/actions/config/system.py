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

from ... import logging as pc_logging
from ...user_config import user_config


def _config_path() -> str:
    """
    Return the path of the file that 'pc system set ...' reads and writes.

    This has to be the very same file that UserConfig loads at startup,
    otherwise a setting can be written and never take effect. UserConfig reads
    'UserConfig.get_config_dir()/config.yaml' -- i.e. '$HOME/.partcad' -- and
    nothing else, so that is the only correct destination.

    In particular this must NOT be derived from 'internalStateDir'.
    'internalStateDir' is itself one of the settings config.yaml carries (see
    features/config.feature), so putting config.yaml under the directory it
    configures is circular: its location would depend on a value only it can
    supply. 'internalStateDir' is also documented as the place for temporary
    files -- the git/tar/sandbox/cache trees that 'pc system reset' is free to
    wipe -- whereas the settings a user typed into 'pc system set' must survive
    that.
    """
    config_dir = user_config.get_config_dir()
    # UserConfig creates this on import, but the directory can be pointed
    # elsewhere (a test, a relocated $HOME), so do not assume it exists.
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, "config.yaml")


def _warn_about_stale_config(config_path: str) -> None:
    """
    Point out a config.yaml left behind under 'internalStateDir'.

    Until this was fixed, 'pc system set ...' wrote there while PartCAD kept
    reading '$HOME/.partcad/config.yaml', so anyone using a custom
    'internalStateDir' has settings recorded in a file that never had any
    effect. We deliberately do not adopt that file: its contents were inert, and
    silently activating stale settings on upgrade would change behaviour the
    user never asked for -- including turning telemetry on or off. Saying it is
    there, and where the real config lives, lets them decide.
    """
    state_dir = user_config.internal_state_dir
    if not state_dir:
        return
    stale_path = os.path.join(state_dir, "config.yaml")
    if not os.path.exists(stale_path):
        return
    if os.path.exists(config_path) and os.path.samefile(stale_path, config_path):
        # The common case: 'internalStateDir' is left at its default, so the two
        # paths name one and the same file and there is nothing stale about it.
        return
    pc_logging.warning(
        "Ignoring '%s': it was written by an older PartCAD that saved system settings "
        "under 'internalStateDir'. PartCAD only reads '%s'. Re-apply anything you still "
        "want from it and delete it." % (stale_path, config_path)
    )


def system_config_get() -> tuple[ruamel.yaml.YAML, dict]:
    """
    Get system configuration.
    """
    config_path = _config_path()
    _warn_about_stale_config(config_path)

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
    config_path = _config_path()

    with open(config_path, "w") as fp:
        yaml.dump(config, fp)
        fp.close()
