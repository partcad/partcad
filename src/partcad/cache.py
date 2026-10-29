#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-17
#
# Licensed under Apache License, Version 2.0
#

import asyncio

from . import cache_backend
from .cache_hash import CacheHash


class Cache:
    """A hierarchy of storage tiers, addressed as one key-value store.

    Entries are flat names ('<hash>.<key>') holding bytes. A read walks the
    tiers nearest-first and stops at the first one that has the entry, and
    copies what it found into the nearer tiers that missed it (see
    '_promote_async'); a write offers the entry to every tier whose size window
    accepts it. Both offer an entry on the same terms ('_admission_sizes').
    Which tiers exist is the user's configuration - see cache_backend.build().

    The files tier is written before a write returns. The remote tiers are
    written behind it, from a bounded queue on the cache's I/O thread, and what
    is queued is visible to every read in this process until it lands (see
    cache_io.py): the files tier is what every process on this machine reads
    first, so it is the one that has to be there when the caller goes on, and
    the remote ones are where a write costs a network round trip.

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

    async def write_data_async(
        self, hash: CacheHash, items: dict[str, bytes], sizes: dict[str, int] = None
    ) -> dict[str, bool]:
        """Store 'items' under 'hash', reporting which of them landed somewhere.

        A key that no tier accepted - too big for one, too small for another,
        every tier disabled - comes back absent rather than False, which is what
        the callers have always keyed their in-memory decisions off.

        'sizes' is the size a tier judges a key by where that is not the length
        of its bytes - None for a key no tier is to take - and defaults to
        '_admission_sizes(items)': an entry that only names another one's
        geometry is worth keeping exactly where that geometry is kept (see
        'ShapeCache._admission_sizes').
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
        if sizes is None:
            sizes = self._admission_sizes(items)

        results = await asyncio.gather(
            *[asyncio.create_task(self._write_backend_async(b, hash_str, items, names, sizes)) for b in self.backends]
        )

        saved = {}
        for stored in results:
            for key in items:
                if stored.get(self._name(hash_str, key), False):
                    saved[key] = True
        return saved

    async def _write_backend_async(
        self, backend, hash_str: str, items: dict[str, bytes], names: dict, sizes: dict[str, int] = None
    ) -> dict:
        """Offer 'items' to one tier: those its size window accepts, and the name sidecar if it keeps one.

        'sizes' is what the window judges a key by where that is not the length
        of its bytes, None for a key no window takes (see '_admission_sizes').
        """
        sizes = sizes or {}
        accepted = {}
        for key, value in items.items():
            size = sizes.get(key, len(value))
            if size is not None and backend.accepts(key, size):
                accepted[self._name(hash_str, key)] = value
        if not accepted:
            return {}
        if backend.stores_names:
            accepted.update(names)
        return await backend.write_async(accepted)

    def _admission_sizes(self, entries: dict[str, bytes]) -> dict:
        """The size each tier's window judges an entry of 'entries' by, where that is not its length.

        By key, and None for an entry no tier is to take. Asked of every write
        and of every promotion, so that a tier is offered an entry on the same
        terms however it comes to be offered it. Here every entry is judged by
        its own length; a cache whose entries name one another says otherwise
        ('ShapeCache._admission_sizes': a shape's components are kept exactly
        where the geometry they are pieces of is).
        """
        return {}

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
        promotions = []
        pending = list(keys)
        for index, backend in enumerate(self.backends):
            if not pending:
                break
            stored = await backend.read_async([self._name(hash_str, key) for key in pending])
            still_pending = []
            hits = {}
            for key in pending:
                data = stored.get(self._name(hash_str, key))
                if data is None:
                    still_pending.append(key)
                else:
                    found[key] = data
                    hits[key] = data
            if hits and index > 0:
                promotions.append((index, hits))
            pending = still_pending

        if promotions:
            # Once every tier has answered rather than as each one does: what a
            # tier is offered may be judged by the size of another entry read
            # with it (see '_admission_sizes'), and that one may have come from
            # a nearer tier, or a farther one.
            sizes = self._admission_sizes({key: data for key, data in found.items() if data})
            for index, hits in promotions:
                await self._promote_async(hash, hash_str, hits, self.backends[:index], sizes)

        # A key nobody had is reported as a miss, the way a missing file was.
        for key in pending:
            found[key] = None
        return found

    async def _promote_async(
        self, hash: CacheHash, hash_str: str, hits: dict[str, bytes], nearer: list, sizes: dict = None
    ) -> None:
        """Copy what a farther tier had into the nearer ones, every one of which missed it.

        Every one: a key is asked of a tier only while no nearer tier has
        answered it. Without this, an entry that only S3 holds is downloaded
        again by every process that wants it, and by this one again as soon as
        the memory tier lets go of it - the local file it would take to stop
        that is never written, because nothing on this machine built the entry.
        So a hit is written down as a write of it would have been: to the tiers
        whose size window accepts it, the files tier before this returns and
        the remote ones behind it (an S3 hit lands in memcached for the team
        too), each judged by what 'sizes' says of it as a write would judge it
        (see '_admission_sizes'). An entry with no bytes in it is a miss to
        every reader, and is not worth copying.
        """
        hits = {key: value for key, value in hits.items() if value}
        if not hits:
            return
        names = {self._name(hash_str, "name"): hash.name.encode()}
        await asyncio.gather(
            *[asyncio.create_task(self._write_backend_async(b, hash_str, hits, names, sizes)) for b in nearer]
        )

    async def flush_async(self) -> None:
        """Wait until what this cache wrote so far has reached every tier it was meant for."""
        for backend in self.backends:
            flush = getattr(backend, "flush_async", None)
            if flush is not None:
                await flush()

    async def contains_data_async(self, hash: CacheHash, keys: list[str]) -> dict[str, bool]:
        """Which of 'keys' some tier holds under 'hash', without reading them.

        The question "would this have to be built?", asked without paying for
        the answer: the tiers are walked nearest-first exactly as a read walks
        them, but each is asked whether it holds the entry rather than for the
        entry itself (see CacheBackend.contains_async). An entry with no bytes
        in it counts as absent, because that is what a read of one amounts to.

        A "yes" is a statement about now: nothing stops the entry being evicted
        between this and the read that follows it, so a caller uses it to
        decide what to do first, never to skip handling a miss.
        """
        found = {key: False for key in keys}
        if not self.backends:
            # Caching is disabled
            return found

        hash_str = hash.get()
        if not hash_str:
            # Hash is not produced
            return found

        pending = list(keys)
        for backend in self.backends:
            if not pending:
                break
            held = await backend.contains_async([self._name(hash_str, key) for key in pending])
            still_pending = []
            for key in pending:
                if held.get(self._name(hash_str, key), False):
                    found[key] = True
                else:
                    still_pending.append(key)
            pending = still_pending
        return found
