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
IDE's tree. The connection is re-established transparently if the IDE restarts,
and a message sent into the connection the restart left behind is sent again
over the new one; a message the IDE is only slow to acknowledge is not.

The connection is also what is known about the IDE at its far end: what it
accepts (see 'protocol.KEY_CAPABILITIES'), which decides how a show is sent -
offered first and sent as blobs, sent whole as blobs, or sent as the JSON frame
every IDE reads.
"""

import os
import re
import socket
import threading
import uuid

from . import protocol
from .protocol import (
    PARTCAD_IDE_HOST,
    PARTCAD_IDE_PORT,
    FrameTooLarge,
    ProtocolError,
)

# How long to wait for the IDE to accept a connection, and for it to acknowledge
# a message once sent. The connect budget is short because a missing viewer is
# the common case (any CLI run) and must not stall the caller; the reply budget
# is generous because the IDE has to hand the payload to a webview and load it.
CONNECT_TIMEOUT = 2.0
REPLY_TIMEOUT = 60.0


class ViewerNotAvailable(Exception):
    """No IDE is listening on the Digital Thread port."""


class StateNotSupported(Exception):
    """The IDE listening answered, but is too old to say what it is showing."""


# How long to wait for the state. Longer than a ping, shorter than a show: the
# IDE asks two webviews and takes a screenshot, all of it on this machine.
STATE_TIMEOUT = 20.0


# Decimal digits only: 'int()' would also take "+9999", " 9999 " and "1_0",
# none of which the JS side reads the same way.
_PORT_RE = re.compile(r"\A[0-9]+\Z")


def _port() -> int:
    """The port to talk to.

    Constant by design (see 'protocol'), with an environment override so that a
    developer running two IDE windows, or a test running against a throwaway
    server, can point a process somewhere else without a rebuild.

    The grammar is plain decimal digits and the range is 1..65535, which is what
    'listenPort()' in 'ide/vscode/src/viewer/protocol.ts' accepts too:
    the two ends have to read the same variable the same way, or one of them
    binds a port the other does not connect to. Port 0 is excluded because it
    means "any free port", which the far end of this protocol cannot find.
    Anything else falls back to the constant rather than failing.
    """
    override = os.environ.get("PARTCAD_IDE_PORT")
    if override is not None and _PORT_RE.match(override):
        port = int(override)
        if 1 <= port <= 65535:
            return port
    return PARTCAD_IDE_PORT


class Connection:
    """A single framed connection to the IDE."""

    def __init__(self, host: str = None, port: int = None, connect_timeout: float = CONNECT_TIMEOUT):
        self.host = host or PARTCAD_IDE_HOST
        self.port = port or _port()
        self.connect_timeout = connect_timeout
        self._socket = None
        # Whether the last 'send' failed because the connection was gone; see there.
        self.lost = False
        # How much of the reply to the message being sent has arrived.
        self._reply_bytes = 0
        # What the IDE at the far end accepts, as it said in its last
        # acknowledgement: None until one has arrived, and empty for an IDE that
        # says nothing, which reads JSON frames and nothing else. Forgotten with
        # the connection, because the next one may be to another window.
        self.capabilities = None

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
            raise ViewerNotAvailable("no Digital Thread is listening on %s:%d (%s)" % (self.host, self.port, e)) from e
        # Interactive traffic: a show should leave for the IDE as soon as it is
        # written, not wait for Nagle to fill a segment.
        try:
            self._socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            # Not fatal, and not supported on every platform/socket family.
            pass

    def close(self):
        self.capabilities = None
        if self._socket is not None:
            try:
                self._socket.close()
            finally:
                self._socket = None

    def send(self, message: dict, reply_timeout: float = REPLY_TIMEOUT, binary: bool = False) -> dict:
        """Send one message and return the IDE's acknowledgement.

        'binary' sends it as a KIND_BINARY frame, which only an IDE that said it
        reads one may be sent (see 'capabilities'). A message too large for a frame
        raises 'FrameTooLarge' before anything is written, and the connection is
        left as it was.

        A connection that fails is dropped, and 'lost' then says whether the
        failure was the connection turning out to be gone: refused as it was
        written to, reset, or closed by the IDE before a byte of the reply. That
        is what a connection held across an IDE restart does when it is next
        used (a half-open connection is indistinguishable from a live one until
        then), and the one failure after which the message can be sent again
        over a new connection without handing it to an IDE that already has it.
        Where it shows depends on the size of the frame: one that fits the
        socket's send buffer is written without complaint into a connection
        whose far end has gone, and the closure is seen only when the reply is
        read -- so "the write failed" alone would not catch it.

        A timeout is never that. The IDE is there, has the frame or as much of it
        as it has read, and is slow to answer -- which is when the frame is
        large, and when sending all of it again would only make it slower.
        """
        parts = protocol.frame_parts(message, binary=binary)
        self.lost = False
        self._reply_bytes = 0
        self.connect()
        try:
            self._socket.settimeout(reply_timeout)
            self._write(parts)
            reply = self._receive()
        except TimeoutError:
            self.close()
            raise
        except OSError:
            # A broken pipe or a reset: the far end is gone, unless it had
            # already begun to answer, in which case it had the message.
            self.lost = self._reply_bytes == 0
            self.close()
            raise
        except ProtocolError:
            # An end of file before the reply set 'lost' where it was read.
            self.close()
            raise
        capabilities = reply.get(protocol.KEY_CAPABILITIES)
        self.capabilities = (
            frozenset(capability for capability in capabilities or () if isinstance(capability, str))
            if isinstance(capabilities, list)
            else frozenset()
        )
        return reply

    # Parts smaller than this are gathered and written together; larger ones -
    # the blobs of a binary frame - are written as they are, rather than copied
    # into one buffer first.
    _GATHER = 64 * 1024

    def _write(self, parts):
        """Write a frame's parts in order, without joining the large ones into a copy."""
        pending = bytearray()
        for part in parts:
            if len(part) < self._GATHER:
                pending += part
                continue
            if pending:
                self._socket.sendall(pending)
                pending = bytearray()
            self._socket.sendall(part)
        if pending:
            self._socket.sendall(pending)

    def _receive(self) -> dict:
        length = protocol.decode_header(self._read_exactly(protocol.HEADER_LENGTH))
        return protocol.decode_payload(self._read_exactly(length))

    def _read_exactly(self, length: int) -> bytes:
        chunks = []
        remaining = length
        while remaining > 0:
            chunk = self._socket.recv(remaining)
            if not chunk:
                self.lost = self._reply_bytes == 0
                raise ProtocolError("the IDE closed the connection after %d of %d bytes" % (length - remaining, length))
            self._reply_bytes += len(chunk)
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)


_shared_lock = threading.Lock()
_shared_connection = None


def _send(message: dict, reply_timeout: float = REPLY_TIMEOUT) -> dict:
    """Send a message over the shared connection, reconnecting once if it is stale (see '_exchange')."""
    return _exchange(lambda connection: connection.send(message, reply_timeout=reply_timeout))


def _exchange(converse):
    """Run 'converse(connection)' over the shared connection, again over a new one if it was stale.

    Stale means found gone ('Connection.lost'), and nothing else does: any other
    failure is about a message the IDE has. A reply timeout used to count as
    well, so a show slower to acknowledge than the timeout was sent again in
    full -- a whole frame of geometry, to an IDE still busy with the first copy,
    and then waited for as long again.

    'converse' may be several messages - a show is offered, then sent - and is
    run again from its start: a connection found gone at any of them is one the
    IDE has not shown anything over yet, since the show is always the last.
    """
    global _shared_connection

    with _shared_lock:
        for attempt in (0, 1):
            if _shared_connection is None:
                _shared_connection = Connection()
            try:
                return converse(_shared_connection)
            except ViewerNotAvailable:
                _shared_connection = None
                raise
            except (OSError, ProtocolError):
                lost = _shared_connection.lost
                _shared_connection.close()
                _shared_connection = None
                if attempt == 1 or not lost:
                    raise
        # Unreachable: the loop either returns or raises.
        raise ViewerNotAvailable("failed to reach the Digital Thread")  # pragma: no cover - unreachable, see above


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
    obj,
    name=None,
    kind=None,
    package=None,
    keep_camera=False,
    reply_timeout: float = REPLY_TIMEOUT,
    tab=None,
    scenario=None,
    section=None,
) -> dict:
    """Display one already-tessellated object in the IDE's Digital Thread.

    'obj' is the root node of the object's tree, as PartCAD's
    'Shape.get_representation(ctx, "gltf")' produces it: nodes carrying geometry,
    where each sits, and what each declares about connections. One shape of
    payload for every kind of subject - a part, a sketch, an assembly, a scene,
    an interface - so nothing here or on the far side asks which it is. The
    protocol module documents the node.

    The glTF of each node is bytes, as the sandbox wrote it ('encode_gltf'); how
    it is written onto the socket is decided here, by what the IDE at the other
    end has said it reads (see '_show'). A payload in the text spelling of a
    PartCAD before this one is taken too.

    'package' is the package the shown object belongs to. The viewer has more to
    say about an object than its geometry - what an assembly is made of, how it
    goes together, where to buy its parts - and it asks the PartCAD daemon for
    all of that by name; a name with no package to resolve it against is not
    enough to ask with. Optional, because a shape shown from a script may belong
    to no package at all.

    'keep_camera' asks the viewer to leave the camera where the user put it,
    which is what makes re-showing the same part after an edit not jump.

    'tab' is the tab of the viewer to open on (see 'protocol.KEY_TAB'), or None
    to leave the viewer on the one it is on. 'scenario' is which of that tab's
    simulations or analysis scenarios to select (see 'protocol.KEY_SCENARIO'),
    and needs a tab that lists them.

    'section' is the cross-section 'obj' was cut to (see 'protocol.KEY_SECTION'),
    or None for the whole object. Sent either way.
    """
    if tab is not None and tab not in protocol.viewer_tab_ids():
        raise ValueError("not a Digital Thread tab: %r (one of %s)" % (tab, ", ".join(protocol.viewer_tab_ids())))
    if scenario is not None and tab not in protocol.SCENARIO_TABS:
        raise ValueError(
            "a scenario is selected on a tab that lists them (one of %s), not on %r"
            % (", ".join(protocol.SCENARIO_TABS), tab)
        )
    if not protocol.is_node(obj):
        raise TypeError(
            "not a shape tree (no %r, %r or %r key): %r"
            % (protocol.KEY_GLTF, protocol.KEY_GLTF_REF, protocol.KEY_ASSEMBLY, obj)
        )

    message = {
        "type": protocol.MSG_SHOW,
        "id": uuid.uuid4().hex,
        "name": name,
        "kind": kind,
        "package": package,
        "keepCamera": bool(keep_camera),
        protocol.KEY_SECTION: section or None,
        protocol.KEY_OBJECT: obj,
    }
    if tab is not None:
        message[protocol.KEY_TAB] = tab
    if scenario is not None:
        message[protocol.KEY_SCENARIO] = scenario
    return _exchange(lambda connection: _show(connection, message, reply_timeout))


# How much geometry one MSG_GEOMETRY frame is given, short of the frame limit by
# room for its message: a digest and an index an entry, a few thousand of them at
# the most.
GEOMETRY_FRAME_BUDGET = protocol.MAX_FRAME_LENGTH - (1 << 20)


def _show(connection, message: dict, reply_timeout: float) -> dict:
    """Send the show 'message' over 'connection', the way the IDE there reads one.

    Offered first to an IDE that accepts offers, so that only the geometry it lacks
    is sent (see 'protocol.MSG_OFFER'); sent whole, as blobs, to one that reads
    binary frames and nothing more; and as a JSON frame to one that has said
    nothing, which is any IDE from before either. A connection nothing is known
    about yet is asked with the offer: a new IDE wants it first anyway, and an old
    one acknowledges it without saying what it accepts.

    A show with no geometry table - no geometry at all, or only on its nodes,
    which PartCAD does not send and a hand-made tree can - goes as a JSON frame
    straight away, which every IDE reads, rather than asking anything first.
    """
    table = message[protocol.KEY_OBJECT].get(protocol.KEY_GEOMETRY)
    offered = {}
    if isinstance(table, dict):
        offered = {digest: payload for digest, payload in table.items() if protocol.is_payload(payload)}
    if not offered:
        return connection.send(message, reply_timeout)

    missing = None
    if connection.capabilities is None:
        missing = _offer(connection, offered, reply_timeout)
    capabilities = connection.capabilities or frozenset()
    if protocol.CAP_BINARY not in capabilities:
        return connection.send(message, reply_timeout)

    if protocol.CAP_OFFER in capabilities:
        if missing is None:
            missing = _offer(connection, offered, reply_timeout)
        held = dict(message)
        held[protocol.KEY_OBJECT] = dict(message[protocol.KEY_OBJECT])
        held[protocol.KEY_OBJECT][protocol.KEY_GEOMETRY] = {
            digest: None if digest in offered else payload for digest, payload in table.items()
        }
        try:
            # Twice at most: an IDE that let go of something between the offer
            # and the show says so and is sent it; one that does it again is
            # sent everything, below, rather than asked a third time.
            for _ in range(2):
                _send_geometry(connection, {digest: offered[digest] for digest in missing}, reply_timeout)
                reply = connection.send(held, reply_timeout, binary=True)
                missing = _missing(reply.get(protocol.KEY_MISSING), offered)
                if not missing:
                    return reply
        except FrameTooLarge:
            # One shape larger than a frame: only the compressed JSON frame below
            # can still carry it.
            pass

    try:
        return connection.send(message, reply_timeout, binary=True)
    except FrameTooLarge:
        # Compressed, as every show was before binary frames, it may fit.
        return connection.send(message, reply_timeout)


def _offer(connection, offered: dict, reply_timeout: float):
    """Offer 'offered' by digest, and return the digests the IDE lacks - all of them, unless it says."""
    reply = connection.send(
        {"type": protocol.MSG_OFFER, "id": uuid.uuid4().hex, protocol.KEY_DIGESTS: list(offered)},
        reply_timeout,
    )
    missing = reply.get(protocol.KEY_MISSING)
    return list(offered) if missing is None else _missing(missing, offered)


def _missing(missing, offered: dict) -> list:
    """What of 'offered' an IDE said it lacks, leaving out anything it named that was not offered."""
    if not isinstance(missing, list):
        return []
    return [digest for digest in missing if isinstance(digest, str) and digest in offered]


def _send_geometry(connection, payloads: dict, reply_timeout: float) -> None:
    """Send 'payloads' by digest, in as few MSG_GEOMETRY frames as hold them."""
    batch = {}
    size = 0

    def flush():
        connection.send(
            {"type": protocol.MSG_GEOMETRY, "id": uuid.uuid4().hex, protocol.KEY_GEOMETRY: batch},
            reply_timeout,
            binary=True,
        )

    for digest, payload in payloads.items():
        if isinstance(payload, str):
            payload = protocol.decode_gltf(payload)
        if batch and size + len(payload) > GEOMETRY_FRAME_BUDGET:
            flush()
            batch = {}
            size = 0
        batch[digest] = payload
        size += len(payload) + 4
    if batch:
        flush()


def clear() -> dict:
    """Empty the viewer."""
    return _send({"type": protocol.MSG_CLEAR, "id": uuid.uuid4().hex})


def state(reply_timeout: float = STATE_TIMEOUT) -> dict:
    """What the IDE is showing: its Explorer, Inspector and Digital Thread (see 'protocol.MSG_STATE').

    Over a connection of its own rather than the shared one: this is a one-off
    question, usually from a process that will never show anything.
    """
    with Connection() as connection:
        reply = connection.send({"type": protocol.MSG_STATE, "id": uuid.uuid4().hex}, reply_timeout=reply_timeout)
    if protocol.KEY_STATE not in reply:
        if reply.get("ok") is False and reply.get("error"):
            raise StateNotSupported(str(reply["error"]))
        raise StateNotSupported(
            "the PartCAD IDE listening on port %d does not report its state; update the PartCAD extension"
            % connection.port
        )
    return reply[protocol.KEY_STATE]
