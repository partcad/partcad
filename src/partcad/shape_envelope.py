#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Pure-Python codec for the shape wire/cache envelope - no OCP, no live shapes.

The core process standardizes on carrying shapes as BREP bytes wrapped in a
small JSON envelope, and never as live OCP objects. This module implements that
envelope without importing OCP, so it is what the core (shape.py, cache_shape.py,
transform.py and the delegating factories) uses to (de)serialize.

The envelope is the same one 'wrappers/ocp_serialize.py' produces and consumes,
so the two are wire-compatible. The difference is deliberate and is the whole
point of the split:

  * The sandbox codec (ocp_serialize) turns a shape object back into a live
    'TopoDS_Shape' on 'decode' - wrappers need the real geometry.
  * This core codec leaves a shape object as its '{"name", "label", "brep"}'
    dict on 'decode' - the core only ever moves the bytes around.

A single shape is '{"name", "label", "brep"}'; an assembly is
'{"name", "label", "assembly": [...]}'. Either may also carry an optional
"location", an optional "properties" and an optional "metadata" (see the keys
below).
Requests/responses are ordinary JSON objects that carry such shape objects
under keys like "shape" or "wrapped".

The "brep" payload is zstd-compressed BREP. Which Python type holds it depends
on the layer, and that is the whole reason this module exists:

  * In memory, in the file cache and in every remote cache it is 'bytes' - the
    compressed frame itself. Nothing there needs it to be text, and base64
    would cost a third more space and a copy in each direction.
  * On the wrapper pipe it is a base64 'str', because that hop is JSON and JSON
    has no byte type. 'encode()' puts it into that form and 'decode()' takes it
    straight back out, so the boundary is these two functions and nowhere else.
"""

import base64
import json

try:
    # Python 3.14 and newer carry zstd in the standard library; below that the
    # backport of that very module provides it, and PartCAD depends on it. Same
    # two-step, for the same reason, as in 'wrappers/ocp_serialize.py': what the
    # two sides exchange is the zstd frame format itself.
    #
    # The incremental decompressor rather than the one-shot 'decompress()': only
    # it takes a bound on how much it will produce. See 'brep_plain()'.
    from compression.zstd import ZstdDecompressor as _ZstdDecompressor
except ImportError:  # pragma: no cover - exercised on the other interpreter
    try:
        from backports.zstd import ZstdDecompressor as _ZstdDecompressor
    except ImportError:
        _ZstdDecompressor = None

# The three object shapes are told apart by which of these keys is present.
KEY_BREP = "brep"
KEY_ASSEMBLY = "assembly"
KEY_BYTES = "__bytes__"
# The geometry of a node, in the other form it can take: deflate-compressed,
# base64 binary glTF. A node carries one form or the other and never both - see
# FORM_BREP/FORM_GLTF below.
KEY_GLTF = "gltf"
# What a node's object declares about connections, as plain data: where its ports
# are, and which interface instance each belongs to. Stamped by the shape itself
# (see 'Shape.get_cache_metadata'), so it is re-applied every time a payload is
# materialized and cannot be served stale out of a cache entry that several
# objects of identical geometry share.
KEY_PORTS = "ports"
KEY_INTERFACES = "interfaces"
# On the root node of a tree: the sketches the ports anywhere in it are drawn with,
# keyed by the reference those ports name. One entry per sketch however many ports
# point at it - a bolt pattern is four ports drawn with one circle. Attached by
# 'port_sketches', which says why it is not on the ports themselves.
KEY_SKETCHES = "sketches"
# Optional placement on a shape/assembly object, carried opaquely by the core
# and turned into a real location by the geometry-side codec (ocp_serialize).
KEY_LOCATION = "location"
# Optional properties on a shape/assembly object: what the shape reports about
# itself ("material", "color", "physics"), as opposed to the parameters it was
# built from. One key rather than three, so that the envelope's key space stays
# small and everything that identifies an object travels beside its name. Like
# the placement, it is data the core carries opaquely and never interprets.
KEY_PROPERTIES = "properties"
# Optional metadata on a shape object: everything learnt about the shape by
# whatever produced it, at the moment it was produced. This is *the* channel for
# such knowledge - there is no second one - and it travels beside the BREP, is
# stored with the BREP, and comes back with the BREP.
#
# It rides here rather than being fetched later because the process that built
# the geometry is the only one that cheaply has it: the importing wrapper has
# the file open, and the encoding wrapper has the live OCCT shape in hand. Once
# either has exited, learning any of this again costs re-reading the file or
# starting a fresh sandbox and shipping the geometry back into it.
KEY_METADATA = "metadata"

# The three sections of that metadata. The core knows these three names and
# nothing below them - it stores them, hands them back, and reports them; it
# never asks which file format produced one.
#
#   measurements - what the geometry measures: its bounding box, its volume, how
#                  many solids that is the volume of. The one generic section:
#                  it is derived from the geometry itself rather than stated by
#                  any file, so it exists for every shape and its shape is fixed
#                  (see METADATA_BBOX and friends). Produced by the codec that
#                  encodes the shape, which is the code holding the live object.
#   annotations  - what the source said about the shape's individual elements,
#                  one opaque record per element. A DXF states these as XDATA
#                  against a line; the angle and radius of a sheet metal bend
#                  are here. A list the core carries and never reads into.
#   sections     - what the source said about *itself*: a STEP file's header and
#                  property sets, a DXF drawing's layers and units. Keyed by the
#                  producing wrapper's own vocabulary, and wholly opaque - the
#                  core reports these keys exactly as it was given them.
METADATA_MEASUREMENTS = "measurements"
METADATA_ANNOTATIONS = "annotations"
METADATA_SECTIONS = "sections"

# The fixed shape of the 'measurements' section. Named here, in the codec both
# ends share, so that the sandbox that fills it in and the core that reports it
# cannot come to disagree about a spelling.
METADATA_BBOX = "bbox"
METADATA_VOLUME = "volume"
METADATA_SOLIDS = "solids"

# The zstd frame header. Sniffed rather than declared in the envelope, so that
# a payload written without compression stays readable; the one copy of this
# constant on the geometry side is 'ocp_serialize.ZSTD_MAGIC'.
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"

# How far a BREP payload may expand before 'brep_plain()' refuses to finish
# decompressing it, as a multiple of the compressed size and never less than the
# floor. Both come from measurement rather than from taste: across the shapes
# the example packages build, BREP compresses by a median of 4.3x and at worst
# by 17.4x, while a zstd frame of 6 KB expands to 200 MB - a ratio of 32,000 -
# and costs nothing to write. The gap between the two is wide enough that a
# limit set in the middle of it cannot be reached by geometry.
#
# It is a ratio rather than a size so that it scales with the part instead of
# guessing how large a part may be, and the floor is there so that a payload of
# a few hundred bytes is not held to a few tens of thousands.
#
# What it defends: this is the one place the *core* process decompresses a shape.
# Everywhere else the payload is moved around unopened, and the one process that
# does open it - a sandbox running a wrapper - is a subprocess whose death costs
# one shape. The core is a daemon that may be serving several workspaces, and
# what it decompresses here comes out of a shape cache, which on a shared
# 'memcache' or 's3' backend is not necessarily something this machine wrote.
MAX_BREP_EXPANSION = 100
MAX_BREP_EXPANSION_FLOOR = 1 << 20


# The two forms a node's geometry can take, and the key each one rides under.
#
# One tree, two payloads. BREP is what the core carries everywhere and what is
# cached: it is exact, it is what every wrapper reads, and it is what an assembly
# is composed out of. glTF is tessellated and is what a renderer can draw - a
# browser has no CAD kernel - so it is what the IDE viewer is sent. Which one a
# caller wants is a parameter of 'Shape.get_representation()'; the hierarchy
# itself is built once, by one piece of code, whichever form its leaves hold.
FORM_BREP = KEY_BREP
FORM_GLTF = KEY_GLTF
FORMS = (FORM_BREP, FORM_GLTF)


def geometry_key(form: str) -> str:
    """The node key the geometry of 'form' rides under."""
    if form not in FORMS:
        raise ValueError("There is no '%s' form of a shape; it is one of %s" % (form, ", ".join(FORMS)))
    return form


def placed(node, location=None, name=None, label=None) -> dict:
    """A node re-stamped for where it sits inside another one.

    The node keeps its own geometry and, if it holds anything, its own internal
    location; the placement being applied is composed onto that - placement
    first, then the node's own - and carried as data. Nothing is realized here:
    that is what makes composing a tree free of a CAD kernel, and it is why every
    consumer of a tree composes the locations down it (see
    'ocp_serialize.decode_shape', which does it for the BREP form).

    The one piece of code that puts a node inside a node, so that an assembly
    placing a child and an interface placing a sketch on one of its ports cannot
    come to disagree about what a placement means.
    """
    from .geom import Location

    entry = dict(node)
    if name is not None:
        entry["name"] = name
    if label is not None:
        entry["label"] = label
    if location is not None:
        location = location if isinstance(location, Location) else Location(location)
        own = node.get(KEY_LOCATION)
        entry[KEY_LOCATION] = (location if own is None else location * Location(own)).as_packed()
    return entry


def is_shape_object(obj) -> bool:
    return isinstance(obj, dict) and KEY_BREP in obj


def is_assembly_object(obj) -> bool:
    return isinstance(obj, dict) and KEY_ASSEMBLY in obj


def is_gltf_object(obj) -> bool:
    """Whether 'obj' is a node whose geometry is tessellated rather than exact."""
    return isinstance(obj, dict) and KEY_GLTF in obj


def is_node(obj) -> bool:
    """Whether 'obj' is a node of a shape tree at all, in either form.

    A node has geometry, or children, or both. One that has neither is still a
    node - an assembly with nothing in it, an interface with no ports - and is
    recognised by the key that says which of the two it would carry.
    """
    return is_shape_object(obj) or is_assembly_object(obj) or is_gltf_object(obj)


def is_shape_envelope(obj) -> bool:
    """Whether 'obj' is a shape or assembly envelope this codec carries opaquely."""
    return is_shape_object(obj) or is_assembly_object(obj)


def brep_bytes(value) -> bytes:
    """The zstd-compressed BREP bytes, whether they arrived raw or base64-encoded.

    Bytes are returned as they are rather than copied: this is the hot path for
    every shape that comes out of a cache.
    """
    if isinstance(value, bytes):
        return value
    if isinstance(value, (bytearray, memoryview)):
        return bytes(value)
    return base64.b64decode(value)


def brep_base64(value) -> str:
    """The same payload as the base64 text that JSON - and only JSON - needs."""
    if isinstance(value, str):
        return value
    return base64.b64encode(value).decode("ascii")


def brep_plain(value) -> bytes:
    """The BREP bytes themselves: the payload, decompressed.

    'brep_bytes()' hands back the payload as it is carried, which is a zstd
    frame; this unwraps it into the ASCII BREP that OCCT wrote. Everything the
    core does with a shape moves the frame around unopened, so this is for the
    one thing that reads it: 'brep_inspect', which answers a question about the
    shape's topology off the bytes rather than by starting a sandbox.

    A payload that is not a zstd frame is returned as it is. That is how a peer
    without zstd writes one (see 'ocp_serialize._compress'), and telling the two
    apart by the frame header rather than by a flag in the envelope is what lets
    either be read without the format saying which it is.

    Bounded (see MAX_BREP_EXPANSION): a frame that keeps producing past the
    limit raises rather than being decompressed to the end. Raising is the right
    answer for the only caller there is - 'brep_inspect.topology()' reads a
    refusal as "this payload could not be read", which is a verdict it already
    has to have, and which reports nothing about the shape.
    """
    data = brep_bytes(value)
    if not data.startswith(ZSTD_MAGIC):
        return data
    if _ZstdDecompressor is None:
        raise RuntimeError(
            "the BREP payload is zstd-compressed, but zstd is not available here. "
            "On Python below 3.14 it comes from the 'backports.zstd' package."
        )

    limit = max(MAX_BREP_EXPANSION_FLOOR, MAX_BREP_EXPANSION * len(data))
    decompressor = _ZstdDecompressor()
    plain = decompressor.decompress(data, max_length=limit)
    if not decompressor.eof:
        # Either the frame is still producing at the limit, or it ended early.
        # Both mean the same thing here: what is in hand is not a payload.
        raise ValueError(
            "the BREP payload did not decompress into %d bytes or fewer (%dx its "
            "compressed size of %d); refusing to read it" % (limit, MAX_BREP_EXPANSION, len(data))
        )
    return plain


def make_shape(brep, name=None, label=None) -> dict:
    """A shape envelope around a zstd-compressed BREP payload."""
    return {"name": name, "label": label, KEY_BREP: brep_bytes(brep)}


def payload_key(obj):
    """The key 'obj' carries its payload under, or None if it is not an envelope."""
    if isinstance(obj, dict):
        if KEY_BREP in obj:
            return KEY_BREP
        if KEY_ASSEMBLY in obj:
            return KEY_ASSEMBLY
    return None


def metadata_of(obj):
    """The metadata an envelope carries, or None.

    'None' rather than an empty dict, because "nothing was recorded" and "the
    producer looked and found nothing" are different answers and only the
    second one is worth reporting.
    """
    if not isinstance(obj, dict):
        return None
    metadata = obj.get(KEY_METADATA)
    return metadata if isinstance(metadata, dict) and metadata else None


def metadata_section(metadata, section):
    """One section of a metadata dict, or None if it is absent or empty."""
    if not isinstance(metadata, dict):
        return None
    value = metadata.get(section)
    return value if value else None


def make_metadata(measurements=None, annotations=None, sections=None):
    """A metadata dict holding whichever of the three sections has content.

    Empty sections are left out rather than written as empty, so that an
    envelope which learnt nothing carries no metadata at all and the absence is
    the answer.
    """
    metadata = {}
    if measurements:
        metadata[METADATA_MEASUREMENTS] = measurements
    if annotations:
        metadata[METADATA_ANNOTATIONS] = list(annotations)
    if sections:
        metadata[METADATA_SECTIONS] = dict(sections)
    return metadata


def without_measurements(metadata):
    """'metadata' with its measurements section removed.

    For the one caller that has to: a shape that has just been transformed
    carries sections that are still true of it and measurements that are not,
    and merging fresh numbers over the old ones silently keeps the old ones when
    there are no fresh numbers to merge.
    """
    return {key: value for key, value in (metadata or {}).items() if key != METADATA_MEASUREMENTS}


def merge_metadata(base, overlay):
    """'base' with 'overlay''s sections laid over it, section by section.

    Used where a shape passes through a second wrapper after the one that
    imported it: 'offset'/'scale' rebuild the geometry, so the measurements that
    come back are the new ones and must win, while the sections and annotations
    the importing wrapper read are still true of the object and must survive.
    A section present in 'overlay' replaces the one in 'base' outright; a
    section absent from it is left alone.
    """
    merged = dict(base or {})
    for section, value in (overlay or {}).items():
        if value:
            merged[section] = value
    return merged


def strip_metadata(obj):
    """Return 'obj' with the outer layer taken off the envelopes it is made of.

    An envelope is a payload ("brep" or "assembly") plus an outer layer that
    says which object this is and where it sits - "name", "label", an optional
    placement, and whatever a later version adds next to them. The payload is
    geometry, which several objects may legitimately share; the outer layer is
    not. Splitting them is what lets the shape cache key an entry on the
    geometry alone (see cache_shape.py).

    Only the envelope 'obj' itself is - or the ones a list of them holds - are
    stripped. The children nested inside an assembly keep their own outer
    layers: those describe the assembly's structure, not the assembly.

    KEY_METADATA is **not** part of the outer layer and stays. The outer layer
    answers "which object is this", which is exactly what objects sharing one
    geometry disagree about; the metadata answers "what is this geometry and
    what was known about it when it was made", which they agree about by
    definition - they share the geometry it describes.
    """
    if isinstance(obj, list):
        return [strip_metadata(item) for item in obj]
    key = payload_key(obj)
    if key is None:
        return obj
    stripped = {key: obj[key]}
    metadata = metadata_of(obj)
    if metadata:
        stripped[KEY_METADATA] = metadata
    return stripped


def apply_metadata(obj, metadata):
    """Inverse of 'strip_metadata()': wrap 'metadata' around the payloads in 'obj'.

    Whatever KEY_METADATA the payload already carries is kept, for the reason
    'strip_metadata()' gives: it came out of the cache entry with the geometry
    and describes the geometry, while the outer layer being applied here is this
    particular object's.
    """
    if isinstance(obj, list):
        return [apply_metadata(item, metadata) for item in obj]
    key = payload_key(obj)
    if key is None:
        return obj
    wrapped = dict(metadata or {})
    wrapped[key] = obj[key]
    own = metadata_of(obj)
    if own:
        wrapped[KEY_METADATA] = own
    return wrapped


def encode(obj, name=None, label=None):
    """Convert 'obj' into a structure made only of JSON-native values.

    Shape and assembly envelopes keep their metadata; their "brep" payload is
    base64-encoded here, which is the one place the core turns the compressed
    bytes it carries into the text JSON can hold. Dicts, lists, tuples and sets
    are walked; other bytes become a '__bytes__' object; exceptions become their
    message. A live OCP object is rejected: the core must not hand one to this
    codec - it has nothing to turn it into bytes, and encoding geometry is a
    wrapper's job.
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj

    if isinstance(obj, dict):
        if KEY_BREP in obj or KEY_ASSEMBLY in obj:
            # An already-built shape/assembly object keeps its metadata verbatim.
            encoded = {}
            for key, value in obj.items():
                if key == KEY_BREP:
                    encoded[key] = brep_base64(value)
                elif key == KEY_ASSEMBLY:
                    encoded[key] = [encode(child, name, label) for child in value]
                elif key in (KEY_LOCATION, "name", "label"):
                    encoded[key] = value
                else:
                    encoded[key] = encode(value, name, label)
            return encoded
        return {key: encode(value, name, label) for key, value in obj.items()}

    if isinstance(obj, (list, tuple, set, frozenset)):
        return [encode(item, name, label) for item in obj]

    if isinstance(obj, (bytes, bytearray)):
        return {KEY_BYTES: base64.b64encode(bytes(obj)).decode("ascii")}

    if isinstance(obj, BaseException):
        return str(obj)

    if type(obj).__module__.split(".")[0] == "OCP":
        raise TypeError(
            "shape_envelope cannot encode the live OCP object %s: the core carries BREP "
            "envelopes, so encode it inside a wrapper (ocp_serialize) instead" % type(obj)
        )

    raise TypeError("Cannot encode %s for the wrapper protocol" % type(obj))


def decode(obj):
    """Inverse of 'encode()' - but shape/assembly objects stay as dicts.

    Unlike the sandbox codec, this never rebuilds a live 'TopoDS_Shape': a shape
    or assembly object is returned as the dict it already is, so the core keeps
    handling opaque BREP envelopes. The one thing that does change is the "brep"
    payload, which comes off the pipe as base64 text and is handed on as the
    compressed bytes every layer above this one carries.
    """
    if isinstance(obj, dict):
        if KEY_BREP in obj or KEY_ASSEMBLY in obj:
            decoded = dict(obj)
            if KEY_BREP in decoded:
                decoded[KEY_BREP] = brep_bytes(decoded[KEY_BREP])
            if KEY_ASSEMBLY in decoded:
                decoded[KEY_ASSEMBLY] = [decode(child) for child in decoded[KEY_ASSEMBLY]]
            return decoded
        if KEY_BYTES in obj and len(obj) == 1:
            return base64.b64decode(obj[KEY_BYTES])
        return {key: decode(value) for key, value in obj.items()}

    if isinstance(obj, list):
        return [decode(item) for item in obj]

    return obj


def dumps(obj, name=None, label=None) -> str:
    """Serialize 'obj' into a single-line JSON string (used by the cache)."""
    return json.dumps(encode(obj, name=name, label=label))


def loads(text) -> object:
    """Deserialize a JSON string produced by 'dumps()'."""
    if isinstance(text, (bytes, bytearray)):
        text = text.decode("utf-8")
    return decode(json.loads(text))


def serialize(obj, name=None, label=None) -> str:
    """Serialize 'obj' into the single-line form that travels over the pipe."""
    return dumps(obj, name=name, label=label)


def deserialize(data) -> dict:
    """Deserialize the form produced by 'serialize()'.

    The response is taken as the last non-empty line of 'data', so any leading
    progress a wrapper wrote to stdout is ignored.
    """
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8")
    line = data.strip()
    if "\n" in line:
        for candidate in reversed(line.splitlines()):
            candidate = candidate.strip()
            if candidate:
                line = candidate
                break
    if not line:
        # A wrapper can exit 0 having written nothing (no result and no stderr),
        # which slips past the exit-code and stderr checks in the callers. Say so
        # here rather than letting loads() raise a bare, contextless JSONDecodeError.
        raise ValueError("the wrapper produced no output to deserialize (empty response)")
    return loads(line)
