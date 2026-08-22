#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The storage tiers a cache is made of, and what each of them expects.

A cache entry is a flat name ('<hash>.<key>') and a blob of bytes. Which bytes
is decided one layer up, in cache_shape.py; this layer only moves them. What
matters here is that they are moved *as they are*: a shape payload is the
zstd-compressed BREP frame the core already holds in memory, and it reaches
every tier - the filesystem, memcached, S3 - without being copied, recompressed
or base64-encoded on the way.

The tiers, fastest first:

  * memory      - not a backend at all. It is the envelope the Shape holds
                  (see cache_shape.py), governed by the 'cacheMem' options.
  * files       - 'cacheFiles', the per-user directory under the internal state
                  directory. Always local, always available.
  * remote      - 'cacheRemote', a memcached-protocol server shared by a team or
                  a CI fleet. Needs the 'memcache' extra.
  * S3          - 'cacheS3', an object store. Slowest and furthest away, but it
                  survives everything else. Needs the 'aws' extra.

Each tier has its own size window, because what is worth a local file is not
necessarily worth a network round trip.
"""

import asyncio
import contextlib

from . import logging as pc_logging

# The cache keys that hold geometry, and so are the ones a size window applies
# to. Everything else a cache holds - a test result, a lint report, a fetched
# repository index - is small by construction and always worth storing.
SIZED_KEYS = ("shape", "sketch", "part", "assembly", "cmps")


class CacheBackend:
    """One storage tier: flat names in, bytes out.

    Subclasses implement '_read_async' and '_write_async' and are expected to
    hand the payload through untouched. A backend that cannot be reached is not
    an error: a cache miss and a warning are always a valid answer, so failures
    are contained here rather than propagated into a build.
    """

    name = "backend"

    def __init__(self, user_config, data_type: str, min_entry_size: int = 0, max_entry_size: int = 0) -> None:
        self.user_config = user_config
        self.data_type = data_type
        self.min_entry_size = min_entry_size
        self.max_entry_size = max_entry_size

    # Whether this tier also stores the '.name' sidecar that records which
    # object a hash belongs to. It is a local debugging aid - worth having when
    # you are looking at a cache directory by hand, not worth a network request.
    stores_names = False

    def accepts(self, key: str, size: int) -> bool:
        """Whether an entry of this size belongs in this tier."""
        if not key.startswith(SIZED_KEYS):
            return True
        # One-byte entries are how a test result is stored, and they are exempt
        # from the minimum: the point of the minimum is to keep small geometry
        # out, not to drop the smallest entries there are.
        if size >= 2 and self.min_entry_size and size < self.min_entry_size:
            return False
        if self.max_entry_size and size > self.max_entry_size:
            return False
        return True

    async def read_async(self, names: list[str]) -> dict[str, bytes]:
        """The entries of 'names' this tier holds, missing ones simply absent."""
        try:
            return await self._read_async(names)
        except Exception as e:
            pc_logging.debug("cache: %s: read failed: %s" % (self.name, e))
            return {}

    async def write_async(self, items: dict[str, bytes]) -> dict[str, bool]:
        """Store 'items', reporting which of them this tier took."""
        if not items:
            return {}
        try:
            return await self._write_async(items)
        except Exception as e:
            pc_logging.debug("cache: %s: write failed: %s" % (self.name, e))
            return {}

    async def _read_async(self, names: list[str]) -> dict[str, bytes]:
        raise NotImplementedError

    async def _write_async(self, items: dict[str, bytes]) -> dict[str, bool]:
        raise NotImplementedError


class PooledCacheBackend(CacheBackend):
    """A tier reached through a client that must not outlive its event loop.

    PartCAD drives its async work through many separate 'asyncio.run()' calls -
    every synchronous accessor is one - and a connection pool belongs to the
    loop that opened it. Kept past that loop it is unusable, and unclosable too,
    which is how leaked sockets and "unclosed session" warnings happen; opened
    afresh for every request it would cost a handshake per cache lookup.

    So the client lives exactly as long as there is a request using it: opened
    for the first, closed after the last. One traversal that builds a hundred
    shapes concurrently shares one client; between commands nothing is held at
    all. Subclasses supply '_open()' and '_close()' and reach the client through
    'connected()'.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Keyed by the event loop, because more than one can be live at a time:
        # PartCAD builds on a thread of its own with 'asyncio.run()' while the
        # caller's loop is still going. Sharing one client between them would let
        # the loop that finished first close the other one's socket. An entry
        # lives only while a request is using it (see 'connected()').
        self._per_loop = {}

    async def _open(self):
        """Build the client. Called with the tier's lock held."""
        raise NotImplementedError

    async def _close(self, client) -> None:
        """Release a client built by '_open()'."""

    def _guard(self):
        """The (loop, state) pair for the loop running now, creating it if new.

        Deliberately not a coroutine: it has to notice the loop and install the
        lock without an await in between, or two requests could each decide they
        are the first and open a client apiece.
        """
        loop = asyncio.get_running_loop()
        state = self._per_loop.get(loop)
        if state is None:
            state = self._per_loop[loop] = {"lock": asyncio.Lock(), "client": None, "users": 0}
        return loop, state

    @contextlib.asynccontextmanager
    async def connected(self):
        """The shared client, for the duration of one request."""
        loop, state = self._guard()
        lock = state["lock"]
        async with lock:
            if state["client"] is None:
                state["client"] = await self._open()
            state["users"] += 1
        try:
            yield state["client"]
        finally:
            async with lock:
                state["users"] -= 1
                client = state["client"] if state["users"] == 0 else None
                if client is not None:
                    state["client"] = None
                    # The last user of this loop's client: the loop keeps
                    # nothing between requests, and its entry goes with it.
                    self._per_loop.pop(loop, None)
            if client is not None:
                try:
                    await self._close(client)
                except Exception as e:
                    pc_logging.debug("cache: %s: failed to close: %s" % (self.name, e))


class CacheDependencyError(ImportError):
    """Raised when a cache tier is enabled without its optional dependency installed."""


def missing_dependency(tier: str, module: str, extra: str) -> CacheDependencyError:
    """The error a backend raises when the extra that carries its client is absent."""
    return CacheDependencyError(
        "The '%s' cache needs the '%s' package, which is not installed. "
        "Install it with: pip install 'partcad[%s]' "
        "(or 'partcad-cli[%s]' when using the command line interface)." % (tier, module, extra, extra)
    )


def build(user_config, data_type: str) -> list[CacheBackend]:
    """The enabled tiers for 'data_type', ordered nearest first.

    Order is what makes the tiers a hierarchy: a read stops at the first tier
    that has the entry, so the local file wins over the memcached server, which
    wins over S3. A tier that cannot be built - its client library is not
    installed, or it was switched on without an address - is reported once and
    left out, rather than failing the run: the cache is an optimization, and
    losing one of its tiers must never be fatal.
    """
    backends = []

    if getattr(user_config, "cache", False):
        from .cache_backend_files import FilesCacheBackend

        backends.append(FilesCacheBackend(user_config, data_type))

    if getattr(user_config, "cache_remote", False):
        _add(backends, "cacheRemote", ".cache_backend_memcache", "MemcacheCacheBackend", user_config, data_type)

    if getattr(user_config, "cache_s3", False):
        _add(backends, "cacheS3", ".cache_backend_s3", "S3CacheBackend", user_config, data_type)

    return backends


def _add(backends: list, option: str, module: str, class_name: str, user_config, data_type: str) -> None:
    """Build one optional tier, or report why it will not be there."""
    import importlib

    try:
        backend_class = getattr(importlib.import_module(module, __package__), class_name)
        backends.append(backend_class(user_config, data_type))
    except (CacheDependencyError, ValueError) as e:
        pc_logging.error("%s is enabled but unusable, and is being skipped: %s" % (option, e))
