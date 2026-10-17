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
"""

import asyncio
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
    finally:
        transport.close()


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
