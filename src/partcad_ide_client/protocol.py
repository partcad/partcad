#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The wire format shared by 'partcad' (Python) and 'ide/vscode' (JS).

The IDE is the server: it binds 'PARTCAD_IDE_PORT' on the loopback interface
with SO_REUSEADDR and SO_REUSEPORT, and this module's client connects to it.
The port is a constant rather than a negotiated one so that a 'partcad' process
started outside the IDE - a CLI run, a notebook, a test - can find a running
viewer without any discovery handshake.

A frame is a fixed 10-byte header followed by its payload:

    offset  size  field
    0       4     magic, always b"PCAD"
    4       1     protocol version, currently 1
    5       1     payload kind: KIND_JSON or KIND_BINARY
    6       4     payload length, big-endian uint32
    10      n     payload

The magic and the explicit length let the reader on either side resynchronize
instead of guessing, and keep a frame from being confused with the LSP traffic
that also flows between these two processes.

A KIND_JSON payload is the message as UTF-8 JSON. A KIND_BINARY payload is the
message and the glTF it carries side by side, rather than one inside the other:

    size  field
    4     length J of the message, big-endian uint32
    J     the message, as UTF-8 JSON
    4     count N of blobs, big-endian uint32
          then N times:
    4       length L of the blob, big-endian uint32
    L       the blob: one binary glTF, as it is

In the message of a binary frame a glTF payload - a node's "gltf", an entry of a
"geometry" table - is an integer: the index of its blob. Nothing else is read as
one, and only nodes are looked in (the object, what is in its "assembly" and its
"sketches"), so nothing a package says about itself - its metadata, its
properties - can be mistaken for a blob. A JSON frame carries the same payloads
as text instead (see "Payloads" below).

**Which kinds an IDE reads is negotiated, per connection.** The extension and
this package are released independently, and an IDE from before KIND_BINARY drops
the connection at the first header it does not know. So every acknowledgement an
IDE sends says what it accepts (KEY_CAPABILITIES), and a client sends a binary
frame only over a connection whose IDE has said it reads them; an IDE that says
nothing is sent JSON frames, exactly as before. A connection is to one IDE window
and a reconnection may be to another (two windows share the port), so what was
learnt goes with the connection.

**An IDE that accepts CAP_OFFER is asked before it is sent geometry.** A show is
mostly its geometry, and most of that is what the IDE was shown a moment ago: an
edit re-renders one part of an assembly, a cross-section leaves the parts it
misses as they were, a reader goes back to the object before. So the client
offers the digests of the show's geometry table first (MSG_OFFER), the IDE
answers which it lacks, those follow (MSG_GEOMETRY, in as many frames as they
need), and then the show itself, with None for every entry of its table - "the
one you hold". An IDE that no longer holds one by then answers the show with
what is missing instead of showing it, and is sent that and the show again;
after a second such answer the show is sent whole.

What a "show" carries is one **object**, as the tree of nodes PartCAD carries
every shape as (see 'partcad.shape_envelope'). There is no per-kind payload and
no flat list of anything: a part or a sketch is that tree one node deep, an
assembly is a node per thing it holds nested as deeply as it goes, and an
interface is a node per port. A node is

    {
      "name":       the object's full name, or null
      "label":      the name the node holding this one addresses it by, or null
                    on the root (which nothing holds)
      "location":   [[tx,ty,tz], [ax,ay,az], angle] - where this node sits inside
                    its parent, or absent for one that was not placed
      "gltf":       this node's own geometry, or absent for one that has none
      "ports":      [{"name", "location", "interface", "instance", "sketch"}, ...]
      "interfaces": [{"name", "instance", "ports": [port name, ...]}, ...]
      "assembly":   [node, ...] - what is inside it, or absent for a leaf
      "sketches":   on the root node only: {reference -> node}, the sketches the
                    ports name, one per sketch however many ports point at it
      "metadata":   what was learnt about this node's shape as it was built, or
                    absent - passed through exactly as 'partcad.shape_envelope'
                    carries it. The viewer reads its "annotations" (one record per
                    element, each with "points" in the node's own frame and the
                    key/value "metadata" said about it) and pins them to the
                    elements as text callouts
      "properties": what this node's shape reports about itself, or absent -
                    its "material", its "color" and its "physics", passed through
                    exactly as 'partcad.shape_envelope' carries them. The viewer
                    reads "color" ("#RRGGBB" or "#RRGGBBAA") and draws the node,
                    and everything under it that states no colour of its own, in
                    it; a node under nothing that states one is drawn in
                    goldenrod, the colour OCCT draws an uncoloured shape in
    }

Placements are **not** baked into the geometry. A node's "gltf" is its own shape
in its own coordinate system and its "location" says where the node sits, exactly
as the BREP form carries it, so whoever draws the tree composes the locations
down it. The same goes for a port: its "location" is in the frame of the object
that declares it, and moves with the node that holds it.

Geometry travels as glTF, never as BREP. The core used to hand live OCP objects
to 'ocp_vscode', which meant the receiving side needed a full CAD stack to
tessellate them; a browser cannot do that, so the sandbox tessellates first and
what crosses the socket is a binary glTF (GLB) buffer.

One glTF per node rather than one for the whole object, because a node is what a
reader of the tree switches on and off, and what it switches off has to be its
own buffer to be hideable.

Payloads
--------

A glTF payload is the GLB itself, as bytes, from the sandbox that wrote it to
the socket ('encode_gltf'): this pipe is loopback, where compressing costs more
than it saves - zlib at its default level took two seconds for a 25 MB assembly,
to take a third off a copy that then costs milliseconds - and the IDE only has
to undo it. In a binary frame it is a blob.

A JSON frame cannot hold bytes, and the IDE it goes to may be one from before
KIND_BINARY, which reads a payload as base64 of a zlib stream and nothing else.
So that is what a JSON frame carries: zlib at level 0 - a stored stream, which
every inflater reads and which costs a copy rather than a compression - unless
the frame would then be over MAX_FRAME_LENGTH, when it is compressed for real.
Readers on both sides take both spellings, and the old one at any level
('decode_gltf' sniffs the zlib header), because a PartCAD from before this
change writes it, and so may whatever it cached.

Remote-SSH changes none of that: the extension host runs where the workspace
is, beside PartCAD, and this socket is loopback there too. What crosses the
network is the extension host's message to its webview, which VS Code carries;
compressing that would be a DecompressionStream in the webview, should it ever
be worth it.
"""

import base64
import json
import struct
import zlib

MAGIC = b"PCAD"
VERSION = 1
KIND_JSON = 1
# The message and its glTF side by side; see the layout above. Sent only to an
# IDE that has said it reads it (CAP_BINARY).
KIND_BINARY = 2
KINDS = (KIND_JSON, KIND_BINARY)

# The lengths inside a binary payload: the message's, the count of blobs, and
# each blob's.
_LENGTH = struct.Struct(">I")

# The glTF binary container's magic, which is how a payload is told from a
# zlib stream of one.
GLB_MAGIC = b"glTF"

HEADER_FORMAT = ">4sBBI"
HEADER_LENGTH = struct.calcsize(HEADER_FORMAT)

# The constant port the IDE listens on. Kept out of the ephemeral range so the
# OS never hands it to an unrelated process, and out of the way of the ports the
# CAD ecosystem already squats on (ocp_vscode's 3939 above all).
PARTCAD_IDE_PORT = 9137
PARTCAD_IDE_HOST = "127.0.0.1"

# A single frame is capped so a desynchronized or hostile peer cannot make the
# reader allocate an arbitrary buffer. Large enough for any tessellation we
# would want to push into a webview in one go.
MAX_FRAME_LENGTH = 256 * 1024 * 1024

# Message types.
MSG_SHOW = "show"
MSG_CLEAR = "clear"
MSG_PING = "ping"
MSG_ACK = "ack"
# On every acknowledgement from an IDE that has any: what it accepts, as a list
# of the CAP_ names below. An acknowledgement without it is from an IDE that
# accepts JSON frames and nothing else, which is every IDE from before it.
KEY_CAPABILITIES = "capabilities"
# Reads KIND_BINARY frames.
CAP_BINARY = "binary"
# Answers MSG_OFFER, takes MSG_GEOMETRY, and resolves a show whose geometry
# table names entries as None. Sent only beside CAP_BINARY: the geometry that
# follows an offer goes as blobs.
CAP_OFFER = "offer"
# Before a show, to an IDE that accepts CAP_OFFER: these are the digests of the
# geometry the show will name ({"type", "id", "digests": [digest, ...]}). The IDE
# answers which of them it does not hold, under KEY_MISSING, and the client sends
# those, and only those, before the show. An IDE from before it acknowledges it
# like any message it does not understand, with no capabilities - which is how a
# client asking it first, over a connection it knows nothing about yet, finds
# out what it is talking to.
MSG_OFFER = "offer"
KEY_DIGESTS = "digests"
# The digests an IDE lacks: in its answer to MSG_OFFER, and in its answer to a
# show naming an entry it no longer holds, which it then has not shown.
KEY_MISSING = "missing"
# Geometry the IDE said it lacks, ahead of the show that names it:
# {"type", "id", "geometry": {digest: payload}}, in a binary frame. Held by the
# IDE for the connection it came over until a show there names it, which is
# what keeps it from being let go of in between.
MSG_GEOMETRY = "geometry"
# A question rather than a display: what the IDE is showing, for 'pc ide state'.
#
# Answered in the acknowledgement every message gets, under KEY_STATE. An IDE
# from before this acknowledges it like any message it does not understand --
# without a state -- which is how a client tells "too old" from "nothing open".
# The reply is
#
#     {
#       "window":    {"pid", "workspaceFolders": [path, ...], "extensionVersion"}
#       "explorer":  {"selection": [{"kind", "path", "package", "name", "type",
#                                    "file"}, ...]}
#       "inspector": {"kind", "path", "package", "name",
#                     "properties": {label: value, ...},
#                     "parameters": {name: {"type", "default", "enum", ...,
#                                           "value": what the field holds now}},
#                     "applied": {name: value} -- what the object was last
#                                 shown with, which the fields may have moved on
#                                 from without "Update" being pressed},
#                    or null when the Inspector shows nothing
#       "viewer":    {"open", "subject": {"name", "kind", "package"},
#                     "tab", "subTab",
#                     "tabs": {group: [{"id", "label", "disabled"}, ...]},
#                     "subTabs": {id: {"filters", "selections"}},
#                     "screenshot": the path of a PNG of the sub-tab on screen,
#                                   written by the IDE into its temporary
#                                   directory, or null with "screenshotError"}
#     }
#
# "filters" is what that sub-tab would send 'pc render --filter', or null for
# the whole object; "selections" is what is chosen in it -- the boxes ticked in
# its tree, and the value of every control in its pane. They differ by sub-tab,
# which is why there is one entry per sub-tab rather than one for the panel.
MSG_STATE = "state"
KEY_STATE = "state"

# The keys of a node. 'gltf' is to this protocol what 'brep' is to the shape
# envelope: the geometry payload of one node (see "Payloads" above).
KEY_GLTF = "gltf"
KEY_NAME = "name"
# The two names answer different questions and a reader needs both.
#
# 'name' is the *object*: '<package>:<object>', what the node holds. An assembly
# that places the same bolt a hundred times stamps one name on a hundred nodes,
# which is what makes the geometry table shareable.
#
# 'label' is the *link*: what the node holding this one addresses it by, which is
# what tells those hundred nodes apart. It is the 'name:' of the ASSY link that
# placed it, or - for a child nothing named - its position in its parent (see
# 'Assembly.link_name'); never a fallback to the object's own name. That is what
# makes it the name a request coming *back* can carry: the panel beside the 2D
# and Draft tabs composes a filter out of the labels it is showing, and a
# 'connect:', a 'map:' and 'pc filter' all name a link the same way.
KEY_LABEL = "label"
# What is inside a node, as nodes. The same key the BREP form uses, because it is
# the same tree.
KEY_ASSEMBLY = "assembly"
# Where a node sits inside its parent, and where a port sits in the frame of the
# object that declares it: the packed [[tx,ty,tz], [ax,ay,az], angle] form
# 'geom.Location.as_packed()' produces.
KEY_LOCATION = "location"
# What a node declares about connections. 'ports' are the coordinate frames, each
# naming the interface instance it belongs to where it belongs to one;
# 'interfaces' are those instances, each naming the ports it is made of. The
# ports are partitioned between the interfaces and the ones that belong to none,
# so nothing is listed twice.
KEY_PORTS = "ports"
KEY_INTERFACES = "interfaces"
# On the root node: the sketches the ports anywhere in the tree are drawn with,
# keyed by the reference those ports name in their own "sketch". A port is a
# coordinate frame, which is drawn as a triad; most ports are also drawn *with*
# something - the circle of a hole, the profile of a rail - and that is this. One
# entry per sketch however many ports point at it, so a bolt pattern of four holes
# carries one circle. Each is an ordinary node, so it carries its geometry the same
# way, in its own coordinate system, to be placed at the port by whoever draws it.
KEY_SKETCHES = "sketches"
# On the root node: every distinct piece of geometry in the tree, keyed by a digest
# of the exact shape it was tessellated from, with each node - and each sketch above
# - naming its entry in 'gltfRef' instead of carrying a copy of it. One entry
# however many nodes are made of it: an assembly that places one bolt a hundred
# times sends that bolt once and names it a hundred times, which is possible
# because a node's placement was never part of its geometry. What draws the tree
# resolves the reference, and can parse and upload each entry once for the same
# reason. PartCAD's own copy of both keys is 'partcad.shape_envelope'.
KEY_GEOMETRY = "geometry"
KEY_GLTF_REF = "gltfRef"
# On a show message: the object itself, as the root node of its tree.
KEY_OBJECT = "object"
# On a show message, beside 'name' and 'kind': the package the shown object
# belongs to. The viewer shows more than geometry - what an assembly is made of,
# how it goes together, where to buy its parts - and asks the PartCAD daemon for
# all of it by '<package>:<name>', which a name on its own cannot spell. Absent
# or None for a shape that belongs to no package.
KEY_PACKAGE = "package"
# On a node: what was learnt about its shape as it was built. PartCAD's own
# 'shape_envelope.KEY_METADATA', carried through the tessellation untouched.
KEY_METADATA = "metadata"
# On a show message: the tab of the Digital Thread to open on, or absent to
# stay on whichever one is open. One of the leaf ids in VIEWER_TABS -- what
# 'pc ide view --design-2d' and its siblings ask for. It travels *with* the show
# rather than as a message of its own because the show is what decides which
# tabs apply (an assembly has no FEA tab), and because two IDE windows sharing
# the port share it by load-balancing connections: a second message could reach
# the other window. A tab that does not apply to the object is not opened, and
# the viewer stays where it was.
KEY_TAB = "tab"
# On a show message that carries a KEY_TAB naming a tab that lists scenarios --
# the Simulation tab, and each analysis tab: which of them to select, by the
# name the object declares it under ('pc ide view --analysis-fea --scenario
# loaded'). Absent selects the first, as opening the tab by hand does. One the
# object does not declare selects nothing new, and the tab stays on its first.
KEY_SCENARIO = "scenario"
# On a show message: the cross-section the object was cut to before it was
# tessellated, as PartCAD normalized it -- '{"x": [lo, hi], "z": [lo, hi]}', in
# millimetres in the frame of the object's root, naming only the axes that cut
# (see 'partcad.shape_section') -- or None for the whole object. Always present on
# a show from a PartCAD that can cut, None included, so that the viewer can tell
# "the whole object" from "a PartCAD too old to be asked for a cut" and offer its
# section sliders only to the first. The viewer asks for a cut by asking the
# daemon to show the object again with one ('inspect.object' with 'section'),
# and this is how it learns what the geometry on screen was cut to.
KEY_SECTION = "section"

# The tabs whose pane is a list of what the object declares, one of which is
# selected and run: its simulations, and its scenarios of each analysis.
SCENARIO_TABS = ("fea", "dynamic", "thermal", "cfd", "simulation")

# The viewer's tabs, by the group whose strip holds them, in the order they are
# shown. 'ide/vscode/src/webview/messages.ts' ('TabId', 'TAB_GROUPS') is the
# other copy, and 'tests/partcad_ide_client/unit/test_protocol.py' holds the two
# to each other. 'supply' is the tab labelled "Buy". Validation's Process
# Emulation is not here: it holds nothing yet and is always disabled, so a flag
# for it could never open it.
VIEWER_TABS = {
    "design": ("3d", "2d", "draft"),
    "analysis": ("fea", "dynamic", "thermal", "cfd"),
    "manufacturing": ("bvb", "build", "supply", "bom", "assembly"),
    "validation": ("test", "simulation"),
}


class ProtocolError(Exception):
    """A frame that could not be parsed, or a payload that is not a message."""


class FrameTooLarge(ProtocolError):
    """A message that does not fit in one frame (MAX_FRAME_LENGTH), found before any of it is written."""


def encode_gltf(glb: bytes) -> bytes:
    """The payload a binary glTF buffer travels as: the buffer itself, as bytes.

    Not compressed, and not text: see "Payloads" in this module's description for
    why, and 'frame_parts' for what a frame of either kind makes of it. The other
    implementation - the one that wrote what PartCAD sends - is
    'partcad.wrappers.ocp_serialize.encode_gltf' in the sandbox, which cannot import
    this package; the two have to stay in step.
    """
    if not isinstance(glb, (bytes, bytearray, memoryview)):
        raise TypeError("glTF payload must be bytes, got %s" % type(glb))
    return bytes(glb)


def decode_gltf(payload) -> bytes:
    """The binary glTF 'payload' carries, whichever of its spellings it is in.

    Bytes, as 'encode_gltf' writes them; or text, as a JSON frame carries them and
    as every PartCAD before KIND_BINARY wrote them everywhere - base64 of a zlib
    stream, at whatever level. Either may hold a zlib stream (a cached tessellation
    from such a release does), so the header is sniffed rather than the spelling
    trusted: a GLB begins with "glTF", which no zlib header can.
    """
    if isinstance(payload, str):
        data = base64.b64decode(payload)
    elif isinstance(payload, (bytes, bytearray, memoryview)):
        data = bytes(payload)
    else:
        raise TypeError("not a glTF payload: %s" % type(payload))
    if is_zlib(data):
        return zlib.decompress(data)
    return data


def is_zlib(data) -> bool:
    """Whether 'data' begins with a zlib header (RFC 1950).

    Deflate in the low nibble of the first byte, a window of at most 32 KiB in its
    high one, and the first two bytes a multiple of 31 together. A GLB's "g" has 7
    in its low nibble, so a glTF buffer is never mistaken for one.
    """
    return len(data) >= 2 and data[0] & 0x0F == 8 and data[0] >> 4 <= 7 and ((data[0] << 8) | data[1]) % 31 == 0


def is_node(obj) -> bool:
    """Whether 'obj' is a node of a shape tree.

    A node has geometry, or something inside it, or both. One that has neither is
    still a node - an empty assembly, an interface whose ports carry no boundary -
    and is recognised by the keys it would carry either in.
    """
    return isinstance(obj, dict) and (KEY_GLTF in obj or KEY_GLTF_REF in obj or KEY_ASSEMBLY in obj)


def make_node(glb: bytes = None, name=None, label=None, children=None) -> dict:
    """Build a node from an already-tessellated GLB buffer and what is inside it."""
    node = {KEY_NAME: name, KEY_LABEL: label}
    if glb is not None:
        node[KEY_GLTF] = encode_gltf(glb)
    if children is not None:
        node[KEY_ASSEMBLY] = list(children)
    return node


def is_payload(value) -> bool:
    """Whether 'value' is a glTF payload in either spelling (see 'decode_gltf')."""
    return isinstance(value, (bytes, bytearray, memoryview, str))


def map_payloads(message: dict, convert) -> dict:
    """'message' with every glTF payload in it replaced by 'convert(payload)'.

    Looked for where a payload can be and nowhere else: a node's KEY_GLTF and the
    entries of a KEY_GEOMETRY table, on the nodes of the object (KEY_OBJECT, and
    every node in a KEY_ASSEMBLY or a KEY_SKETCHES under it) and on the message
    itself, which is where MSG_GEOMETRY carries its table. None - an entry the IDE
    holds - stays None. Copies what it changes and shares the rest, so the tree
    the caller passed, which is the one PartCAD keeps, is never written to.
    """

    def node(value):
        if not isinstance(value, dict):
            return value
        mapped = dict(value)
        if mapped.get(KEY_GLTF) is not None:
            mapped[KEY_GLTF] = convert(mapped[KEY_GLTF])
        table = mapped.get(KEY_GEOMETRY)
        if isinstance(table, dict):
            mapped[KEY_GEOMETRY] = {
                digest: None if payload is None else convert(payload) for digest, payload in table.items()
            }
        children = mapped.get(KEY_ASSEMBLY)
        if isinstance(children, list):
            mapped[KEY_ASSEMBLY] = [node(child) for child in children]
        sketches = mapped.get(KEY_SKETCHES)
        if isinstance(sketches, dict):
            mapped[KEY_SKETCHES] = {reference: node(sketch) for reference, sketch in sketches.items()}
        return mapped

    mapped = node(message)
    if isinstance(message.get(KEY_OBJECT), dict):
        mapped[KEY_OBJECT] = node(message[KEY_OBJECT])
    return mapped


def _legacy_payload(payload, level: int) -> str:
    """'payload' as a JSON frame carries it: base64 of a zlib stream (see "Payloads")."""
    if isinstance(payload, str):
        # Already in that spelling: written by a PartCAD before this one, or
        # cached by it.
        return payload
    return base64.b64encode(zlib.compress(bytes(payload), level)).decode("ascii")


def frame_parts(message: dict, binary: bool = False) -> list:
    """'message' as the buffers its frame is made of, in order; 'encode_frame' joins them.

    'binary' writes a KIND_BINARY frame, every glTF payload a blob, and is only for
    an IDE that has said it reads one (CAP_BINARY); otherwise the frame is
    KIND_JSON, which every IDE reads, with each payload spelled as an IDE from
    before KIND_BINARY reads it.

    The parts rather than the frame because a binary frame is nearly all blobs, and
    joining them would copy all of it once more just to write it out: the client
    writes the parts one after another instead.
    """
    if binary:
        blobs = []
        # By identity: a payload named twice - one buffer on two nodes - is one
        # blob. Every payload looked up is held by 'blobs', so no id is reused.
        indices = {}

        def blob(payload):
            if isinstance(payload, str):
                payload = decode_gltf(payload)
            elif not isinstance(payload, (bytes, bytearray)):
                payload = bytes(payload)
            index = indices.get(id(payload))
            if index is None:
                index = indices[id(payload)] = len(blobs)
                blobs.append(payload)
            return index

        text = json.dumps(map_payloads(message, blob)).encode("utf-8")
        parts = [b"", _LENGTH.pack(len(text)), text, _LENGTH.pack(len(blobs))]
        for payload in blobs:
            parts.append(_LENGTH.pack(len(payload)))
            parts.append(payload)
        kind = KIND_BINARY
    else:
        carried = []

        def legacy(level):
            def spell(payload):
                carried.append(payload)
                return _legacy_payload(payload, level)

            return json.dumps(map_payloads(message, spell)).encode("utf-8")

        text = legacy(0)
        if len(text) > MAX_FRAME_LENGTH and any(not isinstance(payload, str) for payload in carried):
            # Stored, it does not fit; compressed, it may - which is what every
            # payload was before KIND_BINARY, so nothing that fitted then fails now.
            text = legacy(6)
        parts = [b"", text]
        kind = KIND_JSON
    length = sum(len(part) for part in parts)
    if length > MAX_FRAME_LENGTH:
        raise FrameTooLarge("message of %d bytes exceeds the %d byte frame limit" % (length, MAX_FRAME_LENGTH))
    parts[0] = struct.pack(HEADER_FORMAT, MAGIC, VERSION, kind, length)
    return parts


def encode_frame(message: dict, binary: bool = False) -> bytes:
    """Serialize a message into a single frame (see 'frame_parts')."""
    return b"".join(frame_parts(message, binary))


def read_header(header: bytes) -> tuple:
    """Validate a frame header and return the kind and the length of the payload that follows it."""
    if len(header) != HEADER_LENGTH:
        raise ProtocolError("frame header must be %d bytes, got %d" % (HEADER_LENGTH, len(header)))
    magic, version, kind, length = struct.unpack(HEADER_FORMAT, header)
    if magic != MAGIC:
        raise ProtocolError("bad frame magic %r" % (magic,))
    if version != VERSION:
        raise ProtocolError("unsupported protocol version %d (this client speaks %d)" % (version, VERSION))
    if kind not in KINDS:
        raise ProtocolError("unsupported payload kind %d" % kind)
    if length > MAX_FRAME_LENGTH:
        raise ProtocolError("frame of %d bytes exceeds the %d byte limit" % (length, MAX_FRAME_LENGTH))
    return kind, length


def decode_header(header: bytes) -> int:
    """Validate a frame header and return the payload length that follows it (see 'read_header')."""
    return read_header(header)[1]


def decode_payload(payload: bytes, kind: int = KIND_JSON) -> dict:
    """Parse a frame payload of 'kind' into a message.

    A binary payload's blobs are put back where the message names them, as bytes,
    so what comes back is the message 'frame_parts' was handed, in either kind -
    with every payload as bytes rather than in the spelling it was sent in.
    """
    if kind != KIND_BINARY:
        return _decode_json(payload)
    view = memoryview(payload)

    def length_at(offset):
        if offset + _LENGTH.size > len(view):
            raise ProtocolError("binary frame payload ends inside a length, at byte %d of %d" % (offset, len(view)))
        return _LENGTH.unpack_from(view, offset)[0]

    offset = _LENGTH.size + length_at(0)
    if offset > len(view):
        raise ProtocolError("binary frame payload ends inside its message")
    message = _decode_json(bytes(view[_LENGTH.size : offset]))
    count = length_at(offset)
    offset += _LENGTH.size
    blobs = []
    for _ in range(count):
        size = length_at(offset)
        offset += _LENGTH.size
        if offset + size > len(view):
            raise ProtocolError("binary frame payload ends inside blob %d" % len(blobs))
        blobs.append(bytes(view[offset : offset + size]))
        offset += size
    if offset != len(view):
        raise ProtocolError("binary frame payload has %d bytes after its last blob" % (len(view) - offset))

    def resolve(payload):
        # 'type() is int' rather than isinstance: JSON's true is not blob 1.
        if type(payload) is not int:
            return payload
        if not 0 <= payload < len(blobs):
            raise ProtocolError("a payload names blob %d of %d" % (payload, len(blobs)))
        return blobs[payload]

    return map_payloads(message, resolve)


def _decode_json(payload: bytes) -> dict:
    try:
        message = json.loads(bytes(payload).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise ProtocolError("frame payload is not valid JSON: %s" % e) from e
    if not isinstance(message, dict):
        raise ProtocolError("frame payload must be a JSON object, got %s" % type(message))
    return message


def viewer_tab_ids() -> tuple:
    """Every leaf tab of the viewer, group by group: what KEY_TAB may name."""
    return tuple(tab for tabs in VIEWER_TABS.values() for tab in tabs)
