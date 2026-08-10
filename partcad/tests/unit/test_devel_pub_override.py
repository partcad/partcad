#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Redirecting the public index to its unreleased branch ('develPub').

The public index lives in a repository of its own, so nothing in the package
that imports it says which version of it to use: a plain import gets whatever
its default branch holds, which is the released state. 'develPub' redirects it
to the 'devel' branch that release fast-forwards 'main' to.

The dependency is recognized by the repository its URL names rather than by the
name the importing package gave it, so the two things worth pinning down are
that every spelling of that repository is recognized, and that no other
dependency is touched.
"""

import pytest

from partcad import consts
from partcad.project_factory_git import (
    GitImportConfiguration,
    is_pub_index_url,
    repo_path,
)

PUB_INDEX_URLS = [
    "https://github.com/partcad/partcad-index.git",
    "https://github.com/partcad/partcad-index",
    "https://github.com/partcad/partcad-index/",
    "http://github.com/partcad/partcad-index.git",
    "ssh://git@github.com/partcad/partcad-index.git",
    "git@github.com:partcad/partcad-index.git",
    "git@github.com:partcad/partcad-index",
    # The organization the index moved from; packages published before the move
    # still import it under that name and GitHub keeps serving it.
    "https://github.com/openvmp/partcad-index.git",
    # A repository path is case-insensitive on GitHub.
    "https://github.com/PartCAD/PartCAD-Index.git",
]

OTHER_URLS = [
    "https://github.com/partcad/partcad.git",
    "https://github.com/partcad/partcad-index-mirror.git",
    "https://github.com/someone/partcad-index-fork.git",
    "https://github.com/partcad-index/partcad.git",
    "git@github.com:partcad/partcad.git",
    "",
    None,
]


class FakeUserConfig:
    """The subset of ``user_config`` that ``GitImportConfiguration`` reads."""

    def __init__(self, devel_pub=False, url_overrides=None):
        self.devel_pub = devel_pub
        self._url_overrides = url_overrides

    def get(self, key):
        if key == "dependencies.overrides.url":
            return self._url_overrides
        return None


class FakeContext:
    def __init__(self, user_config):
        self.user_config = user_config


class Import(GitImportConfiguration):
    """A git import, resolved the way ``ProjectFactoryGit`` resolves one."""

    def __init__(self, config, user_config=None):
        self.config_obj = config
        self.ctx = FakeContext(user_config if user_config is not None else FakeUserConfig())
        GitImportConfiguration.__init__(self)


# ---- recognizing the repository ---------------------------------------------


@pytest.mark.parametrize("url", PUB_INDEX_URLS)
def test_every_spelling_of_the_index_repository_is_recognized(url):
    assert is_pub_index_url(url)


@pytest.mark.parametrize("url", OTHER_URLS)
def test_other_repositories_are_not_mistaken_for_the_index(url):
    assert not is_pub_index_url(url)


def test_repo_path_drops_the_host_so_a_mirror_is_recognized():
    """The host is not part of the identity: the same repository may be served
    from a mirror, and the dependency overrides already rewrite hosts."""
    assert repo_path("https://gitlab.example.com/partcad/partcad-index.git") == "partcad/partcad-index"


# ---- applying the override ---------------------------------------------------


def test_the_index_is_redirected_to_the_devel_branch():
    imp = Import(
        {"url": "https://github.com/partcad/partcad-index.git"},
        FakeUserConfig(devel_pub=True),
    )
    assert imp.import_revision == consts.PUB_INDEX_DEVEL_REVISION


def test_nothing_is_redirected_when_the_option_is_off():
    imp = Import(
        {"url": "https://github.com/partcad/partcad-index.git"},
        FakeUserConfig(devel_pub=False),
    )
    assert imp.import_revision is None


def test_other_dependencies_keep_their_revision():
    """The option names no dependency, so it must not reach past the index."""
    imp = Import(
        {"url": "https://github.com/partcad/partcad.git", "revision": "0.7.158"},
        FakeUserConfig(devel_pub=True),
    )
    assert imp.import_revision == "0.7.158"


def test_other_dependencies_without_a_revision_stay_on_their_default_branch():
    imp = Import(
        {"url": "https://github.com/partcad/partcad.git"},
        FakeUserConfig(devel_pub=True),
    )
    assert imp.import_revision is None


def test_a_pinned_revision_of_the_index_is_overridden():
    """This is an override: a pin is exactly what it exists to get past."""
    imp = Import(
        {"url": "https://github.com/partcad/partcad-index.git", "revision": "0.8.0"},
        FakeUserConfig(devel_pub=True),
    )
    assert imp.import_revision == consts.PUB_INDEX_DEVEL_REVISION


def test_a_url_rewritten_by_the_dependency_overrides_is_still_recognized():
    """The url overrides run first, so the redirect has to look at the result.

    Reading the URL as written would redirect an index that the overrides had
    just sent somewhere else, which is the one case where both options are in
    play at once. Only the host is rewritten here, which is what a mirror of the
    index is -- the host is not part of what identifies the repository.
    """
    imp = Import(
        {"url": "https://github.com/partcad/partcad-index.git"},
        FakeUserConfig(
            devel_pub=True,
            url_overrides={"https://git.example.com/": "https://github.com/"},
        ),
    )
    assert imp.import_config_url == "https://git.example.com/partcad/partcad-index.git"
    assert imp.import_revision == consts.PUB_INDEX_DEVEL_REVISION


def test_the_relative_path_within_the_repository_is_left_alone():
    imp = Import(
        {"url": "https://github.com/partcad/partcad-index.git", "relPath": "std"},
        FakeUserConfig(devel_pub=True),
    )
    assert imp.import_rel_path == "std"
    assert imp.import_revision == consts.PUB_INDEX_DEVEL_REVISION
