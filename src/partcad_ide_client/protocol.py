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

Geometry travels as glTF, never as BREP. The core used to hand live OCP objects
to 'ocp_vscode', which meant the receiving side needed a full CAD stack to
tessellate them; a browser cannot do that, so the sandbox tessellates first and
what crosses the socket is a binary glTF (GLB) buffer, deflate-compressed and
base64-encoded (see 'encode_gltf'/'decode_gltf'). Note that this is zlib and
not the zstd the BREP envelopes in 'partcad.shape_envelope' use: both ends of
*this* pipe have to decompress it, and zlib is in the standard library of both
Python and Node, whereas zstd is not (Node gained it only in 23.8).
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

# Keys of a displayable object. 'gltf' is to this protocol what 'brep' is to the
# shape envelope: the compressed geometry payload that identifies the object.
KEY_GLTF = "gltf"
KEY_NAME = "name"
KEY_LABEL = "label"
# On a marker: the packed [[tx,ty,tz], [ax,ay,az], angle] frame to draw axes at.
KEY_LOCATION = "location"


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


def is_object(obj) -> bool:
    """Whether 'obj' is a displayable object this protocol carries."""
    return isinstance(obj, dict) and KEY_GLTF in obj


def make_object(glb: bytes, name=None, label=None) -> dict:
    """Build a displayable object from an already-tessellated GLB buffer."""
    return {KEY_NAME: name, KEY_LABEL: label, KEY_GLTF: encode_gltf(glb)}


def make_marker(marker) -> dict:
    """Normalize a coordinate-frame marker for the wire.

    Accepts either an already-built '{"name", "location"}' dict or a bare packed
    '[[tx,ty,tz], [ax,ay,az], angle]' location, which is the form PartCAD's
    'geom.Location.as_packed()' produces.
    """
    if isinstance(marker, dict):
        location = marker.get(KEY_LOCATION)
        name = marker.get(KEY_NAME)
    else:
        location, name = marker, None

    if not isinstance(location, (list, tuple)) or len(location) != 3:
        raise TypeError("a marker location must be the packed [[t], [axis], angle] form, got %r" % (location,))

    translation, axis, angle = location
    return {
        KEY_NAME: name,
        KEY_LOCATION: [
            [float(translation[0]), float(translation[1]), float(translation[2])],
            [float(axis[0]), float(axis[1]), float(axis[2])],
            float(angle),
        ],
    }


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
