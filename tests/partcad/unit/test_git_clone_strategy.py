#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import pytest

from partcad.project_factory_git import (
    get_clone_options,
    get_fallback_clone_options,
    looks_like_commit_id,
)

COMMIT_IDS = [
    "a307044f91c9cc5433fde92cb1fa145c01b2bde7",  # full
    "a307044",  # abbreviated
    "deadbeef",
]

REFS = [
    "main",
    "devel",
    "0.7.128",
    "feature/partcad",
    "feature/partcad-shim",
    "examples-in-partcad",
    "hotfix/cqgi-hidden-errors",
    "partcad-examples-update-2",
]


@pytest.mark.parametrize("revision", COMMIT_IDS)
def test_commit_ids_are_recognised(revision):
    assert looks_like_commit_id(revision)


@pytest.mark.parametrize("revision", REFS)
def test_refs_are_not_mistaken_for_commit_ids(revision):
    assert not looks_like_commit_id(revision)


def test_no_revision_clones_a_single_commit():
    options = get_clone_options(None)
    assert options.depth == 1
    assert options.revision is None
    assert not options.single_commit


@pytest.mark.parametrize("revision", REFS)
def test_a_ref_is_requested_from_the_server_directly(revision):
    options = get_clone_options(revision)
    assert options.depth == 1
    assert options.revision == revision


@pytest.mark.parametrize("revision", REFS)
def test_a_ref_is_never_requested_as_a_commit_id(revision):
    """Asking for a ref by id would send a name no server can resolve."""
    assert not get_clone_options(revision).single_commit


@pytest.mark.parametrize("revision", COMMIT_IDS)
def test_a_commit_id_is_requested_by_id(revision):
    """A clone cannot check out a commit id, so it has to be fetched by id.

    Verified against a real repository: asking for a commit id as a branch gives
    "Remote branch <id> not found in upstream origin".
    """
    options = get_clone_options(revision)
    assert options.single_commit
    assert options.revision == revision
    assert options.depth == 1


@pytest.mark.parametrize("revision", COMMIT_IDS)
def test_a_refusing_server_costs_the_whole_commit_graph(revision):
    """A shallow clone would not contain an arbitrary commit.

    Where the commit cannot be requested by id, every commit reachable from the
    default refs has to come down so the checkout can find it locally.
    """
    options = get_fallback_clone_options(revision)
    assert options.depth == 0
    assert options.revision is None


@pytest.mark.parametrize("revision", REFS + [None])
def test_a_ref_is_still_asked_for_by_name_when_shallow_is_refused(revision):
    """Only the depth has to go: the server still knows the ref by name."""
    options = get_fallback_clone_options(revision)
    assert options.depth == 0
    assert options.revision == revision
