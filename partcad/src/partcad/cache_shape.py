#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-17
#
# Licensed under Apache License, Version 2.0.
#

import base64
import json

from .cache import Cache
from .cache_hash import CacheHash
from .utils import total_size
from . import shape_envelope
from . import telemetry

# The on-disk shape cache used to be pickled. That worked only because the
# wrapper protocol installed OCP 'copyreg' handlers as a global side effect -
# without them 'pickle.dumps()' cannot serialize a TopoDS_Shape at all. Now
# that the protocol no longer registers them, the cache stores plain data,
# which also removes an arbitrary code execution path from a cache file.
#
# What it stores is the payload alone - never the envelope's outer layer. A
# lone shape (a part or a sketch, and the bulk of what is cached) is stored as
# the BREP bytes themselves, with no JSON around them at all; anything else (an
# assembly tree, a list of components) is stored as JSON. The two are told
# apart on read by the leading bytes: JSON produced here is always an object or
# an array, while a BREP payload is either a zstd frame or the ASCII BREP
# header - the same distinction 'wrappers/ocp_serialize.py' already relies on.
_BREP_PREFIXES = (b"\x28\xb5\x2f\xfd", b"CASCADE Topology", b"DBRep_DrawableShape")


def _serialize(value) -> bytes:
    """The bytes to store for a cache value, with no outer layer left in them."""
    payload = shape_envelope.strip_metadata(value)
    if isinstance(payload, dict) and list(payload) == [shape_envelope.KEY_BREP]:
        return base64.b64decode(payload[shape_envelope.KEY_BREP])
    return json.dumps(payload).encode("utf-8")


def _deserialize(data: bytes):
    """Inverse of '_serialize()' - the payload, still without an outer layer."""
    if data.startswith(_BREP_PREFIXES):
        return {shape_envelope.KEY_BREP: base64.b64encode(data).decode("ascii")}
    return json.loads(data.decode("utf-8"))


@telemetry.instrument()
class ShapeCache(Cache):
    """The on-disk cache of shape geometry.

    An entry is keyed on a hash of what produces the geometry, so objects that
    produce identical geometry legitimately share one entry - and objects that
    share an entry are not the same object: they differ in name, in label, and
    an assembly also in placement. None of that is stored. 'write_async' strips
    the envelope's outer layer and keeps the payload, and 'read_async' wraps the
    caller's own outer layer back around it as the shape is materialized.
    Storing it instead would let whichever object reached the cache first lend
    its name to every other object that shares its geometry.
    """

    def __init__(self, user_config=None) -> None:
        super().__init__("shapes", user_config)

    async def write_async(self, hash: CacheHash, items: dict[str, object]) -> dict[str, bool]:
        results = {}
        if self.user_config.cache:
            serialized_items = {key: _serialize(value) for key, value in items.items()}
            cached_in_files = await self.write_data_async(hash, serialized_items)

        for key, value in items.items():
            if self.user_config.cache:
                key_is_cached_in_files = cached_in_files.get(key, False)
                data_len = total_size(value)
            else:
                key_is_cached_in_files = False
                if self.user_config.cache_memory_max_entry_size > 0:
                    # Need to know the object size to check the max limit
                    data_len = total_size(value)

            if self.user_config.cache_memory_max_entry_size > 0 and data_len > self.user_config.cache_memory_max_entry_size:
                # If the object is too big, we can free the memory
                results[key] = False
            elif (
                key_is_cached_in_files
                and self.user_config.cache_memory_double_cache_max_entry_size > 0
                and data_len > self.user_config.cache_memory_double_cache_max_entry_size
            ):
                # The object is bigger than what we want to store in both caches
                results[key] = False
            else:
                results[key] = True

        return results

    async def read_async(
        self, hash: CacheHash, keys: list[str], metadata: dict = None
    ) -> tuple[dict[str, object], dict[str, bool]]:
        """Read the cached payloads and materialize them as the caller's own objects.

        'metadata' is the outer layer to wrap around every payload read back -
        the name, the label and anything else that identifies the object asking
        rather than the geometry it shares. A value that is a list of payloads
        (the components of a shape) gets it wrapped around each of them.
        """
        if not self.user_config.cache:
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

            try:
                payload = _deserialize(data)
            except Exception:
                results[key] = None
                in_memory[key] = False
                continue
            results[key] = shape_envelope.apply_metadata(payload, metadata)

            data_len = len(data)

            if self.user_config.cache_memory_max_entry_size > 0 and data_len > self.user_config.cache_memory_max_entry_size:
                # If the object is too big, we can free the memory
                in_memory[key] = False
            elif (
                self.user_config.cache_memory_double_cache_max_entry_size > 0
                and data_len > self.user_config.cache_memory_double_cache_max_entry_size
            ):
                # The object is bigger than what we want to store in both caches
                in_memory[key] = False
            else:
                # Return the object and advise to keep it in memory
                in_memory[key] = True

        return results, in_memory
