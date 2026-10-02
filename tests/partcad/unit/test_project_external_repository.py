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
import threading
import time

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
    # Normalized on the way out - the declaration carries the name it is
    # declared under, and what the package says about anything it produces,
    # whether or not anything has been made out of it yet.
    assert repo.object_config("part", "bolt") == {
        "type": "step",
        "name": "bolt",
        "orig_name": "bolt",
        "manufacturable": True,
    }
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


def test_a_lookup_by_name_asks_for_that_one_object(tmp_path):
    """Not for the catalog it is in.

    'object_config' falls back to a targeted single fetch precisely so that a
    plugin-backed package can serve one object without listing everything it
    has - and 'get_object' defeated that by taking the enumerated mapping as an
    argument, which materialized it at the call site before the lookup began.
    'pc render //pub/universe/lego/ldraw/bricks:3001' is the case: one part, and
    a round trip for the category.
    """
    data = {
        "objects/part/bolt": {"type": "step", "path": "bolt.step"},
        "objects/part": {"bolt": {"type": "step"}, "nut": {"type": "step"}},
    }
    ctx = pc.Context("examples")
    repo = ProjectExternalRepository(ctx, "//ext", str(tmp_path), config_obj={})
    fake = FakeRepository(data)
    repo._repository = fake

    repo.get_part("bolt", quiet=True)

    assert fake.keys == ["objects/part/bolt"]
    assert "objects/part" not in fake.keys


def test_a_parametrized_lookup_reads_a_normalized_base(tmp_path):
    """The declaration the variant is derived from is a declaration.

    The parameterized branch used to index the raw enumerated mapping, so what
    it copied was whatever the plugin sent - without the 'name' and the
    'manufacturable' that every other reader of a declaration is handed (see
    'Project._normalized').
    """
    data = {"objects/part/widget": {"type": "step", "parameters": {"width": {"default": 2.0}}}}
    ctx = pc.Context("examples")
    repo = ProjectExternalRepository(ctx, "//ext", str(tmp_path), config_obj={})
    repo._repository = FakeRepository(data)

    base = repo.get_part_config("widget")
    assert base["name"] == "widget"
    assert base["manufacturable"] is True


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


def test_a_plugin_package_that_names_no_supplier_has_none():
    """An empty set, and not a missing attribute.

    A plugin-backed package skips the object initialization a local one does,
    and the suppliers used to be skipped with it - so asking any part of one
    who sells it raised AttributeError instead of answering "nobody".
    """
    ctx = pc.Context("examples")
    repo, _ = _make_repo(ctx, {"meta": {"desc": "No store"}})
    assert repo.get_suppliers() == {}


def test_the_suppliers_come_from_the_metadata():
    ctx = pc.Context("examples")
    repo, _ = _make_repo(ctx, {"meta": {"suppliers": {"//pub/svc/store:shop": {"discount": "x"}}}})
    asyncio.run(repo.ensure_enumerated_async())
    assert repo.get_suppliers() == {"//pub/svc/store:shop": {"discount": "x"}}


def test_the_suppliers_are_read_without_a_traversal():
    """A package looked up on its own still says who sells it.

    'pc supply quote' of one part resolves that part's package and nothing
    else, so no traversal has applied its metadata by the time the suppliers
    are asked for. Asking is what fetches it, and only once.
    """
    ctx = pc.Context("examples")
    repo, fake = _make_repo(ctx, {"meta": {"suppliers": ["//pub/svc/store:shop"]}})
    assert fake.keys == []
    assert repo.get_suppliers() == {"//pub/svc/store:shop": {}}
    assert repo.get_suppliers() == {"//pub/svc/store:shop": {}}
    assert fake.keys == ["meta"]
    # The traversal arriving later applies nothing twice.
    asyncio.run(repo.ensure_enumerated_async())
    assert fake.keys == ["meta", "deps"]


def test_the_metadata_counts_as_applied_only_once_it_has_been():
    """The flag a reader skips the work on is the last thing to be set.

    It used to be the first, so a 'get_suppliers()' on another thread could
    see it, skip the metadata, and read the constructor's empty suppliers
    while this thread was still on its way to setting them.
    """
    ctx = pc.Context("examples")
    repo, _ = _make_repo(ctx, {"meta": {"suppliers": ["//pub/svc/store:shop"]}})
    seen = []
    init_suppliers = repo.init_suppliers

    def observing():
        seen.append(repo._meta_applied)
        init_suppliers()

    repo.init_suppliers = observing
    assert repo.get_suppliers() == {"//pub/svc/store:shop": {}}
    assert seen == [False]
    assert repo._meta_applied


def test_concurrent_lookups_apply_the_metadata_once_and_all_see_it():
    ctx = pc.Context("examples")
    repo, fake = _make_repo(ctx, {"meta": {"suppliers": ["//pub/svc/store:shop"]}})
    applied = []
    init_suppliers = repo.init_suppliers

    def counting():
        applied.append(1)
        time.sleep(0.05)  # widen the window a lookup used to fall into
        init_suppliers()

    repo.init_suppliers = counting
    results = []
    threads = [threading.Thread(target=lambda: results.append(repo.get_suppliers())) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results == [{"//pub/svc/store:shop": {}}] * 8
    assert len(applied) == 1
    assert fake.keys.count("meta") == 1


def test_a_supplier_is_resolved_against_the_package_that_names_it():
    ctx = pc.Context("examples")
    repo, _ = _make_repo(ctx, {"meta": {"suppliers": "shop"}})
    assert repo.get_suppliers() == {"//ext:shop": {}}


def test_a_supplier_lookup_from_a_loop_never_stops_it(monkeypatch):
    """Who sells a part is asked from a loop, so the metadata is fetched on it.

    'pc supply find' and the IDE's cart ask from inside a coroutine, where the
    synchronous 'get_suppliers()' would complete its fetch on another thread
    with the loop stopped - the wait 'Context._warm_project_async' is there to
    keep a part lookup out of.
    """
    ctx = pc.Context("examples")
    repo, fake = _make_repo(ctx, {"meta": {"suppliers": ["//pub/svc/store:shop"]}})
    stopped = []
    original = ProjectExternalRepository._run_elsewhere

    def waited_for(coroutine):
        stopped.append(coroutine.__qualname__)
        return original(coroutine)

    monkeypatch.setattr(ProjectExternalRepository, "_run_elsewhere", staticmethod(waited_for))

    assert asyncio.run(repo.get_suppliers_async()) == {"//pub/svc/store:shop": {}}
    assert stopped == []
    assert fake.keys == ["meta"]


def test_a_local_package_answers_a_supplier_lookup_from_a_loop_as_it_always_has():
    ctx = pc.Context("examples/provider_store")
    project = ctx.get_project("//")
    assert asyncio.run(project.get_suppliers_async()) == project.get_suppliers()


def test_a_child_is_told_the_plugin_and_not_the_cache_version():
    """A child carries the plugin reference and nothing about the cache.

    The version belongs to the plugin, and a child names the same plugin, so it
    arrives at the same namespace by reading the same script. Passing the number
    between packages would make every child a place it could be wrong.
    """
    ctx = pc.Context("examples")
    top = ProjectExternalRepository(ctx, "//ext", "/tmp/ext", plugin_ref="//ext:remote")
    top._repository = FakeRepository({"deps": ["motors"]})
    child = top.dependencies()["motors"]
    assert child["plugin"] == "//ext:remote"
    assert "cacheVersion" not in child


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


# --- asked from a loop, under the context's lock (#704) ----------------------
#
# 'Context.get_project()' holds the context's lock all the way down to the
# package it is after, and asks every package on the way for its
# 'dependencies()'. For a plugin-backed package that is a fetch, and on a thread
# that runs a loop - an assembly resolving its parts - the fetch is completed on
# a worker thread while the asking thread waits. Resolving the plugin is a
# 'get_project()' too, so a worker that did it waited for the lock the thread
# waiting for it held: 'pc test' over //pub stopped, with no CPU spent, on the
# first plugin-backed package it reached with nothing cached.


class _ImpatientLock:
    """The context's lock, except that waiting long for it is an error.

    A regression here is a deadlock, and a deadlocked worker thread is one the
    interpreter waits for on its way out: the test would not fail, the run
    would hang. This turns it into a failure the fetch reports, and the lookup
    comes back without the package.
    """

    def __init__(self):
        self._lock = threading.RLock()

    def __enter__(self):
        if not self._lock.acquire(timeout=10):
            raise TimeoutError("waited 10 seconds for the context's lock")

    def __exit__(self, *_args):
        self._lock.release()


def _plugin_package_under_a_root(tmp_path, data):
    """A root hosting a repository plugin, and a package that plugin serves.

    The package is loaded but has neither resolved its plugin nor fetched
    anything, which is how a hierarchy's top package is found by the first
    lookup into it when the plugin's cache is cold.
    """
    root = tmp_path / "root"
    root.mkdir()
    (root / "partcad.yaml").write_text("name: //test\n")
    ctx = pc.Context(str(root))
    ctx.lock = _ImpatientLock()
    fake = FakeRepository(data)
    # What the repository's factory registers on the package declaring it.
    ctx.get_project("//test").repositories["remote"] = fake
    ext = ProjectExternalRepository(ctx, "//test/ext", str(tmp_path), plugin_ref="//test:remote", config_obj={})
    ctx.projects[ext.name] = ext
    return ctx, ext, fake


def test_a_lookup_from_a_loop_resolves_through_a_cold_plugin_package(tmp_path):
    ctx, _, fake = _plugin_package_under_a_root(tmp_path, {"deps": ["motors"]})

    async def as_an_assembly_asks():
        return ctx.get_project("//test/ext/motors")

    found = asyncio.run(as_an_assembly_asks())

    assert found is not None and found.name == "//test/ext/motors"
    assert fake.keys == ["deps"]


def test_a_plugin_that_cannot_be_resolved_is_reported_only_when_it_is_needed():
    """Resolving on the waiting thread must not report what the cache answers.

    From a loop the plugin is resolved on the thread that waits, between the
    worker's look at the caches and its fetch - and only if the caches missed.
    A failure to resolve is an error only for a fetch that needed the plugin;
    one logged for a fetch that did not would still be the command's exit
    status.
    """
    ctx = pc.Context("examples")
    cache = Cache("external/test_unresolvable", ctx.user_config)
    errors = []
    original = pc.logging.error
    try:
        first = ProjectExternalRepository(ctx, "//ext", "/tmp/ext", cache=cache)
        first._repository = FakeRepository({"deps": ["child"]})
        assert list(first.dependencies()) == ["child"]  # now on disk

        second = ProjectExternalRepository(ctx, "//ext", "/tmp/ext", plugin_ref="//nowhere:remote", cache=cache)

        def unresolvable():
            raise RuntimeError("no such package")

        second._get_repository = unresolvable
        pc.logging.error = lambda msg, *a: errors.append(msg)

        async def from_a_loop(key):
            return second.get_data(key)

        assert asyncio.run(from_a_loop("deps")) == ["child"]
        assert errors == []

        assert asyncio.run(from_a_loop("meta")) is None  # not cached: needs the plugin
        assert len(errors) == 1 and "no such package" in errors[0], errors
    finally:
        pc.logging.error = original
        for backend in cache.backends:
            if isinstance(backend, FilesCacheBackend):
                shutil.rmtree(backend.cache_dir, ignore_errors=True)


def test_a_plugin_nobody_declares_is_looked_for_only_when_it_is_needed(tmp_path):
    """The same through the real resolution, which reports a missing plugin itself.

    Resolving a repository the hosting package does not declare logs that it is
    not there - from 'Project.get_repository' and again from '_get_repository'.
    Neither may happen for a fetch the on-disk cache answers.
    """
    root = tmp_path / "root"
    root.mkdir()
    (root / "partcad.yaml").write_text("name: //test\n")
    ctx = pc.Context(str(root))
    cache = Cache("external/test_missing_plugin", ctx.user_config)
    errors = []
    original = pc.logging.error
    try:
        first = ProjectExternalRepository(ctx, "//test/ext", str(tmp_path), cache=cache, config_obj={})
        first._repository = FakeRepository({"deps": ["child"]})
        assert list(first.dependencies()) == ["child"]  # now on disk

        second = ProjectExternalRepository(
            ctx, "//test/ext", str(tmp_path), plugin_ref="//test:missing", cache=cache, config_obj={}
        )
        ctx.projects[second.name] = second
        pc.logging.error = lambda msg, *a: errors.append(msg % a if a else msg)

        async def from_a_loop(key):
            return second.get_data(key)

        assert asyncio.run(from_a_loop("deps")) == ["child"]
        assert errors == []

        assert asyncio.run(from_a_loop("meta")) is None  # not cached: needs the plugin
        assert any("repository plugin not found" in error for error in errors), errors
    finally:
        pc.logging.error = original
        for backend in cache.backends:
            if isinstance(backend, FilesCacheBackend):
                shutil.rmtree(backend.cache_dir, ignore_errors=True)


def test_an_assembly_resolving_a_cold_plugin_part_never_stops_its_loop(tmp_path, monkeypatch):
    """Nothing it reads is fetched by a synchronous call that waits with the loop stopped.

    Resolving through the lock no longer deadlocks, but waiting is still
    waiting: a synchronous fetch from a loop holds up every other task on it,
    including a sandbox process whose input the loop is writing, and the
    environment lock and process slot that process's task holds - which the
    fetch, running the plugin in a sandbox, may need. 'pc test' over //pub
    stopped that way on macOS after #704's cycle was gone: the test's thread
    waiting in 'get_data' for a part's declaration, and a 'wrapper_bbox.py'
    waiting for the rest of its input.
    """
    ctx, _, fake = _plugin_package_under_a_root(
        tmp_path,
        {"deps": ["motors"], "motors/objects/part/rotor": {"type": "step", "path": "rotor.step"}},
    )
    # The child is imported the way a real one is, with an on-disk cache named
    # after the plugin - which outlives the test unless it lives in the test's
    # own directory, and a declaration read from it would never be fetched.
    monkeypatch.setattr(ctx.user_config, "internal_state_dir", str(tmp_path / "state"))
    stopped = []
    original = ProjectExternalRepository._run_elsewhere

    def waited_for(coroutine):
        stopped.append(coroutine.__qualname__)
        return original(coroutine)

    monkeypatch.setattr(ProjectExternalRepository, "_run_elsewhere", staticmethod(waited_for))

    part = asyncio.run(ctx.get_part_async("//test/ext/motors:rotor"))

    assert part is not None and part.name == "rotor"
    assert stopped == []
    assert "deps" in fake.keys and "motors/objects/part/rotor" in fake.keys


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
# 'prefetch_object_configs', so that the wiring is what is under test: a
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


def test_the_kinds_a_walk_does_not_filter_on_are_warmed_too(tmp_path):
    """'pc list interfaces -r' walks every package, so nothing gated warms it.

    The walk is not gated on 'has_stuff' for the kinds that are not geometry
    (interfaces, software, materials), so until the listing warmed the kind
    itself, each package of a plugin-backed tree was asked for its enumeration
    as the walk reached it - one round trip per package, each waited out end to
    end. LDraw has ninety-odd categories.
    """
    ctx, repo, fake = _listing_context(tmp_path, {"objects/interface": {"thru": {"desc": "an opening"}}})
    asked = _record_prefetches(repo)

    ctx.prefetch_object_configs("//test", ["interface"])

    assert asked == [("interface",)]
    assert [k for k in fake.keys if k.startswith("objects/")] == ["objects/interface"]
    # ...and reading it back is the memo, not a second round trip.
    assert list(repo.object_descriptions("interface")) == ["thru"]
    assert [k for k in fake.keys if k.startswith("objects/")] == ["objects/interface"]


def test_warming_several_packages_is_one_wait_rather_than_one_each(tmp_path):
    """They go in flight together, which is the whole of the difference."""
    import time

    delay = 0.2
    packages = 6

    class SlowRepository:
        def __init__(self, data):
            self.data = data

        async def get_data(self, key):
            await asyncio.sleep(delay)
            return self.data.get(key)

    (tmp_path / "partcad.yaml").write_text("name: //test\ndesc: root\n")
    ctx = pc.Context(str(tmp_path))
    for index in range(packages):
        name = "//test/cat%d" % index
        repo = ProjectExternalRepository(ctx, name, "/tmp/ext", config_obj={})
        repo._repository = SlowRepository({"objects/interface": {"i%d" % index: {}}})
        ctx.projects[name] = repo

    started = time.time()
    ctx.prefetch_object_configs("//test", ["interface"])
    for index in range(packages):
        assert ctx.projects["//test/cat%d" % index].object_count("interface") == 1
    elapsed = time.time() - started

    # One wait, not six. Generously bounded: what it must not be is serial.
    assert elapsed < delay * packages / 2


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


def test_listing_one_kind_does_not_instantiate_the_others():
    """'pc list assemblies' must not build every part of every package.

    Reading one of the three eager dictionaries used to instantiate all three,
    so a recursive listing of assemblies over the public index created every
    LDraw part of every category - hundreds per package, each through the
    'InitWrapper' factory - to report that those packages hold no assemblies.
    """
    ctx = pc.Context("examples")
    data = {
        "objects/part": {"bolt": {"type": "step"}, "nut": {"type": "step"}},
        "objects/sketch": {"outline": {"type": "dxf"}},
        "objects/assembly": {},
    }
    repo, fake = _make_repo(ctx, data)

    assert repo.assemblies == {}
    # The assemblies were enumerated; the parts and the sketches were not even
    # asked for, let alone instantiated.
    assert repo._parts == {} and repo._sketches == {}
    assert fake.keys == ["objects/assembly"]


def test_each_kind_is_instantiated_on_its_own_first_access():
    """Per kind, and still once per kind."""
    ctx = pc.Context("examples")
    data = {
        "objects/part": {"bolt": {"type": "step"}},
        "objects/sketch": {},
        "objects/assembly": {},
    }
    repo, fake = _make_repo(ctx, data)

    assert repo.assemblies == {}
    assert repo._instantiated_kinds == {"assembly"}
    assert fake.keys == ["objects/assembly"]

    _ = repo.parts
    assert repo._instantiated_kinds == {"assembly", "part"}
    assert fake.keys == ["objects/assembly", "objects/part"]

    # Read again: no second enumeration and no second instantiation pass.
    _ = repo.parts
    assert fake.keys == ["objects/assembly", "objects/part"]
