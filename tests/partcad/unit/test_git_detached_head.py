#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Pins the repository-state assumptions the refresh path depends on.

Importing a revision checks that revision out without a branch, which leaves
HEAD detached. The refresh path then has to read the current commit and move it
to whatever the next fetch brings in, and both have to work in that state.
"""

from pathlib import Path

import pygit2
import pytest
from pygit2.enums import ResetMode

from partcad.project_factory_git import _checkout


def _commit(repo, text):
    """Add one commit changing the single file the tests look at."""
    (Path(repo.workdir) / "f.txt").write_text(text)
    repo.index.add("f.txt")
    repo.index.write()
    signature = pygit2.Signature("test", "test@example.com")
    parents = [] if repo.head_is_unborn else [repo.head.target]
    return repo.create_commit("HEAD", signature, signature, text, repo.index.write_tree(), parents)


def _repo_with_a_tag(tmp_path):
    """An upstream with two commits and a tag on the first, plus a clone."""
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    up = pygit2.init_repository(upstream, initial_head="main")

    first = _commit(up, "A")
    up.references.create("refs/tags/v1", first)
    _commit(up, "B")

    clone = tmp_path / "clone"
    return first, pygit2.clone_repository(str(upstream), str(clone))


def test_a_tag_checkout_leaves_head_detached(tmp_path):
    _, repo = _repo_with_a_tag(tmp_path)
    _checkout(repo, "v1")
    assert repo.head_is_detached


def test_there_is_no_branch_to_read_while_detached(tmp_path):
    """The regression this guards against: the refresh crashed here."""
    _, repo = _repo_with_a_tag(tmp_path)
    _checkout(repo, "v1")
    with pytest.raises(KeyError):
        repo.branches[repo.head.shorthand]


def test_head_reports_the_checked_out_revision(tmp_path):
    """What the refresh path uses instead, and it has to be the right commit."""
    first, repo = _repo_with_a_tag(tmp_path)
    _checkout(repo, "v1")
    assert repo.head.target == first


def test_head_also_works_while_attached(tmp_path):
    """The default-branch path shares this code, so it must not regress."""
    _, repo = _repo_with_a_tag(tmp_path)
    assert not repo.head_is_detached
    assert repo.head.target == repo.branches[repo.head.shorthand].target


def test_a_detached_head_can_still_be_moved_to_a_new_commit(tmp_path):
    """The refresh resets HEAD to what it just fetched, detached or not."""
    first, repo = _repo_with_a_tag(tmp_path)
    _checkout(repo, "v1")
    tip = repo.lookup_reference("refs/remotes/origin/main").target

    repo.reset(tip, ResetMode.HARD)

    assert repo.head.target == tip
    assert repo.head.target != first
    assert (Path(repo.workdir) / "f.txt").read_text() == "B"
