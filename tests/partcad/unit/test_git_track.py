#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A git dependency stays where it was downloaded until 'pc update' moves its pin.

The contract, end to end against a real repository:

* loading a package never fetches a dependency it has downloaded before -- not
  a day later, not ever -- unless the "force auto-update" setting
  ('forceUpdate') is on;
* 'track:' names the branch a dependency follows, and 'pc update' rewrites its
  'revision:' to where that branch is now, in the 'partcad.yaml' the user owns;
* under 'forceUpdate', loading follows 'track:' past the pin.

The upstream is a repository on the local file system: none of this is about the
transport, and the tests that are cover it over HTTP.
"""

import os
import time
from pathlib import Path

import pygit2
import pytest
import yaml

import partcad as pc
from partcad.actions.package.update import pin_tracked_dependencies, update, workspace_packages
from partcad.project_factory_git import GitImportConfiguration
from partcad.user_config import UserConfig

SIGNATURE = pygit2.Signature("test", "test@example.com")


class Upstream:
    """A repository a package imports, with a 'main' branch that can be moved."""

    def __init__(self, path: Path):
        self.path = path
        path.mkdir()
        self.repo = pygit2.init_repository(str(path), initial_head="main")
        (path / "partcad.yaml").write_text("desc: the dependency\n")
        self.commit("A")

    @property
    def url(self) -> str:
        return self.path.as_posix()

    def head(self) -> str:
        return str(self.repo.head.target)

    def commit(self, text: str) -> str:
        """Move 'main' to a new commit whose 'version.txt' says 'text'."""
        (self.path / "version.txt").write_text(text)
        self.repo.index.add("partcad.yaml")
        self.repo.index.add("version.txt")
        self.repo.index.write()
        parents = [] if self.repo.head_is_unborn else [self.repo.head.target]
        oid = self.repo.create_commit("HEAD", SIGNATURE, SIGNATURE, text, self.repo.index.write_tree(), parents)
        return str(oid)


@pytest.fixture
def upstream(tmp_path):
    return Upstream(tmp_path / "upstream")


@pytest.fixture
def user_config(tmp_path):
    config = UserConfig()
    config.internal_state_dir = str(tmp_path / "state")
    config.force_update = False
    config.offline = False
    return config


@pytest.fixture(autouse=True)
def connected(monkeypatch):
    """Count the connectivity probes, and answer them: the upstream is on disk."""
    probes = []

    def is_connected(self):
        probes.append(True)
        return True

    monkeypatch.setattr(pc.Context, "is_connected", is_connected)
    return probes


def write_package(directory: Path, dependency: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    config = directory / "partcad.yaml"
    config.write_text("dependencies:\n" + dependency)
    return config


def load_version(directory: Path, user_config, name="//dep") -> str:
    ctx = pc.Context(str(directory), search_root=False, user_config=user_config)
    project = ctx.get_project(name)
    assert project is not None, "%s did not load" % name
    return (Path(project.config_dir) / "version.txt").read_text()


def dependency(upstream, **fields) -> str:
    text = "  dep:\n    type: git\n    url: '%s'\n" % upstream.url
    for key, value in fields.items():
        text += "    %s: %s\n" % (key, value)
    return text


def age_every_copy(user_config, seconds):
    """Make every downloaded copy look as old as 'seconds' to whatever reads its timestamps."""
    git_dir = Path(user_config.internal_state_dir) / "git"
    then = time.time() - seconds
    for guard in git_dir.glob("*/.partcad.git.cloned"):
        os.utime(guard, (then, then))


# ---- loading ------------------------------------------------------------------


def test_a_downloaded_branch_is_not_fetched_again_a_day_later(tmp_path, upstream, user_config, connected):
    """The refresh that used to happen to any copy older than a day is gone."""
    workspace = tmp_path / "ws"
    write_package(workspace, dependency(upstream, revision="main"))
    assert load_version(workspace, user_config) == "A"

    upstream.commit("B")
    age_every_copy(user_config, 3 * 24 * 3600)
    connected.clear()

    assert load_version(workspace, user_config) == "A"
    # Not even asked whether there is a network: nothing here needs one.
    assert connected == []


def test_a_default_branch_import_is_not_fetched_again_either(tmp_path, upstream, user_config):
    workspace = tmp_path / "ws"
    write_package(workspace, dependency(upstream))
    assert load_version(workspace, user_config) == "A"

    upstream.commit("B")
    age_every_copy(user_config, 3 * 24 * 3600)

    assert load_version(workspace, user_config) == "A"


def test_track_without_a_pin_is_downloaded_once_at_the_branch(tmp_path, upstream, user_config):
    workspace = tmp_path / "ws"
    write_package(workspace, dependency(upstream, track="main"))
    assert load_version(workspace, user_config) == "A"

    upstream.commit("B")
    assert load_version(workspace, user_config) == "A"


def test_the_pin_is_what_is_loaded_not_the_branch_it_tracks(tmp_path, upstream, user_config):
    first = upstream.repo.head.target
    upstream.commit("B")
    workspace = tmp_path / "ws"
    write_package(workspace, dependency(upstream, track="main", revision=str(first)))

    assert load_version(workspace, user_config) == "A"


def test_force_auto_update_follows_the_branch_past_the_pin(tmp_path, upstream, user_config):
    first = str(upstream.repo.head.target)
    workspace = tmp_path / "ws"
    config = write_package(workspace, dependency(upstream, track="main", revision=first))
    assert load_version(workspace, user_config) == "A"

    upstream.commit("B")
    user_config.force_update = True
    assert load_version(workspace, user_config) == "B"

    upstream.commit("C")
    assert load_version(workspace, user_config) == "C"
    # It is the loading that followed the branch: the pin is where it was.
    assert "revision: %s" % first in config.read_text()

    user_config.force_update = False
    assert load_version(workspace, user_config) == "A"


def test_force_auto_update_refreshes_an_old_style_branch(tmp_path, upstream, user_config):
    workspace = tmp_path / "ws"
    write_package(workspace, dependency(upstream, revision="main"))
    assert load_version(workspace, user_config) == "A"

    upstream.commit("B")
    user_config.force_update = True
    assert load_version(workspace, user_config) == "B"


def test_an_unfinished_download_is_downloaded_again(tmp_path, upstream, user_config):
    """A copy without the marker the clone writes last is not built from."""
    workspace = tmp_path / "ws"
    write_package(workspace, dependency(upstream, revision="main"))
    assert load_version(workspace, user_config) == "A"

    (guard,) = (Path(user_config.internal_state_dir) / "git").glob("*/.partcad.git.cloned")
    (guard.parent / "version.txt").write_text("half of A")
    guard.unlink()
    upstream.commit("B")

    assert load_version(workspace, user_config) == "B"


# ---- pc update ----------------------------------------------------------------


def run_update(directory: Path, user_config):
    ctx = pc.Context(str(directory), search_root=False, user_config=user_config)
    stats = update(ctx)
    assert ctx.refresh_imports is False, "the refresh must not outlive the update"
    return ctx, stats


def test_update_pins_the_revision_to_the_tip_of_track(tmp_path, upstream, user_config):
    workspace = tmp_path / "ws"
    config = write_package(workspace, dependency(upstream, track="main"))
    assert load_version(workspace, user_config) == "A"

    tip = upstream.commit("B")
    ctx, stats = run_update(workspace, user_config)

    assert stats["pinned"] == 1 and stats["failed"] == 0
    assert config.read_text() == dependency_text(upstream, track="main", revision=tip)
    assert (Path(ctx.get_project("//dep").config_dir) / "version.txt").read_text() == "B"
    # And that is what every later load uses, wherever the branch goes next.
    upstream.commit("C")
    assert load_version(workspace, user_config) == "B"


def dependency_text(upstream, **fields) -> str:
    return "dependencies:\n" + dependency(upstream, **fields)


def test_update_moves_an_existing_pin(tmp_path, upstream, user_config):
    first = str(upstream.repo.head.target)
    workspace = tmp_path / "ws"
    config = write_package(workspace, dependency(upstream, track="main", revision=first))

    tip = upstream.commit("B")
    _, stats = run_update(workspace, user_config)

    assert stats["pinned"] == 1
    assert config.read_text() == dependency_text(upstream, track="main", revision=tip)
    assert load_version(workspace, user_config) == "B"


def test_update_leaves_a_current_pin_alone(tmp_path, upstream, user_config):
    tip = str(upstream.repo.head.target)
    workspace = tmp_path / "ws"
    config = write_package(workspace, dependency(upstream, track="main", revision=tip[:12]))
    before = config.read_text()

    _, stats = run_update(workspace, user_config)

    assert stats == {"pinned": 0, "current": 1, "failed": 0, "count": stats["count"]}
    assert config.read_text() == before


def test_update_still_moves_an_old_style_branch_without_touching_the_file(tmp_path, upstream, user_config):
    workspace = tmp_path / "ws"
    config = write_package(workspace, dependency(upstream, revision="main"))
    before = config.read_text()
    assert load_version(workspace, user_config) == "A"

    upstream.commit("B")
    ctx, stats = run_update(workspace, user_config)

    assert stats["pinned"] == 0
    assert config.read_text() == before
    assert (Path(ctx.get_project("//dep").config_dir) / "version.txt").read_text() == "B"


def test_update_refreshes_what_a_warm_context_has_loaded_already(tmp_path, upstream, user_config):
    """The daemon keeps a context between commands; 'pc update' must not answer from it."""
    workspace = tmp_path / "ws"
    write_package(workspace, dependency(upstream, revision="main"))
    ctx = pc.Context(str(workspace), search_root=False, user_config=user_config)
    assert (Path(ctx.get_project("//dep").config_dir) / "version.txt").read_text() == "A"

    upstream.commit("B")
    update(ctx)

    assert (Path(ctx.get_project("//dep").config_dir) / "version.txt").read_text() == "B"


def pin(directory: Path, user_config):
    """The first half of 'update' alone: what is written, before anything is fetched."""
    return pin_tracked_dependencies(pc.Context(str(directory), search_root=False, user_config=user_config))


def test_update_reports_a_branch_that_does_not_exist(tmp_path, upstream, user_config):
    workspace = tmp_path / "ws"
    config = write_package(workspace, dependency(upstream, track="no-such-branch"))
    before = config.read_text()

    stats = pin(workspace, user_config)

    assert stats["failed"] == 1
    assert config.read_text() == before


def test_update_offline_moves_nothing(tmp_path, upstream, user_config):
    workspace = tmp_path / "ws"
    config = write_package(workspace, dependency(upstream, track="main"))
    before = config.read_text()
    user_config.offline = True

    stats = pin(workspace, user_config)

    assert stats["failed"] == 1 and stats["pinned"] == 0
    assert config.read_text() == before


def test_update_pins_in_every_package_of_the_workspace(tmp_path, upstream, user_config):
    workspace = tmp_path / "ws"
    root_config = write_package(workspace, dependency(upstream, track="main"))
    sub_config = write_package(workspace / "sub", dependency(upstream, track="main"))

    tip = upstream.commit("B")
    _, stats = run_update(workspace, user_config)

    assert stats["pinned"] == 2
    assert "revision: %s" % tip in root_config.read_text()
    assert "revision: %s" % tip in sub_config.read_text()


def test_update_never_edits_a_package_it_imported(tmp_path, upstream, user_config):
    """An imported package's pins are its maintainers' to move, and its files are a cached copy."""
    other = Upstream(tmp_path / "other")
    (upstream.path / "partcad.yaml").write_text(
        "desc: the dependency\ndependencies:\n  nested:\n    type: git\n    url: '%s'\n    track: main\n" % other.url
    )
    upstream.commit("A2")
    workspace = tmp_path / "ws"
    write_package(workspace, dependency(upstream, track="main"))

    ctx, stats = run_update(workspace, user_config)

    assert stats["pinned"] == 1
    assert [p.name for p in workspace_packages(ctx)] == ["//"]
    imported = Path(ctx.get_project("//dep").config_dir) / "partcad.yaml"
    assert "revision" not in imported.read_text()


# ---- what a dependency asks for -----------------------------------------------


class _UserConfig:
    def __init__(self, force_update=False, devel_index=False):
        self.force_update = force_update
        self.devel_index = devel_index

    def get(self, key):
        return None


class _Context:
    def __init__(self, user_config):
        self.user_config = user_config


class _Import(GitImportConfiguration):
    def __init__(self, config, **settings):
        self.config_obj = config
        self.ctx = _Context(_UserConfig(**settings))
        GitImportConfiguration.__init__(self)


URL = "https://example.com/dep.git"
INDEX_URL = "https://github.com/partcad/partcad-index.git"


@pytest.mark.parametrize(
    "config, settings, expected",
    [
        ({"url": URL}, {}, None),
        ({"url": URL, "revision": "abc1234"}, {}, "abc1234"),
        ({"url": URL, "track": "main"}, {}, "main"),
        ({"url": URL, "track": "main", "revision": "abc1234"}, {}, "abc1234"),
        # The "force auto-update": the branch, past the pin.
        ({"url": URL, "track": "main", "revision": "abc1234"}, {"force_update": True}, "main"),
        # Nothing to follow: the pin is all there is.
        ({"url": URL, "revision": "abc1234"}, {"force_update": True}, "abc1234"),
        # 'develIndex' still has the last word on the public index.
        ({"url": INDEX_URL, "track": "main", "revision": "abc1234"}, {"devel_index": True}, "devel"),
        ({"url": INDEX_URL, "track": "main"}, {"devel_index": True, "force_update": True}, "devel"),
    ],
)
def test_which_revision_is_checked_out(config, settings, expected):
    assert _Import(config, **settings).import_revision == expected


# ---- pc add dep -----------------------------------------------------------------


def added(tmp_path, user_config, location, **kwargs):
    workspace = tmp_path / "ws"
    config = write_package(workspace, "")
    ctx = pc.Context(str(workspace), search_root=False, user_config=user_config)
    ok = ctx.get_project(ctx.name).add_import("dep", location, **kwargs)
    return ok, yaml.safe_load(config.read_text())["dependencies"]


def test_add_dep_pins_a_git_dependency_to_the_default_branch(tmp_path, upstream, user_config):
    url = upstream.path.as_uri()
    ok, dependencies = added(tmp_path, user_config, url)

    assert ok
    assert dependencies["dep"] == {"url": url, "type": "git", "track": "main", "revision": upstream.head()}
    assert load_version(tmp_path / "ws", user_config) == "A"


def test_add_dep_tracks_the_branch_it_is_told_to(tmp_path, upstream, user_config):
    side = upstream.repo.branches.local.create("side", upstream.repo.head.peel(pygit2.Commit))
    upstream.commit("B")

    ok, dependencies = added(tmp_path, user_config, upstream.path.as_uri(), track="side")

    assert ok
    assert dependencies["dep"]["track"] == "side"
    assert dependencies["dep"]["revision"] == str(side.target)


def test_add_dep_adds_nothing_it_could_not_pin(tmp_path, upstream, user_config):
    ok, dependencies = added(tmp_path, user_config, upstream.path.as_uri(), track="no-such-branch")

    assert not ok
    assert dependencies is None


def test_add_dep_adds_nothing_offline(tmp_path, upstream, user_config):
    user_config.offline = True
    ok, dependencies = added(tmp_path, user_config, upstream.path.as_uri())

    assert not ok
    assert dependencies is None
