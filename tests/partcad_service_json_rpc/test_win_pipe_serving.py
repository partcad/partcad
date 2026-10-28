#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Serving the Windows named-pipe daemon: what a client sees on one connection.

Every connection to it used to end after its first answer. Each one was served
by an ``asyncio.Protocol`` of the module's own, and ``StreamWriter.drain()``
needs a method only asyncio's stream protocols have, so the first ``drain()``
raised and took the connection's task with it. The editor, which keeps one
connection open, lost it within milliseconds on every Windows run of
"IDE (end to end)"; ``pc``, which opens one per command, never noticed.

The first test below pins the protocol on any platform, over a socket: drain()
is not Windows-specific, only the pipe is. The second serves a real pipe, which
only Windows can, and does what the editor does -- a quick request sent back to
back with one that emits as it runs, three rounds on one connection. The events
are written from the request's worker thread, which an asyncio transport does
not allow either, so they also have to arrive whole, in order, and before the
answer.

What a connection is served by is not Windows-specific either, so the rest of
this module serves it over a socket: the same rounds, a cancellation, and the
writer that drops a client that stops reading.
"""

import asyncio
import base64
import contextlib
import socket
import sys
import threading
import time
import types
import uuid

import pytest

from partcad_service_json_rpc import config_restart
from partcad_service_json_rpc import win_pipe as service_win_pipe
from partcad_service_json_rpc.core import events
from partcad_service_json_rpc.rpc.dispatcher import REQUEST_CANCELLED, Dispatcher
from partcad_service_json_rpc.transport.dispatch import Dispatch
from partcad_utils import framing
from partcad_utils import win_pipe as rendezvous

# Enough that the worker is still writing while the loop finishes each write
# before it: the race needs the two to overlap, and a handful rarely did.
EVENTS = 2000
TIMEOUT = 30


def _chatty(session, params):
    for i in range(EVENTS):
        session.emitter.info("event %d" % i)
    return {"done": True}


REGISTRY = {"rpc.discover": lambda session, params: {"methods": []}, "chatty": _chatty}


def test_a_connection_is_served_past_its_first_answer():
    async def run():
        loop = asyncio.get_running_loop()
        served = loop.create_future()

        async def handler(reader, writer):
            # What 'serve_pipe' does with each request: answer, then drain.
            try:
                for _ in range(3):
                    request = await rendezvous.read_frame(reader)
                    rendezvous.write_frame(writer, {"jsonrpc": "2.0", "id": request["id"], "result": {}})
                    await writer.drain()
                served.set_result(None)
            except Exception as e:  # pylint: disable=broad-except
                served.set_exception(e)

        ours, theirs = socket.socketpair()
        await loop.connect_accepted_socket(lambda: service_win_pipe._connection_protocol(handler), ours)
        reader, writer = await asyncio.open_connection(sock=theirs)
        try:
            for request_id in (1, 2, 3):
                rendezvous.write_frame(writer, {"jsonrpc": "2.0", "id": request_id, "method": "x"})
                await writer.drain()
                answer = await asyncio.wait_for(rendezvous.read_frame(reader), TIMEOUT)
                assert answer is not None and answer["id"] == request_id, (request_id, answer)
            await asyncio.wait_for(served, TIMEOUT)
        finally:
            writer.close()

    asyncio.run(run())


async def _rounds(name: str, rounds: int) -> list:
    """Per round: the events between the two answers, and the second answer."""
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    transport, _ = await asyncio.wait_for(loop.create_pipe_connection(lambda: protocol, name), TIMEOUT)
    writer = asyncio.StreamWriter(transport, protocol, reader, loop)
    try:
        return await _rounds_on(reader, writer, rounds)
    finally:
        transport.close()


async def _rounds_on(reader, writer, rounds: int) -> list:
    """`_rounds`, on a connection already made."""
    if True:  # pylint: disable=using-constant-test
        seen = []
        for n in range(rounds):
            quick, slow = 2 * n + 1, 2 * n + 2
            rendezvous.write_frame(writer, {"jsonrpc": "2.0", "id": quick, "method": "rpc.discover"})
            rendezvous.write_frame(writer, {"jsonrpc": "2.0", "id": slow, "method": "chatty", "params": {}})
            await writer.drain()
            lines = []
            while True:
                frame = await asyncio.wait_for(rendezvous.read_frame(reader), TIMEOUT)
                assert frame is not None, "round %d: the connection closed after %d events" % (n, len(lines))
                if frame.get("method") == events.INFO:
                    lines.append(frame["params"])
                elif frame.get("id") == slow:
                    seen.append((lines, frame))
                    break
                else:
                    assert frame.get("id") == quick, frame
        return seen


@pytest.fixture
def pipe(monkeypatch):
    """A daemon serving a pipe of its own on a thread of this process; yields the pipe's name."""
    # Nothing here is about the configuration file, and a change to the real one
    # would end the daemon mid-test.
    monkeypatch.setattr(config_restart, "watch", lambda on_change: None)
    name = r"\\.\pipe\partcad-test-%s" % uuid.uuid4().hex
    session = types.SimpleNamespace(emitter=events.EventEmitter())
    server = threading.Thread(target=service_win_pipe.serve_pipe, args=(session, REGISTRY, name), daemon=True)
    server.start()
    deadline = time.monotonic() + TIMEOUT
    while not rendezvous.is_pipe_alive(name):
        assert server.is_alive(), "the daemon stopped before it served %s" % name
        assert time.monotonic() < deadline, "nothing served %s in %ss" % (name, TIMEOUT)
        time.sleep(0.1)
    try:
        yield name
    finally:
        rendezvous.pipe_request(name, rendezvous.STOP_METHOD, 5)
        server.join(TIMEOUT)


@pytest.mark.skipif(sys.platform != "win32", reason="serves a real named pipe")
def test_a_request_s_events_arrive_in_order_before_its_answer_and_the_connection_stays(pipe):
    rounds = asyncio.run(_rounds(pipe, 3))

    assert len(rounds) == 3
    for lines, answer in rounds:
        assert lines == ["event %d" % i for i in range(EVENTS)]
        assert answer["result"] == {"done": True}


def test_the_pipe_carries_attachments_to_a_client_that_reads_them():
    # The editor on Windows reaches this daemon over a pipe, and says it reads
    # attachments as it does on a socket. Pinned over a socket for the same
    # reason as the test above: the framing is not Windows-specific.
    picture = bytes(range(256)) * 2048  # several reads' worth

    async def run():
        loop = asyncio.get_running_loop()
        peers = []

        async def handler(reader, writer):
            peer = framing.Peer()
            peers.append(peer)
            while True:
                request = await rendezvous.read_frame(reader, peer)
                if request is None:
                    break
                answer = {"jsonrpc": "2.0", "id": request["id"], "result": {"content": picture}}
                rendezvous.write_frame(writer, answer, peer.attachments)
                await writer.drain()

        ours, theirs = socket.socketpair()
        await loop.connect_accepted_socket(lambda: service_win_pipe._connection_protocol(handler), ours)
        reader, writer = await asyncio.open_connection(sock=theirs)
        try:
            # A client from before attachments first, then one that reads them.
            writer.write(b"".join(framing.encode_message({"jsonrpc": "2.0", "id": 1, "method": "x"})))
            await writer.drain()
            older = await asyncio.wait_for(rendezvous.read_frame(reader), TIMEOUT)
            assert older["result"]["content"] == base64.b64encode(picture).decode("ascii")

            writer.write(
                b"".join(framing.encode_message({"jsonrpc": "2.0", "id": 2, "method": "x"}, accept_attachments=True))
            )
            await writer.drain()
            newer = await asyncio.wait_for(rendezvous.read_frame(reader), TIMEOUT)
            assert newer["result"]["content"] == picture
            assert peers[0].attachments is True
        finally:
            writer.close()

    asyncio.run(run())


# ---- one connection, served over a socket --------------------------------------


@contextlib.asynccontextmanager
async def _served(registry):
    """A connection served as 'serve_pipe' serves each one; yields the client's (reader, writer)."""
    loop = asyncio.get_running_loop()
    session = types.SimpleNamespace(emitter=events.EventEmitter())
    dispatcher = Dispatcher(registry)
    dispatch = Dispatch(dispatcher, session)
    stopped = []
    handle = service_win_pipe._connection_handler(
        dispatcher=dispatcher,
        dispatch=dispatch,
        session=session,
        connections=config_restart.Connections(),
        stop=lambda: stopped.append(True),
        restart=lambda: None,
        stopping=lambda: bool(stopped),
    )
    done = loop.create_future()

    async def handled(reader, writer):
        try:
            await handle(reader, writer)
        finally:
            done.set_result(None)

    ours, theirs = socket.socketpair()
    await loop.connect_accepted_socket(lambda: service_win_pipe._connection_protocol(handled), ours)
    reader, writer = await asyncio.open_connection(sock=theirs)
    try:
        yield reader, writer
    finally:
        writer.close()
        # Served to the end -- its requests answered or cancelled, its writer
        # closed -- before the loop goes.
        await asyncio.wait_for(done, TIMEOUT)
        dispatch.stop()


def test_a_request_s_events_arrive_in_order_before_its_answer_over_a_socket_too():
    # The rounds the Windows test makes, through the same handler: the events
    # come from the dispatch thread and go out on the loop, and the answer goes
    # out behind them.
    async def run():
        async with _served(REGISTRY) as (reader, writer):
            return await _rounds_on(reader, writer, 3)

    rounds = asyncio.run(run())
    assert len(rounds) == 3
    for lines, answer in rounds:
        assert lines == ["event %d" % i for i in range(EVENTS)]
        assert answer["result"] == {"done": True}


def test_a_queued_request_that_is_cancelled_is_answered_at_once_and_never_runs():
    entered, release = threading.Event(), threading.Event()
    ran = []

    def busy(session, params):
        entered.set()
        assert release.wait(TIMEOUT)
        return "done"

    async def run():
        loop = asyncio.get_running_loop()
        async with _served({"busy": busy, "quick": lambda s, p: ran.append(p)}) as (reader, writer):
            rendezvous.write_frame(writer, {"jsonrpc": "2.0", "id": 1, "method": "busy"})
            await writer.drain()
            assert await loop.run_in_executor(None, entered.wait, TIMEOUT)
            rendezvous.write_frame(writer, {"jsonrpc": "2.0", "id": 2, "method": "quick"})
            rendezvous.write_frame(writer, {"jsonrpc": "2.0", "method": "$/cancelRequest", "params": {"id": 2}})
            await writer.drain()
            cancelled = await asyncio.wait_for(rendezvous.read_frame(reader), TIMEOUT)
            release.set()
            finished = await asyncio.wait_for(rendezvous.read_frame(reader), TIMEOUT)
            return cancelled, finished

    try:
        cancelled, finished = asyncio.run(run())
    finally:
        release.set()
    assert cancelled["id"] == 2 and cancelled["error"]["code"] == REQUEST_CANCELLED
    assert finished == {"jsonrpc": "2.0", "id": 1, "result": "done"}
    assert ran == []


def test_a_cancellation_sent_as_a_request_is_answered_as_well():
    """The editor sends '$/cancelRequest' as a notification; a client that sends it with an id waits for an answer."""

    async def run():
        async with _served({}) as (reader, writer):
            rendezvous.write_frame(
                writer, {"jsonrpc": "2.0", "id": 7, "method": "$/cancelRequest", "params": {"id": 99}}
            )
            await writer.drain()
            return await asyncio.wait_for(rendezvous.read_frame(reader), TIMEOUT)

    assert asyncio.run(run()) == {"jsonrpc": "2.0", "id": 7, "result": None}


async def _writer_pair():
    """A 'PipeWriter' writing to a socket whose other end nobody reads, and that end."""
    loop = asyncio.get_running_loop()
    ours, theirs = socket.socketpair()
    connected = loop.create_future()

    def accepted(reader, writer):
        connected.set_result(writer)

    await loop.connect_accepted_socket(lambda: asyncio.StreamReaderProtocol(asyncio.StreamReader(), accepted), ours)
    return await asyncio.wait_for(connected, TIMEOUT), theirs


def test_the_pipe_writer_drops_a_client_that_takes_nothing():
    async def run():
        writer, theirs = await _writer_pair()
        told = []
        out = service_win_pipe.PipeWriter(writer, on_drop=told.append, timeout=0.3)
        try:
            out.put([b"x" * (32 * 1024 * 1024)])
            await out.sent(TIMEOUT)
            return out.dropped, told
        finally:
            await out.close(TIMEOUT)
            theirs.close()

    dropped, told = asyncio.run(run())
    assert dropped is not None and "accepted nothing" in dropped
    assert told == [dropped]


def test_the_pipe_writer_drops_a_client_that_lets_too_much_pile_up():
    async def run():
        writer, theirs = await _writer_pair()
        out = service_win_pipe.PipeWriter(writer, timeout=TIMEOUT, max_backlog=1024 * 1024)
        try:
            # One frame bigger than the bound is the answer the client asked
            # for; what piles up behind it is what is bounded.
            out.put([b"x" * (16 * 1024 * 1024)])
            out.put([b"y" * (200 * 1024)])
            first = out.dropped
            for _ in range(8):
                out.put([b"y" * (200 * 1024)])
            return first, out.dropped
        finally:
            await out.close(TIMEOUT)
            theirs.close()

    first, dropped = asyncio.run(run())
    assert first is None
    assert dropped is not None and "stopped reading" in dropped


def test_the_pipe_writer_sends_everything_in_order_to_a_client_that_reads():
    async def run():
        loop = asyncio.get_running_loop()
        writer, theirs = await _writer_pair()
        out = service_win_pipe.PipeWriter(writer, timeout=TIMEOUT)
        try:
            for n in range(300):
                out.put(framing.encode_message({"jsonrpc": "2.0", "method": "n", "params": n}))
            out.put(framing.encode_message({"jsonrpc": "2.0", "id": 1, "result": b"\x01" * 3000000}, True))
            stream = theirs.makefile("rb")
            theirs.settimeout(TIMEOUT)
            got = await loop.run_in_executor(None, lambda: [framing.read_message(stream) for _ in range(301)])
            await out.sent(TIMEOUT)
            return got, out.dropped
        finally:
            await out.close(TIMEOUT)
            theirs.close()

    got, dropped = asyncio.run(run())
    assert [m["params"] for m in got[:300]] == list(range(300))
    assert got[300]["result"] == b"\x01" * 3000000
    assert dropped is None
