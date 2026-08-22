#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The remote tier of the cache ('cacheRemote'), over the memcached protocol.

This is the tier a team or a CI fleet shares: one memcached server in front of
everybody's local file cache, so that geometry somebody has already built is
fetched rather than rebuilt. The protocol is memcached's own, so anything that
speaks it will do - a real memcached, a compatible proxy, or the mock server the
tests drive (partcad/tests/unit/memcached_server.py).

What travels is the entry as it is stored everywhere else: for a shape, the
zstd-compressed BREP frame. memcached values are opaque bytes, so the payload
goes onto the socket without a copy or an encoding step, which is the whole
reason the compression happens before the cache rather than inside it.

The client library ('aiomcache') is an optional extra: pip install
'partcad[memcache]'.
"""

import asyncio

from .cache_backend import PooledCacheBackend, missing_dependency
from . import logging as pc_logging
from . import telemetry

# memcached refuses a key with whitespace or control characters, and caps it at
# 250 bytes. A cache entry name is '<hex hash>.<key>' and a namespace is user
# text, so the namespace is what has to be kept in line.
MAX_KEY_LENGTH = 250

# 'Cache' prefixes every name with '<hex hash>.' only after 'accepts()' has had
# its say, so the room the longest digest 'CacheHash' can produce (sha256) takes
# is reserved here instead.
HASH_KEY_LENGTH = 64 + len(".")


@telemetry.instrument()
class MemcacheCacheBackend(PooledCacheBackend):
    """Cache entries as memcached items, keyed '<namespace>:<data type>:<name>'."""

    name = "remote"

    def __init__(self, user_config, data_type: str) -> None:
        super().__init__(
            user_config,
            data_type,
            min_entry_size=user_config.cache_remote_min_entry_size,
            max_entry_size=user_config.cache_remote_max_entry_size,
        )
        try:
            import aiomcache
        except ImportError:
            raise missing_dependency("cacheRemote", "aiomcache", "memcache")

        self._aiomcache = aiomcache
        self.host, self.port = _split_server(user_config.cache_remote_server)
        self.expiration = user_config.cache_remote_expiration
        self._prefix = "%s:%s:" % (user_config.cache_remote_namespace, data_type)
        self._prefix_length = len(self._prefix.encode("utf-8"))
        # The namespace is user text and the key travels in a command line, so a
        # space or a control character in it would not make the entry unreachable
        # - it would desynchronize the protocol. Refusing the tier here is what
        # 'cache_backend.build()' reports and skips.
        if any(byte <= 0x20 or byte == 0x7F for byte in self._prefix.encode("utf-8")):
            raise ValueError(
                "cacheRemoteNamespace must not contain whitespace or control characters: %r"
                % user_config.cache_remote_namespace
            )

    def _key(self, name: str) -> bytes:
        return (self._prefix + name).encode("utf-8")

    def accepts(self, key: str, size: int) -> bool:
        # memcached measures a key in bytes, so a non-ASCII namespace is longer
        # than it looks, and the hash 'Cache' puts in front of the key counts too.
        if self._prefix_length + HASH_KEY_LENGTH + len(key.encode("utf-8")) > MAX_KEY_LENGTH:
            return False
        return super().accepts(key, size)

    async def _open(self):
        # aiomcache connects lazily and pools connections of its own, so this
        # costs nothing until the first request actually goes out.
        return self._aiomcache.Client(self.host, self.port)

    async def _close(self, client) -> None:
        await client.close()

    async def _read_async(self, names: list[str]) -> dict[str, bytes]:
        async with self.connected() as client:
            # One 'get' round trip for all of them, which is what makes a remote
            # tier affordable when a shape and its components are read together.
            values = await client.multi_get(*[self._key(name) for name in names])
        return {name: value for name, value in zip(names, values) if value is not None}

    async def _write_async(self, items: dict[str, bytes]) -> dict[str, bool]:
        async with self.connected() as client:

            async def task_item(name: str, value: bytes):
                try:
                    await client.set(self._key(name), value, exptime=self.expiration)
                    return name, True
                except Exception as e:
                    # A server that is full, or an item it considers too large,
                    # is a normal outcome for a shared cache: the entry is
                    # simply not there next time.
                    pc_logging.debug("cache: %s: failed to store '%s': %s" % (self.name, name, e))
                    return name, False

            results = await asyncio.gather(*[asyncio.create_task(task_item(n, v)) for n, v in items.items()])
        return {name: ok for name, ok in results if ok}


def _split_server(server: str) -> tuple[str, int]:
    """'host:port' (or a bare host) as the pair aiomcache wants."""
    server = (server or "").strip()
    if not server:
        raise ValueError("cacheRemoteServer is not set, but cacheRemote is enabled")
    if server.count(":") == 1:
        host, _, port = server.partition(":")
        return host, int(port)
    return server, 11211
