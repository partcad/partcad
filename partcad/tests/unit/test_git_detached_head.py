#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Pins the repository-state assumptions the refresh path depends on.

Importing a revision that is a tag or a commit id checks that revision out,
which leaves HEAD detached. The refresh path then has to read the current
commit, and the obvious spelling for that, Repo.active_branch, is exactly the
one that does not work while detached.
"""

import pytest

from git import Repo


def _repo_with_a_tag(tmp_path):
    """An upstream with two commits and a tag on the first, plus a clone."""
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    up = Repo.init(upstream, initial_branch="main")
    with up.config_writer() as cw:
        cw.set_value("user", "email", "test@example.com")
        cw.set_value("user", "name", "test")

    (upstream / "f.txt").write_text("A")
    up.index.add(["f.txt"])
    first = up.index.commit("A")
    up.create_tag("v1")

    (upstream / "f.txt").write_text("B")
    up.index.add(["f.txt"])
    up.index.commit("B")

    clone = tmp_path / "clone"
    return first, Repo.clone_from(str(upstream), str(clone))


def test_a_tag_checkout_leaves_head_detached(tmp_path):
    _, repo = _repo_with_a_tag(tmp_path)
    repo.git.checkout("v1", force=True)
    assert repo.head.is_detached


def test_active_branch_is_unusable_while_detached(tmp_path):
    """The regression this guards against: the refresh crashed here."""
    _, repo = _repo_with_a_tag(tmp_path)
    repo.git.checkout("v1", force=True)
    with pytest.raises(TypeError):
        repo.active_branch.commit


def test_head_commit_still_reports_the_checked_out_revision(tmp_path):
    """What the refresh path uses instead, and it has to be the right commit."""
    first, repo = _repo_with_a_tag(tmp_path)
    repo.git.checkout("v1", force=True)
    assert repo.head.commit.hexsha == first.hexsha


def test_head_commit_also_works_while_attached(tmp_path):
    """The default-branch path shares this code, so it must not regress."""
    _, repo = _repo_with_a_tag(tmp_path)
    assert not repo.head.is_detached
    assert repo.head.commit == repo.active_branch.commit
