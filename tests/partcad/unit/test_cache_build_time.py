#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Which tiers keep a shape, by how long it took to build.

A tier is worth writing to only if fetching the entry back costs less than
building the shape again: a file read is milliseconds, a memcached or S3 round
trip tens of them. So a shape built faster than a tier's 'min build time' is
kept in this process's memory instead ('cacheFilesMinBuildTime' 10 ms,
'cacheRemoteMinBuildTime' and 'cacheS3MinBuildTime' 50 ms), and a 'basic' one
- built in place, in a fraction of a millisecond - never touches the shape
cache, a thread pool or the log at all.

Timing is never what a test here waits on: the thresholds are set to nought or
to a minute, so a slow runner cannot move a verdict.
"""

import asyncio

import pytest

import partcad as pc
from partcad import cache as pc_cache
from partcad import sync_threads
from partcad.user_config import OPTION_KEYS, UserConfig

PACKAGE = """
sketches:
  ring:
    type: basic
    circle: 5
    inner:
      circle: 3
parts:
  block:
    type: basic
    cuboid: [10, 20, 5]
"""


# --------------------------------------------------------------------------- #
# The settings                                                                #
# --------------------------------------------------------------------------- #


def test_the_thresholds_default_to_ten_milliseconds_locally_and_fifty_remotely():
    config = UserConfig()
    assert config.cache_files_min_build_time == 0.01
    assert config.cache_remote_min_build_time == 0.05
    assert config.cache_s3_min_build_time == 0.05


@pytest.mark.parametrize(
    "variable, attribute",
    [
        ("PC_CACHE_FILES_MIN_BUILD_TIME", "cache_files_min_build_time"),
        ("PC_CACHE_REMOTE_MIN_BUILD_TIME", "cache_remote_min_build_time"),
        ("PC_CACHE_S3_MIN_BUILD_TIME", "cache_s3_min_build_time"),
    ],
)
def test_a_threshold_is_set_from_the_environment(monkeypatch, variable, attribute):
    monkeypatch.setenv(variable, "0.25")
    assert getattr(UserConfig(), attribute) == 0.25
    monkeypatch.setenv(variable, "0")
    assert getattr(UserConfig(), attribute) == 0.0


@pytest.mark.parametrize("value", ["fast", "-1", "inf", "nan"])
def test_a_threshold_that_is_not_a_duration_is_the_default(monkeypatch, value):
    monkeypatch.setenv("PC_CACHE_FILES_MIN_BUILD_TIME", value)
    assert UserConfig().cache_files_min_build_time == 0.01


def test_the_thresholds_travel_with_a_configuration_to_the_daemon():
    for key in ("cacheFilesMinBuildTime", "cacheRemoteMinBuildTime", "cacheS3MinBuildTime"):
        assert key in OPTION_KEYS


# --------------------------------------------------------------------------- #
# Which tiers are offered an entry                                            #
# --------------------------------------------------------------------------- #


class _Tier:
    def __init__(self, name, min_build_seconds):
        self.name = name
        self.min_build_seconds = min_build_seconds
        self.stores_names = False
        self.written = []

    def worth_keeping(self, build_seconds):
        return build_seconds is None or build_seconds >= self.min_build_seconds

    def accepts(self, key, size):
        return True

    async def write_async(self, items):
        self.written.extend(items)
        return {name: True for name in items}


def _cache(*tiers):
    cache = pc_cache.Cache.__new__(pc_cache.Cache)
    cache.data_type = "test"
    cache.backends = list(tiers)
    return cache


class _Hash:
    name = "//pkg:thing"

    def get(self):
        return "0123abcd"


@pytest.mark.parametrize(
    "build_seconds, files, remote",
    [(0.001, False, False), (0.02, True, False), (0.2, True, True), (None, True, True)],
)
def test_a_tier_keeps_what_took_long_enough_to_build(build_seconds, files, remote):
    local, shared = _Tier("files", 0.01), _Tier("remote", 0.05)
    stored = asyncio.run(
        _cache(local, shared).write_data_async(_Hash(), {"part": b"x" * 200}, build_seconds=build_seconds)
    )

    assert bool(local.written) == files
    assert bool(shared.written) == remote
    assert stored.get("part", False) == (files or remote)


# --------------------------------------------------------------------------- #
# A shape built through the cache                                             #
# --------------------------------------------------------------------------- #


@pytest.fixture
def package(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "partcad.yaml").write_text(PACKAGE)
    return tmp_path


def _context(root, **settings):
    config = UserConfig()
    config.internal_state_dir = str(root / "state")
    for name, value in settings.items():
        setattr(config, name, value)
    return pc.Context(str(root / "pkg"), user_config=config)


def _built_through_the_cache(ctx):
    """'block', made to go through the cache as any other part does, and whether the files tier kept it."""
    part = ctx.get_part("block")
    part.built_in_place = False
    envelope = asyncio.run(part.get_wrapped(ctx))
    kept = asyncio.run(ctx.cache_shapes.contains_data_async(part.hash, ["part"])).get("part", False)
    return part, envelope, kept


def test_a_shape_built_faster_than_the_threshold_is_kept_in_memory_only(package):
    part, envelope, kept = _built_through_the_cache(_context(package, cache_files_min_build_time=60.0))

    assert envelope is not None
    assert not kept
    assert part._wrapped is envelope


def test_a_shape_built_slower_than_the_threshold_is_kept_on_disk(package):
    part, envelope, kept = _built_through_the_cache(_context(package, cache_files_min_build_time=0.0))

    assert envelope is not None
    assert kept


def test_a_shape_memory_will_not_hold_is_kept_on_disk_however_fast(package):
    """Built in neither, it would be built on every ask - and an assembly a daemon asked for first never counted as built."""
    _part, envelope, kept = _built_through_the_cache(
        _context(package, cache_files_min_build_time=60.0, cache_memory=False)
    )

    assert envelope is not None
    assert kept


# --------------------------------------------------------------------------- #
# A shape built in place                                                      #
# --------------------------------------------------------------------------- #


def test_a_basic_shape_never_touches_the_shape_cache_a_pool_or_the_log(package, monkeypatch):
    ctx = _context(package, cache_files_min_build_time=0.0)

    def refuse(*args, **kwargs):
        raise AssertionError("a basic shape went to the shape cache or a thread pool")

    monkeypatch.setattr(ctx.cache_shapes, "read_async", refuse)
    monkeypatch.setattr(ctx.cache_shapes, "write_async", refuse)
    monkeypatch.setattr(sync_threads.threadpool_manager, "run_async", refuse)

    actions = []
    original = pc.logging.Action.__init__

    def recording(self, op, package, item=None, extra=None):
        actions.append((op, item))
        original(self, op, package, item, extra)

    monkeypatch.setattr(pc.logging.Action, "__init__", recording)

    for shape in (ctx.get_part("block"), ctx.get_sketch("ring")):
        assert shape.built_in_place
        envelope = asyncio.run(shape.get_wrapped(ctx))
        assert envelope is not None
        assert shape._wrapped is envelope
        # Still keyed, for what is derived from it: a render, a tessellation, a verdict.
        assert shape.hash.get() is not None

    assert [action for action in actions if action[1] in ("block", "ring")] == []
