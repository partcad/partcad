#
# PartCAD, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-07-22
#
# Licensed under Apache License, Version 2.0.
#

import asyncio
import json
import threading

from .cache_hash import CacheHash
from .project_plugin import ProjectPlugin
from .sync_threads import threadpool_manager
from . import logging as pc_logging
from . import tags as pc_tags

# Distinguishes "no cached value" from a cached value of None.
_MISSING = object()


class ProjectExternalRepository(ProjectPlugin):
    """A package whose contents are served by an external repository plugin.

    Every remote interaction is funneled through 'request()', which memoizes a
    single external call by an arbitrary key. Caching one request at a time -
    rather than a whole 'list' or a whole 'get' - keeps entries small and
    composable: a paged listing becomes several keyed entries, and many
    single-object fetches can share the enumeration entry instead of each
    producing its own. All access to the backing plugin goes through 'request()'.

    Data is addressed as key/value pairs so that new metadata or new kinds of
    objects can be introduced without changing this class:

        objects/<kind>              -> {name: config, ...}   (enumeration)
        objects/<kind>/<name>       -> config                (single fetch)
        deps                        -> [child package names]
        meta                        -> package-level metadata

    'get_data(key)' is the single method a repository plugin must implement; the
    accessors below are expressed entirely in terms of it.
    """

    def __init__(
        self,
        ctx,
        name,
        path,
        plugin_ref: str = None,
        subfolder: str = "",
        repository=None,
        cache=None,
        cache_version: int = 0,
        config_obj=None,
        inherited_config=None,
    ):
        # 'plugin_ref' is the '<package>:<repository>' reference to the backing
        # repository plugin; it is resolved to the actual Repository object
        # lazily, on first use, because the package that hosts it may not be
        # fully loaded when this package is constructed.
        self._plugin_ref = plugin_ref
        # 'subfolder' scopes every request to a location within the repository.
        # A hierarchy is served by one plugin: the top package uses "", and each
        # child forwards the same requests under its own subfolder, so a child
        # in "motors" asks for "motors/objects/part" instead of "objects/part".
        self._subfolder = subfolder
        self._repository = repository
        self._cache = cache
        # Carried so that child packages served by the same plugin inherit it and
        # land in the same versioned cache namespace (see 'dependencies()').
        self._cache_version = cache_version
        self._request_cache: dict[str, object] = {}
        self._request_lock = threading.Lock()
        # Objects are instantiated once, lazily, the first time this package's
        # 'parts'/'sketches'/'assemblies' are accessed (see '_lazy_objects').
        # '_instantiating' is the reentrancy guard so factories can write into
        # the backing dicts during instantiation without re-triggering it.
        self._parts = {}
        self._sketches = {}
        self._assemblies = {}
        self._objects_instantiated = False
        self._instantiating = False
        super().__init__(ctx, name, path, config_obj=config_obj, inherited_config=inherited_config)

    def request(self, key: str, handler):
        """Return 'handler()' for 'key', invoking 'handler' at most once per key.

        'handler' performs the actual (expensive, possibly remote) call. The
        first request for a key runs it and caches the result; later requests
        for the same key return the cached value. Concurrent first-requests for
        the same key are collapsed to a single 'handler' invocation.
        """
        with self._request_lock:
            if key in self._request_cache:
                return self._request_cache[key]

        # TODO(clairbee): consult and populate the on-disk 'self._cache' here so
        #                 that the result survives across runs, honoring
        #                 user_config.force_update / offline like the git and
        #                 tar dependency factories do.
        pc_logging.debug("%s: external request: %s" % (self.name, key))
        value = handler()

        with self._request_lock:
            # 'setdefault' so a racing request that already stored a value wins
            # and every caller observes the same object.
            return self._request_cache.setdefault(key, value)

    def _get_repository(self):
        """Resolve the backing repository plugin, once, on first use."""
        if self._repository is None and self._plugin_ref is not None:
            package_name, repository_name = self.ctx.get_project(self.name).resolve(self._plugin_ref)
            source = self.ctx.get_project(package_name)
            if source is not None:
                self._repository = source.get_repository(repository_name)
            if self._repository is None:
                pc_logging.error("%s: repository plugin not found: %s" % (self.name, self._plugin_ref))
        return self._repository

    def _scope(self, key: str) -> str:
        """Prefix a key with this package's subfolder within the repository."""
        return self._subfolder + "/" + key if self._subfolder else key

    async def get_data_async(self, key: str):
        """Fetch the value for 'key' from the repository plugin (cached).

        The async path used when already inside an event loop (e.g. the import
        traversal). Three layers back it: the in-memory memo (this process), the
        on-disk cache (across runs), and finally the repository itself. The
        scoped key is the cache key throughout, so sibling packages served by
        the same repository never collide and the synchronous 'get_data' below
        reuses whatever this fetched.
        """
        scoped = self._scope(key)

        # 1. In-memory memo.
        with self._request_lock:
            if scoped in self._request_cache:
                return self._request_cache[scoped]

        # 2. On-disk cache. Skipped on a forced refresh, but consulted anyway
        #    when offline (there is no way to refresh), mirroring the git/tar
        #    dependency factories.
        offline = self.ctx.user_config.offline
        if self._cache is not None and (not self.ctx.user_config.force_update or offline):
            cached = await self._read_cache(scoped)
            if cached is not _MISSING:
                with self._request_lock:
                    return self._request_cache.setdefault(scoped, cached)

        # 3. The repository. A broken or unreachable repository must not crash
        #    the caller (e.g. 'pc list' over many packages); treat it as empty.
        value = None
        try:
            repository = self._get_repository()
            if repository is not None:
                value = await repository.get_data(scoped)
        except Exception as e:
            pc_logging.error("%s: failed to fetch '%s' from the repository: %s" % (self.name, scoped, e))

        # Persist a successful fetch so it survives across runs.
        if value is not None and self._cache is not None:
            await self._write_cache(scoped, value)

        with self._request_lock:
            return self._request_cache.setdefault(scoped, value)

    def _cache_hash(self, scoped_key: str) -> CacheHash:
        # The cache directory is already scoped to this repository instance, so
        # the scoped key alone identifies the entry within it.
        h = CacheHash(scoped_key, cache=True)
        h.add_string(scoped_key)
        return h

    async def _read_cache(self, scoped_key: str):
        try:
            got = await self._cache.read_data_async(self._cache_hash(scoped_key), ["data"])
            raw = got.get("data")
            if raw is None:
                return _MISSING
            return json.loads(raw.decode())
        except Exception as e:
            pc_logging.debug("%s: cache read failed for '%s': %s" % (self.name, scoped_key, e))
            return _MISSING

    async def _write_cache(self, scoped_key: str, value):
        try:
            await self._cache.write_data_async(
                self._cache_hash(scoped_key), {"data": json.dumps(value).encode()}
            )
        except Exception as e:
            pc_logging.debug("%s: cache write failed for '%s': %s" % (self.name, scoped_key, e))

    def get_data(self, key: str):
        """Synchronous fetch, for accessors reached outside an event loop.

        Returns the cached value if present (so this never blocks once the async
        traversal has warmed the cache). On a miss it bridges to the async
        fetch. The bridge is normally 'asyncio.run', but a synchronous accessor
        can also be reached from *within* a running loop (e.g. 'render_async'
        calls the synchronous 'get_part', which reaches here through
        'object_configs'). Nesting 'asyncio.run' in that case raises; instead the
        coroutine is completed on a worker thread, so the accessor stays usable
        from both contexts even when the cache was not pre-warmed.
        """
        scoped = self._scope(key)
        with self._request_lock:
            if scoped in self._request_cache:
                return self._request_cache[scoped]

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # No loop is running: bridge directly.
            return asyncio.run(self.get_data_async(key))

        # A loop is already running in this thread: run the fetch to completion
        # on the shared, otel-context-preserving executor to avoid nesting event
        # loops (a raw ThreadPoolExecutor would drop the tracing context).
        future = threadpool_manager.unconstrained_executor.submit(lambda: asyncio.run(self.get_data_async(key)))
        return future.result()

    async def ensure_enumerated_async(self):
        """Warm the package's structure (metadata and child list) from the plugin.

        Called from the async import traversal. Only the cheap, package-level
        data is warmed here: 'meta' (so 'desc' etc. are known) and 'deps' (so the
        child packages can be discovered). The objects of a package (parts,
        sketches, assemblies) are NOT enumerated here: doing so eagerly for every
        package makes loading a large repository (thousands of parts across many
        sub-packages) prohibitively expensive. They are enumerated lazily, per
        package, the first time that package's objects are actually accessed (see
        the 'parts'/'sketches'/'assemblies' properties below).
        """
        await self._materialize_meta_async()
        # Warm 'deps' so the synchronous 'dependencies()' is a cache hit.
        await self.get_data_async("deps")

    def _instantiate_enumerated(self):
        """Instantiate this package's enumerated objects into the eager dicts.

        Runs at most once, the first time a consumer reads 'parts'/'sketches'/
        'assemblies' (see those properties). Each object is created
        independently and defensively: one that cannot be built (an unsupported
        type, a file-backed object whose file is absent) is skipped with a
        warning instead of hiding every other object from a 'list'. Geometry is
        not built here - only the factories.
        """
        for kind, getter in (
            ("sketch", self.get_sketch),
            ("part", self.get_part),
            ("assembly", self.get_assembly),
        ):
            for name in self.object_names(kind):
                try:
                    getter(name)
                except Exception as e:
                    pc_logging.warning("%s: could not instantiate %s '%s': %s" % (self.name, kind, name, e))

    def _lazy_objects(self):
        """Instantiate the enumerated objects on first access, once."""
        if self._objects_instantiated or self._instantiating:
            return
        self._instantiating = True
        try:
            self._instantiate_enumerated()
            self._objects_instantiated = True
        finally:
            self._instantiating = False

    # The eager object dictionaries the synchronous consumers (the CLI 'list'
    # commands, render, export, get_*) read. They are populated lazily, per
    # package, so that loading a large repository does not enumerate every
    # sub-package's objects up front. The reentrancy guard lets the factories
    # write into the backing dict during instantiation without re-triggering.
    @property
    def parts(self):
        self._lazy_objects()
        return self._parts

    @parts.setter
    def parts(self, value):
        self._parts = value

    @property
    def sketches(self):
        self._lazy_objects()
        return self._sketches

    @sketches.setter
    def sketches(self, value):
        self._sketches = value

    @property
    def assemblies(self):
        self._lazy_objects()
        return self._assemblies

    @assemblies.setter
    def assemblies(self, value):
        self._assemblies = value

    async def _materialize_meta_async(self):
        """Fill package-level metadata from the repository.

        Metadata is just another key in the same key/value space, so a plugin
        package can carry any package property a local one can (desc, render,
        manufacturable, ...) with no new methods here. The location-derived
        fields already set on the package win; the repository fills the rest.
        """
        meta = await self.get_data_async("meta")
        if not meta:
            return
        # The repository supplies package properties, but never the identity
        # (name) or the import-derived fields: those pin where and how this
        # package was loaded. Child packages come from the 'deps' key, not from
        # any 'dependencies' the metadata might carry.
        protected = {"name", "type", "isRoot", "importUrl", "dependencies"}
        for key, value in meta.items():
            if key not in protected:
                self.config_obj[key] = value
        # Re-derive the fields Configuration computed from config_obj at
        # construction, now that the repository has supplied them.
        if isinstance(meta.get("desc"), str):
            self.desc = meta["desc"].strip()
        if "manufacturable" in meta:
            self.is_manufacturable = bool(meta["manufacturable"])
        if pc_tags.UNLESS_KEY in meta:
            # Re-derived here for the same reason as the two above: the
            # constructor read a 'config_obj' the repository had not filled yet,
            # so a package that excludes itself only says so once this returns.
            # Nothing has been enumerated by then - object access is lazy for a
            # plugin package - so emptying it now is as good as never filling it.
            try:
                self.skipped_by = pc_tags.excluded_by(self.config_obj, self.ctx.tags, self.name)
            except ValueError as e:
                pc_logging.error(str(e))
                self.skipped_by = None
            self.skipped = self.skipped_by is not None
            if self.skipped:
                pc_logging.info("Skipping the package '%s': excluded by 'unless' (%s)" % (self.name, self.skipped_by))
                self._object_configs = {kind: {} for kind in self._object_configs}

    # --- Object-access hooks (see Project) sourced from the repository ---

    def _augment(self, config):
        """Mark a file-backed object so its file is materialized on demand.

        A plugin-backed package has no source tree, so an object that references
        a file by 'path' must fetch it from the plugin. Tagging it with
        'fileFrom: plugin' both defers the file's existence check to build time
        and routes materialization through 'FileFactoryPlugin'.
        """
        if isinstance(config, dict) and "path" in config and "fileFrom" not in config:
            config = dict(config)
            config["fileFrom"] = "plugin"
        return config

    def _enumerate_object_configs(self, kind):
        configs = self.get_data("objects/" + kind)
        if not configs:
            return {}
        return {name: self._augment(config) for name, config in configs.items()}

    def _fetch_object_config(self, kind, name):
        return self._augment(self.get_data("objects/" + kind + "/" + name))

    def dependencies(self):
        """Child packages of this package, served by the same repository.

        The repository lists its children by name under the 'deps' key; each
        child is imported as another external package backed by the same plugin,
        forwarding requests under the child's subfolder. This is what lets a
        plugin-backed package host a hierarchy just like a local monorepo.
        """
        names = self.get_data("deps") or []
        deps = {}
        for child in names:
            deps[child] = {
                "type": "external",
                "plugin": self._plugin_ref,
                "subfolder": self._scope(child),
            }
            # Propagate the cache version so a child computes the same versioned
            # cache namespace as its parent (the whole hierarchy shares one cache).
            if self._cache_version:
                deps[child]["cacheVersion"] = self._cache_version
        return deps
