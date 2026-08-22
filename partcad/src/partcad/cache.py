#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-17
#
# Licensed under Apache License, Version 2.0
#

import asyncio

from .cache_hash import CacheHash
from . import cache_backend


class Cache:
    """A hierarchy of storage tiers, addressed as one key-value store.

    Entries are flat names ('<hash>.<key>') holding bytes. A read walks the
    tiers nearest-first and stops at the first one that has the entry; a write
    offers the entry to every tier whose size window accepts it. Which tiers
    exist is the user's configuration - see cache_backend.build().

    Nothing here inspects, converts or copies a payload: what a caller hands in
    is what every tier stores, and a shape payload is the zstd-compressed BREP
    frame the core already holds (see cache_shape.py).
    """

    def __init__(self, data_type: str, user_config) -> None:
        """Initialize cache for specific data type."""
        self.data_type = data_type
        self.user_config = user_config
        self.backends = cache_backend.build(user_config, data_type)

    @property
    def enabled(self) -> bool:
        return bool(self.backends)

    def _name(self, hash_str: str, key: str) -> str:
        return "%s.%s" % (hash_str, key)

    async def write_data_async(self, hash: CacheHash, items: dict[str, bytes]) -> dict[str, bool]:
        """Store 'items' under 'hash', reporting which of them landed somewhere.

        A key that no tier accepted - too big for one, too small for another,
        every tier disabled - comes back absent rather than False, which is what
        the callers have always keyed their in-memory decisions off.
        """
        if not self.backends:
            # Caching is disabled
            return {}

        hash_str = hash.get()
        if not hash_str:
            # Hash is not produced
            return {}

        # The sidecar that records which object this hash belongs to. Only the
        # tiers that want it get it (see CacheBackend.stores_names).
        names = {self._name(hash_str, "name"): hash.name.encode()}

        async def task_backend(backend):
            accepted = {
                self._name(hash_str, key): value
                for key, value in items.items()
                if backend.accepts(key, len(value))
            }
            if not accepted:
                return {}
            if backend.stores_names:
                accepted.update(names)
            return await backend.write_async(accepted)

        results = await asyncio.gather(*[asyncio.create_task(task_backend(b)) for b in self.backends])

        saved = {}
        for stored in results:
            for key in items:
                if stored.get(self._name(hash_str, key), False):
                    saved[key] = True
        return saved

    async def read_data_async(self, hash: CacheHash, keys: list[str]) -> dict[str, bytes]:
        """Read 'keys' under 'hash' from the nearest tier that holds each of them."""
        if not self.backends:
            # Caching is disabled
            return {}

        hash_str = hash.get()
        if not hash_str:
            # Hash is not produced
            return {}

        found = {}
        pending = list(keys)
        for backend in self.backends:
            if not pending:
                break
            stored = await backend.read_async([self._name(hash_str, key) for key in pending])
            still_pending = []
            for key in pending:
                data = stored.get(self._name(hash_str, key))
                if data is None:
                    still_pending.append(key)
                else:
                    found[key] = data
            pending = still_pending

        # A key nobody had is reported as a miss, the way a missing file was.
        for key in pending:
            found[key] = None
        return found
