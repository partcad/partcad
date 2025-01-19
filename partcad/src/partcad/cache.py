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
from .user_config import user_config
import aiofiles


class Cache:
    def __init__(self, data_type: str):
        """Initialize cache for specific data type."""
        self.data_type = data_type
        self.cache_dir = Path(user_config.internal_state_dir) / "cache" / data_type
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_cache_path(self, hash: CacheHash) -> Path:
        """Get the file path for a cached object."""
        return self.cache_dir / hash.get()

    def _needs_write_data(self, data_len: int) -> bool:
        """Check if object needs to be written to cache."""
        # Make an exception for 1 byte objects to cache test results
        if data_len >= 2 and data_len < user_config.cache_min_entry_size:
            # This object is too small to cache
            return False
        if data_len > user_config.cache_max_entry_size:
            # This object is too big to cache
            return False

        return True

    async def write_data_async(self, hash: CacheHash, items: dict[str, bytes]) -> dict[str, bool]:
        """Write object to cache and return its hash."""
        if not user_config.cache:
            # Caching is disabled
            return {}

        cache_path = self.get_cache_path(hash)

        saved = {}

        async def task_item(key, value) -> None:
            async with aiofiles.open(f"{cache_path}.{key}", "wb") as f:
                await f.write(value)
            saved[key] = True

        tasks = []
        for key, value in items.items():
            if key.startswith(("shape", "sketch", "part", "assembly", "cmps")):
                data_len = len(value)
                if not self._needs_write_data(data_len):
                    continue

            tasks.append(asyncio.create_task(task_item(key, value)))

        if tasks:
            tasks.append(asyncio.create_task(task_item("name", hash.name.encode())))
            await asyncio.gather(*tasks)

        # Report that it is saved to the filesystem
        return saved

    async def read_data_async(self, hash: CacheHash, keys: list[str]) -> dict[str, bytes]:
        """Read object from cache using its hash."""
        if not user_config.cache:
            # Caching is disabled
            return {}

        cache_path = self.get_cache_path(hash)

        async def task_item(key: str) -> list:
            try:
                async with aiofiles.open(f"{cache_path}.{key}", "rb") as f:
                    return [key, await f.read()]
            except FileNotFoundError:
                return [key, None]

        tasks = [asyncio.create_task(task_item(key)) for key in keys]

        results = {result[0]: result[1] for result in await asyncio.gather(*tasks)}
        return results

    def exists(self, obj_hash: str) -> bool:
        """Check if object exists in cache."""
        return self.get_cache_path(obj_hash).exists()
