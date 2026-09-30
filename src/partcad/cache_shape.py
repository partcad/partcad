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
from .cache_backend import PROPERTIES_SUFFIX
from .cache_hash import CacheHash
from .utils import total_size

# The on-disk shape cache used to be pickled. That worked only because the
# wrapper protocol installed OCP 'copyreg' handlers as a global side effect -
# without them 'pickle.dumps()' cannot serialize a TopoDS_Shape at all. Now
# that the protocol no longer registers them, the cache stores plain data,
# which also removes an arbitrary code execution path from a cache file.
#
# What it stores is the payload plus the metadata the producer recorded with it,
# and never the envelope's outer layer. The outer layer (name, label, placement)
# says which object this is, which several objects sharing one geometry cannot
# agree on; the metadata describes the geometry itself, so it belongs to the
# entry exactly as much as the BREP does.
#
# **One entry holds both.** Everything learnt about a shape as it was built -
# how big it is, what its source file stated, what that file said about
# individual elements - was previously written to sibling entries keyed on the
# same hash with a suffix. That made the geometry and the facts about it
# separately present, separately missing, and separately readable, which is
# three ways for them to disagree about one object. Now a cache hit either
# carries the lot or is not a hit.
#
# A lone shape (a part or a sketch, and the bulk of what is cached) is stored as
# the zstd-compressed BREP frame the core already holds in memory: it goes to
# the storage tier byte for byte, with no JSON, no base64 and no re-encoding.
# That is worth keeping, so metadata does not turn such an entry into JSON.
# Instead it is framed in front of the BREP, which stays exactly the bytes it
# was (see _FRAME_MAGIC).
#
# Anything else (an assembly tree, a list of components) has to be JSON, and
# there each payload it holds is base64 - the one form JSON can carry.
#
# The three are told apart on read by the leading bytes: the frame by its magic,
# JSON produced here is always an object or an array, and a BREP payload is
# either a zstd frame or, where the peer had no zstd, the ASCII BREP header -
# the same distinction 'wrappers/ocp_serialize.py' already relies on.
_BREP_PREFIXES = (b"\x28\xb5\x2f\xfd", b"CASCADE Topology", b"DBRep_DrawableShape")

# A BREP payload with metadata in front of it:
#
#     b"PCM1" | 4-byte big-endian length of the JSON | JSON metadata | BREP
#
# Chosen over putting the BREP inside the JSON because the BREP is by far the
# largest thing here and base64 would cost a third of its size and a copy in
# each direction, on every read and every write, to carry a few hundred bytes of
# metadata. Here the BREP is still the exact bytes the core holds, at a known
# offset, and reading it back is a slice.
#
# The magic cannot collide with either of the other two forms: no zstd frame and
# no BREP file begins with it, and neither does JSON.
_FRAME_MAGIC = b"PCM1"
_FRAME_HEADER = len(_FRAME_MAGIC) + 4


def _serialize(value) -> bytes:
    """The bytes to store for a cache value, with no outer layer left in them.

    A lone shape with nothing recorded about it needs no conversion at all: the
    core already carries its payload as the compressed bytes, so they are handed
    to the storage tier as they are, with nothing copied and nothing re-encoded.
    One with metadata is the same bytes behind a small frame (see _FRAME_MAGIC),
    so that the geometry and what is known about it are one entry without the
    geometry paying for it.
    """
    metadata = shape_envelope.metadata_of(value)
    payload = shape_envelope.strip_metadata(value)
    # The metadata is taken out before asking whether this is a lone shape,
    # because 'strip_metadata()' deliberately leaves it in place. Asking with it
    # still there answers "no" for every shape that carries any, which silently
    # sends the largest thing here down the base64 path it exists to avoid.
    geometry = payload
    if isinstance(payload, dict) and shape_envelope.KEY_METADATA in payload:
        geometry = {key: value for key, value in payload.items() if key != shape_envelope.KEY_METADATA}
    if isinstance(geometry, dict) and list(geometry) == [shape_envelope.KEY_BREP]:
        brep = shape_envelope.brep_bytes(geometry[shape_envelope.KEY_BREP])
        if not metadata:
            return brep
        header = json.dumps(metadata).encode("utf-8")
        return _FRAME_MAGIC + len(header).to_bytes(4, "big") + header + brep
    payload = geometry
    if metadata:
        # An assembly or a component list: already JSON, so the metadata is one
        # more key in it rather than a frame around it.
        payload = dict(payload)
        payload[shape_envelope.KEY_METADATA] = metadata
    return json.dumps(shape_envelope.encode(payload)).encode("utf-8")


def _deserialize(data: bytes):
    """Inverse of '_serialize()' - the payload and its metadata, no outer layer."""
    if data.startswith(_FRAME_MAGIC):
        length = int.from_bytes(data[len(_FRAME_MAGIC) : _FRAME_HEADER], "big")
        metadata = json.loads(data[_FRAME_HEADER : _FRAME_HEADER + length].decode("utf-8"))
        return {
            shape_envelope.KEY_BREP: data[_FRAME_HEADER + length :],
            shape_envelope.KEY_METADATA: metadata,
        }
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

    This is the one thing about a shape that is still kept apart from it, and
    the reason is the sentence above: it is *declared* rather than produced,
    so the hash the geometry is keyed on does not cover it. Everything the
    machinery that built the geometry learnt - its size, what its source file
    stated - is inside the geometry's own entry, because the same hash makes
    it valid or stale.
    """
    return kind + PROPERTIES_SUFFIX


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
