#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The filesystem tier of the cache ('cacheFiles').

One file per entry, named after the entry, under the per-user internal state
directory. The payload is written byte for byte - a shape entry is the
zstd-compressed BREP frame the core holds in memory, so there is nothing to
encode on the way in and nothing to decode on the way out.
"""

import asyncio
import os
import uuid
from pathlib import Path

import aiofiles

from .cache_backend import CacheBackend
from . import telemetry


@telemetry.instrument()
class FilesCacheBackend(CacheBackend):
    """Cache entries as files under '<internal state dir>/cache/<data type>'."""

    name = "files"
    stores_names = True

    def __init__(self, user_config, data_type: str) -> None:
        super().__init__(
            user_config,
            data_type,
            min_entry_size=user_config.cache_min_entry_size,
            max_entry_size=user_config.cache_max_entry_size,
        )
        self.cache_dir = Path(user_config.internal_state_dir) / "cache" / data_type
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def path(self, name: str) -> Path:
        return self.cache_dir / name

    async def _read_async(self, names: list[str]) -> dict[str, bytes]:
        async def task_item(name: str):
            try:
                async with aiofiles.open(self.path(name), "rb") as f:
                    return name, await f.read()
            except FileNotFoundError:
                return name, None

        results = await asyncio.gather(*[asyncio.create_task(task_item(name)) for name in names])
        return {name: data for name, data in results if data is not None}

    async def _write_async(self, items: dict[str, bytes]) -> dict[str, bool]:
        saved = {}

        async def task_item(name: str, value: bytes) -> None:
            # Through a temporary file in the same directory: opening the entry
            # itself for writing truncates what is there before the new payload
            # is complete, and a read running at the same time would come back
            # with an empty or half-written frame.
            path = self.path(name)
            tmp_path = path.with_name("%s.%s.tmp" % (path.name, uuid.uuid4().hex))
            try:
                async with aiofiles.open(tmp_path, "wb") as f:
                    await f.write(value)
                os.replace(tmp_path, path)
            except BaseException:
                tmp_path.unlink(missing_ok=True)
                raise
            saved[name] = True

        await asyncio.gather(*[asyncio.create_task(task_item(name, value)) for name, value in items.items()])
        return saved
