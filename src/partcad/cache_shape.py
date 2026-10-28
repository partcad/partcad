#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-17
#
# Licensed under Apache License, Version 2.0.
#

import json

try:
    # As in 'shape_envelope': the standard library from 3.14, its backport below.
    from compression.zstd import ZstdDecompressor as _ZstdDecompressor
    from compression.zstd import compress as _zstd_compress
except ImportError:  # pragma: no cover - exercised on the other interpreter
    try:
        from backports.zstd import ZstdDecompressor as _ZstdDecompressor
        from backports.zstd import compress as _zstd_compress
    except ImportError:
        _ZstdDecompressor = None
        _zstd_compress = None

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
# An assembly's tree is mostly repeats: the LEGO castle is 731 placements of 9
# bricks. Written as JSON with each node's payload in base64, that entry was
# 33 MB for 4.6 MB of geometry - over every file tier's limit, so the castle was
# never cached at all and every run put it together again. So a tree is framed
# too (see _TREE_MAGIC): the tree as JSON with each node naming its payload, and
# each distinct payload once, after it, as the bytes it is.
#
# A tree written as plain JSON, by an earlier release, is still read: JSON
# produced here is always an object or an array. An earlier release reading a
# framed tree finds neither and counts it a miss, which is the right answer for
# an entry it cannot read; it builds the tree and writes it in its own form.
# That is also why nothing else is framed - see _serialize - with one exception
# no earlier release can meet: the components of a shape that are pieces of it
# (shape_envelope.KEY_CHILD), which name the payload of the geometry entry beside
# them instead of holding a copy of it.
#
# They are told apart on read by the leading bytes: each frame by its magic, JSON
# by its first character, and a BREP payload is either a zstd frame or, where the
# peer had no zstd, the BREP header - binary or ASCII, each of which OCCT writes
# after a newline - the same distinction 'wrappers/ocp_serialize.py' already
# relies on.
_BREP_PREFIXES = (
    b"\x28\xb5\x2f\xfd",
    b"\nOpen CASCADE Topology",
    b"\nCASCADE Topology",
    b"CASCADE Topology",
    b"DBRep_DrawableShape",
)

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

# An assembly's tree, with each distinct payload once:
#
#     b"PCT1" | 1-byte encoding | 4-byte big-endian length of the header | header | payloads
#
# The header is JSON, zstd-compressed when the encoding byte is b"Z" and plain
# when it is b"J": {"tree": <the tree, each node naming its payload by
# 'shape_envelope.KEY_BREP_REF'>, "payloads": [[digest, length], ...]}. The
# payloads follow in that order, each the compressed BREP it is in memory.
# Reading it back gives every node naming one digest the same bytes object, so
# the tree held in memory holds each payload once too.
#
# A header may also say "beside": {digest: key} - payloads the tree names that
# are not in this entry at all, because they are the geometry of the entry
# written beside it under 'key', in the same write. That is how a shape's
# components are stored when they are pieces of it (shape_envelope.KEY_CHILD):
# the shape's payload once, in its own entry, and in the components' entry
# which piece of it each one is. Read back, such an entry needs that other entry
# read with it, and holding the payload it names - checked by its digest -
# or it is a miss.
_TREE_MAGIC = b"PCT1"
_TREE_COMPRESSED = b"Z"
_TREE_PLAIN = b"J"
_TREE_HEADER = len(_TREE_MAGIC) + 1 + 4

# How far a tree's compressed header may expand when it is read back, as a
# multiple of its compressed size and never less than the floor. A header is
# names, labels, placements and ports, which compress well but not without
# limit; what the bound is for is an entry that came out of a shared tier and
# was not written by this code (see 'shape_envelope.MAX_BREP_EXPANSION').
_TREE_MAX_EXPANSION = 200
_TREE_MAX_EXPANSION_FLOOR = 64 << 20


def _serialize(value, beside=None) -> bytes:
    """The bytes to store for a cache value, with no outer layer left in them.

    A lone shape with nothing recorded about it needs no conversion at all: the
    core already carries its payload as the compressed bytes, so they are handed
    to the storage tier as they are, with nothing copied and nothing re-encoded.
    One with metadata is the same bytes behind a small frame (see _FRAME_MAGIC),
    so that the geometry and what is known about it are one entry without the
    geometry paying for it.

    'beside' is the payloads of the lone shapes written in the same write, by
    their keys: a list of components that are pieces of one of them names it
    rather than holding it (see _TREE_MAGIC).
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
        # An assembly or a component list: a tree, whose header is JSON, so the
        # metadata is one more key in it rather than a frame of its own.
        payload = dict(payload)
        payload[shape_envelope.KEY_METADATA] = metadata
    if shape_envelope.is_assembly_object(payload):
        return _serialize_tree(payload)
    if _holds_pieces(payload):
        # Components that are pieces of the geometry beside them
        # (shape_envelope.KEY_CHILD): as JSON, each would carry a copy of that
        # geometry's payload, so they are framed, and name it instead. Framing
        # is safe here, as it is not for the JSON below, because no earlier
        # release ever reads such an entry: the wrappers that make these
        # components raised their CACHE_VERSION when they started to, and the
        # key of every shape carries the versions of the wrappers that build
        # it - so a release that does not make them computes another key, and
        # misses this entry and the geometry beside it alike.
        return _serialize_tree(payload, beside)
    # Everything else is the plain JSON it always was, and for a reason beyond
    # there being nothing to share. A part's components ('cmps') sit beside its
    # geometry in an entry of their own, and an earlier release reading a frame
    # it does not know counts that one entry a miss: the geometry beside it
    # would be a hit, and the part would come back without its components - a
    # partial hit, which is worse than a miss. An assembly's tree is the whole
    # of the assembly, so for it a frame an earlier release cannot read is a
    # miss of everything, and a rebuild.
    return json.dumps(shape_envelope.encode(payload)).encode("utf-8")


def _holds_pieces(value) -> bool:
    """Whether a list of components holds one that is a piece of another shape (KEY_CHILD)."""
    if isinstance(value, list):
        return any(_holds_pieces(item) for item in value)
    return isinstance(value, dict) and shape_envelope.KEY_CHILD in value


def _serialize_tree(payload, beside=None) -> bytes:
    """A tree as a _TREE_MAGIC frame: its structure, then each distinct payload once.

    A payload that is one of 'beside' (by key) is named rather than written.
    """
    payloads = shape_envelope.Payloads()
    tree = shape_envelope.encode(payload, payloads=payloads)
    order = []
    named = {}
    for digest, value in payloads.by_digest.items():
        key = _beside_key(value, beside)
        if key is None:
            order.append((digest, value))
        else:
            named[digest] = key
    header = {"tree": tree, "payloads": [[digest, len(shape_envelope.brep_bytes(value))] for digest, value in order]}
    if named:
        header["beside"] = named
    header = json.dumps(header).encode("utf-8")
    if _zstd_compress is not None:
        encoding, header = _TREE_COMPRESSED, _zstd_compress(header)
    else:  # pragma: no cover - PartCAD depends on zstd; see shape_envelope
        encoding = _TREE_PLAIN
    return b"".join(
        [_TREE_MAGIC, encoding, len(header).to_bytes(4, "big"), header]
        + [shape_envelope.brep_bytes(value) for _digest, value in order]
    )


def _beside_key(value, beside):
    """The key of the entry in 'beside' whose payload 'value' is, or None."""
    if not beside:
        return None
    data = shape_envelope.brep_bytes(value)
    for key, other in beside.items():
        # Usually the very object: the components were decoded out of the
        # same answer as the shape, and hold the one bytes object.
        if other is data or other == data:
            return key
    return None


def _deserialize_tree(data: bytes, beside=None):
    """Inverse of '_serialize_tree()'. 'beside' is the payloads read with it, by their keys."""
    encoding = data[len(_TREE_MAGIC) : len(_TREE_MAGIC) + 1]
    length = int.from_bytes(data[len(_TREE_MAGIC) + 1 : _TREE_HEADER], "big")
    header = data[_TREE_HEADER : _TREE_HEADER + length]
    if encoding == _TREE_COMPRESSED:
        if _ZstdDecompressor is None:  # pragma: no cover - see _serialize_tree
            raise ValueError("this tree's header is zstd-compressed, and zstd is not available here")
        limit = max(_TREE_MAX_EXPANSION_FLOOR, _TREE_MAX_EXPANSION * len(header))
        decompressor = _ZstdDecompressor()
        header = decompressor.decompress(header, max_length=limit)
        if not decompressor.eof:
            raise ValueError("this tree's header did not decompress into %d bytes or fewer" % limit)
    elif encoding != _TREE_PLAIN:
        raise ValueError("unknown tree encoding %r" % (encoding,))
    header = json.loads(header.decode("utf-8"))
    view = memoryview(data)
    table = {}
    offset = _TREE_HEADER + length
    for digest, size in header["payloads"]:
        # A size the writer could not have written -- negative, or not a whole
        # number -- would read the wrong bytes for every payload after it.
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ValueError("this tree's header gives a payload a size of %r" % (size,))
        if offset + size > len(data):
            raise ValueError("this tree's payloads end before its header says they do")
        table[digest] = bytes(view[offset : offset + size])
        offset += size
    # And nothing after the last one: the writer writes nothing there.
    if offset != len(data):
        raise ValueError("this tree goes on %d bytes past its last payload" % (len(data) - offset))
    for digest, key in (header.get("beside") or {}).items():
        # The entry beside it could have been written by another build - a
        # shared tier, an entry evicted and written again - and the pieces of
        # one compound are not the pieces of another.
        payload = (beside or {}).get(key)
        if payload is None or shape_envelope.payload_digest(payload) != digest:
            raise ValueError(
                "this entry names the geometry of the entry %r beside it, which was not read with it" % key
            )
        table[digest] = payload
    return shape_envelope.decode(header["tree"], table)


def _is_tree(data) -> bool:
    """Whether stored bytes are a _TREE_MAGIC frame."""
    return data is not None and bytes(data[: len(_TREE_MAGIC)]) == _TREE_MAGIC


def _deserialize(data: bytes, beside=None):
    """Inverse of '_serialize()' - the payload and its metadata, no outer layer."""
    if data.startswith(_FRAME_MAGIC):
        length = int.from_bytes(data[len(_FRAME_MAGIC) : _FRAME_HEADER], "big")
        metadata = json.loads(data[_FRAME_HEADER : _FRAME_HEADER + length].decode("utf-8"))
        return {
            shape_envelope.KEY_BREP: data[_FRAME_HEADER + length :],
            shape_envelope.KEY_METADATA: metadata,
        }
    if data.startswith(_TREE_MAGIC):
        return _deserialize_tree(data, beside)
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
            # The geometry written in this write, which components that are
            # pieces of it name rather than repeat.
            beside = {
                key: shape_envelope.brep_bytes(value[shape_envelope.KEY_BREP])
                for key, value in items.items()
                if shape_envelope.is_shape_object(value) and shape_envelope.KEY_CHILD not in value
            }
            stored = await self.write_data_async(hash, {key: _serialize(value, beside) for key, value in items.items()})

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
        # Frames last: one may name the payload of another entry read in the
        # same call (see _TREE_MAGIC), which has to have been read first.
        beside = {}
        for key in sorted(keys, key=lambda key: _is_tree(values.get(key))):
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
                payload = _deserialize(data, beside)
            except Exception:
                results[key] = None
                in_memory[key] = False
                continue
            if shape_envelope.is_shape_object(payload) and shape_envelope.KEY_CHILD not in payload:
                beside[key] = payload[shape_envelope.KEY_BREP]
            results[key] = shape_envelope.apply_metadata(payload, metadata)
            # It came from a persistent tier, so the tighter of the two memory
            # limits is the one that applies.
            in_memory[key] = self._keep_in_memory(len(data), True)

        return results, in_memory
