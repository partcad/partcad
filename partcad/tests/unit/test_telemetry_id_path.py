#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Where the telemetry id lives.

There used to be two answers. The id was written next to the configuration file
(`telemetry_sentry.py`) and read back out of `internalStateDir` (`pc system
telemetry info` and `pc system telemetry clear`). Those are the same directory
unless something sets PC_INTERNAL_STATE_DIR, which nothing did -- until the snap
package, which points the state directory at the snap's own per-user directory
and so made the two disagree: the id was written in one place and reported
missing from the other.

There is one answer now, `UserConfig.get_generated_id_path()`, and it is the
configuration directory. The id identifies a user, and `internalStateDir` holds
caches and sandboxes and is redirected per installation, so an id that followed
it would make one user look like several.
"""

import os

from partcad.user_config import UserConfig


def test_the_id_lives_next_to_the_configuration():
    assert UserConfig.get_generated_id_path() == os.path.join(UserConfig.get_config_dir(), ".generated_id")


def test_the_id_does_not_follow_the_internal_state_dir(tmp_path):
    """Redirecting the state directory must not give this machine a new identity."""
    before = UserConfig.get_generated_id_path()

    config = UserConfig()
    # Assigned directly rather than through PC_INTERNAL_STATE_DIR, as the other
    # unit tests do: what is under test is where the id goes, not vyper's
    # environment binding.
    config.internal_state_dir = str(tmp_path)

    assert config.get_generated_id_path() == before
    assert not config.get_generated_id_path().startswith(str(tmp_path))
