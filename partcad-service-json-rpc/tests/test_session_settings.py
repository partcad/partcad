#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Reading the session settings the two kinds of client send.

The same setting arrives spelled differently depending on who is talking. The
daemon's own command line turns a flag into the string ``"true"``, while the VS
Code extension forwards its configuration values with their JSON types intact,
so a boolean setting arrives as a real boolean. Both have to mean the same
thing, or a setting is silently ignored for one of the two clients.
"""

import pytest
from partcad_service_json_rpc.core.session import _as_bool


@pytest.mark.parametrize("value", [True, "true", "True", "TRUE", "1", "yes", "on", " true "])
def test_every_spelling_of_yes_reads_as_true(value):
    assert _as_bool(value) is True


@pytest.mark.parametrize("value", [False, "false", "False", "0", "no", "off", "", "nonsense"])
def test_everything_else_reads_as_false(value):
    assert _as_bool(value) is False
