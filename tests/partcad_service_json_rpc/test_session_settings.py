#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Reading the session settings the two kinds of client send.

The same setting arrives spelled differently depending on who is talking. The
daemon's own command line turns a flag into the string ``"true"``, while the VS
Code extension forwards its configuration values with their JSON types intact,
so a boolean setting arrives as a real boolean and an older string-enum setting
as ``"true"``/``"false"``. Both have to mean the same thing, or a setting is
silently ignored for one of the two clients.

The reading is shared with the one ``UserConfig`` applies to the ``PC_*``
environment variables, which is the point: there is one answer, not three.
"""

import pytest
from partcad_utils.booleans import to_bool


@pytest.mark.parametrize("value", [True, "true", "True", "TRUE", "1", "yes", "on", " true "])
def test_every_spelling_of_yes_reads_as_true(value):
    assert to_bool(value) is True


@pytest.mark.parametrize("value", [False, "false", "False", "0", "no", "off", ""])
def test_every_spelling_of_no_reads_as_false(value):
    assert to_bool(value) is False


def test_the_session_helper_is_the_shared_one():
    """The daemon must not grow a second reading of its own."""
    from partcad_service_json_rpc.core import session

    assert session.to_bool is to_bool
