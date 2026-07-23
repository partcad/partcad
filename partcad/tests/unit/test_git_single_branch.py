#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Covers what an import is allowed to download from a repository with many branches.

A depth limit alone does not bound a clone: the default refspec is a wildcard,
so every branch still arrives, each with a complete snapshot of its tree. git
calls the cure --single-branch; here it is the refspec the remote is created
with, so these tests check the refspecs rather than the flags.

Served over HTTP because libgit2 refuses a shallow request on the local
transport, and a shallow clone is what makes the wildcard expensive.
"""

from contextlib import contextmanager

import pygit2
import pytest

from git_http_server import mirror, serve_git

from partcad.project_factory_git import (
    CloneOptions,
    _clone,
    _create_origin,
    _tracking_refspecs,
)

BRANCHES = ["main", "side", "other"]


@contextmanager
def _upstream(tmp_path):
    """Serve a repository whose default branch is one of several."""
    work = tmp_path / "work"
    work.mkdir()
    repo = pygit2.init_repository(work, initial_head="main")
    signature = pygit2.Signature("test", "test@example.com")

    (work / "f.txt").write_text("A")
    repo.index.add("f.txt")
    repo.index.write()
    first = repo.create_commit("HEAD", signature, signature, "A", repo.index.write_tree(), [])
    for branch in BRANCHES[1:]:
        repo.branches.local.create(branch, repo.get(first))

    root = tmp_path / "srv"
    root.mkdir()
    served = root / "upstream.git"
    mirror(work, served)

    with serve_git(root, protocol_v2=True) as base_url:
        yield "%s/upstream.git" % base_url


def test_a_clone_tracks_the_default_branch_alone(tmp_path):
    with _upstream(tmp_path) as url:
        repo = _clone(url, str(tmp_path / "cache"), {}, CloneOptions(revision=None, depth=1))

        assert repo.remotes["origin"].fetch_refspecs == ["+refs/heads/main:refs/remotes/origin/main"]


def test_the_other_branches_are_never_downloaded(tmp_path):
    with _upstream(tmp_path) as url:
        repo = _clone(url, str(tmp_path / "cache"), {}, CloneOptions(revision=None, depth=1))

        tracked = [str(ref) for ref in repo.references if str(ref).startswith("refs/remotes/")]
        for branch in BRANCHES[1:]:
            assert "refs/remotes/origin/%s" % branch not in tracked


def test_the_default_branch_is_still_checked_out(tmp_path):
    """Narrowing the refspec must not cost the clone its working tree."""
    with _upstream(tmp_path) as url:
        repo = _clone(url, str(tmp_path / "cache"), {}, CloneOptions(revision=None, depth=1))

        assert not repo.head_is_detached
        assert repo.head.shorthand == "main"
        assert (tmp_path / "cache" / "f.txt").read_text() == "A"


@pytest.mark.parametrize("revision", ["devel", "0.7.128", "feature/partcad"])
def test_a_named_revision_is_tracked_both_ways(revision):
    """The import configuration does not say whether a revision is a tag."""
    refspecs = _tracking_refspecs(revision)

    assert "+refs/heads/{r}:refs/remotes/origin/{r}".format(r=revision) in refspecs
    assert "+refs/tags/{r}:refs/tags/{r}".format(r=revision) in refspecs
    assert not any("*" in refspec for refspec in refspecs)


def test_a_named_revision_narrows_the_remote(tmp_path):
    repo = pygit2.init_repository(tmp_path / "repo")

    _create_origin(repo, "https://example.com/repo.git", "devel")

    assert repo.remotes["origin"].fetch_refspecs == _tracking_refspecs("devel")


def test_a_commit_id_has_no_ref_to_narrow_to(tmp_path):
    """It is asked for by id instead, so the wildcard costs nothing."""
    repo = pygit2.init_repository(tmp_path / "repo")

    _create_origin(repo, "https://example.com/repo.git", "a307044f91c9cc5433fde92cb1fa145c01b2bde7")

    assert repo.remotes["origin"].fetch_refspecs == ["+refs/heads/*:refs/remotes/origin/*"]
