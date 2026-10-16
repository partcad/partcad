#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Serving the Windows named-pipe daemon: what a client sees on one connection.

The daemon dispatches each request on a worker thread, and a request emits
events while it runs. Those used to be written to the pipe from that thread,
through an asyncio transport that only the loop's own thread may write to, and
the two threads' writes raced: the editor's connections closed within
milliseconds of the first event, every time, on every Windows run of
"IDE (end to end)". Nothing short of a real pipe and a real event loop shows
that, so this serves one -- which only Windows can, and CI runs Windows.

The client does what the editor does: a quick request sent back to back with
one whose worker emits, so that the loop is still writing the first answer when
the first event arrives. And then the same again, on the same
connection, because the failure was a connection that did not survive.
"""

import asyncio
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

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="serves a real named pipe")

# Enough that the worker is still writing while the loop finishes each write
# before it: the race needs the two to overlap, and a handful rarely did.
EVENTS = 2000
TIMEOUT = 30


def _chatty(session, params):
    for i in range(EVENTS):
        session.emitter.info("event %d" % i)
    return {"done": True}


REGISTRY = {"rpc.discover": lambda session, params: {"methods": []}, "chatty": _chatty}


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


def test_a_request_s_events_arrive_in_order_before_its_answer_and_the_connection_stays(pipe):
    rounds = asyncio.run(_rounds(pipe, 3))

    assert len(rounds) == 3
    for lines, answer in rounds:
        assert lines == ["event %d" % i for i in range(EVENTS)]
        assert answer["result"] == {"done": True}
