#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import pytest

from partcad.project_factory_git import get_clone_options, looks_like_commit_id

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
    assert "--depth 1" in options
    assert "--single-branch" in options
    assert not any(o.startswith("--branch") for o in options)


@pytest.mark.parametrize("revision", REFS)
def test_a_ref_is_requested_from_the_server_directly(revision):
    options = get_clone_options(revision)
    assert "--depth 1" in options
    assert "--branch %s" % revision in options


@pytest.mark.parametrize("revision", COMMIT_IDS)
def test_a_commit_id_never_becomes_a_branch_argument(revision):
    """git clone --branch <commit id> fails outright, so it must never happen.

    Verified against a real repository: asking for a commit id as a branch gives
    "Remote branch <id> not found in upstream origin".
    """
    options = get_clone_options(revision)
    assert not any(o.startswith("--branch") for o in options), options


@pytest.mark.parametrize("revision", COMMIT_IDS)
def test_a_commit_id_keeps_the_whole_commit_graph(revision):
    """A shallow clone would not contain an arbitrary commit.

    Filtering blobs instead keeps every commit reachable, so the checkout
    succeeds, while historical file contents stay on the server.
    """
    options = get_clone_options(revision)
    assert "--filter=blob:none" in options
    assert "--depth 1" not in options


def test_options_are_separate_arguments():
    """multi_options entries are passed through to git as written."""
    for revision in [None, "main", COMMIT_IDS[0]]:
        for option in get_clone_options(revision):
            assert option.startswith("--"), option
