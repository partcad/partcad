#
# PartCAD, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-07-22
#
# Licensed under Apache License, Version 2.0.
#

import threading

from .project_plugin import ProjectPlugin
from . import logging as pc_logging


class ProjectExternalRepository(ProjectPlugin):
    """A package whose contents are served by an external repository plugin.

    Every remote interaction is funneled through 'request()', which memoizes a
    single external call by an arbitrary key. Caching one request at a time -
    rather than a whole 'list' or a whole 'get' - keeps entries small and
    composable: a paged listing becomes several keyed entries, and many
    single-object fetches can share the enumeration entry instead of each
    producing its own. Repository query implementations are expected to route
    every call to the backing plugin through 'request()'.

    The keys are cache keys, so they must be stable and fully identify the
    request (e.g. 'objects/part', 'objects/part/bolt_m4', 'meta'). The value is
    whatever the handler returns; it is treated as opaque here.
    """

    def __init__(self, ctx, name, path, repository=None, cache=None, config_obj=None, inherited_config=None):
        # The backing repository plugin (the singleton that answers queries) and
        # the on-disk cache scoped to this repository instance. Both may be None
        # while the wiring is being built out; 'request()' still memoizes
        # in-memory so callers can rely on the contract regardless.
        self._repository = repository
        self._cache = cache
        self._request_cache: dict[str, object] = {}
        self._request_lock = threading.Lock()
        super().__init__(ctx, name, path, config_obj=config_obj, inherited_config=inherited_config)

    def request(self, key: str, handler):
        """Return 'handler()' for 'key', invoking 'handler' at most once per key.

        'handler' performs the actual (expensive, possibly remote) call. The
        first request for a key runs it and caches the result; later requests
        for the same key return the cached value without calling 'handler'
        again. Concurrent first-requests for the same key are collapsed to a
        single 'handler' invocation.
        """
        # Fast path: already memoized in this process.
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
