#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The client half of the PartCAD IDE protocol.

'partcad' imports this package lazily from 'Shape.show()' and 'Interface.show()'
and calls 'show()' below. Nothing here imports 'partcad', OCP or any CAD library:
the geometry has already been tessellated into glTF by the time it gets here, so
this package is pure standard library and stays installable next to 'partcad' in
whatever interpreter the IDE happens to be driving.

The module keeps one connection open per process and reuses it, because a show
is interactive: reconnecting per part adds a round trip to every click in the
IDE's tree. The connection is re-established transparently if the IDE restarts.
"""

import os
import socket
import threading
import uuid

from . import protocol
from .protocol import (
    PARTCAD_IDE_HOST,
    PARTCAD_IDE_PORT,
    ProtocolError,
)

# How long to wait for the IDE to accept a connection, and for it to acknowledge
# a message once sent. The connect budget is short because a missing viewer is
# the common case (any CLI run) and must not stall the caller; the reply budget
# is generous because the IDE has to hand the payload to a webview and load it.
CONNECT_TIMEOUT = 2.0
REPLY_TIMEOUT = 60.0


class ViewerNotAvailable(Exception):
    """No IDE is listening on the PartCAD viewer port."""


def _port() -> int:
    """The port to talk to.

    Constant by design (see 'protocol'), with an environment override so that a
    developer running two IDE windows, or a test running against a throwaway
    server, can point a process somewhere else without a rebuild.
    """
    override = os.environ.get("PARTCAD_IDE_PORT")
    if override:
        try:
            return int(override)
        except ValueError:
            pass
    return PARTCAD_IDE_PORT


class Connection:
    """A single framed connection to the IDE."""

    def __init__(self, host: str = None, port: int = None, connect_timeout: float = CONNECT_TIMEOUT):
        self.host = host or PARTCAD_IDE_HOST
        self.port = port or _port()
        self.connect_timeout = connect_timeout
        self._socket = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False

    def connect(self):
        if self._socket is not None:
            return
        try:
            self._socket = socket.create_connection((self.host, self.port), timeout=self.connect_timeout)
        except OSError as e:
            self._socket = None
            raise ViewerNotAvailable("no PartCAD viewer is listening on %s:%d (%s)" % (self.host, self.port, e)) from e
        # Interactive traffic: a show should leave for the IDE as soon as it is
        # written, not wait for Nagle to fill a segment.
        try:
            self._socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            # Not fatal, and not supported on every platform/socket family.
            pass

    def close(self):
        if self._socket is not None:
            try:
                self._socket.close()
            finally:
                self._socket = None

    def send(self, message: dict, reply_timeout: float = REPLY_TIMEOUT) -> dict:
        """Send one message and return the IDE's acknowledgement."""
        self.connect()
        try:
            self._socket.settimeout(reply_timeout)
            self._socket.sendall(protocol.encode_frame(message))
            return self._receive()
        except (OSError, ProtocolError):
            # A half-open connection (the IDE was restarted while we held it) is
            # indistinguishable from a real failure until we try to use it, so
            # drop it and let the caller decide whether to retry.
            self.close()
            raise

    def _receive(self) -> dict:
        length = protocol.decode_header(self._read_exactly(protocol.HEADER_LENGTH))
        return protocol.decode_payload(self._read_exactly(length))

    def _read_exactly(self, length: int) -> bytes:
        chunks = []
        remaining = length
        while remaining > 0:
            chunk = self._socket.recv(remaining)
            if not chunk:
                raise ProtocolError("the IDE closed the connection after %d of %d bytes" % (length - remaining, length))
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)


_shared_lock = threading.Lock()
_shared_connection = None


def _send(message: dict, reply_timeout: float = REPLY_TIMEOUT) -> dict:
    """Send a message over the shared connection, reconnecting once if it is stale."""
    global _shared_connection

    with _shared_lock:
        for attempt in (0, 1):
            if _shared_connection is None:
                _shared_connection = Connection()
            try:
                return _shared_connection.send(message, reply_timeout=reply_timeout)
            except ViewerNotAvailable:
                _shared_connection = None
                raise
            except (OSError, ProtocolError):
                _shared_connection = None
                if attempt == 1:
                    raise
        # Unreachable: the loop either returns or raises.
        raise ViewerNotAvailable("failed to reach the PartCAD viewer")


def disconnect():
    """Drop the shared connection, if any. Safe to call when not connected."""
    global _shared_connection

    with _shared_lock:
        if _shared_connection is not None:
            _shared_connection.close()
            _shared_connection = None


def is_available() -> bool:
    """Whether an IDE viewer is currently listening."""
    try:
        _send({"type": protocol.MSG_PING, "id": uuid.uuid4().hex}, reply_timeout=CONNECT_TIMEOUT)
    except (ViewerNotAvailable, OSError, ProtocolError):
        return False
    return True


def show(
    objects,
    name=None,
    kind=None,
    keep_camera=False,
    markers=None,
    reply_timeout: float = REPLY_TIMEOUT,
) -> dict:
    """Display already-tessellated objects in the IDE's PartCAD Viewer.

    'objects' is a list of '{"name", "label", "gltf"}' dicts as produced by
    'protocol.make_object()' - the glTF is compressed and base64-encoded there,
    not here, so a caller that already holds an encoded payload (PartCAD's
    sandbox does) never has to decode it just to hand it over.

    'markers' are coordinate frames with no geometry of their own - PartCAD's
    interface ports - as packed '[[tx,ty,tz], [ax,ay,az], angle]' locations. The
    viewer draws axes at each; there is no glTF primitive for "a frame".

    'keep_camera' asks the viewer to leave the camera where the user put it,
    which is what makes re-showing the same part after an edit not jump.
    """
    objects = list(objects or [])
    for obj in objects:
        if not protocol.is_object(obj):
            raise TypeError("not a displayable object (no %r key): %r" % (protocol.KEY_GLTF, obj))

    return _send(
        {
            "type": protocol.MSG_SHOW,
            "id": uuid.uuid4().hex,
            "name": name,
            "kind": kind,
            "keepCamera": bool(keep_camera),
            "objects": objects,
            "markers": [protocol.make_marker(marker) for marker in (markers or [])],
        },
        reply_timeout=reply_timeout,
    )


def clear() -> dict:
    """Empty the viewer."""
    return _send({"type": protocol.MSG_CLEAR, "id": uuid.uuid4().hex})
