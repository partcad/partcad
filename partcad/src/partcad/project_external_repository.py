#
# PartCAD, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-07-22
#
# Licensed under Apache License, Version 2.0.
#

import asyncio
import threading

from .project import OBJECT_KINDS
from .project_plugin import ProjectPlugin
from . import logging as pc_logging


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
        self._request_cache: dict[str, object] = {}
        self._request_lock = threading.Lock()
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
        traversal). The scoped key is also the cache key, so sibling packages
        served by the same repository never collide and the synchronous
        'get_data' below reuses whatever this fetched.
        """
        scoped = self._scope(key)
        with self._request_lock:
            if scoped in self._request_cache:
                return self._request_cache[scoped]

        value = None
        try:
            repository = self._get_repository()
            if repository is not None:
                value = await repository.get_data(scoped)
        except Exception as e:
            # A repository being broken or unreachable must not crash the caller
            # (e.g. 'pc list' over many packages); treat it as empty.
            pc_logging.error("%s: failed to fetch '%s' from the repository: %s" % (self.name, scoped, e))

        with self._request_lock:
            return self._request_cache.setdefault(scoped, value)

    def get_data(self, key: str):
        """Synchronous fetch, for accessors reached outside an event loop.

        Returns the cached value if present (so this never blocks once the async
        traversal has warmed the cache); otherwise it bridges to the async fetch.
        Bridging is only safe outside a running loop, which holds for the CLI
        entry points; inside the loop, enumeration is warmed via
        'ensure_enumerated_async' so this path stays a cache hit.
        """
        scoped = self._scope(key)
        with self._request_lock:
            if scoped in self._request_cache:
                return self._request_cache[scoped]
        return asyncio.run(self.get_data_async(key))

    async def ensure_enumerated_async(self):
        """Warm the object and dependency caches from the repository.

        Called from the async import traversal so that the synchronous accessors
        (object_configs, dependencies, ...) reached later only ever hit the
        cache and never bridge to async from within a running loop.
        """
        for kind in OBJECT_KINDS:
            if self._object_configs.get(kind) is None:
                configs = await self.get_data_async("objects/" + kind)
                self._object_configs[kind] = configs if configs else {}
        # Warm 'deps' too, so the synchronous 'dependencies()' is a cache hit.
        await self.get_data_async("deps")

    # --- Object-access hooks (see Project) sourced from the repository ---

    def _enumerate_object_configs(self, kind):
        configs = self.get_data("objects/" + kind)
        return configs if configs else {}

    def _fetch_object_config(self, kind, name):
        return self.get_data("objects/" + kind + "/" + name)

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
        return deps
