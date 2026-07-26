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
"""

import asyncio
import json

from aiohttp import web

from ..rpc.dispatcher import PARSE_ERROR, Dispatcher


def build_app(session, registry) -> web.Application:
    """Build the aiohttp application serving the JSON-RPC service."""
    app = web.Application()
    dispatcher = Dispatcher(registry)
    subscribers: set = set()
    state = {"loop": None}

    def sink(event, payload):
        message = {"jsonrpc": "2.0", "method": event, "params": payload}
        loop = state["loop"]
        for q in list(subscribers):
            if loop is not None:
                loop.call_soon_threadsafe(q.put_nowait, message)
            else:
                q.put_nowait(message)

    session.emitter.set_sink(sink)

    async def handle_rpc(request: web.Request) -> web.Response:
        loop = asyncio.get_running_loop()
        state["loop"] = loop
        try:
            body = await request.json()
        except Exception:  # pylint: disable=broad-except
            return web.json_response(
                {"jsonrpc": "2.0", "id": None, "error": {"code": PARSE_ERROR, "message": "Parse error"}}
            )
        response = await loop.run_in_executor(None, dispatcher.dispatch, body, session)
        return web.json_response(response if response is not None else {})

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
        q: "asyncio.Queue" = asyncio.Queue()
        subscribers.add(q)
        try:
            while True:
                message = await q.get()
                await resp.write(("data: %s\n\n" % json.dumps(message)).encode("utf-8"))
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            subscribers.discard(q)
        return resp

    app.router.add_post("/rpc", handle_rpc)
    app.router.add_get("/events", handle_events)
    return app


def serve_http(session, registry, host: str, port: int) -> None:
    """Serve the JSON-RPC service over HTTP until interrupted."""
    session.start_log_stream()
    web.run_app(build_app(session, registry), host=host, port=port, print=None)
