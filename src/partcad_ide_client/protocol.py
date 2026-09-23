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

A frame is a fixed 10-byte header followed by a UTF-8 JSON payload:

    offset  size  field
    0       4     magic, always b"PCAD"
    4       1     protocol version, currently 1
    5       1     payload kind, currently only KIND_JSON
    6       4     payload length, big-endian uint32
    10      n     payload

The magic and the explicit length let the reader on either side resynchronize
instead of guessing, and keep a frame from being confused with the LSP traffic
that also flows between these two processes.

What a "show" carries is one **object**, as the tree of nodes PartCAD carries
every shape as (see 'partcad.shape_envelope'). There is no per-kind payload and
no flat list of anything: a part or a sketch is that tree one node deep, an
assembly is a node per thing it holds nested as deeply as it goes, and an
interface is a node per port. A node is

    {
      "name":       the object's full name, or null
      "label":      what this node is called where it sits, or null
      "location":   [[tx,ty,tz], [ax,ay,az], angle] - where this node sits inside
                    its parent, or absent for one that was not placed
      "gltf":       this node's own geometry, or absent for one that has none
      "ports":      [{"name", "location", "interface", "instance", "sketch"}, ...]
      "interfaces": [{"name", "instance", "ports": [port name, ...]}, ...]
      "assembly":   [node, ...] - what is inside it, or absent for a leaf
      "sketches":   on the root node only: {reference -> node}, the sketches the
                    ports name, one per sketch however many ports point at it
    }

Placements are **not** baked into the geometry. A node's "gltf" is its own shape
in its own coordinate system and its "location" says where the node sits, exactly
as the BREP form carries it, so whoever draws the tree composes the locations
down it. The same goes for a port: its "location" is in the frame of the object
that declares it, and moves with the node that holds it.

Geometry travels as glTF, never as BREP. The core used to hand live OCP objects
to 'ocp_vscode', which meant the receiving side needed a full CAD stack to
tessellate them; a browser cannot do that, so the sandbox tessellates first and
what crosses the socket is a binary glTF (GLB) buffer, deflate-compressed and
base64-encoded (see 'encode_gltf'/'decode_gltf'). Note that this is zlib and
not the zstd the BREP envelopes in 'partcad.shape_envelope' use: both ends of
*this* pipe have to decompress it, and zlib is in the standard library of both
Python and Node, whereas zstd is not (Node gained it only in 23.8).

One glTF per node rather than one for the whole object, because a node is what a
reader of the tree switches on and off, and what it switches off has to be its
own buffer to be hideable.
"""

import base64
import json
import struct
import zlib

MAGIC = b"PCAD"
VERSION = 1
KIND_JSON = 1

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

# The keys of a node. 'gltf' is to this protocol what 'brep' is to the shape
# envelope: the compressed geometry payload of one node.
KEY_GLTF = "gltf"
KEY_NAME = "name"
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


class ProtocolError(Exception):
    """A frame that could not be parsed, or a payload that is not a message."""


def encode_gltf(glb: bytes) -> str:
    """Compress and base64 a binary glTF buffer for transport."""
    if not isinstance(glb, (bytes, bytearray)):
        raise TypeError("glTF payload must be bytes, got %s" % type(glb))
    return base64.b64encode(zlib.compress(bytes(glb), 6)).decode("ascii")


def decode_gltf(payload: str) -> bytes:
    """Inverse of 'encode_gltf()'. Only used by tests and by Python-side tooling."""
    return zlib.decompress(base64.b64decode(payload))


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


def encode_frame(message: dict) -> bytes:
    """Serialize a message into a single frame."""
    payload = json.dumps(message).encode("utf-8")
    if len(payload) > MAX_FRAME_LENGTH:
        raise ProtocolError("message of %d bytes exceeds the %d byte frame limit" % (len(payload), MAX_FRAME_LENGTH))
    return struct.pack(HEADER_FORMAT, MAGIC, VERSION, KIND_JSON, len(payload)) + payload


def decode_header(header: bytes) -> int:
    """Validate a frame header and return the payload length that follows it."""
    if len(header) != HEADER_LENGTH:
        raise ProtocolError("frame header must be %d bytes, got %d" % (HEADER_LENGTH, len(header)))
    magic, version, kind, length = struct.unpack(HEADER_FORMAT, header)
    if magic != MAGIC:
        raise ProtocolError("bad frame magic %r" % (magic,))
    if version != VERSION:
        raise ProtocolError("unsupported protocol version %d (this client speaks %d)" % (version, VERSION))
    if kind != KIND_JSON:
        raise ProtocolError("unsupported payload kind %d" % kind)
    if length > MAX_FRAME_LENGTH:
        raise ProtocolError("frame of %d bytes exceeds the %d byte limit" % (length, MAX_FRAME_LENGTH))
    return length


def decode_payload(payload: bytes) -> dict:
    """Parse a frame payload into a message."""
    try:
        message = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise ProtocolError("frame payload is not valid JSON: %s" % e) from e
    if not isinstance(message, dict):
        raise ProtocolError("frame payload must be a JSON object, got %s" % type(message))
    return message
