#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Covers cloning a commit id against a real server.

The interesting behaviour belongs to the server, not the client: whether it
will serve a commit id by name at all. Under protocol v2, the default since git
2.26, a reachable commit is served regardless of
uploadpack.allowReachableSHA1InWant. A server still speaking v0 applies that
setting and refuses. Both answers have to work, so these tests run against a
real smart-HTTP server where the refusal is genuine rather than simulated.

A local path cannot be used for this: it serves the commit either way, so the
fallback would never be reached and the test would pass without testing it. It
could not be shallow either, which libgit2 refuses on the local transport.
"""

from contextlib import contextmanager
from pathlib import Path

import pygit2
import pytest
from pygit2.enums import ObjectType

from git_http_server import mirror, serve_git

from partcad.project_factory_git import clone_single_commit

CONTENT = ["A", "B", "C", "D", "E"]
# Deliberately not the tip. A tip is served under a separate setting
# (allowTipSHA1InWant), so reaching an older commit is what actually exercises
# the unadvertised-object path.
TARGET = 1


SIDE_BRANCH_CONTENT = "F"


@contextmanager
def _upstream(tmp_path, serves_commit_ids, on_a_side_branch=False):
    """Serve a bare repository of five commits, yielding its URL and a sha.

    serves_commit_ids models the two kinds of server: a current one speaking
    protocol v2, and an older one that both refuses unadvertised objects and
    does not speak v2.

    on_a_side_branch puts the wanted commit where the default branch does not
    reach it, which is the case a clone of the default branch alone would miss.
    """
    work = tmp_path / "work"
    work.mkdir()
    repo = pygit2.init_repository(work, initial_head="main")
    signature = pygit2.Signature("test", "test@example.com")

    shas = []
    for text in CONTENT:
        (work / "f.txt").write_text(text)
        repo.index.add("f.txt")
        repo.index.write()
        parents = [] if repo.head_is_unborn else [repo.head.target]
        shas.append(str(repo.create_commit("HEAD", signature, signature, text, repo.index.write_tree(), parents)))

    wanted = shas[TARGET]
    if on_a_side_branch:
        (work / "f.txt").write_text(SIDE_BRANCH_CONTENT)
        repo.index.add("f.txt")
        repo.index.write()
        tree = repo.index.write_tree()
        wanted = str(
            repo.create_commit("refs/heads/side", signature, signature, SIDE_BRANCH_CONTENT, tree, [repo.head.target])
        )
        repo.checkout_tree(repo.get(shas[-1]), strategy=pygit2.enums.CheckoutStrategy.FORCE)

    root = tmp_path / "srv"
    root.mkdir()
    served = root / "upstream.git"
    mirror(work, served)
    pygit2.Repository(served).config["uploadpack.allowReachableSHA1InWant"] = serves_commit_ids

    with serve_git(root, protocol_v2=serves_commit_ids) as base_url:
        yield "%s/upstream.git" % base_url, wanted


def _checked_out(repo):
    return (Path(repo.workdir) / "f.txt").read_text()


def _commits_present(repo):
    """How much history came down, counted in the object database itself.

    Walking from HEAD cannot answer this: in a shallow repository the walk
    stops at the boundary whether or not more history is present.
    """
    return sum(1 for oid in repo.odb if repo.get(oid).type == ObjectType.COMMIT)


def test_the_refusing_server_really_refuses(tmp_path):
    """Guards the fixture itself.

    If a server meant to refuse ever starts answering, the fallback test below
    would still pass while silently no longer exercising the fallback.
    """
    with _upstream(tmp_path, serves_commit_ids=False) as (url, sha):
        repo = pygit2.init_repository(tmp_path / "probe")
        repo.remotes.create("origin", url)
        with pytest.raises(pygit2.GitError) as caught:
            repo.remotes["origin"].fetch([sha], depth=1)
        assert "cannot fetch a specific object" in str(caught.value)


def test_a_current_server_serves_exactly_one_commit(tmp_path):
    """The happy path: no history is downloaded at all."""
    with _upstream(tmp_path, serves_commit_ids=True) as (url, sha):
        repo = clone_single_commit(url, str(tmp_path / "cache"), sha)

        assert _checked_out(repo) == CONTENT[TARGET]
        assert _commits_present(repo) == 1


def test_a_refusing_server_falls_back_and_still_checks_out(tmp_path):
    """The fallback path: correctness is preserved where the shortcut is not."""
    with _upstream(tmp_path, serves_commit_ids=False) as (url, sha):
        repo = clone_single_commit(url, str(tmp_path / "cache"), sha)

        assert _checked_out(repo) == CONTENT[TARGET]
        # The fallback keeps the commit graph, which is how it reaches a commit
        # the server would not hand over directly.
        assert _commits_present(repo) == len(CONTENT)


def test_the_fallback_searches_every_branch_for_the_commit(tmp_path):
    """A commit id names no branch, so the default branch alone will not do."""
    with _upstream(tmp_path, serves_commit_ids=False, on_a_side_branch=True) as (url, sha):
        repo = clone_single_commit(url, str(tmp_path / "cache"), sha)

        assert _checked_out(repo) == SIDE_BRANCH_CONTENT
        assert str(repo.head.target) == sha


def test_the_checked_out_revision_is_left_detached(tmp_path):
    """A commit id belongs to no branch, so there is none to be on."""
    with _upstream(tmp_path, serves_commit_ids=True) as (url, sha):
        repo = clone_single_commit(url, str(tmp_path / "cache"), sha)

        assert repo.head_is_detached
        assert str(repo.head.target) == sha


def test_git_config_is_passed_through(tmp_path):
    """The user's git settings must reach the repository before it is filled."""
    with _upstream(tmp_path, serves_commit_ids=True) as (url, sha):
        repo = clone_single_commit(
            url,
            str(tmp_path / "cache"),
            sha,
            git_config={"http.postBuffer": "524288000"},
        )

        assert repo.config["http.postBuffer"] == "524288000"
        assert _checked_out(repo) == CONTENT[TARGET]
