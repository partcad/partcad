#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-17
#
# Licensed under Apache License, Version 2.0
#

import asyncio
from pathlib import Path

from .cache_hash import CacheHash
import aiofiles


class Cache:
    def __init__(self, data_type: str, user_config) -> None:
        """Initialize cache for specific data type."""
        self.data_type = data_type
        self.user_config = user_config
        self.cache_dir = Path(user_config.internal_state_dir) / "cache" / data_type
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_cache_path(self, hash: CacheHash) -> Path:
        """Get the file path for a cached object."""
        hash_str = hash.get()
        if not hash_str:
            return None
        return self.cache_dir / hash_str

    def _needs_write_data(self, data_len: int) -> bool:
        """Check if object needs to be written to cache."""
        # Make an exception for 1 byte objects to cache test results
        if data_len >= 2 and data_len < self.user_config.cache_min_entry_size:
            # This object is too small to cache
            return False
        if data_len > self.user_config.cache_max_entry_size:
            # This object is too big to cache
            return False

        return True

    def _should_cache_key(self, key: str, value: bytes) -> bool:
        if not key.startswith(("shape", "sketch", "part", "assembly", "cmps")):
            return True
        return self._needs_write_data(len(value))

    async def write_data_async(self, hash: CacheHash, items: dict[str, bytes]) -> dict[str, bool]:
        """Write object to cache and return its hash."""
        if not self.user_config.cache:
            # Caching is disabled
            return {}

        cache_path = self.get_cache_path(hash)
        if not cache_path:
            # Hash is not produced
            return {}

        saved = {}

        async def task_item(key: str, value: bytes) -> None:
            async with aiofiles.open(f"{cache_path}.{key}", "wb") as f:
                await f.write(value)
            saved[key] = True

        tasks = [
            asyncio.create_task(task_item(key, value))
            for key, value in items.items()
            if self._should_cache_key(key, value)
        ]
        if tasks:
            tasks.append(asyncio.create_task(task_item("name", hash.name.encode())))
            await asyncio.gather(*tasks)

        # Report that it is saved to the filesystem
        return saved

    async def read_data_async(self, hash: CacheHash, keys: list[str]) -> dict[str, bytes]:
        """Read object from cache using its hash."""
        if not self.user_config.cache:
            # Caching is disabled
            return {}

        cache_path = self.get_cache_path(hash)
        if not cache_path:
            # Hash is not produced
            return {}

        async def task_item(key: str) -> tuple[str, bytes]:
            try:
                async with aiofiles.open(f"{cache_path}.{key}", "rb") as f:
                    return [key, await f.read()]
            except FileNotFoundError:
                return [key, None]

        tasks = [asyncio.create_task(task_item(key)) for key in keys]

        return dict(await asyncio.gather(*tasks))
