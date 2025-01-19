#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-17
#
# Licensed under Apache License, Version 2.0.
#

import pickle

from .cache import Cache
from .cache_hash import CacheHash
from .shape import Shape
from .user_config import user_config
from .utils import total_size

SERIALIZATION_PICKLE = 1
SERIALIZATION_BREP = 2


class ShapeCache(Cache):
    def __init__(self, serialization: int = SERIALIZATION_PICKLE) -> None:
        super().__init__("shapes")
        self.serialization = serialization

    async def write_async(self, hash: CacheHash, items: dict[str, object]) -> dict[str, bool]:
        results = {}
        if user_config.cache:
            serialized_items = {}
            for key, value in items.items():
                # TODO(clairbee): if we know this is a valid solid, then we should use faster BREP
                # if key.startswith(["part", "assembly"]):
                #     # serialization = SERIALIZATION_BREP
                # else:
                serialization = self.serialization
                if serialization == SERIALIZATION_PICKLE:
                    data = pickle.dumps(value)
                elif serialization == SERIALIZATION_BREP:
                    data = Shape.to_brep(value)
                else:
                    raise ValueError(f"Unknown serialization type: {serialization}")
                serialized_items[key] = data

            cached_in_files = await self.write_data_async(hash, serialized_items)

        for key, value in items.items():
            if user_config.cache:
                key_is_cached_in_files = cached_in_files.get(key, False)
                data_len = total_size(value)
            else:
                key_is_cached_in_files = False
                if user_config.cache_memory_max_entry_size > 0:
                    # Need to know the object size to check the max limit
                    data_len = total_size(value)

            if user_config.cache_memory_max_entry_size > 0 and data_len > user_config.cache_memory_max_entry_size:
                # If the object is too big, we can free the memory
                results[key] = False
            elif (
                key_is_cached_in_files
                and user_config.cache_memory_double_cache_max_entry_size > 0
                and data_len > user_config.cache_memory_double_cache_max_entry_size
            ):
                # The object is bigger than what we want to store in both caches
                results[key] = False
            else:
                results[key] = True

        return results

    async def read_async(self, hash: CacheHash, keys: list[str]) -> tuple[dict[str, object], dict[str, bool]]:
        if not user_config.cache:
            # Caching is disabled
            return {}, {}

        hash_str = hash.get()
        if hash_str is None:
            # Not enough data to hash
            return {}, {}

        results = {}
        in_memory = {}
        values = await self.read_data_async(hash, keys)
        for key in keys:
            if key not in values:
                results[key] = None
                in_memory[key] = False
                continue

            data = values[key]
            if data is None or len(data) == 0:
                results[key] = None
                in_memory[key] = False
                continue

            # TODO(clairbee): if we know this is a valid solid, then we should use faster BREP
            # if key.startswith(["part", "assembly"]):
            #     # serialization = SERIALIZATION_BREP
            # else:
            serialization = self.serialization
            if serialization == SERIALIZATION_PICKLE:
                try:
                    obj = pickle.loads(data)
                except pickle.UnpicklingError:
                    results[key] = None
                    in_memory[key] = False
                    continue
            elif serialization == SERIALIZATION_BREP:
                obj = Shape.from_brep(data)
            else:
                raise ValueError(f"Unknown serialization type: {serialization}")
            results[key] = obj

            data_len = len(data)

            if user_config.cache_memory_max_entry_size > 0 and data_len > user_config.cache_memory_max_entry_size:
                # If the object is too big, we can free the memory
                in_memory[key] = False
            elif (
                user_config.cache_memory_double_cache_max_entry_size > 0
                and data_len > user_config.cache_memory_double_cache_max_entry_size
            ):
                # The object is bigger than what we want to store in both caches
                in_memory[key] = False
            else:
                # Return the object and advise to keep it in memory
                in_memory[key] = True

        return results, in_memory
