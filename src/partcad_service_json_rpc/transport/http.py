#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Optional HTTP transport for the JSON-RPC service.

``POST /rpc`` carries JSON-RPC 2.0 request/response. The server-to-client
notification stream is delivered over Server-Sent Events at ``GET /events``.
There is no authentication yet (by design, for now). Requests are dispatched in
a worker thread so a long CAD operation does not block the event loop, and
events are marshalled back onto the loop thread-safely.

There are no attachments here (see ``partcad_utils.framing``): a file in an
answer is base64 text, as it always was over HTTP, which is what any HTTP client
of this already reads. ``framing.to_json`` is what writes it so.

**Nothing is encoded on the event loop.** The loop is every client's: an answer
carrying a forty-megabyte file used to be base64-encoded and dumped there, and
every other request and event stream waited for it. An answer is encoded on the
worker thread that produced it, and an event once, on the thread that emitted
it, however many subscribers it then goes to.

**Every event goes to every subscriber**, as it always has. Sending a request's
events to the client that made it alone would need two things this transport
does not have: a subscriber that says who it is (``GET /events`` takes nothing)
and a way to tell which request an event belongs to -- requests here run
concurrently, and the session has one sink for all of them. A subscriber that
stops reading is dropped rather than buffered for without limit, by the policy
the socket daemon applies to its connections (``transport.writer``).
"""

import asyncio
import collections
import contextlib
import sys

from aiohttp import web

from partcad_utils.framing import to_json

from ..rpc.dispatcher import PARSE_ERROR, Dispatcher
from .writer import MAX_BACKLOG, WRITE_TIMEOUT


class _Subscriber:
    """One ``GET /events`` stream: the events waiting for it, and whether it was dropped.

    Touched on the loop's thread only.
    """

    def __init__(self, max_backlog: int = MAX_BACKLOG):
        self.events: collections.deque = collections.deque()
        self.ready = asyncio.Event()
        self.backlog = 0
        self.max_backlog = max_backlog
        self.dropped = None

    def put(self, data: bytes) -> None:
        if self.dropped is not None:
            return
        if self.backlog + len(data) > self.max_backlog and self.events:
            self.drop("it stopped reading, and %d MB were waiting for it" % ((self.backlog + len(data)) >> 20))
            return
        self.events.append(data)
        self.backlog += len(data)
        self.ready.set()

    def drop(self, why: str) -> None:
        if self.dropped is None:
            self.dropped = why
            self.events.clear()
            self.backlog = 0
            self.ready.set()
            print("PartCAD service: dropped an event stream: %s" % why, file=sys.stderr, flush=True)


def build_app(session, registry) -> web.Application:
    """Build the aiohttp application serving the JSON-RPC service."""
    app = web.Application()
    # No traceback in HTTP error responses: this transport has no authentication
    # and can be bound to a non-loopback address, so a caller must not be able to
    # read server paths and stack frames by provoking an exception. The traceback
    # is still logged server-side.
    dispatcher = Dispatcher(registry, include_traceback=False)
    subscribers: set = set()
    state = {"loop": None}

    def sink(event, payload):
        # Encoded here, once, on the thread that emitted it -- not on the loop,
        # and not once per subscriber.
        data = ("data: %s\n\n" % to_json({"jsonrpc": "2.0", "method": event, "params": payload})).encode("utf-8")
        loop = state["loop"]
        for subscriber in list(subscribers):
            if loop is not None:
                with contextlib.suppress(RuntimeError):
                    # The loop has closed: nobody is listening any more.
                    loop.call_soon_threadsafe(subscriber.put, data)
            else:
                subscriber.put(data)

    session.emitter.set_sink(sink)

    def answer(body) -> bytes:
        # The request and the encoding of its answer, both on a worker thread.
        response = dispatcher.dispatch(body, session)
        return to_json(response if response is not None else {}).encode("utf-8")

    async def handle_rpc(request: web.Request) -> web.Response:
        loop = asyncio.get_running_loop()
        state["loop"] = loop
        try:
            body = await request.json()
        except Exception:  # pylint: disable=broad-except
            return web.json_response(
                {"jsonrpc": "2.0", "id": None, "error": {"code": PARSE_ERROR, "message": "Parse error"}}
            )
        encoded = await loop.run_in_executor(None, answer, body)
        # What 'web.json_response' would have sent, minus encoding it here.
        return web.Response(body=encoded, content_type="application/json", charset="utf-8")

    async def handle_events(request: web.Request) -> web.StreamResponse:
        state["loop"] = asyncio.get_running_loop()
        resp = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )
        await resp.prepare(request)
        subscriber = _Subscriber()
        subscribers.add(subscriber)
        try:
            while True:
                while not subscriber.events and subscriber.dropped is None:
                    subscriber.ready.clear()
                    await subscriber.ready.wait()
                if subscriber.dropped is not None:
                    break
                data = subscriber.events.popleft()
                subscriber.backlog -= len(data)
                try:
                    # A write waits for the client to take what is buffered; one
                    # that takes nothing for this long has stopped reading.
                    await asyncio.wait_for(resp.write(data), WRITE_TIMEOUT)
                except asyncio.TimeoutError:
                    subscriber.drop("it accepted nothing it was sent for %gs" % WRITE_TIMEOUT)
                    break
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            subscribers.discard(subscriber)
        return resp

    app.router.add_post("/rpc", handle_rpc)
    app.router.add_get("/events", handle_events)
    return app


def serve_http(session, registry, host: str, port: int) -> None:
    """Serve the JSON-RPC service over HTTP until interrupted.

    The session already has remote-log forwarding started by ``_build_session``;
    its ``log`` events are delivered to clients over the SSE channel.
    """
    web.run_app(build_app(session, registry), host=host, port=port, print=None)
