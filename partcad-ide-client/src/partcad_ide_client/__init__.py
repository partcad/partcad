#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Python side of the PartCAD IDE viewer protocol.

'partcad' loads this package lazily when a shape is shown, and the PartCAD IDE
extension installs it next to 'partcad'. It is deliberately tiny and dependency
free - see 'client' for why.
"""

from .client import (
    CONNECT_TIMEOUT,
    REPLY_TIMEOUT,
    Connection,
    ViewerNotAvailable,
    clear,
    disconnect,
    is_available,
    show,
)
from .protocol import (
    PARTCAD_IDE_HOST,
    PARTCAD_IDE_PORT,
    VERSION,
    ProtocolError,
    decode_gltf,
    encode_gltf,
    is_object,
    make_marker,
    make_object,
)

__version__ = "0.7.180"

__all__ = [
    "CONNECT_TIMEOUT",
    "Connection",
    "PARTCAD_IDE_HOST",
    "PARTCAD_IDE_PORT",
    "ProtocolError",
    "REPLY_TIMEOUT",
    "VERSION",
    "ViewerNotAvailable",
    "clear",
    "decode_gltf",
    "disconnect",
    "encode_gltf",
    "is_available",
    "is_object",
    "make_marker",
    "make_object",
    "show",
]
