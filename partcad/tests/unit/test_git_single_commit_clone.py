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

file:// cannot be used for this: it serves the commit either way, so the
fallback would never be reached and the test would pass without testing it.
"""

from contextlib import contextmanager
from pathlib import Path

import pytest
from git import Repo, exc

from git_http_server import serve_git

from partcad.project_factory_git import clone_single_commit

CONTENT = ["A", "B", "C", "D", "E"]
# Deliberately not the tip. A tip is served under a separate setting
# (allowTipSHA1InWant), so reaching an older commit is what actually exercises
# the unadvertised-object path.
TARGET = 1


@contextmanager
def _upstream(tmp_path, serves_commit_ids):
    """Serve a bare repository of five commits, yielding its URL and a sha.

    serves_commit_ids models the two kinds of server: a current one speaking
    protocol v2, and an older one that both refuses unadvertised objects and
    does not speak v2.
    """
    work = tmp_path / "work"
    work.mkdir()
    repo = Repo.init(work, initial_branch="main")
    with repo.config_writer() as cw:
        cw.set_value("user", "email", "test@example.com")
        cw.set_value("user", "name", "test")

    shas = []
    for text in CONTENT:
        (work / "f.txt").write_text(text)
        repo.index.add(["f.txt"])
        shas.append(repo.index.commit(text).hexsha)

    root = tmp_path / "srv"
    root.mkdir()
    served = root / "upstream.git"
    Repo.clone_from(str(work), str(served), bare=True)
    with Repo(served).config_writer() as cw:
        cw.set_value("uploadpack", "allowReachableSHA1InWant", serves_commit_ids)

    with serve_git(root, protocol_v2=serves_commit_ids) as base_url:
        yield "%s/upstream.git" % base_url, shas[TARGET]


def _checked_out(repo):
    return (Path(repo.working_dir) / "f.txt").read_text()


def _commits_present(repo):
    return int(repo.git.rev_list("--count", "--all"))


def test_the_refusing_server_really_refuses(tmp_path):
    """Guards the fixture itself.

    If a server meant to refuse ever starts answering, the fallback test below
    would still pass while silently no longer exercising the fallback.
    """
    with _upstream(tmp_path, serves_commit_ids=False) as (url, sha):
        repo = Repo.init(tmp_path / "probe")
        repo.create_remote("origin", url)
        with pytest.raises(exc.GitCommandError) as caught:
            repo.git.execute(["git", "fetch", "--depth", "1", "origin", sha])
        assert "unadvertised object" in str(caught.value)


def test_a_current_server_serves_exactly_one_commit(tmp_path):
    """The happy path: no history is downloaded at all."""
    with _upstream(tmp_path, serves_commit_ids=True) as (url, sha):
        repo = clone_single_commit(url, str(tmp_path / "cache"), sha)
        repo.git.checkout(sha, force=True)

        assert _checked_out(repo) == CONTENT[TARGET]
        assert _commits_present(repo) == 1


def test_a_refusing_server_falls_back_and_still_checks_out(tmp_path):
    """The fallback path: correctness is preserved where the shortcut is not."""
    with _upstream(tmp_path, serves_commit_ids=False) as (url, sha):
        repo = clone_single_commit(url, str(tmp_path / "cache"), sha)
        repo.git.checkout(sha, force=True)

        assert _checked_out(repo) == CONTENT[TARGET]
        # The fallback keeps the commit graph, which is how it reaches a commit
        # the server would not hand over directly.
        assert _commits_present(repo) == len(CONTENT)


def test_the_fallback_still_leaves_file_history_on_the_server(tmp_path):
    """Falling back must not become a plain full clone."""
    with _upstream(tmp_path, serves_commit_ids=False) as (url, sha):
        repo = clone_single_commit(url, str(tmp_path / "cache"), sha)

        configured = repo.git.config("--get", "remote.origin.partialclonefilter")
        assert "blob:none" in configured


def test_git_config_options_are_passed_through(tmp_path):
    """The -c options callers rely on must survive the raw git invocation."""
    with _upstream(tmp_path, serves_commit_ids=True) as (url, sha):
        repo = clone_single_commit(
            url,
            str(tmp_path / "cache"),
            sha,
            git_config_options=["-c http.postBuffer=524288000"],
        )
        repo.git.checkout(sha, force=True)
        assert _checked_out(repo) == CONTENT[TARGET]
