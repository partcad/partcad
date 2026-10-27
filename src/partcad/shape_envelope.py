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
"location", an optional "properties", an optional "joint", an optional
"attached", an optional "kind", an optional "fixed" and an optional "metadata"
(see the keys below).

The two names answer different questions and a reader needs both. "name" is the
*object*: '<package>:<object>', what the node holds, shared by every node that
holds it. "label" is the *link*: what the node holding it addresses it by, which
is what tells a hundred placements of one bolt apart and what a 'connect:', a
'map:' and a filter name (see 'Assembly.link_name'). A label is therefore never
a fallback to something else -- a child nothing named is labelled by its
position in its parent.
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
import hashlib
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
# On the root node of a tree in the glTF form: the tessellated geometry of every
# node in it, keyed by a digest of the exact geometry it was made from, with each
# node naming its entry through KEY_GLTF_REF instead of carrying a copy.
#
# One entry per distinct geometry, however many nodes are made of it. An assembly
# places the same bolt a hundred times and a hundred nodes then name one table
# entry: tessellated once rather than a hundred times, sent once rather than a
# hundred times, and parsed and uploaded to the GPU once by whoever draws it. The
# placements are what differ between those nodes, and placements were never in the
# geometry (see 'placed()' below) - which is what makes the sharing possible at
# all.
#
# It is the same arrangement as KEY_SKETCHES above, one level up: a table on the
# root and a reference from everything that uses it. Sketches keep their own table
# because they are keyed by the PartCAD reference the ports already name, which is
# the identity a *declaration* has; this one is keyed by content, which is the only
# identity two independently built solids can share.
KEY_GEOMETRY = "geometry"
# On a node: which entry of that table is this node's geometry. A node carries this
# or KEY_GLTF, never both - a sketch in the KEY_SKETCHES table carries the geometry
# itself, since its table already holds one copy per sketch.
KEY_GLTF_REF = "gltfRef"
# On the top level of a serialized document: every BREP payload the document
# carries, once each, keyed by a digest of the payload; and on a node, which
# entry of that table is this node's geometry, in place of KEY_BREP.
#
# The glTF form already had this (KEY_GEOMETRY above); this is the same thing
# for BREP, and it exists for the same reason. An assembly is mostly repeats of
# a few parts: the LEGO castle is 731 placements of 9 bricks, and written a node
# at a time its render request was 33 MB of JSON for 4.6 MB of geometry. With a
# table it is 8.7 MB.
#
# Unlike KEY_GEOMETRY it is a property of the *serialized* document and of
# nothing in memory. In memory every node keeps its own KEY_BREP, which is what
# every reader of a tree reads; the nodes that came out of one table entry
# simply hold the one bytes object. 'dumps(share=True)' writes the table and
# 'loads()' takes it back out, on both sides of the pipe (see the same pair in
# 'wrappers/ocp_serialize.py'), so nothing that walks a tree ever sees it. It is
# written only when it makes the document smaller ('table_saves_space'), so a
# document with nothing repeated is exactly the document it always was.
KEY_BREPS = "__breps__"
KEY_BREP_REF = "brepRef"

# What naming a payload costs in a document, as against carrying it: the
# digest, as the node's reference and again as the table's key, and the JSON
# around each. Generous rather than exact; it only decides whether a table is
# worth writing, and for any real part it is.
_REFERENCE_COST = 64 + 16


def table_saves_space(lengths) -> bool:
    """Whether a table makes a document smaller, given each payload's base64 length and how many nodes carry it.

    'lengths' is '[(length, uses), ...]', one entry per distinct payload. One
    rule for both ends of the pipe, so that the core and a sandbox writing the
    same tree make the same decision.
    """
    carried = sum(length * uses for length, uses in lengths)
    tabled = sum(length + _REFERENCE_COST + uses * _REFERENCE_COST for length, uses in lengths)
    return tabled < carried


def base64_length(size: int) -> int:
    """How long 'size' bytes are in base64."""
    return 4 * ((size + 2) // 3)


# Optional placement on a shape/assembly object, carried opaquely by the core
# and turned into a real location by the geometry-side codec (ocp_serialize).
KEY_LOCATION = "location"
# Optional properties on a shape/assembly object: what the shape reports about
# itself ("material", "color", "physics"), as opposed to the parameters it was
# built from. One key rather than three, so that the envelope's key space stays
# small and everything that identifies an object travels beside its name. Like
# the placement, it is data the core carries opaquely and never interprets.
KEY_PROPERTIES = "properties"
# Optional on a node placed by connecting it to a sibling that it then moves
# against: the joint, as plain data - its name, the two links by their labels,
# the ordered steps the placement is the product of (fixed ones, and free ones
# with their kind, axis, range and starting value) and its physics. Stamped by
# the assembly placing the node (see 'Assembly._place' and 'Joint.to_envelope'),
# because it belongs to the placement and not to the object: one part may sit
# rigidly in one place and on a hinge in another. Carried opaquely by the core,
# like the properties beside it, for an exporter that walks the tree.
KEY_JOINT = "joint"
# Optional on a node an assembly places by connecting it rigidly to a sibling - a
# 'connect:' that keeps no degree of freedom, or a URDF link on a fixed joint:
# that sibling's label. A rigid connection is no joint (PartCAD has no fixed
# joints), but it does say what the node is welded to, and that is not always
# its container: a gripper bolted to a wrist that turns turns with the wrist.
# Stamped by the assembly placing the node, like the joint, and only inside an
# assembly - a scene's 'connect:' attaches nothing. Read by the body rule
# ('wrappers/kinematics.py').
KEY_ATTACHED = "attached"
# On every node an assembly or a scene places, and on the root of an assembly or
# a scene: what the node holds - "part", "assembly" or "scene", the object's own
# 'kind'. It is what decides which nodes of a tree are rigid bodies (see
# docs/design/simulation.md, section 7, and 'wrappers/kinematics.py'): every
# element of a scene is a body of its own, and everything inside an assembly is
# attached to it. A node without one is read by what it carries - children make
# it an assembly, geometry a part - which is what a lone part has always been and
# what a tree written before this said about everything.
KEY_KIND = "kind"
# On a node a scene places with 'fixed: true': welded to the world rather than
# free to fall. Absent means free, which is what every element of a scene was
# before a scene could say otherwise. Stamped by the scene placing the node, like
# the joint above, because it belongs to the placement and not to the object: one
# table may stand bolted down in one scene and loose in another.
KEY_FIXED = "fixed"
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
# How many shells in the shape no solid bounds itself with: a skin rather than
# a body, which the 'shell' check fails a part for (see 'partcad.brep_inspect').
# Recorded because a binary payload cannot be read for it without a kernel, and
# counted where the shape is live ('shape_measure.free_shells') by the rule
# 'brep_inspect' applies to an ASCII one, so the two cannot answer differently.
METADATA_FREE_SHELLS = "freeShells"
# Where that volume is and how it is spread: the centroid in millimetres, and
# the 3x3 inertia tensor about it at a density of one, in mm^5. The geometry's
# half of a mass, a centre of mass and an inertia - the other half is a density,
# multiplied in by the core (see 'partcad.physics'). Absent for a shape with no
# solid, or with one whose faces are turned inward.
METADATA_CENTROID = "centroid"
METADATA_UNIT_INERTIA = "unitInertia"

# The zstd frame header. Sniffed rather than declared in the envelope, so that
# a payload written without compression stays readable; the one copy of this
# constant on the geometry side is 'ocp_serialize.ZSTD_MAGIC'.
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"

# How far a BREP payload may expand before 'brep_plain()' refuses to finish
# decompressing it, as a multiple of the compressed size and never less than the
# floor. Both come from measurement rather than from taste: across the shapes
# the example packages build, ASCII BREP compresses by a median of 4.3x and at
# worst by 17.4x - the binary BREP payloads are now written in compresses less,
# by 1.8x to 7.5x on the example STEP parts - while a zstd frame of 6 KB expands to 200 MB - a ratio of 32,000 -
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
    """Whether 'obj' is a node whose geometry is tessellated rather than exact.

    Either spelling of it: the geometry itself, or a reference into the root's
    table of it (KEY_GEOMETRY). A reader that only knew the first would stop
    recognising every node of an assembly the moment the geometry was shared.
    """
    return isinstance(obj, dict) and (KEY_GLTF in obj or KEY_GLTF_REF in obj)


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
    frame; this unwraps it into the BREP that OCCT wrote - binary, from every
    Python wrapper, and ASCII from Chili3D or an earlier release (see
    'ocp_serialize.shape_from_brep'). Everything the core does with a shape
    moves the frame around unopened, so this is for the two things that open
    it: 'brep_inspect', which answers a question about an ASCII payload's
    topology off the bytes rather than by starting a sandbox, and the
    interference check, which writes what two parts share out as '.brep' files
    for a 'brep' part to read back.

    A payload that is not a zstd frame is returned as it is. That is how a peer
    without zstd writes one (see 'ocp_serialize._compress'), and telling the two
    apart by the frame header rather than by a flag in the envelope is what lets
    either be read without the format saying which it is.

    Bounded (see MAX_BREP_EXPANSION): a frame that keeps producing past the
    limit raises rather than being decompressed to the end. Raising is the right
    answer for both callers - 'brep_inspect.topology()' reads a refusal as "this
    payload could not be read", which is a verdict it already has to have and
    reports nothing about the shape, and the interference check keeps nothing
    to look at rather than failing its verdict.
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


def payload_digest(value) -> str:
    """A stable name for one piece of exact geometry: a digest of its compressed bytes.

    The same function as 'ocp_serialize.payload_digest' on the far side of the
    pipe, so a digest written by either end names the same payload for the other.
    """
    return hashlib.sha256(brep_bytes(value)).hexdigest()


class Payloads:
    """The distinct BREP payloads of one document, as 'encode()' meets them.

    'ref(value)' answers the digest a node names its payload by, and keeps the
    payload once under it. Every leaf of a tree built in this process shares the
    bytes object of the part it holds, so the digest is computed once per object
    rather than once per node; and two objects with the same bytes - a
    sub-assembly read back from the cache next to one just built - still end up
    as one entry.
    """

    def __init__(self):
        self.by_digest = {}
        self.uses = {}
        # By the identity of the payload object, and holding on to each object so
        # that its identity cannot be reused while the document is encoded.
        self._digests = {}
        self._held = []

    def ref(self, value) -> str:
        digest = self._digests.get(id(value))
        if digest is None:
            digest = payload_digest(value)
            self._digests[id(value)] = digest
            self._held.append(value)
        self.by_digest.setdefault(digest, value)
        self.uses[digest] = self.uses.get(digest, 0) + 1
        return digest

    @property
    def worth_a_table(self) -> bool:
        """Whether writing each payload once, in a table, makes the JSON document smaller."""
        return table_saves_space(
            [(base64_length(len(brep_bytes(value))), self.uses[digest]) for digest, value in self.by_digest.items()]
        )


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


def moved_annotations(metadata, move_point):
    """'metadata' with every annotation's points passed through 'move_point'.

    For the caller that has just moved or scaled a shape: the annotations say
    where each element *is*, and an element that moved with the geometry is no
    longer where the source drew it. Left alone, what was said about a bend line
    would go on pointing at the place the line used to be.

    This is the one field of a record the core reads, and it reads it only to
    keep it true: 'points' is a list of [x, y, z] in the shape's own frame, and
    nothing else of the record is looked at or changed. A point that is not
    three numbers is left as it stands rather than guessed at. The 'sections'
    are not touched - they are what the source said about *itself*, reported as
    it said it.
    """
    annotations = metadata_section(metadata, METADATA_ANNOTATIONS)
    if not annotations:
        return metadata

    def moved(point):
        if isinstance(point, (list, tuple)) and len(point) == 3:
            try:
                return [float(value) for value in move_point([float(axis) for axis in point])]
            except (TypeError, ValueError):
                return point
        return point

    records = []
    for record in annotations:
        if isinstance(record, dict) and isinstance(record.get("points"), list):
            record = dict(record)
            record["points"] = [moved(point) for point in record["points"]]
        records.append(record)
    result = dict(metadata)
    result[METADATA_ANNOTATIONS] = records
    return result


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


# What a node holds of its geometry, or learnt from it, rather than says about it.
_GEOMETRY_KEYS = frozenset((KEY_BREP, KEY_GLTF, KEY_GEOMETRY, KEY_METADATA))


def description(obj):
    """'obj' with its geometry left out: what a tree says about its shapes, as plain data.

    Every node keeps its name and label, its placement, its properties, its
    joint and the rest of its outer layer, and loses its payload (KEY_BREP,
    KEY_GLTF), the root's table of tessellated geometry (KEY_GEOMETRY) and what
    was measured of the geometry (KEY_METADATA). That is what a file made out
    of a tree is keyed on beside the key of the shape it is of: the shape's key
    covers the geometry, and nothing of the outer layer - not a placement it
    got from somewhere else, not the colour a renderer paints it with, since
    'properties' is no part of a shape's key. Any other bytes are kept as their
    digest, marked as bytes the way 'encode' marks them, which is all a key needs
    of them and cannot be mistaken for a string that happens to spell it.

    The keys are left out of nodes only: the root, the children in its
    KEY_ASSEMBLY lists at every depth, and the sketches in its KEY_SKETCHES
    table. Everything else a node holds is data under names its writer chose -
    a 'physics' property may well say 'geometry', a joint 'metadata' - and is
    kept whole.
    """
    return _described_node(obj)


def _described_node(node):
    if not isinstance(node, dict):
        return _described_data(node)
    described = {}
    for key, value in node.items():
        if key in _GEOMETRY_KEYS:
            continue
        if key == KEY_ASSEMBLY and isinstance(value, list):
            described[key] = [_described_node(child) for child in value]
        elif key == KEY_SKETCHES and isinstance(value, dict):
            described[key] = {reference: _described_node(sketch) for reference, sketch in value.items()}
        else:
            described[key] = _described_data(value)
    return described


def _described_data(obj):
    if isinstance(obj, dict):
        return {key: _described_data(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_described_data(item) for item in obj]
    if isinstance(obj, (bytes, bytearray)):
        return {KEY_BYTES: hashlib.sha256(bytes(obj)).hexdigest()}
    return obj


def encode(obj, name=None, label=None, payloads=None):
    """Convert 'obj' into a structure made only of JSON-native values.

    Shape and assembly envelopes keep their metadata; their "brep" payload is
    base64-encoded here, which is the one place the core turns the compressed
    bytes it carries into the text JSON can hold. Dicts, lists, tuples and sets
    are walked; other bytes become a '__bytes__' object; exceptions become their
    message. A live OCP object is rejected: the core must not hand one to this
    codec - it has nothing to turn it into bytes, and encoding geometry is a
    wrapper's job.

    Given 'payloads' (a 'Payloads'), a node names its payload by KEY_BREP_REF
    instead, and the payload is kept there, unencoded, for whoever writes the
    table: 'dumps()' as base64 JSON, the shape cache as raw bytes.
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj

    if isinstance(obj, dict):
        if KEY_BREP in obj or KEY_ASSEMBLY in obj:
            # An already-built shape/assembly object keeps its metadata verbatim.
            encoded = {}
            for key, value in obj.items():
                if key == KEY_BREP:
                    if payloads is None:
                        encoded[key] = brep_base64(value)
                    else:
                        encoded[KEY_BREP_REF] = payloads.ref(value)
                elif key == KEY_ASSEMBLY:
                    encoded[key] = [encode(child, name, label, payloads) for child in value]
                elif key in (KEY_LOCATION, "name", "label"):
                    encoded[key] = value
                else:
                    encoded[key] = encode(value, name, label, payloads)
            return encoded
        return {key: encode(value, name, label, payloads) for key, value in obj.items()}

    if isinstance(obj, (list, tuple, set, frozenset)):
        return [encode(item, name, label, payloads) for item in obj]

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


def decode(obj, table=None):
    """Inverse of 'encode()' - but shape/assembly objects stay as dicts.

    Unlike the sandbox codec, this never rebuilds a live 'TopoDS_Shape': a shape
    or assembly object is returned as the dict it already is, so the core keeps
    handling opaque BREP envelopes. The one thing that does change is the "brep"
    payload, which comes off the pipe as base64 text and is handed on as the
    compressed bytes every layer above this one carries.

    'table' is the document's payloads by digest, as bytes (see KEY_BREPS): a
    node naming one gets it under KEY_BREP, and every node naming the same entry
    holds the same bytes object.
    """
    if isinstance(obj, dict):
        if KEY_BREP_REF in obj:
            obj = _with_payload(obj, table)
        if KEY_BREP in obj or KEY_ASSEMBLY in obj:
            decoded = dict(obj)
            if KEY_BREP in decoded:
                decoded[KEY_BREP] = brep_bytes(decoded[KEY_BREP])
            if KEY_ASSEMBLY in decoded:
                decoded[KEY_ASSEMBLY] = [decode(child, table) for child in decoded[KEY_ASSEMBLY]]
            return decoded
        if KEY_BYTES in obj and len(obj) == 1:
            return base64.b64decode(obj[KEY_BYTES])
        return {key: decode(value, table) for key, value in obj.items()}

    if isinstance(obj, list):
        return [decode(item, table) for item in obj]

    return obj


def _with_payload(node, table):
    """'node' with the payload its KEY_BREP_REF names, under KEY_BREP."""
    ref = node[KEY_BREP_REF]
    if table is None or ref not in table:
        raise ValueError("A shape names the payload %r, which the document does not carry" % (ref,))
    resolved = {key: value for key, value in node.items() if key != KEY_BREP_REF}
    resolved[KEY_BREP] = table[ref]
    return resolved


def table_of(document):
    """Take the table of payloads (KEY_BREPS) off a parsed document, as bytes by digest, or None."""
    if not isinstance(document, dict) or KEY_BREPS not in document:
        return None
    return {digest: brep_bytes(value) for digest, value in document.pop(KEY_BREPS).items()}


def dumps(obj, name=None, label=None, share=False) -> str:
    """Serialize 'obj' into a single-line JSON string.

    'share' writes each payload once, in a table on the top level (KEY_BREPS),
    when that makes the document smaller ('table_saves_space') and 'obj' is a
    dict to put the table on; otherwise the document is the one it has always
    been. Only
    a reader that knows the table may be handed it: 'loads()' here, and
    'ocp_serialize' in a Python sandbox.
    """
    if share and isinstance(obj, dict):
        payloads = Payloads()
        encoded = encode(obj, name=name, label=label, payloads=payloads)
        if payloads.worth_a_table:
            encoded[KEY_BREPS] = {digest: brep_base64(value) for digest, value in payloads.by_digest.items()}
            return json.dumps(encoded)
    return json.dumps(encode(obj, name=name, label=label))


def loads(text) -> object:
    """Deserialize a JSON string produced by 'dumps()', with or without its table."""
    if isinstance(text, (bytes, bytearray)):
        text = text.decode("utf-8")
    document = json.loads(text)
    return decode(document, table_of(document))


def serialize(obj, name=None, label=None, share=False) -> str:
    """Serialize 'obj' into the single-line form that travels over the pipe. See 'dumps()'."""
    return dumps(obj, name=name, label=label, share=share)


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
