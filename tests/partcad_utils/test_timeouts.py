#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Reading an assembly's ``timeout:``, as both ends of the connection do.

What is pinned here is what counts as a timeout at all -- the declaration is
user input, and a value that is not a positive number of seconds must read as
no timeout rather than fail a build -- and the shape of the marker that carries
one across the wire.
"""

import math

import pytest

from partcad_utils import timeouts


@pytest.mark.parametrize("value, expected", [(1800, 1800.0), (2.5, 2.5), (1, 1.0)])
def test_a_positive_number_of_seconds_is_a_timeout(value, expected):
    assert timeouts.seconds(value) == expected


@pytest.mark.parametrize("value", [None, 0, -5, "1800", True, False, math.inf, math.nan, [1800], {"s": 1}])
def test_anything_else_is_no_timeout(value):
    """Including True, which Python would otherwise count as one second."""
    assert timeouts.seconds(value) is None


def test_a_declaration_states_it_under_its_key():
    assert timeouts.declared({"type": "assy", "timeout": 900}) == 900.0
    assert timeouts.declared({"type": "assy"}) is None
    # A short-form alias is a string until it is normalized; it states nothing.
    assert timeouts.declared("//other:assembly") is None
    assert timeouts.declared(None) is None


def test_a_marker_says_what_declared_it():
    marker = timeouts.event(timeouts.START, 900.0, "//pub/robots", "arm")
    assert marker == {"kind": "timeout_start", "seconds": 900.0, "package": "//pub/robots", "item": "arm"}
    assert timeouts.subject(marker) == "//pub/robots:arm"
    assert timeouts.subject(timeouts.event(timeouts.END, 900.0, "//pub/robots", None)) == "//pub/robots"


def test_the_markers_are_not_progress_events():
    """A client replaying progress must not mistake a window for an action."""
    from partcad_utils.logging_remote_server import PC_EVENTS

    assert not set(timeouts.KINDS) & set(PC_EVENTS)
