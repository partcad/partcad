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

import partcad as pc
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
    # Nothing enumerated or instantiated at construction.
    assert repo._object_configs["part"] is None
    assert repo.parts == {}
    assert fake.keys == []


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
    assert repo.object_config("part", "bolt") == {"type": "step", "path": "bolt.step"}
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
