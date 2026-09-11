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
from partcad import context as pc_context
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
    top = ProjectExternalRepository(ctx, "//ext", "/tmp/ext", plugin_ref="//ext:remote", cache_version=3)
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


# --- 'objectKinds': the kinds a repository says it does not have -------------
#
# A package has ten kinds of object and every one of them is a separate key -
# which, for a plugin-backed package, is a separate run of the plugin's script.
# A repository that says which kinds it holds is not asked about the rest.
#
# The declaration is read out of the metadata the traversal has already
# fetched, so these warm it the way 'ensure_enumerated_async' does.


def test_a_kind_the_metadata_leaves_out_is_never_asked_for():
    ctx = pc.Context("examples")
    data = {
        "meta": {"desc": "Parts only", "objectKinds": ["part"]},
        "objects/part": {"bolt": {"type": "step"}},
        # Served, but never asked for: the metadata does not list the kind.
        "objects/sketch": {"outline": {"type": "basic"}},
    }
    repo, fake = _make_repo(ctx, data)
    asyncio.run(repo.ensure_enumerated_async())

    assert repo.object_names("part") == ["bolt"]
    assert repo.object_names("sketch") == []
    assert repo.object_config("sketch", "outline") is None
    assert "objects/sketch" not in fake.keys
    assert "objects/sketch/outline" not in fake.keys


def test_a_repository_that_says_nothing_is_asked_about_everything():
    """The default, and what every repository written before this did."""
    ctx = pc.Context("examples")
    data = {"meta": {"desc": "No declaration"}, "objects/sketch": {"outline": {"type": "basic"}}}
    repo, fake = _make_repo(ctx, data)
    asyncio.run(repo.ensure_enumerated_async())

    assert repo.object_names("sketch") == ["outline"]
    assert "objects/sketch" in fake.keys


def test_a_malformed_declaration_is_ignored_rather_than_guessed_at():
    ctx = pc.Context("examples")
    data = {"meta": {"objectKinds": "part"}, "objects/sketch": {"outline": {"type": "basic"}}}
    repo, fake = _make_repo(ctx, data)
    asyncio.run(repo.ensure_enumerated_async())

    assert repo.object_names("sketch") == ["outline"]
    assert "objects/sketch" in fake.keys


def test_the_declaration_is_never_worth_a_round_trip_of_its_own():
    """It narrows what is asked for; it must not add a question to find out.

    A package reached without the traversal has not read its metadata, so the
    kinds are asked for as they always were - one fetch, not two.
    """
    ctx = pc.Context("examples")
    data = {
        "meta": {"objectKinds": ["part"]},
        "objects/part": {"bolt": {"type": "step"}},
        "objects/sketch": {"outline": {"type": "basic"}},
    }
    repo, fake = _make_repo(ctx, data)

    assert repo.object_names("part") == ["bolt"]
    assert fake.keys == ["objects/part"]  # no 'meta' fetched to decide


# --- prefetching the kinds a listing is about to read ------------------------


def test_prefetch_fetches_the_declared_kinds_together():
    ctx = pc.Context("examples")
    data = {
        "meta": {"objectKinds": ["part", "assembly"]},
        "objects/part": {"bolt": {"type": "step"}},
        "objects/assembly": {"rig": {"type": "assy"}},
    }
    repo, fake = _make_repo(ctx, data)
    asyncio.run(repo.ensure_enumerated_async())

    asyncio.run(repo.prefetch_object_configs_async(("sketch", "part", "assembly", "scene")))
    # Only the declared kinds were asked for...
    assert sorted(k for k in fake.keys if k.startswith("objects/")) == [
        "objects/assembly",
        "objects/part",
    ]

    # ...and the synchronous accessors that follow add no round trips at all.
    before = list(fake.keys)
    assert repo.object_names("part") == ["bolt"]
    assert repo.object_names("assembly") == ["rig"]
    assert repo.object_names("sketch") == []
    assert repo.object_names("scene") == []
    assert fake.keys == before


def test_prefetch_of_an_undeclared_repository_warms_every_kind_asked_for():
    ctx = pc.Context("examples")
    data = {"objects/part": {"bolt": {"type": "step"}}}
    repo, fake = _make_repo(ctx, data)

    asyncio.run(repo.prefetch_object_configs_async(("part", "scene")))
    assert sorted(k for k in fake.keys if k.startswith("objects/")) == ["objects/part", "objects/scene"]
    before = list(fake.keys)
    assert repo.object_names("part") == ["bolt"]
    assert fake.keys == before


def test_a_local_package_has_nothing_to_prefetch():
    """The hook exists on every package; for a local one it is a no-op."""
    ctx = pc.Context("examples")
    project = ctx.get_project(ctx.name)
    assert project is not None
    before = project.object_count("part")
    asyncio.run(project.prefetch_object_configs_async(("part",)))
    assert project.object_count("part") == before


def test_a_malformed_declaration_is_complained_about_once():
    """Ten kinds asked about must not be ten copies of the same warning."""
    ctx = pc.Context("examples")
    data = {"meta": {"objectKinds": "part"}, "objects/sketch": {"outline": {"type": "basic"}}}
    repo, _ = _make_repo(ctx, data)
    asyncio.run(repo.ensure_enumerated_async())

    warnings = []
    original = pc.logging.warning
    pc.logging.warning = lambda msg, *a: warnings.append(msg)
    try:
        for kind in ("sketch", "part", "assembly", "scene"):
            repo.object_names(kind)
    finally:
        pc.logging.warning = original
    assert len(warnings) == 1, warnings


# --- the listing warms what it is about to read ------------------------------
#
# 'Context.get_all_packages(has_stuff=True)' prefetches HAS_STUFF_KINDS before
# 'get_packages' reads them back one at a time. Nothing exercised that wiring:
# the two 'get_all_packages' calls elsewhere in the suite pass has_stuff=False,
# which skips the prefetch entirely, so the whole point of the change went
# untested. These go in through the listing rather than through
# '_prefetch_object_configs', so that the wiring is what is under test: a
# listing that stopped prefetching would still pass a test that prefetched for
# it.


def _listing_context(tmp_path, data, name="//test/ext"):
    """A context with one plugin-backed package in it, ready to be listed.

    The package is injected rather than imported: a real one would need a
    plugin to run, and what is under test here is the listing rather than the
    import. Everything after that point sees an ordinary loaded package.
    """
    (tmp_path / "partcad.yaml").write_text("name: //test\ndesc: root\n")
    ctx = pc.Context(str(tmp_path))
    repo = ProjectExternalRepository(ctx, name, "/tmp/ext", config_obj={})
    fake = FakeRepository(data)
    repo._repository = fake
    asyncio.run(repo.ensure_enumerated_async())  # as the import would have
    ctx.projects[name] = repo
    return ctx, repo, fake


def _record_prefetches(repo):
    """What the listing asks this package to warm, in the order it asks."""
    asked = []
    original = repo.prefetch_object_configs_async

    async def spy(kinds):
        asked.append(tuple(kinds))
        await original(kinds)

    repo.prefetch_object_configs_async = spy
    return asked


def test_the_listing_warms_the_kinds_it_is_about_to_read(tmp_path):
    ctx, repo, fake = _listing_context(
        tmp_path, {"meta": {"objectKinds": ["part"]}, "objects/part": {"bolt": {"type": "step"}}}
    )
    asked = _record_prefetches(repo)

    listed = [package["name"] for package in ctx.get_all_packages(has_stuff=True)]

    # The listing warmed the package, once, for exactly the kinds it filters on.
    assert asked == [pc_context.HAS_STUFF_KINDS]
    # Only the declared kind was a round trip; the other three are answered from
    # the metadata -- and there is only one of it, so what 'get_packages' read
    # back afterwards was the memo. That cache hit is the whole point.
    assert [k for k in fake.keys if k.startswith("objects/")] == ["objects/part"]
    assert "//test/ext" in listed


def test_a_listing_that_filters_on_nothing_warms_nothing(tmp_path):
    """has_stuff=False reads no kinds out of the packages, so it warms none."""
    ctx, repo, fake = _listing_context(tmp_path, {"objects/part": {"bolt": {"type": "step"}}})
    asked = _record_prefetches(repo)

    listed = [package["name"] for package in ctx.get_all_packages(has_stuff=False)]

    assert asked == []
    assert [k for k in fake.keys if k.startswith("objects/")] == []
    assert "//test/ext" in listed


def test_the_listing_skips_packages_outside_the_parent(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "partcad.yaml").write_text("desc: sub\n")
    ctx, repo, fake = _listing_context(tmp_path, {"objects/part": {"bolt": {"type": "step"}}})
    ctx.import_all()  # so that '//test/sub' is a package a listing can start from
    asked = _record_prefetches(repo)

    # '//test/sub' is not this package's parent, so nothing is warmed for it --
    # and in particular no round trip is sent to a repository out of scope.
    ctx.get_all_packages(parent_name="//test/sub", has_stuff=True)
    assert asked == []
    assert [k for k in fake.keys if k.startswith("objects/")] == []


def test_an_unreachable_repository_does_not_take_the_listing_down(tmp_path):
    """The prefetch is a warm-up; nothing downstream depends on it having worked."""

    class Unreachable:
        async def get_data(self, key):
            raise RuntimeError("the repository is not answering")

    ctx, repo, _ = _listing_context(tmp_path, {})
    repo._repository = Unreachable()

    ctx.get_all_packages(has_stuff=True)  # must not raise
    # ...and the package is still readable afterwards, the slow way.
    assert repo.object_count("part") == 0
