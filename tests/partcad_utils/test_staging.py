#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Reading a daemon's "not yet -- build these first".

The protocol both ends of a two-phase assembly build read from one place. What
is pinned here is the reading: which errors count as a request to build
something, which entries survive it, and what the request that builds one says.
"""

from partcad_utils import staging


def names(items):
    return [staging.identity(item) for item in items]


def test_the_entries_the_daemon_named():
    data = staging.error_data(
        [
            {"package": "//sub", "name": "unit"},
            {"package": "//sub", "name": "unit;gap=4.0"},
        ]
    )

    assert names(staging.pending_subassemblies(staging.RETRY_LATER, data)) == [
        "//sub:unit",
        "//sub:unit;gap=4.0",
    ]


def test_an_ordinary_error_is_not_a_request_to_build_anything():
    """Every other failure reaches the user as it always did."""
    data = staging.error_data([{"package": "//sub", "name": "unit"}])

    assert staging.pending_subassemblies(-32602, data) == []
    assert staging.pending_subassemblies(None, None) == []


def test_a_malformed_payload_is_nothing_to_act_on():
    """Which is what makes the error be reported: the caller rethrows on empty."""
    assert staging.pending_subassemblies(staging.RETRY_LATER, {}) == []
    assert staging.pending_subassemblies(staging.RETRY_LATER, {staging.SUBASSEMBLIES: "unit"}) == []
    assert staging.pending_subassemblies(staging.RETRY_LATER, {staging.SUBASSEMBLIES: [{"package": "//sub"}, 7]}) == []


def test_a_staging_request_keeps_the_result_on_the_daemon():
    assert staging.request_params({"package": "//sub", "name": "unit"}) == {
        "package": "//sub",
        "name": "unit",
        staging.KIND: staging.KIND_ASSEMBLY,
        staging.CACHE_ONLY: True,
    }


def test_a_scene_is_asked_for_as_a_scene():
    """The same files and the same tree, but a package registers the two apart."""
    item = {"package": "//sub", "name": "bench", staging.KIND: "scene"}

    assert staging.request_params(item)[staging.KIND] == "scene"
    # And it is a different entry from an assembly of that name, so staging one
    # is not staging the other.
    assert staging.identity(item) != staging.identity({"package": "//sub", "name": "bench"})


def test_the_context_travels_with_it_when_there_is_one():
    """A warm daemon serves several; the wrong one is another workspace."""
    assert staging.request_params({"name": "unit"}, "ctx-7")["context"] == "ctx-7"
    assert "context" not in staging.request_params({"name": "unit"})


def test_the_message_says_what_to_do_about_it():
    """For a client that does not implement any of this, this is the answer."""
    message = staging.error_message([{"package": "//sub", "name": "unit"}])

    assert "//sub:unit" in message
    assert "first" in message
