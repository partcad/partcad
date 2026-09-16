#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-17
#
# Licensed under Apache License, Version 2.0.
#

import json

from . import shape_envelope, telemetry
from .cache import Cache
from .cache_backend import MEASUREMENTS_SUFFIX, METADATA_SUFFIX, PROPERTIES_SUFFIX
from .cache_hash import CacheHash
from .utils import total_size

# The on-disk shape cache used to be pickled. That worked only because the
# wrapper protocol installed OCP 'copyreg' handlers as a global side effect -
# without them 'pickle.dumps()' cannot serialize a TopoDS_Shape at all. Now
# that the protocol no longer registers them, the cache stores plain data,
# which also removes an arbitrary code execution path from a cache file.
#
# What it stores is the payload alone - never the envelope's outer layer. A
# lone shape (a part or a sketch, and the bulk of what is cached) is stored as
# the zstd-compressed BREP frame the core already holds in memory: it goes to
# the storage tier byte for byte, with no JSON, no base64 and no re-encoding.
# Anything else (an assembly tree, a list of components) has to be JSON, and
# there each payload it holds is base64 - the one form JSON can carry.
#
# The two are told apart on read by the leading bytes: JSON produced here is
# always an object or an array, while a BREP payload is either a zstd frame or,
# where the peer had no zstd, the ASCII BREP header - the same distinction
# 'wrappers/ocp_serialize.py' already relies on.
_BREP_PREFIXES = (b"\x28\xb5\x2f\xfd", b"CASCADE Topology", b"DBRep_DrawableShape")


def _serialize(value) -> bytes:
    """The bytes to store for a cache value, with no outer layer left in them.

    A lone shape needs no conversion at all: the core already carries its
    payload as the compressed bytes, so they are handed to the storage tier as
    they are, with nothing copied and nothing re-encoded.
    """
    payload = shape_envelope.strip_metadata(value)
    if isinstance(payload, dict) and list(payload) == [shape_envelope.KEY_BREP]:
        return shape_envelope.brep_bytes(payload[shape_envelope.KEY_BREP])
    return json.dumps(shape_envelope.encode(payload)).encode("utf-8")


def _deserialize(data: bytes):
    """Inverse of '_serialize()' - the payload, still without an outer layer."""
    if data.startswith(_BREP_PREFIXES):
        return {shape_envelope.KEY_BREP: data}
    return shape_envelope.decode(json.loads(data.decode("utf-8")))


def properties_key(kind: str) -> str:
    """The key holding what the shape cached under 'kind' reports about itself.

    Beside the geometry rather than inside it, because the two go stale on
    different occasions: the hash covers 'parameters', 'offset' and 'scale'
    only, so editing a 'properties:' section leaves the geometry entry valid,
    and properties buried in that entry would go on being answered with the ones
    it happened to be written with. An entry of its own is written, read and
    missed on its own - and a shape's properties can be had without pulling its
    geometry back out of the cache.
    """
    return kind + PROPERTIES_SUFFIX


def metadata_key(kind: str) -> str:
    """The key holding what the *file* the shape came from stated about itself.

    A STEP file's layers and property sets, a DXF drawing's layers and units:
    read by the wrapper that imports the file, carried back on the envelope
    beside the BREP, and stored here.

    Beside the geometry for the same reason the properties are, and one more of
    its own: it is answered without pulling a BREP back out of the cache, which
    is what 'pc info' wants - it asks what the file said, not what the shape is.
    A shape type that reads no file never writes this entry, and a missing entry
    reads as "nothing stated" rather than as a reason to build again.
    """
    return kind + METADATA_SUFFIX


def measurements_key(kind: str) -> str:
    """The key holding what the geometry measures: its box, its volume, its solids.

    Unlike the two above this is *derived* from the geometry rather than stated
    beside it, so it is exactly as valid as the entry it is named after - the
    same hash covers both, and a shape that rebuilds measures again. It is a
    separate entry all the same, because the measuring costs a sandbox and the
    question ("how big is it?") is asked far more often than the BREP is needed.
    """
    return kind + MEASUREMENTS_SUFFIX


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

    def _keep_in_memory(self, data_len: int, stored: bool) -> bool:
        """Whether an entry of this size is worth holding on to in memory.

        'stored' says whether a persistent tier took it, which is what makes the
        second, tighter limit apply: an entry that is on disk or on a server
        already is cheap to get back, so keeping a large copy of it in memory as
        well buys little.
        """
        if not self.user_config.cache_memory:
            return False
        max_size = self.user_config.cache_memory_max_entry_size
        if max_size > 0 and data_len > max_size:
            # If the object is too big, we can free the memory
            return False
        double_max_size = self.user_config.cache_memory_double_cache_max_entry_size
        if stored and double_max_size > 0 and data_len > double_max_size:
            # The object is bigger than what we want to store in both caches
            return False
        return True

    async def write_async(self, hash: CacheHash, items: dict[str, object]) -> dict[str, bool]:
        stored = {}
        if self.enabled:
            stored = await self.write_data_async(hash, {key: _serialize(value) for key, value in items.items()})

        results = {}
        for key, value in items.items():
            if not self.user_config.cache_memory:
                results[key] = False
                continue
            results[key] = self._keep_in_memory(total_size(value), stored.get(key, False))
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
        if not self.enabled:
            # Every persistent tier is disabled
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
            # It came from a persistent tier, so the tighter of the two memory
            # limits is the one that applies.
            in_memory[key] = self._keep_in_memory(len(data), True)

        return results, in_memory
