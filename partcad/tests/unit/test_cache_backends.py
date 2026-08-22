#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""The cache tiers that reach off this machine, driven against local mock servers.

What every one of these asserts, one way or another, is that the payload is not
touched: the bytes a caller hands the cache are the bytes that go onto the
socket and the bytes that come back. For a shape those bytes are a
zstd-compressed BREP frame, and the whole point of compressing before the cache
rather than inside it is that no tier has to know that.
"""

import asyncio

import pytest
from cache_config import CacheUserConfig
from memcached_server import serve_memcached
from s3_server import serve_s3

from partcad import cache_backend
from partcad.cache import Cache
from partcad.cache_hash import CacheHash
from partcad.cache_shape import ShapeCache

# These talk to a socket, and a protocol bug is far more likely to hang than to
# fail: fail instead.
pytestmark = pytest.mark.timeout(60)

# A payload that looks like what the cache really carries: a zstd frame, opaque
# to every layer below the one that compressed it, and full of bytes that no
# text encoding would survive.
ZSTD_FRAME = b"\x28\xb5\x2f\xfd" + bytes(range(256)) * 8


@pytest.fixture
def aws_credentials(monkeypatch):
    """Throwaway credentials, so boto3 signs rather than looking for a profile."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "partcad-test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "partcad-test")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.delenv("AWS_PROFILE", raising=False)


def _hash(name="shape", data="identical-geometry"):
    cache_hash = CacheHash(name, cache=True)
    cache_hash.add_string(data)
    return cache_hash


def _memcache_config(tmp_path, server, **overrides):
    return CacheUserConfig(
        tmp_path,
        cache=False,  # only the tier under test
        cache_remote=True,
        cache_remote_server="%s:%d" % (server.host, server.port),
        **overrides,
    )


def _s3_config(tmp_path, url, **overrides):
    return CacheUserConfig(
        tmp_path,
        cache=False,  # only the tier under test
        cache_s3=True,
        cache_s3_bucket="partcad-cache",
        cache_s3_endpoint_url=url,
        **overrides,
    )


# ---------------------------------------------------------------- memcached --


def test_memcache_round_trips_the_payload_untouched(tmp_path):
    """What the server holds is the frame itself - not base64, not re-encoded."""
    with serve_memcached() as server:

        async def main():
            cache = Cache("shapes", _memcache_config(tmp_path, server))
            written = await cache.write_data_async(_hash(), {"part": ZSTD_FRAME})
            read = await cache.read_data_async(_hash(), ["part"])
            return written, read

        written, read = asyncio.run(main())

    assert written == {"part": True}
    assert read == {"part": ZSTD_FRAME}
    assert list(server.storage.values()) == [ZSTD_FRAME]


def test_memcache_keys_are_namespaced_by_installation_and_data_type(tmp_path):
    """One server can back several projects, so a key says which one it is for."""
    with serve_memcached() as server:

        async def main():
            config = _memcache_config(tmp_path, server, cache_remote_namespace="team-a")
            await Cache("shapes", config).write_data_async(_hash(), {"part": ZSTD_FRAME})

        asyncio.run(main())

    key = next(iter(server.storage))
    assert key.startswith(b"team-a:shapes:")
    assert key.endswith(b".part")


def test_memcache_refuses_an_entry_above_the_servers_item_limit(tmp_path):
    """The size window keeps a doomed write off the wire entirely."""
    with serve_memcached() as server:

        async def main():
            config = _memcache_config(tmp_path, server, cache_remote_max_entry_size=len(ZSTD_FRAME) - 1)
            cache = Cache("shapes", config)
            written = await cache.write_data_async(_hash(), {"part": ZSTD_FRAME})
            read = await cache.read_data_async(_hash(), ["part"])
            return written, read

        written, read = asyncio.run(main())

    assert written == {}
    assert read == {"part": None}
    assert server.storage == {}


def test_memcache_expiration_is_what_the_configuration_says(tmp_path):
    with serve_memcached() as server:

        async def main():
            config = _memcache_config(tmp_path, server, cache_remote_expiration=3600)
            await Cache("shapes", config).write_data_async(_hash(), {"part": ZSTD_FRAME})

        asyncio.run(main())

    assert set(server.expirations.values()) == {3600}


def test_memcache_read_of_a_missing_entry_is_a_miss(tmp_path):
    with serve_memcached() as server:

        async def main():
            cache = Cache("shapes", _memcache_config(tmp_path, server))
            return await cache.read_data_async(_hash(), ["part", "cmps"])

        assert asyncio.run(main()) == {"part": None, "cmps": None}


def test_a_server_that_is_not_there_is_a_miss_and_not_a_failure(tmp_path):
    """A cache is an optimization: losing a tier must never fail a build."""

    async def main():
        # Port 1 on loopback: nothing listens there, and connecting is refused
        # immediately rather than hanging.
        config = CacheUserConfig(tmp_path, cache=False, cache_remote=True, cache_remote_server="127.0.0.1:1")
        cache = Cache("shapes", config)
        written = await cache.write_data_async(_hash(), {"part": ZSTD_FRAME})
        read = await cache.read_data_async(_hash(), ["part"])
        return written, read

    written, read = asyncio.run(main())

    assert written == {}
    assert read == {"part": None}


# ------------------------------------------------------------ loop affinity --


def test_a_second_event_loop_gets_a_working_client(tmp_path):
    """A connection belongs to the loop that opened it, and every accessor is a loop.

    Regression: a client held across 'asyncio.run()' calls keeps sockets
    registered with a loop that has since closed, so the second call never
    answers - and every synchronous PartCAD accessor is another 'asyncio.run()'.
    """
    with serve_memcached() as server:
        cache = Cache("shapes", _memcache_config(tmp_path, server))

        asyncio.run(cache.write_data_async(_hash(), {"part": ZSTD_FRAME}))
        # Same cache object, same backend, three more loops.
        for _ in range(3):
            assert asyncio.run(cache.read_data_async(_hash(), ["part"])) == {"part": ZSTD_FRAME}


def test_one_client_serves_overlapping_requests_and_goes_when_they_do(tmp_path):
    """The client is shared while requests overlap, and released once they finish."""
    with serve_memcached() as server:
        cache = Cache("shapes", _memcache_config(tmp_path, server))
        remote = cache.backends[0]

        async def main():
            depth = []

            async def one():
                async with remote.connected():
                    depth.append(remote._users)
                    await asyncio.sleep(0)

            await asyncio.gather(*[one() for _ in range(4)])
            return depth

        depth = asyncio.run(main())

    # They really did overlap ...
    assert max(depth) > 1
    # ... and the last one out released it.
    assert remote._client is None


# ----------------------------------------------------------------------- S3 --


def test_s3_round_trips_the_payload_untouched(tmp_path, aws_credentials):
    with serve_s3() as (url, storage):

        async def main():
            cache = Cache("shapes", _s3_config(tmp_path, url))
            written = await cache.write_data_async(_hash(), {"part": ZSTD_FRAME})
            read = await cache.read_data_async(_hash(), ["part"])
            return written, read

        written, read = asyncio.run(main())

    assert written == {"part": True}
    assert read == {"part": ZSTD_FRAME}
    assert list(storage.values()) == [ZSTD_FRAME]


def test_s3_objects_live_under_the_configured_prefix_and_data_type(tmp_path, aws_credentials):
    with serve_s3() as (url, storage):

        async def main():
            config = _s3_config(tmp_path, url, cache_s3_prefix="builds/main")
            await Cache("shapes", config).write_data_async(_hash(), {"part": ZSTD_FRAME})

        asyncio.run(main())

    key = next(iter(storage))
    # A missing trailing slash on the prefix is not the user's problem.
    assert key.startswith("partcad-cache/builds/main/shapes/")
    assert key.endswith(".part")


def test_s3_read_of_a_missing_object_is_a_miss(tmp_path, aws_credentials):
    """S3 answers a missing key with an error, and that error means 'not cached'."""
    with serve_s3() as (url, storage):

        async def main():
            return await Cache("shapes", _s3_config(tmp_path, url)).read_data_async(_hash(), ["part"])

        read = asyncio.run(main())

    assert read == {"part": None}
    assert storage == {}


# --------------------------------------------------------------- hierarchy --


def test_the_nearest_tier_wins_and_the_far_one_backs_it(tmp_path, aws_credentials):
    """Files, then memcached, then S3: a read stops at the first tier that has it."""
    with serve_s3() as (url, storage), serve_memcached() as server:
        config = CacheUserConfig(
            tmp_path,
            cache=True,
            cache_remote=True,
            cache_remote_server="%s:%d" % (server.host, server.port),
            cache_s3=True,
            cache_s3_bucket="partcad-cache",
            cache_s3_endpoint_url=url,
        )
        cache = Cache("shapes", config)
        assert [b.name for b in cache.backends] == ["files", "remote", "s3"]

        # A write reaches every tier that accepts it.
        asyncio.run(cache.write_data_async(_hash(), {"part": ZSTD_FRAME}))

        # With the local files gone, the read falls through to memcached.
        for path in cache.backends[0].cache_dir.iterdir():
            path.unlink()
        from_remote = asyncio.run(cache.read_data_async(_hash(), ["part"]))

        # With memcached emptied too, S3 is what is left.
        server.storage.clear()
        from_s3 = asyncio.run(cache.read_data_async(_hash(), ["part"]))

    assert from_remote == {"part": ZSTD_FRAME}
    assert from_s3 == {"part": ZSTD_FRAME}
    # Every tier held the same bytes, and they are the ones handed in.
    assert list(storage.values()) == [ZSTD_FRAME]


def test_only_the_local_tier_records_which_object_a_hash_belongs_to(tmp_path):
    """The '.name' sidecar is a local debugging aid, not worth a network trip."""
    with serve_memcached() as server:
        config = CacheUserConfig(
            tmp_path,
            cache=True,
            cache_remote=True,
            cache_remote_server="%s:%d" % (server.host, server.port),
        )
        cache = Cache("shapes", config)
        asyncio.run(cache.write_data_async(_hash("pkg:widget"), {"part": ZSTD_FRAME}))

        on_disk = sorted(p.name.rsplit(".", 1)[1] for p in cache.backends[0].cache_dir.iterdir())

    assert on_disk == ["name", "part"]
    assert [k.rsplit(b".", 1)[1] for k in server.storage] == [b"part"]


def test_a_shape_reaches_the_remote_tier_as_the_compressed_frame(tmp_path):
    """End to end: ShapeCache stores geometry, and memcached holds exactly it."""
    with serve_memcached() as server:
        cache = ShapeCache(user_config=_memcache_config(tmp_path, server))

        async def main():
            shape = {"name": "pkg:first", "label": "first", "brep": ZSTD_FRAME}
            await cache.write_async(_hash(), {"part": shape})
            read, _ = await cache.read_async(_hash(), ["part"], {"name": "pkg:second", "label": "second"})
            return read

        read = asyncio.run(main())

    # The envelope was rebuilt around the payload for whoever asked...
    assert read["part"] == {"name": "pkg:second", "label": "second", "brep": ZSTD_FRAME}
    # ...and what crossed the wire was the payload alone.
    assert list(server.storage.values()) == [ZSTD_FRAME]


# -------------------------------------------------------------- extras gate --


def test_a_tier_without_its_extra_is_reported_and_skipped(tmp_path, monkeypatch):
    """Enabling a tier whose client is missing must not take the others down."""
    import builtins

    real_import = builtins.__import__

    def no_aiomcache(name, *args, **kwargs):
        if name == "aiomcache":
            raise ImportError("no aiomcache here")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_aiomcache)

    errors = []
    monkeypatch.setattr(cache_backend.pc_logging, "error", errors.append)

    config = CacheUserConfig(tmp_path, cache=True, cache_remote=True, cache_remote_server="127.0.0.1:1")
    backends = cache_backend.build(config, "shapes")

    assert [b.name for b in backends] == ["files"]
    assert len(errors) == 1
    assert "pip install 'partcad[memcache]'" in errors[0]


def test_a_tier_switched_on_without_an_address_is_reported_and_skipped(tmp_path, monkeypatch):
    """Half-configured is the same as unusable, and just as survivable."""
    errors = []
    monkeypatch.setattr(cache_backend.pc_logging, "error", errors.append)

    config = CacheUserConfig(tmp_path, cache=True, cache_remote=True, cache_s3=True)
    backends = cache_backend.build(config, "shapes")

    assert [b.name for b in backends] == ["files"]
    assert [e.split(" ")[0] for e in errors] == ["cacheRemote", "cacheS3"]
    assert "cacheRemoteServer" in errors[0] and "cacheS3Bucket" in errors[1]
