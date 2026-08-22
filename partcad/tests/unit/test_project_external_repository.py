#!/usr/bin/env python3
#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for plugin-backed packages (ProjectExternalRepository).

These inject a fake repository in place of the plugin subprocess/endpoint, so
the lazy object-access layer is exercised without a runtime or a CAD kernel.
"""

import asyncio
import shutil

import partcad as pc
from partcad.cache import Cache
from partcad.cache_backend_files import FilesCacheBackend
from partcad.project_external_repository import ProjectExternalRepository


class FakeRepository:
    """Stands in for a repository plugin; records the keys it is asked for."""

    def __init__(self, data):
        self.data = data
        self.keys = []

    async def get_data(self, key):
        self.keys.append(key)
        return self.data.get(key)


def _make_repo(ctx, data):
    repo = ProjectExternalRepository(ctx, "//ext", "/tmp/ext", config_obj={})
    fake = FakeRepository(data)
    repo._repository = fake
    return repo, fake


def test_request_memoizes_by_key():
    ctx = pc.Context("examples")
    repo, _ = _make_repo(ctx, {})
    calls = []
    handler = lambda: (calls.append(1), ["a", "b"])[1]
    assert repo.request("k", handler) == ["a", "b"]
    assert repo.request("k", handler) == ["a", "b"]
    assert len(calls) == 1  # handler invoked once


def test_construction_defers_everything():
    ctx = pc.Context("examples")
    repo, fake = _make_repo(ctx, {"objects/part": {"bolt": {"type": "step"}}})
    # Nothing is enumerated, instantiated or fetched at construction: not the
    # object configs, and not even a single request to the repository.
    assert repo._object_configs["part"] is None
    assert fake.keys == []


def test_accessing_parts_enumerates_lazily():
    # Objects are enumerated the first time a package's 'parts' are accessed,
    # not eagerly at load, so a large repository stays cheap to import.
    ctx = pc.Context("examples")
    repo, fake = _make_repo(ctx, {"objects/part": {"bolt": {"type": "step"}}})
    assert fake.keys == []
    _ = repo.parts  # first access triggers enumeration
    assert "objects/part" in fake.keys


def test_enumeration_is_lazy_and_cached():
    ctx = pc.Context("examples")
    data = {"objects/part": {"bolt": {"type": "step"}, "nut": {"type": "step"}}}
    repo, fake = _make_repo(ctx, data)

    assert sorted(repo.object_names("part")) == ["bolt", "nut"]
    assert fake.keys == ["objects/part"]

    # A subsequent enumeration and single lookups come from the cache.
    repo.object_configs("part")
    assert repo.object_config("part", "bolt") == {"type": "step"}
    assert fake.keys == ["objects/part"]  # no new remote calls


def test_single_fetch_avoids_full_enumeration():
    ctx = pc.Context("examples")
    data = {"objects/part/bolt": {"type": "step", "path": "bolt.step"}}
    repo, fake = _make_repo(ctx, data)

    # Asking for one object before enumerating fetches just that object.
    config = repo.object_config("part", "bolt")
    assert config["type"] == "step" and config["path"] == "bolt.step"
    # A file-backed object is tagged so its file is materialized on demand.
    assert config["fileFrom"] == "plugin"
    assert fake.keys == ["objects/part/bolt"]
    assert "objects/part" not in fake.keys


def test_ensure_enumerated_async_warms_the_sync_accessors():
    """After the async warm-up, the sync accessors never bridge to async."""
    ctx = pc.Context("examples")
    data = {"objects/part": {"bolt": {"type": "step"}}, "deps": ["child"]}
    repo, fake = _make_repo(ctx, data)

    asyncio.run(repo.ensure_enumerated_async())

    # Now these are pure cache reads (no event loop involved).
    assert repo.object_names("part") == ["bolt"]
    assert list(repo.dependencies()) == ["child"]


def test_on_disk_cache_persists_across_instances():
    """A second package instance is served from disk without re-querying."""
    ctx = pc.Context("examples")
    cache = Cache("external/test_persist", ctx.user_config)
    try:
        data = {"objects/part": {"bolt": {"type": "step"}}}

        first, fake1 = ProjectExternalRepository(ctx, "//ext", "/tmp/ext", cache=cache), FakeRepository(data)
        first._repository = fake1
        assert first.object_names("part") == ["bolt"]
        assert fake1.keys == ["objects/part"]  # fetched from the repository

        # A fresh in-memory instance sharing the on-disk cache; its repository
        # would return nothing, so a correct read must come from disk.
        second, fake2 = ProjectExternalRepository(ctx, "//ext", "/tmp/ext", cache=cache), FakeRepository({})
        second._repository = fake2
        assert second.object_names("part") == ["bolt"]
        assert fake2.keys == []  # served from disk, repository never called
    finally:
        # The entries have to go, or the next run is served from them and never
        # queries the repository at all. Only the local tier writes a directory;
        # a developer who has a remote tier switched on gets nothing extra here.
        for backend in cache.backends:
            if isinstance(backend, FilesCacheBackend):
                shutil.rmtree(backend.cache_dir, ignore_errors=True)


def test_file_backed_configs_are_tagged_for_materialization():
    """Served configs with a 'path' get fileFrom=plugin; others are untouched."""
    ctx = pc.Context("examples")
    data = {
        "objects/part": {
            "bolt": {"type": "step", "path": "bolt.step"},
            "ref": {"type": "alias", "source": "//x:y"},
        }
    }
    repo, _ = _make_repo(ctx, data)
    configs = repo.object_configs("part")
    assert configs["bolt"]["fileFrom"] == "plugin"  # file-backed -> materialized
    assert "fileFrom" not in configs["ref"]  # alias has no file


def test_tagging_survives_async_warmup():
    """The import-time warm-up must tag configs too, not just lazy access.

    The async warm-up runs first in the real flow; if it skipped the tagging,
    a file-backed part would demand its file at list time instead of deferring
    to materialization.
    """
    ctx = pc.Context("examples")
    data = {"objects/part": {"bolt": {"type": "step", "path": "bolt.step"}}}
    repo, _ = _make_repo(ctx, data)
    asyncio.run(repo.ensure_enumerated_async())
    assert repo.object_config("part", "bolt")["fileFrom"] == "plugin"


def test_metadata_materializes_from_the_repository():
    """Package-level metadata comes from the 'meta' key; identity is protected."""
    ctx = pc.Context("examples")
    data = {
        "meta": {"desc": "A remote package", "manufacturable": False, "render": {"svg": {}}, "name": "//evil"},
    }
    repo, _ = _make_repo(ctx, data)
    asyncio.run(repo.ensure_enumerated_async())

    assert repo.desc == "A remote package"
    assert repo.is_manufacturable is False
    assert repo.config_obj["render"] == {"svg": {}}
    assert repo.name == "//ext"  # identity is never overridden by metadata


def test_cache_version_propagates_to_children():
    """The cache version is inherited by every child of a plugin-backed
    hierarchy, so the whole tree shares one versioned cache namespace."""
    ctx = pc.Context("examples")
    top = ProjectExternalRepository(
        ctx, "//ext", "/tmp/ext", plugin_ref="//ext:remote", cache_version=3
    )
    top._repository = FakeRepository({"deps": ["motors"]})
    child = top.dependencies()["motors"]
    assert child["cacheVersion"] == 3
    assert child["plugin"] == "//ext:remote"


def test_no_cache_version_leaves_children_unversioned():
    """Without a cache version (the default), children carry no cacheVersion,
    preserving the pre-existing cache namespace."""
    ctx = pc.Context("examples")
    top = ProjectExternalRepository(ctx, "//ext", "/tmp/ext", plugin_ref="//ext:remote")
    top._repository = FakeRepository({"deps": ["motors"]})
    assert "cacheVersion" not in top.dependencies()["motors"]


def test_hierarchy_forwards_under_a_subfolder():
    """A child of the hierarchy scopes its requests to its subfolder."""
    ctx = pc.Context("examples")
    data = {
        "deps": ["motors"],
        "motors/objects/part": {"rotor": {"type": "step"}},
    }
    top = ProjectExternalRepository(ctx, "//ext", "/tmp/ext", plugin_ref="//ext:remote")
    fake = FakeRepository(data)
    top._repository = fake

    # The top package advertises its children with their subfolders.
    assert top.dependencies()["motors"]["subfolder"] == "motors"

    # A child scoped to 'motors' fetches 'motors/objects/part'.
    child = ProjectExternalRepository(ctx, "//ext/motors", "/tmp/ext", plugin_ref="//ext:remote", subfolder="motors")
    child._repository = fake
    assert child.object_names("part") == ["rotor"]
    assert "motors/objects/part" in fake.keys
