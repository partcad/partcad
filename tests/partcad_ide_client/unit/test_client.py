#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import socket
import threading

import pytest

from partcad_ide_client import client, protocol


class FakeIde:
    """The smallest server that speaks the protocol, standing in for the IDE.

    Binds an ephemeral port rather than the constant one so the suite never
    collides with a PartCAD IDE the developer actually has open.
    """

    def __init__(self, reply=True):
        self.reply = reply
        self.received = []
        self.connections = 0
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(4)
        # Poll rather than block: closing a listening socket does not reliably
        # wake a thread already parked in accept(), so close() would otherwise
        # have to wait out its join timeout on every test that never connects.
        self._socket.settimeout(0.05)
        self.port = self._socket.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._socket.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            self.connections += 1
            with conn:
                conn.settimeout(0.05)
                try:
                    self._handle(conn)
                except OSError:
                    pass

    def _handle(self, conn):
        while not self._stop.is_set():
            try:
                header = self._read_exactly(conn, protocol.HEADER_LENGTH)
            except TimeoutError:
                continue
            if header is None:
                return
            length = protocol.decode_header(header)
            # The idle poll above is only safe between frames; once a header has
            # arrived the rest of the frame is already on its way, so wait for it.
            conn.settimeout(5)
            payload = self._read_exactly(conn, length)
            conn.settimeout(0.05)
            if payload is None:
                return
            message = protocol.decode_payload(payload)
            self.received.append(message)
            if not self.reply:
                return
            conn.sendall(protocol.encode_frame({"type": protocol.MSG_ACK, "id": message.get("id"), "ok": True}))

    @staticmethod
    def _read_exactly(conn, length):
        chunks = []
        remaining = length
        while remaining > 0:
            chunk = conn.recv(remaining)
            if not chunk:
                return None
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def close(self):
        self._stop.set()
        self._socket.close()
        self._thread.join(timeout=5)


@pytest.fixture
def ide(monkeypatch):
    server = FakeIde()
    monkeypatch.setenv("PARTCAD_IDE_PORT", str(server.port))
    client.disconnect()
    try:
        yield server
    finally:
        client.disconnect()
        server.close()


@pytest.fixture
def no_ide(monkeypatch):
    """Point the client at a port nothing is listening on."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    monkeypatch.setenv("PARTCAD_IDE_PORT", str(port))
    client.disconnect()
    try:
        yield port
    finally:
        client.disconnect()


def test_show_sends_objects_and_returns_the_ack(ide):
    obj = protocol.make_object(b"glTF-payload", name="//pkg:part", label="part")

    ack = client.show([obj], name="//pkg:part", kind="part", package="//pkg", keep_camera=True)

    assert ack["type"] == protocol.MSG_ACK
    assert ack["ok"] is True

    (message,) = ide.received
    assert message["type"] == protocol.MSG_SHOW
    assert message["name"] == "//pkg:part"
    assert message["kind"] == "part"
    # What the viewer's other tabs are about: they ask the daemon about
    # '<package>:<name>', which a name on its own cannot spell.
    assert message[protocol.KEY_PACKAGE] == "//pkg"
    assert message["keepCamera"] is True
    assert protocol.decode_gltf(message["objects"][0][protocol.KEY_GLTF]) == b"glTF-payload"


def test_show_without_a_package_says_so_rather_than_omitting_it(ide):
    """A shape belonging to no package still has geometry to show"""
    client.show([protocol.make_object(b"glTF-payload")], name="widget")

    (message,) = ide.received
    # Present and null, not absent: the viewer reads it to decide which tabs to
    # offer, and "the sender did not say" is the answer it needs.
    assert message[protocol.KEY_PACKAGE] is None


def test_show_rejects_objects_without_geometry(ide):
    with pytest.raises(TypeError, match="gltf"):
        client.show([{"name": "//pkg:part"}])
    assert ide.received == []


def test_show_reuses_one_connection(ide):
    obj = protocol.make_object(b"glTF")
    client.show([obj])
    client.show([obj])

    assert len(ide.received) == 2
    # A show is interactive, so the second one must not pay for a fresh TCP
    # handshake: both arrived over the one connection the IDE accepted.
    assert ide.connections == 1


def test_clear_and_ping(ide):
    client.clear()
    assert client.is_available()

    assert [message["type"] for message in ide.received] == [protocol.MSG_CLEAR, protocol.MSG_PING]


def test_show_reconnects_after_the_ide_restarts(ide):
    obj = protocol.make_object(b"glTF")
    client.show([obj])

    # Drop the connection under the client's feet, the way restarting the IDE
    # extension host does. The next show must transparently reconnect.
    client._shared_connection._socket.close()

    client.show([obj])
    assert len(ide.received) == 2
    assert ide.connections == 2


def test_missing_viewer_raises_rather_than_hanging(no_ide):
    with pytest.raises(client.ViewerNotAvailable):
        client.show([protocol.make_object(b"glTF")])


def test_is_available_is_false_without_a_viewer(no_ide):
    assert client.is_available() is False


def test_is_available_is_true_with_a_viewer(ide):
    assert client.is_available() is True


def test_port_override_falls_back_when_unparseable(monkeypatch):
    monkeypatch.setenv("PARTCAD_IDE_PORT", "not-a-port")
    assert client._port() == protocol.PARTCAD_IDE_PORT

    monkeypatch.delenv("PARTCAD_IDE_PORT")
    assert client._port() == protocol.PARTCAD_IDE_PORT


@pytest.mark.parametrize(
    "override, expected",
    [
        ("9999", 9999),
        ("65535", 65535),
        ("1", 1),
        # Out of range: 0 means "any free port", which the IDE cannot bind and
        # still be findable, and 65536 is not a port at all.
        ("0", protocol.PARTCAD_IDE_PORT),
        ("70000", protocol.PARTCAD_IDE_PORT),
        # Spellings 'int()' would take and the JS 'listenPort()' would not.
        ("+9999", protocol.PARTCAD_IDE_PORT),
        (" 9999 ", protocol.PARTCAD_IDE_PORT),
        ("1_0", protocol.PARTCAD_IDE_PORT),
        # Spellings 'Number()' would take and 'int()' would not; both ends have
        # to reject them, or one moves off the default port alone.
        ("1e4", protocol.PARTCAD_IDE_PORT),
        ("0x270f", protocol.PARTCAD_IDE_PORT),
        ("99.5", protocol.PARTCAD_IDE_PORT),
        ("", protocol.PARTCAD_IDE_PORT),
    ],
)
def test_port_override_matches_the_js_parser(monkeypatch, override, expected):
    monkeypatch.setenv("PARTCAD_IDE_PORT", override)
    assert client._port() == expected
