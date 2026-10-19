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

import gc
import itertools
import os
import subprocess
import sys
import time
from pathlib import Path

import pygit2
import pytest
import yaml

import partcad as pc
from partcad import project_factory_git as rfg
from partcad.actions.package.update import pin_tracked_dependencies, update, workspace_packages
from partcad.project_factory_git import GitImportConfiguration, cache_dir_name, get_clone_options
from partcad.revision import package_revision
from partcad.user_config import UserConfig
from partcad_utils import config_yaml

# At a fixed time, so that every commit id below is the same in every run: a
# test whose outcome depends on what an id looks like fails every time or never.
SIGNATURE = pygit2.Signature("test", "test@example.com", 1767225600, 0)


def digits(sha: str) -> bool:
    """An id whose first 12 characters YAML reads as an int, and as the int they say.

    About one in three hundred. 'revision: 875940244746' was read as a number,
    which the git import then failed on as an 'int' with no 'strip'.
    """
    return sha[:12].isdigit() and sha[0] != "0"


def mixed(sha: str) -> bool:
    """An id whose first 12 characters have a hex letter in them, which YAML reads as text."""
    return not sha[:12].isdigit()


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

    def commit(self, text: str, shape=None) -> str:
        """Move 'main' to a new commit whose 'version.txt' says 'text'.

        With 'shape', to one whose id 'shape' accepts. An id is a hash, so one
        of a given shape is found by asking: the message is varied until the
        id comes out right, which takes a few hundred tries for 'digits'.
        """
        (self.path / "version.txt").write_text(text)
        self.repo.index.add("partcad.yaml")
        self.repo.index.add("version.txt")
        self.repo.index.write()
        tree = self.repo.index.write_tree()
        parents = [] if self.repo.head_is_unborn else [self.repo.head.target]
        for attempt in itertools.count():
            message = text if attempt == 0 else "%s (%d)" % (text, attempt)
            oid = self.repo.create_commit(None, SIGNATURE, SIGNATURE, message, tree, parents)
            if shape is None or shape(str(oid)):
                break
        self.repo.references.create("refs/heads/main", oid, force=True)
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


def test_a_pin_of_digits_alone_is_the_commit_it_names(tmp_path, upstream, user_config):
    """'revision: 875940244746' is an int to YAML, and has to be read as the commit all the same."""
    wanted = upstream.commit("B", shape=digits)
    upstream.commit("C")
    workspace = tmp_path / "ws"
    write_package(workspace, dependency(upstream, track="main", revision=wanted[:12]))
    assert isinstance(yaml.safe_load((workspace / "partcad.yaml").read_text())["dependencies"]["dep"]["revision"], int)

    assert load_version(workspace, user_config) == "B"


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


@pytest.mark.parametrize("shape", [mixed, digits])
def test_update_leaves_a_current_pin_alone(tmp_path, upstream, user_config, shape):
    """An abbreviated pin at the tip of its branch, written plain: as text, or as the int YAML reads digits as."""
    tip = upstream.commit("B", shape=shape)
    workspace = tmp_path / "ws"
    config = write_package(workspace, dependency(upstream, track="main", revision=tip[:12]))
    before = config.read_text()

    _, stats = run_update(workspace, user_config)

    assert stats == {"pinned": 0, "current": 1, "failed": 0, "count": stats["count"]}
    assert config.read_text() == before


# A whole commit id of decimal digits alone: one in about 150 million, so not
# one a test can make, but the one whose plain text YAML reads as a number.
DIGITS = "8759402447468759402447468759402447468759"

# Spelled the way YAML 1.1 reads as an int, and as one that is not the name:
# 1000, 83, 31, 5 and 90.
SPELLED_LIKE_INTS = ["1_000", "0123", "0x1f", "0b101", "1:30"]


def test_update_writes_a_pin_of_digits_that_is_read_back_as_the_pin(tmp_path, upstream, user_config, monkeypatch):
    workspace = tmp_path / "ws"
    config = write_package(workspace, dependency(upstream, track="main"))
    monkeypatch.setattr(rfg, "tracked_commit", lambda user_config, url, track=None: (track, DIGITS))

    assert pin(workspace, user_config) == {"pinned": 1, "current": 0, "failed": 0}
    assert "    revision: '%s'\n" % DIGITS in config.read_text()
    assert yaml.safe_load(config.read_text())["dependencies"]["dep"]["revision"] == DIGITS

    # And, read back, it is where the branch is: nothing to move, nothing written.
    before = config.read_text()
    assert pin(workspace, user_config) == {"pinned": 0, "current": 1, "failed": 0}
    assert config.read_text() == before


@pytest.mark.parametrize("track", ["2024"] + SPELLED_LIKE_INTS)
def test_update_reads_a_track_of_digits_as_the_branch_it_names(tmp_path, upstream, user_config, monkeypatch, track):
    workspace = tmp_path / "ws"
    write_package(workspace, dependency(upstream, track=track))
    asked = []
    monkeypatch.setattr(
        rfg, "tracked_commit", lambda user_config, url, track=None: asked.append(track) or (track, DIGITS)
    )

    assert pin(workspace, user_config)["pinned"] == 1
    assert asked == [track]


# A branch or a tag name YAML reads as an int, and a decoy named after that int:
# what PartCAD would have asked for, had it gone by the int.
NAMED_LIKE_INTS = [("1_000", "1000"), ("0123", "83"), ("0x1f", "31")]


def named(upstream, kind: str, name: str, decoy: str) -> str:
    """Make 'name' a branch or a tag at a new commit, and 'decoy' one at the commit after; 'main' moves on past both."""
    wanted = upstream.commit("wanted")
    upstream.repo.references.create("refs/%s/%s" % (kind, name), pygit2.Oid(hex=wanted))
    decoyed = upstream.commit("decoy")
    upstream.repo.references.create("refs/%s/%s" % (kind, decoy), pygit2.Oid(hex=decoyed))
    upstream.commit("main")
    return wanted


@pytest.mark.parametrize("name, decoy", NAMED_LIKE_INTS)
def test_a_track_spelled_like_an_int_is_the_branch_of_that_name(tmp_path, upstream, user_config, name, decoy):
    """'track: 1_000' is branch '1_000', not the branch '1000' that YAML's int would name."""
    named(upstream, "heads", name, decoy)
    workspace = tmp_path / "ws"
    write_package(workspace, dependency(upstream, track=name))

    assert load_version(workspace, user_config) == "wanted"


@pytest.mark.parametrize("name, decoy", NAMED_LIKE_INTS)
def test_update_pins_a_track_spelled_like_an_int_to_the_branch_of_that_name(
    tmp_path, upstream, user_config, name, decoy
):
    wanted = named(upstream, "heads", name, decoy)
    workspace = tmp_path / "ws"
    config = write_package(workspace, dependency(upstream, track=name))

    ctx, stats = run_update(workspace, user_config)

    assert stats["pinned"] == 1 and stats["failed"] == 0
    assert config.read_text() == dependency_text(upstream, track=name, revision=wanted)
    assert (Path(ctx.get_project("//dep").config_dir) / "version.txt").read_text() == "wanted"


@pytest.mark.parametrize("name, decoy", [("2024", "2023")] + NAMED_LIKE_INTS)
def test_a_revision_naming_a_tag_spelled_like_an_int_is_that_tag(tmp_path, upstream, user_config, name, decoy):
    named(upstream, "tags", name, decoy)
    workspace = tmp_path / "ws"
    write_package(workspace, dependency(upstream, revision=name))

    assert load_version(workspace, user_config) == "wanted"


def test_update_refuses_a_track_whose_text_yaml_lost(tmp_path, upstream, user_config, caplog):
    workspace = tmp_path / "ws"
    config = write_package(workspace, dependency(upstream, track="1.10"))
    before = config.read_text()

    with caplog.at_level("ERROR"):
        stats = pin(workspace, user_config)

    assert stats["failed"] == 1 and stats["pinned"] == 0
    assert config.read_text() == before
    assert "float 1.1" in caplog.text and "quote it" in caplog.text


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


@pytest.mark.parametrize(
    "config, settings, expected",
    [
        ({"url": URL}, {}, None),
        ({"url": URL, "revision": "abc1234"}, {}, "abc1234"),
        # One copy per tracked branch, moved from pin to pin.
        ({"url": URL, "track": "main"}, {}, "main"),
        ({"url": URL, "track": "main", "revision": "abc1234"}, {}, "main"),
        ({"url": URL, "track": "main", "revision": "abc1234"}, {"force_update": True}, "main"),
        # The index under 'develIndex' has its own, so toggling it moves nothing.
        ({"url": INDEX_URL, "track": "main", "revision": "abc1234"}, {"devel_index": True}, "devel"),
    ],
)
def test_which_copy_it_is_kept_in(config, settings, expected):
    assert _Import(config, **settings).import_cache_name == expected


def read(text: str, **settings):
    """What a dependency declared as 'text' asks for, read as 'ProjectLocal' reads 'partcad.yaml'."""
    return _Import(config_yaml.load("name: //dep\nurl: %s\n%s" % (URL, text)), **settings)


@pytest.mark.parametrize(
    "written, expected, commit",
    [
        ("87594a244746", "87594a244746", True),
        # An int to YAML, and its decimal text is what was written.
        ("875940244746", "875940244746", True),
        (DIGITS, DIGITS, True),
        ("'875940244746'", "875940244746", True),
        # An octal-looking commit id: 21913025 to YAML.
        ("0123456701", "0123456701", True),
        # Text to YAML already, however numeric they look.
        ("123e4567", "123e4567", True),
        ("0189abcdef", "0189abcdef", True),
        # A tag named like a number, which YAML reads as one.
        ("2024", "2024", False),
    ]
    + [(written, written, False) for written in SPELLED_LIKE_INTS],
)
def test_a_revision_is_read_as_the_text_it_was_written_as(written, expected, commit):
    imported = read("revision: %s\n" % written)
    assert imported.import_revision == expected
    assert imported.import_cache_name == expected
    # Which is what decides how it is downloaded: by its id, as a commit, or by name.
    assert get_clone_options(imported.import_revision).single_commit is commit


@pytest.mark.parametrize(
    "written, expected",
    [("main", "main"), ("2024", "2024"), ("'2024'", "2024")] + [(written, written) for written in SPELLED_LIKE_INTS],
)
def test_a_track_is_read_as_the_text_it_was_written_as(written, expected):
    imported = read("track: %s\n" % written)
    assert imported.import_track == expected
    assert imported.import_revision == expected
    assert imported.import_cache_name == expected


@pytest.mark.parametrize(
    "written, read_as",
    [("1.10", "the float 1.1"), ("yes", "the bool True"), ("2024-01-01", "the date 2024-01-01")],
)
@pytest.mark.parametrize("key", ["revision", "track"])
def test_a_value_whose_text_yaml_lost_is_refused_with_the_fix(key, written, read_as):
    with pytest.raises(ValueError) as error:
        read("%s: %s\n" % (key, written))
    message = str(error.value)
    assert "'%s:' of //dep" % key in message and read_as in message
    assert "quote it" in message


# ---- the copy of a tracked branch -----------------------------------------------


def copies(user_config, upstream) -> list[str]:
    """The names of the downloaded copies of 'upstream' (or of the url it is), without the hash they share."""
    prefix = cache_dir_name(getattr(upstream, "url", upstream), None)
    git_dir = Path(user_config.internal_state_dir) / "git"
    return sorted(
        p.name[len(prefix) :] for p in git_dir.glob(prefix + "*") if p.is_dir() and not p.name.endswith(".claims")
    )


def head_of(path) -> str:
    return str(pygit2.Repository(pygit2.discover_repository(str(path))).head.target)


def test_a_pinned_dependency_is_kept_in_the_copy_of_its_branch(tmp_path, upstream, user_config):
    first = upstream.head()
    upstream.commit("B")
    workspace = tmp_path / "ws"
    write_package(workspace, dependency(upstream, track="main", revision=first))

    assert load_version(workspace, user_config) == "A"
    assert copies(user_config, upstream) == ["-main"]


def test_update_moves_the_copy_rather_than_adding_one(tmp_path, upstream, user_config):
    workspace = tmp_path / "ws"
    write_package(workspace, dependency(upstream, track="main", revision=upstream.head()))
    assert load_version(workspace, user_config) == "A"

    tip = upstream.commit("B")
    ctx, _ = run_update(workspace, user_config)

    assert copies(user_config, upstream) == ["-main"]
    project = ctx.get_project("//dep")
    assert (Path(project.config_dir) / "version.txt").read_text() == "B"
    assert head_of(project.config_dir) == tip


def test_a_warm_context_moves_the_copy_and_reports_the_new_revision(tmp_path, upstream, user_config):
    """A daemon keeps the context, the copy keeps its path, and neither may answer with the old commit."""
    workspace = tmp_path / "ws"
    write_package(workspace, dependency(upstream, track="main", revision=upstream.head()))
    ctx = pc.Context(str(workspace), search_root=False, user_config=user_config)
    first = ctx.get_project("//dep")
    assert package_revision(first) == upstream.head()

    tip = upstream.commit("B")
    update(ctx)

    project = ctx.get_project("//dep")
    assert project.config_dir == first.config_dir
    assert (Path(project.config_dir) / "version.txt").read_text() == "B"
    assert package_revision(project) == tip


def test_loading_moves_the_copy_back_to_the_pin_after_a_forced_update(tmp_path, upstream, user_config):
    first = upstream.head()
    workspace = tmp_path / "ws"
    write_package(workspace, dependency(upstream, track="main", revision=first))
    upstream.commit("B")

    user_config.force_update = True
    assert load_version(workspace, user_config) == "B"
    user_config.force_update = False
    assert load_version(workspace, user_config) == "A"
    assert copies(user_config, upstream) == ["-main"]


def test_two_pins_of_one_branch_in_one_context_do_not_share_the_copy(tmp_path, upstream, user_config):
    """Moving the copy for the second would change the files under the first."""
    first = upstream.head()
    second = upstream.commit("B")
    workspace = tmp_path / "ws"
    write_package(
        workspace,
        dependency(upstream, track="main", revision=first)
        + dependency(upstream, track="main", revision=second).replace("  dep:", "  other:"),
    )
    ctx = pc.Context(str(workspace), search_root=False, user_config=user_config)

    dep = ctx.get_project("//dep")
    other = ctx.get_project("//other")

    assert (Path(dep.config_dir) / "version.txt").read_text() == "A"
    assert (Path(other.config_dir) / "version.txt").read_text() == "B"
    assert copies(user_config, upstream) == sorted(["-main", "-" + second])


def pinned_context(directory: Path, upstream, user_config, revision):
    """A warm context, as a daemon serving the workspace in 'directory' keeps one, with '//dep' loaded."""
    write_package(directory, dependency(upstream, track="main", revision=revision))
    ctx = pc.Context(str(directory), search_root=False, user_config=user_config)
    assert ctx.get_project("//dep") is not None
    return ctx


def test_a_copy_another_context_is_pinned_to_is_not_moved_under_it(tmp_path, upstream, user_config):
    """Two workspaces open at once, pinned to two commits of one branch, each served by a daemon of its own."""
    first = upstream.head()
    second = upstream.commit("B")
    one = pinned_context(tmp_path / "one", upstream, user_config, first)

    two = pinned_context(tmp_path / "two", upstream, user_config, second)

    # What the first reads lazily is still the commit it is pinned to.
    assert (Path(one.get_project("//dep").config_dir) / "version.txt").read_text() == "A"
    assert (Path(two.get_project("//dep").config_dir) / "version.txt").read_text() == "B"
    assert copies(user_config, upstream) == sorted(["-main", "-" + second])


def test_a_claim_goes_with_the_context(tmp_path, upstream, user_config):
    """A context nobody holds any more claims nothing, collected or not."""
    first = upstream.head()
    second = upstream.commit("B")
    pinned_context(tmp_path / "one", upstream, user_config, first)  # and dropped

    two = pinned_context(tmp_path / "two", upstream, user_config, second)

    assert (Path(two.get_project("//dep").config_dir) / "version.txt").read_text() == "B"
    assert copies(user_config, upstream) == ["-main"]
    claims = Path(user_config.internal_state_dir) / "git" / (cache_dir_name(upstream.url, "main") + ".claims")
    assert [p.name.split(".")[0] for p in claims.iterdir()] == [second]


def test_contexts_that_agree_on_the_pin_cost_no_collection(tmp_path, upstream, user_config, monkeypatch):
    """A daemon keeps a context per directory it is asked about; most of them pin what the others do."""
    first = upstream.head()
    one = pinned_context(tmp_path / "one", upstream, user_config, first)

    collections = []
    collect = gc.collect
    monkeypatch.setattr(gc, "collect", lambda *args: collections.append(args) or collect(*args))
    two = pinned_context(tmp_path / "two", upstream, user_config, first)

    assert collections == []
    assert one.get_project("//dep").config_dir == two.get_project("//dep").config_dir


@pytest.mark.timeout(300)
def test_a_claim_goes_with_the_process_that_held_it(tmp_path, upstream, user_config):
    """Another process holds a claim until it ends, however it ends: killed, it leaves the file, not the claim."""
    first = upstream.head()
    second = upstream.commit("B")
    pinned_context(tmp_path / "one", upstream, user_config, first)  # downloaded, so the other process needs no network

    log_path = tmp_path / "holder.log"
    log = open(log_path, "w")
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys\n"
            "import partcad as pc\n"
            "from partcad.user_config import UserConfig\n"
            "config = UserConfig()\n"
            "config.internal_state_dir = sys.argv[2]\n"
            "config.force_update = False\n"
            "config.offline = False\n"
            "ctx = pc.Context(sys.argv[1], search_root=False, user_config=config)\n"
            "assert ctx.get_project('//dep') is not None\n"
            "print('loaded', flush=True)\n"
            "sys.stdin.read()\n",
            str(tmp_path / "one"),
            user_config.internal_state_dir,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        # A file, not a pipe: nobody reads it until the end, and a pipe that
        # fills up with the holder's logs would stop it before it says 'loaded'.
        stderr=log,
        text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "loaded", log_path.read_text()

        pinned_context(tmp_path / "two", upstream, user_config, second)
        assert copies(user_config, upstream) == sorted(["-main", "-" + second])
        assert head_of(Path(user_config.internal_state_dir) / "git" / cache_dir_name(upstream.url, "main")) == first
    finally:
        holder.kill()
        holder.wait()
        holder.stdin.close()
        holder.stdout.close()
        log.close()

    three = pinned_context(tmp_path / "three", upstream, user_config, second)
    assert head_of(Path(three.get_project("//dep").config_dir)) == second
    assert Path(three.get_project("//dep").config_dir).name == cache_dir_name(upstream.url, "main")


def test_an_unpinned_copy_another_context_is_built_from_is_not_moved_under_it(tmp_path, upstream, user_config):
    """'pc init' offline tracks the index with no pin yet: the commit it was downloaded at is the one it reads from."""
    write_package(tmp_path / "one", dependency(upstream, track="main"))
    one = pc.Context(str(tmp_path / "one"), search_root=False, user_config=user_config)
    assert one.get_project("//dep") is not None
    second = upstream.commit("B")

    pinned_context(tmp_path / "two", upstream, user_config, second)

    assert (Path(one.get_project("//dep").config_dir) / "version.txt").read_text() == "A"
    assert copies(user_config, upstream) == sorted(["-main", "-" + second])


def test_force_auto_update_follows_the_branch_past_a_claimed_copy_in_one_of_its_own(tmp_path, upstream, user_config):
    first = upstream.head()
    one = pinned_context(tmp_path / "one", upstream, user_config, first)
    tip = upstream.commit("B")

    user_config.force_update = True
    assert load_version(tmp_path / "one", user_config) == "B"

    assert (Path(one.get_project("//dep").config_dir) / "version.txt").read_text() == "A"
    assert copies(user_config, upstream) == sorted(["-main", "-" + tip])


def test_force_auto_update_uses_a_claimed_copy_that_is_where_the_branch_is(tmp_path, upstream, user_config):
    one = pinned_context(tmp_path / "one", upstream, user_config, upstream.head())

    user_config.force_update = True
    assert load_version(tmp_path / "one", user_config) == "A"

    assert copies(user_config, upstream) == ["-main"]
    assert one.get_project("//dep") is not None


def test_force_auto_update_offline_leaves_a_claimed_copy_and_says_so(
    tmp_path, upstream, user_config, monkeypatch, caplog
):
    first = upstream.head()
    one = pinned_context(tmp_path / "one", upstream, user_config, first)
    upstream.commit("B")

    monkeypatch.setattr(pc.Context, "is_connected", lambda self: False)
    user_config.force_update = True
    with caplog.at_level("WARNING"):
        version = load_version(tmp_path / "one", user_config)

    assert version == "A"
    assert (Path(one.get_project("//dep").config_dir) / "version.txt").read_text() == "A"
    assert "Not updating" in caplog.text and first in caplog.text


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


def test_add_dep_writes_what_is_read_back_as_text(tmp_path, upstream, user_config, monkeypatch):
    """A commit id of digits alone, and a branch YAML 1.1 reads as a bool, both written to be read as text."""
    monkeypatch.setattr(rfg, "tracked_commit", lambda user_config, url, track=None: ("on", DIGITS))

    ok, dependencies = added(tmp_path, user_config, upstream.path.as_uri())

    assert ok
    assert dependencies["dep"]["track"] == "on"
    assert dependencies["dep"]["revision"] == DIGITS


def test_add_dep_adds_nothing_it_could_not_pin(tmp_path, upstream, user_config):
    ok, dependencies = added(tmp_path, user_config, upstream.path.as_uri(), track="no-such-branch")

    assert not ok
    assert dependencies is None


def test_add_dep_adds_nothing_offline(tmp_path, upstream, user_config):
    user_config.offline = True
    ok, dependencies = added(tmp_path, user_config, upstream.path.as_uri())

    assert not ok
    assert dependencies is None


# ---- pc init --------------------------------------------------------------------

INDEX_URL = "https://github.com/partcad/partcad-index.git"


def initialized(tmp_path, user_config, upstream=None):
    """Create a public package; the template's index is served by 'upstream', if given."""
    if upstream is not None:
        user_config.set("dependencies.overrides.url", {upstream.path.as_uri(): INDEX_URL})
    config = tmp_path / "ws" / "partcad.yaml"
    config.parent.mkdir()
    assert pc.create_package(str(config), {"private": False}, user_config=user_config)
    return config, yaml.safe_load(config.read_text())["dependencies"]["pub"]


def test_init_pins_the_index_to_the_tip_of_main(tmp_path, upstream, user_config):
    # As the real index is: its default branch is 'devel', which is ahead of or
    # behind the released 'main' -- and 'main' is what a new package gets.
    unreleased = upstream.repo.head.peel(pygit2.Commit)
    released = upstream.commit("B")
    upstream.repo.branches.local.create("devel", unreleased)
    upstream.repo.set_head("refs/heads/devel")

    config, pub = initialized(tmp_path, user_config, upstream)

    # The URL the package is published with, not the one that answered.
    assert pub == {"type": "git", "url": INDEX_URL, "track": "main", "revision": released}
    # Written the way 'pc update' writes it, so the template's comments survive.
    assert "track: main\n    revision: %s\n" % released in config.read_text()
    assert "# Add dependencies here" in config.read_text()


def test_init_offline_creates_the_package_tracking_main_unpinned(tmp_path, user_config, caplog):
    user_config.offline = True

    _, pub = initialized(tmp_path, user_config)

    assert pub == {"type": "git", "url": INDEX_URL, "track": "main"}
    assert "Run 'pc update' to pin it" in caplog.text


def test_init_creates_the_package_unpinned_when_the_branch_cannot_be_found(tmp_path, upstream, user_config, caplog):
    upstream.repo.branches.local["main"].rename("trunk")

    _, pub = initialized(tmp_path, user_config, upstream)

    assert "revision" not in pub and pub["track"] == "main"
    assert "There is no branch 'main'" in caplog.text and "Run 'pc update' to pin it" in caplog.text


def test_a_pin_the_remote_does_not_have_keeps_the_copy_and_says_why(tmp_path, upstream, user_config, caplog):
    """A commit that is not there cannot be checked out, and that is no reason to lose the copy that is."""
    workspace = tmp_path / "ws"
    config = write_package(workspace, dependency(upstream, track="main", revision=upstream.head()))
    assert load_version(workspace, user_config) == "A"

    missing = "0123456789abcdef0123456789abcdef01234567"
    config.write_text(dependency_text(upstream, track="main", revision=missing))
    with caplog.at_level("WARNING"):
        version = load_version(workspace, user_config)

    assert version == "A"
    assert copies(user_config, upstream) == ["-main"]
    assert missing in caplog.text


def test_a_server_that_will_not_serve_a_commit_by_id_still_gets_the_copy_moved(tmp_path, user_config):
    """The copy is downloaded again beside itself, and replaced once that has worked.

    Over HTTP and protocol v0, with 'uploadpack.allowReachableSHA1InWant' off:
    the server that refuses a commit asked for by its id. A local remote serves
    it either way, so it could not reach this path.
    """
    from git_http_server import mirror, serve_git

    work = Upstream(tmp_path / "work")
    root = tmp_path / "srv"
    root.mkdir()
    served = root / "upstream.git"
    mirror(work.path, served)
    pygit2.Repository(str(served)).config["uploadpack.allowReachableSHA1InWant"] = False

    with serve_git(root, protocol_v2=False) as base_url:
        url = "%s/upstream.git" % base_url
        workspace = tmp_path / "ws"

        def pinned(revision):
            write_package(
                workspace, "  dep:\n    type: git\n    url: '%s'\n    track: main\n    revision: %s\n" % (url, revision)
            )

        pinned(work.head())
        assert load_version(workspace, user_config) == "A"

        # Two more commits, and the pin moves to the first: neither downloaded
        # yet nor the tip of a branch, so nothing but its id names it.
        wanted = work.commit("B")
        work.commit("C")
        pygit2.Repository(str(served)).remotes.create_anonymous(str(work.path)).fetch(
            ["+refs/heads/main:refs/heads/main"]
        )
        pinned(wanted)

        assert load_version(workspace, user_config) == "B"

    assert copies(user_config, url) == ["-main"]


@pytest.fixture
def windows_deletes(monkeypatch):
    """Delete files the way Windows does, which refuses two kinds of file.

    One without its write bit: libgit2 writes a repository's objects read-only,
    and 'shutil.rmtree(..., ignore_errors=True)' gave up on them in silence,
    leaving half a repository behind.

    And one this process has open or mapped: a repository object nobody let go
    of keeps its pack files mapped, and removing its directory then leaves them
    there too. Which files those are is read off '/proc/self', so that part is
    checked where there is one; on Windows itself both rules hold anyway.
    """
    import stat

    real_unlink = os.unlink
    proc = "/proc/self"

    def in_use():
        if not os.path.isdir(proc):
            return set()
        paths = set()
        for fd in os.listdir(os.path.join(proc, "fd")):
            try:
                paths.add(os.readlink(os.path.join(proc, "fd", fd)))
            except OSError:
                pass
        with open(os.path.join(proc, "maps")) as maps:
            for line in maps:
                fields = line.split(None, 5)
                if len(fields) == 6 and fields[5].startswith("/"):
                    paths.add(fields[5].strip())
        return paths

    def unlink(path, *, dir_fd=None):
        if not os.stat(path, dir_fd=dir_fd, follow_symlinks=False).st_mode & stat.S_IWRITE:
            raise PermissionError(13, "Access is denied", path)
        full = path
        if dir_fd is not None and os.path.isdir(proc):
            full = os.path.join(os.readlink(os.path.join(proc, "fd", str(dir_fd))), path)
        if os.path.abspath(full) in in_use():
            raise PermissionError(32, "The process cannot access the file because it is being used", path)
        real_unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(os, "unlink", unlink)
    monkeypatch.setattr(os, "remove", unlink)


def test_an_unfinished_download_with_read_only_objects_is_downloaded_again(
    tmp_path, upstream, user_config, windows_deletes
):
    test_an_unfinished_download_is_downloaded_again(tmp_path, upstream, user_config)


def test_the_copy_moved_by_a_new_download_with_read_only_objects(tmp_path, user_config, windows_deletes):
    test_a_server_that_will_not_serve_a_commit_by_id_still_gets_the_copy_moved(tmp_path, user_config)


def test_a_pin_the_remote_does_not_have_with_files_windows_will_not_delete(
    tmp_path, upstream, user_config, caplog, windows_deletes
):
    test_a_pin_the_remote_does_not_have_keeps_the_copy_and_says_why(tmp_path, upstream, user_config, caplog)


def test_a_pin_no_server_has_leaves_no_download_behind(tmp_path, user_config, windows_deletes):
    """Over HTTP the failed download has a pack open when it is cleared away, and must let go of it first."""
    from git_http_server import mirror, serve_git

    work = Upstream(tmp_path / "work")
    root = tmp_path / "srv"
    root.mkdir()
    served = root / "upstream.git"
    mirror(work.path, served)
    pygit2.Repository(str(served)).config["uploadpack.allowReachableSHA1InWant"] = False

    with serve_git(root, protocol_v2=False) as base_url:
        url = "%s/upstream.git" % base_url
        workspace = tmp_path / "ws"

        def pinned(revision):
            write_package(
                workspace, "  dep:\n    type: git\n    url: '%s'\n    track: main\n    revision: %s\n" % (url, revision)
            )

        pinned(work.head())
        assert load_version(workspace, user_config) == "A"

        pinned("0123456789abcdef0123456789abcdef01234567")
        assert load_version(workspace, user_config) == "A"

    assert copies(user_config, url) == ["-main"]
