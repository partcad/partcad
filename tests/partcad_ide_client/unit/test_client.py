#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import base64
import socket
import threading
import zlib

import pytest

from partcad_ide_client import client, protocol


class FakeIde:
    """The smallest server that speaks the protocol, standing in for the IDE.

    Binds an ephemeral port rather than the constant one so the suite never
    collides with a PartCAD IDE the developer actually has open.

    'capabilities' None is an IDE from before them, which says nothing and reads
    JSON frames only - and drops the connection at a binary one, as such an IDE
    does. Given CAP_OFFER it answers offers from what it holds, which is what it
    was sent; 'forget' is how many shows it answers as having let go of
    everything it was offered meanwhile.
    """

    def __init__(self, reply=True, ack=None, capabilities=None, forget=0):
        self.reply = reply
        # More to say in the acknowledgement: what an IDE answers a 'state' with.
        self.ack = ack or {}
        self.capabilities = capabilities
        self.forget = forget
        self.held = {}
        self.received = []
        # The kind of frame each message came in.
        self.kinds = []
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
        # 'hang_up()': close the connection being served, from this end.
        self._hang_up = threading.Event()
        self._hung_up = threading.Event()
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
            if self._hang_up.is_set():
                self._hang_up.clear()
                self._hung_up.set()

    def _handle(self, conn):
        while not self._stop.is_set():
            if self._hang_up.is_set():
                return
            try:
                header = self._read_exactly(conn, protocol.HEADER_LENGTH)
            except TimeoutError:
                continue
            if header is None:
                return
            kind, length = protocol.read_header(header)
            if kind != protocol.KIND_JSON and self.capabilities is None:
                # What an extension from before binary frames does with one.
                return
            # The idle poll above is only safe between frames; once a header has
            # arrived the rest of the frame is already on its way, so wait for it.
            conn.settimeout(5)
            payload = self._read_exactly(conn, length)
            conn.settimeout(0.05)
            if payload is None:
                return
            message = protocol.decode_payload(payload, kind)
            self.received.append(message)
            self.kinds.append(kind)
            if not self.reply:
                return
            ack = {"type": protocol.MSG_ACK, "id": message.get("id"), "ok": True}
            if self.capabilities is not None:
                ack[protocol.KEY_CAPABILITIES] = list(self.capabilities)
                ack.update(self._answer(message))
            ack.update(self.ack.get(message.get("type"), {}))
            conn.sendall(protocol.encode_frame(ack))

    def _answer(self, message):
        """What an IDE that accepts offers says beyond 'ok'."""
        if protocol.CAP_OFFER not in self.capabilities:
            return {}
        if message["type"] == protocol.MSG_OFFER:
            return {protocol.KEY_MISSING: [d for d in message[protocol.KEY_DIGESTS] if d not in self.held]}
        if message["type"] == protocol.MSG_GEOMETRY:
            self.held.update(message[protocol.KEY_GEOMETRY])
            return {}
        if message["type"] == protocol.MSG_SHOW:
            table = message[protocol.KEY_OBJECT].get(protocol.KEY_GEOMETRY) or {}
            if self.forget > 0:
                self.forget -= 1
                self.held.clear()
            missing = [digest for digest, payload in table.items() if payload is None and digest not in self.held]
            if missing:
                return {"ok": False, protocol.KEY_MISSING: missing}
            self.held.update({digest: payload for digest, payload in table.items() if payload is not None})
        return {}

    def shown(self):
        """The geometry of the last show as the IDE ends up with it: what came with it, or what it held."""
        show = [message for message in self.received if message["type"] == protocol.MSG_SHOW][-1]
        table = show[protocol.KEY_OBJECT].get(protocol.KEY_GEOMETRY) or {}
        return {digest: self.held[digest] if payload is None else payload for digest, payload in table.items()}

    def types(self):
        return [message["type"] for message in self.received]

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

    def hang_up(self):
        """Close the connection being served from this end, as an IDE that restarts does.

        Between frames, and only once it is closed: the client is left holding a
        connection whose far end has gone, and nothing it writes afterwards is
        read by this server.
        """
        self._hung_up.clear()
        self._hang_up.set()
        assert self._hung_up.wait(timeout=10), "the fake IDE did not hang up"

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
def ide_with(monkeypatch):
    """A FakeIde made as the test says, connected to like 'ide'."""
    servers = []

    def make(**options):
        server = FakeIde(**options)
        servers.append(server)
        monkeypatch.setenv("PARTCAD_IDE_PORT", str(server.port))
        client.disconnect()
        return server

    try:
        yield make
    finally:
        client.disconnect()
        for server in servers:
            server.close()


@pytest.fixture
def no_ide(monkeypatch):
    """Point the client at a port nothing is listening on.

    The port stays bound, and not listening, for as long as the test runs: a
    connection to it is refused all the same, and nothing else can take it in
    the meantime -- which a port that was only free a moment ago does not
    promise, with other pytest-xdist workers starting servers of their own.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]

    monkeypatch.setenv("PARTCAD_IDE_PORT", str(port))
    client.disconnect()
    try:
        yield port
    finally:
        client.disconnect()
        probe.close()


def test_show_sends_the_object_tree_and_returns_the_ack(ide):
    obj = protocol.make_node(
        b"glTF-payload",
        name="//pkg:mount",
        label="mount",
        children=[protocol.make_node(b"child-glTF", name="//pkg:plate", label="bottom")],
    )

    ack = client.show(obj, name="//pkg:mount", kind="assembly", package="//pkg", keep_camera=True)

    assert ack["type"] == protocol.MSG_ACK
    assert ack["ok"] is True

    (message,) = ide.received
    assert message["type"] == protocol.MSG_SHOW
    assert message["name"] == "//pkg:mount"
    assert message["kind"] == "assembly"
    # What the viewer's other tabs are about: they ask the daemon about
    # '<package>:<name>', which a name on its own cannot spell.
    assert message[protocol.KEY_PACKAGE] == "//pkg"
    assert message["keepCamera"] is True

    # One object, as the tree it is, nested as deeply as it goes.
    sent = message[protocol.KEY_OBJECT]
    assert protocol.decode_gltf(sent[protocol.KEY_GLTF]) == b"glTF-payload"
    (child,) = sent[protocol.KEY_ASSEMBLY]
    assert child[protocol.KEY_LABEL] == "bottom"
    assert protocol.decode_gltf(child[protocol.KEY_GLTF]) == b"child-glTF"


def test_show_carries_the_tab_asked_for(ide):
    client.show(protocol.make_node(b"glTF"), name="//pkg:beam", kind="part", package="//pkg", tab="fea")

    (message,) = ide.received
    assert message[protocol.KEY_TAB] == "fea"


def test_show_carries_the_section_it_was_cut_to(ide):
    client.show(protocol.make_node(b"glTF"), name="//pkg:beam", section={"z": [0.0, 2.5]})

    (message,) = ide.received
    assert message[protocol.KEY_SECTION] == {"z": [0.0, 2.5]}


def test_show_of_the_whole_object_says_so(ide):
    """None and not absent: absent is a PartCAD that cannot cut, and the viewer offers it no sliders."""
    client.show(protocol.make_node(b"glTF"), name="//pkg:beam")

    (message,) = ide.received
    assert protocol.KEY_SECTION in message
    assert message[protocol.KEY_SECTION] is None


def test_show_without_a_tab_sends_no_tab_key(ide):
    """An IDE from before the key, and every show that names no tab, leave the viewer where it is."""
    client.show(protocol.make_node(b"glTF"), name="//pkg:beam")

    (message,) = ide.received
    assert protocol.KEY_TAB not in message


def test_show_takes_reply_timeout_where_it_always_was(ide):
    """`tab` came after it, so a caller passing the timeout by position is not reading it as a tab."""
    client.show(protocol.make_node(b"glTF"), "//pkg:beam", "part", "//pkg", False, 30.0)

    (message,) = ide.received
    assert protocol.KEY_TAB not in message


def test_show_carries_the_scenario_to_select_on_the_tab(ide):
    client.show(protocol.make_node(b"glTF"), name="//pkg:beam", tab="fea", scenario="loaded")

    (message,) = ide.received
    assert (message[protocol.KEY_TAB], message[protocol.KEY_SCENARIO]) == ("fea", "loaded")


def test_show_without_a_scenario_sends_no_scenario_key(ide):
    """The tab selects its first, as it does when it is opened by hand."""
    client.show(protocol.make_node(b"glTF"), name="//pkg:beam", tab="simulation")

    (message,) = ide.received
    assert protocol.KEY_SCENARIO not in message


@pytest.mark.parametrize("tab", [None, "3d"])
def test_show_refuses_a_scenario_on_a_tab_that_lists_none(ide, tab):
    with pytest.raises(ValueError, match="a scenario is selected on a tab that lists them"):
        client.show(protocol.make_node(b"glTF"), name="//pkg:beam", tab=tab, scenario="loaded")
    assert ide.received == []


def test_show_refuses_a_tab_the_viewer_does_not_have(ide):
    with pytest.raises(ValueError, match="not a Digital Thread tab"):
        client.show(protocol.make_node(b"glTF"), name="//pkg:beam", tab="buy")
    assert ide.received == []


def test_show_without_a_package_says_so_rather_than_omitting_it(ide):
    """A shape belonging to no package still has geometry to show"""
    client.show(protocol.make_node(b"glTF-payload"), name="widget")

    (message,) = ide.received
    # Present and null, not absent: the viewer reads it to decide which tabs to
    # offer, and "the sender did not say" is the answer it needs.
    assert message[protocol.KEY_PACKAGE] is None


def test_show_rejects_anything_that_is_not_a_tree(ide):
    with pytest.raises(TypeError, match="gltf"):
        client.show({"name": "//pkg:part"})
    assert ide.received == []


def test_show_accepts_a_node_that_only_holds_others(ide):
    """An assembly's own node carries no geometry, and is a tree all the same."""
    client.show(protocol.make_node(name="//pkg:mount", children=[]))

    (message,) = ide.received
    assert protocol.KEY_GLTF not in message[protocol.KEY_OBJECT]


def test_show_reuses_one_connection(ide):
    obj = protocol.make_node(b"glTF")
    client.show(obj)
    client.show(obj)

    assert len(ide.received) == 2
    # A show is interactive, so the second one must not pay for a fresh TCP
    # handshake: both arrived over the one connection the IDE accepted.
    assert ide.connections == 1


def test_clear_and_ping(ide):
    client.clear()
    assert client.is_available()

    assert [message["type"] for message in ide.received] == [protocol.MSG_CLEAR, protocol.MSG_PING]


def test_show_reconnects_after_the_ide_restarts(ide):
    obj = protocol.make_node(b"glTF")
    client.show(obj)

    # Drop the connection under the client's feet, the way restarting the IDE
    # extension host does. The next show must transparently reconnect.
    client._shared_connection._socket.close()

    client.show(obj)
    assert len(ide.received) == 2
    assert ide.connections == 2


def test_show_reconnects_after_the_ide_hangs_up_on_an_idle_connection(ide):
    """The restart as it really happens: the IDE closes its end, not ours.

    A small frame is then written into the dead connection without complaint,
    and the connection is found gone only when the reply is read - so a client
    that resent only after a failed write would not reconnect at all.
    """
    obj = protocol.make_node(b"glTF")
    client.show(obj)

    ide.hang_up()

    client.show(obj)
    assert len(ide.received) == 2
    assert ide.connections == 2


# ---- how a show is sent, by what the IDE says it reads -----------------------

BOLT = b"glTF-bolt" + bytes(range(256)) * 8
NUT = b"glTF-nut" + bytes(range(255, -1, -1)) * 8
WASHER = b"glTF-washer"


def assembly(**geometry):
    """A tree the way PartCAD sends one: nodes naming the entries of a table on the root."""
    return {
        "name": "//pkg:assy",
        "label": None,
        "assembly": [{"name": "//pkg:%s" % digest, "label": digest, "gltfRef": digest} for digest in geometry],
        protocol.KEY_GEOMETRY: dict(geometry),
    }


NEW_IDE = (protocol.CAP_BINARY, protocol.CAP_OFFER)


def test_an_ide_from_before_capabilities_is_asked_once_and_sent_json(ide_with):
    old = ide_with()

    client.show(assembly(bolt=BOLT, nut=NUT))
    client.show(assembly(bolt=BOLT, nut=NUT))

    # The offer is how the client finds out; an IDE that does not know it says
    # nothing, and from then on, over that connection, is not asked again.
    assert old.types() == [protocol.MSG_OFFER, protocol.MSG_SHOW, protocol.MSG_SHOW]
    assert old.kinds == [protocol.KIND_JSON] * 3
    assert old.connections == 1
    # In the spelling such an IDE inflates.
    table = old.received[-1][protocol.KEY_OBJECT][protocol.KEY_GEOMETRY]
    assert {digest: zlib.decompress(base64.b64decode(payload)) for digest, payload in table.items()} == {
        "bolt": BOLT,
        "nut": NUT,
    }


def test_an_ide_that_accepts_offers_is_sent_only_what_it_lacks(ide_with):
    new = ide_with(capabilities=NEW_IDE)

    client.show(assembly(bolt=BOLT, nut=NUT))
    assert new.types() == [protocol.MSG_OFFER, protocol.MSG_GEOMETRY, protocol.MSG_SHOW]
    assert new.received[1][protocol.KEY_GEOMETRY] == {"bolt": BOLT, "nut": NUT}
    # The show itself names everything and carries nothing.
    assert new.received[2][protocol.KEY_OBJECT][protocol.KEY_GEOMETRY] == {"bolt": None, "nut": None}
    assert new.kinds[1:] == [protocol.KIND_BINARY, protocol.KIND_BINARY]
    assert new.shown() == {"bolt": BOLT, "nut": NUT}

    # An edit: the nut changed, the bolt did not, a washer is new.
    del new.received[:]
    client.show(assembly(bolt=BOLT, washer=WASHER))
    assert new.types() == [protocol.MSG_OFFER, protocol.MSG_GEOMETRY, protocol.MSG_SHOW]
    assert new.received[1][protocol.KEY_GEOMETRY] == {"washer": WASHER}
    assert new.shown() == {"bolt": BOLT, "washer": WASHER}

    # The same again: nothing to send but the tree.
    del new.received[:]
    client.show(assembly(bolt=BOLT, washer=WASHER))
    assert new.types() == [protocol.MSG_OFFER, protocol.MSG_SHOW]
    assert new.connections == 1


def test_the_tree_shown_is_left_as_it_was(ide_with):
    ide_with(capabilities=NEW_IDE)
    tree = assembly(bolt=BOLT)

    client.show(tree)

    assert tree[protocol.KEY_GEOMETRY] == {"bolt": BOLT}


def test_an_ide_that_let_go_between_the_offer_and_the_show_is_sent_it_again(ide_with):
    new = ide_with(capabilities=NEW_IDE)
    client.show(assembly(bolt=BOLT))
    del new.received[:]
    new.forget = 1

    reply = client.show(assembly(bolt=BOLT, nut=NUT))

    assert reply["ok"] is True
    assert new.types() == [
        protocol.MSG_OFFER,
        protocol.MSG_GEOMETRY,
        protocol.MSG_SHOW,
        protocol.MSG_GEOMETRY,
        protocol.MSG_SHOW,
    ]
    assert new.received[3][protocol.KEY_GEOMETRY] == {"bolt": BOLT, "nut": NUT}
    assert new.shown() == {"bolt": BOLT, "nut": NUT}


def test_an_ide_that_keeps_letting_go_is_sent_the_show_whole(ide_with):
    new = ide_with(capabilities=NEW_IDE, forget=2)

    reply = client.show(assembly(bolt=BOLT))

    assert reply["ok"] is True
    assert new.types()[-1] == protocol.MSG_SHOW
    assert new.received[-1][protocol.KEY_OBJECT][protocol.KEY_GEOMETRY] == {"bolt": BOLT}
    assert new.kinds[-1] == protocol.KIND_BINARY


def test_an_ide_that_reads_binary_frames_and_takes_no_offers_is_sent_the_show_whole(ide_with):
    binary = ide_with(capabilities=(protocol.CAP_BINARY,))

    client.show(assembly(bolt=BOLT))
    client.show(assembly(bolt=BOLT))

    assert binary.types() == [protocol.MSG_OFFER, protocol.MSG_SHOW, protocol.MSG_SHOW]
    assert binary.kinds[1:] == [protocol.KIND_BINARY, protocol.KIND_BINARY]
    assert binary.received[-1][protocol.KEY_OBJECT][protocol.KEY_GEOMETRY] == {"bolt": BOLT}


def test_what_an_ide_accepts_is_forgotten_with_its_connection(ide_with):
    """The next connection may be to another window, which may be another release."""
    new = ide_with(capabilities=NEW_IDE)
    client.show(assembly(bolt=BOLT))
    assert client._shared_connection.capabilities == frozenset(NEW_IDE)

    new.hang_up()
    del new.received[:]
    new.held.clear()
    client.show(assembly(bolt=BOLT))

    assert new.connections == 2
    assert new.types() == [protocol.MSG_OFFER, protocol.MSG_GEOMETRY, protocol.MSG_SHOW]


def test_a_tree_without_a_table_goes_as_json_without_asking(ide_with):
    new = ide_with(capabilities=NEW_IDE)

    client.show(protocol.make_node(BOLT, name="//pkg:bolt"))

    assert new.types() == [protocol.MSG_SHOW]
    assert new.kinds == [protocol.KIND_JSON]
    assert protocol.decode_gltf(new.received[0][protocol.KEY_OBJECT][protocol.KEY_GLTF]) == BOLT


def test_geometry_larger_than_a_frame_follows_in_several(ide_with, monkeypatch):
    new = ide_with(capabilities=NEW_IDE)
    monkeypatch.setattr(client, "GEOMETRY_FRAME_BUDGET", len(BOLT) + len(NUT) // 2)

    client.show(assembly(bolt=BOLT, nut=NUT, washer=WASHER))

    assert new.types() == [protocol.MSG_OFFER, protocol.MSG_GEOMETRY, protocol.MSG_GEOMETRY, protocol.MSG_SHOW]
    assert new.shown() == {"bolt": BOLT, "nut": NUT, "washer": WASHER}


def test_a_shape_too_large_for_a_binary_frame_goes_compressed(ide_with, monkeypatch):
    """What fitted a frame before binary frames - compressed - fits one still."""
    new = ide_with(capabilities=NEW_IDE)
    huge = b"glTF" + b"\x00" * 200000
    monkeypatch.setattr(protocol, "MAX_FRAME_LENGTH", 50000)
    monkeypatch.setattr(client, "GEOMETRY_FRAME_BUDGET", 40000)

    reply = client.show(assembly(bolt=huge))

    assert reply["ok"] is True
    assert new.types()[-1] == protocol.MSG_SHOW
    assert new.kinds[-1] == protocol.KIND_JSON
    assert new.shown() == {"bolt": base64.b64encode(zlib.compress(huge, 6)).decode("ascii")}


def test_a_show_offered_over_a_connection_found_gone_is_offered_again_over_a_new_one(ide_with):
    new = ide_with(capabilities=NEW_IDE)
    client.show(assembly(bolt=BOLT))
    new.hang_up()
    del new.received[:]

    reply = client.show(assembly(bolt=BOLT, nut=NUT))

    assert reply["ok"] is True
    assert new.types() == [protocol.MSG_OFFER, protocol.MSG_GEOMETRY, protocol.MSG_SHOW]
    assert new.shown() == {"bolt": BOLT, "nut": NUT}


class FakeSocket:
    """A connection to an IDE that does what a test says, with no network at all.

    'behaviour' is what happens to the frame written to it:

    * "ack": it is acknowledged.
    * "timeout": nothing comes back before the reply timeout.
    * "refused": the write fails, as it does into a connection reset by its peer.
    * "closed": the write succeeds and the connection turns out closed when the
      reply is read, as a small frame does into a connection whose IDE has gone.
    * "reset": the same, ending in a reset rather than an end of file.
    * "reset-mid-reply": part of the acknowledgement arrives, then a reset.
    * "garbage": something answers that does not speak the protocol.
    """

    def __init__(self, behaviour, written):
        self.behaviour = behaviour
        self.written = written
        self.reply = b""

    def setsockopt(self, *args):
        pass

    def settimeout(self, timeout):
        pass

    def close(self):
        pass

    def sendall(self, data):
        if self.behaviour == "refused":
            raise BrokenPipeError(32, "Broken pipe")
        message = protocol.decode_payload(bytes(data)[protocol.HEADER_LENGTH :])
        self.written.append((self, message))
        ack = protocol.encode_frame({"type": protocol.MSG_ACK, "id": message.get("id"), "ok": True})
        if self.behaviour == "ack":
            self.reply = ack
        elif self.behaviour == "reset-mid-reply":
            self.reply = ack[:4]
        elif self.behaviour == "garbage":
            self.reply = b"HTTP/1.1 400 Bad Request\r\n\r\n"

    def recv(self, size):
        if self.behaviour == "timeout":
            raise TimeoutError("timed out")
        if self.reply:
            chunk, self.reply = self.reply[:size], self.reply[size:]
            return chunk
        if self.behaviour in ("reset", "reset-mid-reply"):
            raise ConnectionResetError(104, "Connection reset by peer")
        return b""


@pytest.fixture
def connections(monkeypatch):
    """Script the connections the client makes: append a behaviour per connection.

    Yields the list to append to and the list of (socket, message) pairs
    written; a connection made past the end of the script is refused.
    """
    behaviours = []
    written = []
    sockets = []

    def create_connection(address, timeout=None):
        if len(sockets) == len(behaviours):
            raise ConnectionRefusedError(111, "Connection refused")
        sockets.append(FakeSocket(behaviours[len(sockets)], written))
        return sockets[-1]

    monkeypatch.setattr(client.socket, "create_connection", create_connection)
    client.disconnect()
    try:
        yield behaviours, written, sockets
    finally:
        client.disconnect()


def test_a_show_whose_reply_times_out_is_not_sent_again(connections):
    # The IDE has the frame and is working through it; a second copy is a whole
    # frame of geometry more for it to read, and another timeout to wait out.
    behaviours, written, sockets = connections
    behaviours += ["timeout", "ack"]

    with pytest.raises(TimeoutError):
        client.show(protocol.make_node(b"glTF"))
    assert len(written) == 1
    assert len(sockets) == 1

    # The connection that timed out is not reused: the IDE may yet answer on it,
    # and that answer would be read as the reply to the next message.
    client.show(protocol.make_node(b"glTF"))
    assert [connection for connection, _ in written] == sockets


@pytest.mark.parametrize("behaviour", ["refused", "closed", "reset"])
def test_a_connection_found_gone_is_replaced_and_the_message_sent_again(connections, behaviour):
    behaviours, written, sockets = connections
    behaviours += [behaviour, "ack"]

    reply = client.show(protocol.make_node(b"glTF"))

    assert reply["ok"] is True
    assert len(sockets) == 2
    # Answered over the second connection, with the message the first one lost.
    assert written[-1][0] is sockets[1]
    assert {message["id"] for _, message in written} == {reply["id"]}


@pytest.mark.parametrize(
    "behaviour, error", [("reset-mid-reply", ConnectionResetError), ("garbage", protocol.ProtocolError)]
)
def test_an_ide_that_began_to_answer_is_not_sent_the_message_again(connections, behaviour, error):
    behaviours, written, sockets = connections
    behaviours += [behaviour, "ack"]

    with pytest.raises(error):
        client.show(protocol.make_node(b"glTF"))
    assert len(written) == 1
    assert len(sockets) == 1


def test_a_message_is_sent_again_once_and_no_more(connections):
    behaviours, written, sockets = connections
    behaviours += ["closed", "closed", "ack"]

    with pytest.raises(protocol.ProtocolError, match="closed the connection"):
        client.show(protocol.make_node(b"glTF"))
    assert len(sockets) == 2


def test_missing_viewer_raises_rather_than_hanging(no_ide):
    with pytest.raises(client.ViewerNotAvailable):
        client.show(protocol.make_node(b"glTF"))


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


def _ide_answering(monkeypatch, ack):
    server = FakeIde(ack=ack)
    monkeypatch.setenv("PARTCAD_IDE_PORT", str(server.port))
    return server


def test_state_is_asked_for_and_returned(monkeypatch):
    shown = {"explorer": {"selection": [{"kind": "part", "path": "//:cube"}]}}
    server = _ide_answering(monkeypatch, {protocol.MSG_STATE: {protocol.KEY_STATE: shown}})
    try:
        assert client.state() == shown
        assert server.received[0]["type"] == protocol.MSG_STATE
    finally:
        server.close()


def test_an_ide_too_old_to_say_is_told_apart_from_no_ide(monkeypatch):
    """It acknowledges 'state' like any message it does not know, without one."""
    server = _ide_answering(monkeypatch, {})
    try:
        with pytest.raises(client.StateNotSupported, match="update the PartCAD extension"):
            client.state()
    finally:
        server.close()


def test_an_ide_that_failed_to_collect_its_state_says_why(monkeypatch):
    server = _ide_answering(
        monkeypatch, {protocol.MSG_STATE: {"ok": False, "error": "the Digital Thread did not answer"}}
    )
    try:
        with pytest.raises(client.StateNotSupported, match="the Digital Thread did not answer"):
            client.state()
    finally:
        server.close()


def test_state_with_no_ide_is_no_ide(no_ide):
    with pytest.raises(client.ViewerNotAvailable):
        client.state()
