#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The object-store tier of the cache ('cacheS3').

The furthest tier and the slowest, but the one that keeps what the others lose:
a memcached server evicts under pressure and a developer's cache directory goes
away with the machine, while a bucket holds a build's geometry for as long as
its lifecycle policy says. It is what a CI fleet warms and a new checkout reads
from before building anything itself.

One object per entry, at '<prefix><data type>/<name>'. The body is the entry as
every other tier stores it - for a shape, the zstd-compressed BREP frame - so
S3 receives exactly the bytes the core already holds, with no copy, no base64
and no transfer encoding of our own. 'cacheS3EndpointUrl' points the client at
something other than AWS, which is both how a MinIO or Ceph deployment is used
and how the tests drive it against a mock server.

The client library ('aioboto3') is an optional extra: pip install
'partcad[aws]'.
"""

import asyncio

from .cache_backend import PooledCacheBackend, missing_dependency
from . import logging as pc_logging
from . import telemetry

# The errors S3 answers a missing object with. Both are ordinary cache misses,
# not failures: a HEAD-less GET says NoSuchKey, and a bucket the caller may not
# list says 404.
_MISS_CODES = ("NoSuchKey", "404", "NoSuchBucket")


@telemetry.instrument()
class S3CacheBackend(PooledCacheBackend):
    """Cache entries as S3 objects under a configured bucket and prefix."""

    name = "s3"

    def __init__(self, user_config, data_type: str) -> None:
        super().__init__(
            user_config,
            data_type,
            min_entry_size=user_config.cache_s3_min_entry_size,
            max_entry_size=user_config.cache_s3_max_entry_size,
        )
        try:
            import aioboto3
        except ImportError:
            raise missing_dependency("cacheS3", "aioboto3", "aws")

        self.bucket = user_config.cache_s3_bucket
        if not self.bucket:
            raise ValueError("cacheS3Bucket is not set, but cacheS3 is enabled")
        prefix = user_config.cache_s3_prefix or ""
        if prefix and not prefix.endswith("/"):
            prefix += "/"
        self._prefix = "%s%s/" % (prefix, data_type)
        self._client_kwargs = _client_kwargs(user_config)
        # The session is not bound to a loop and caches the loaded service
        # model, so keeping it is what makes opening a client cheap.
        self._session = aioboto3.Session()

    def _key(self, name: str) -> str:
        return self._prefix + name

    async def _open(self):
        # An aioboto3 client is an async context manager over an HTTP session,
        # entered here and exited in '_close()'.
        context = self._session.client("s3", **self._client_kwargs)
        return context, await context.__aenter__()

    async def _close(self, client) -> None:
        context, _ = client
        await context.__aexit__(None, None, None)

    async def _read_async(self, names: list[str]) -> dict[str, bytes]:
        async with self.connected() as (_, client):

            async def task_item(name: str):
                try:
                    response = await client.get_object(Bucket=self.bucket, Key=self._key(name))
                except Exception as e:
                    if not _is_miss(e):
                        pc_logging.debug("cache: %s: failed to read '%s': %s" % (self.name, name, e))
                    return name, None
                async with response["Body"] as body:
                    return name, await body.read()

            results = await asyncio.gather(*[asyncio.create_task(task_item(name)) for name in names])
        return {name: data for name, data in results if data is not None}

    async def _write_async(self, items: dict[str, bytes]) -> dict[str, bool]:
        async with self.connected() as (_, client):

            async def task_item(name: str, value: bytes):
                try:
                    await client.put_object(Bucket=self.bucket, Key=self._key(name), Body=value)
                    return name, True
                except Exception as e:
                    pc_logging.debug("cache: %s: failed to store '%s': %s" % (self.name, name, e))
                    return name, False

            results = await asyncio.gather(*[asyncio.create_task(task_item(n, v)) for n, v in items.items()])
        return {name: ok for name, ok in results if ok}


def _client_kwargs(user_config) -> dict:
    """The client options the user configured, leaving the rest to boto3.

    Anything not set here falls through to the standard AWS resolution chain -
    environment, profile, instance role - so a deployment that already has
    credentials needs nothing but the bucket name.
    """
    kwargs = {}
    if user_config.cache_s3_endpoint_url:
        kwargs["endpoint_url"] = user_config.cache_s3_endpoint_url
    if user_config.cache_s3_region:
        kwargs["region_name"] = user_config.cache_s3_region
    return kwargs


def _is_miss(error: Exception) -> bool:
    """Whether an S3 error means 'no such entry' rather than a real failure."""
    response = getattr(error, "response", None)
    if not isinstance(response, dict):
        return False
    code = str(response.get("Error", {}).get("Code", ""))
    status = str(response.get("ResponseMetadata", {}).get("HTTPStatusCode", ""))
    return code in _MISS_CODES or status == "404"
