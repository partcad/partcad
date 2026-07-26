#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A minimal, transport-agnostic JSON-RPC 2.0 dispatcher.

The dispatcher turns a parsed request object into a response object (or
``None`` for notifications). It is deliberately independent of the transport:
stdio, HTTP, and the tests all feed it plain dicts. Handlers are looked up in a
registry and called as ``handler(session, params)``.
"""

import traceback
from typing import Any, Callable, Mapping, Optional

# Standard JSON-RPC 2.0 error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

Handler = Callable[[Any, Any], Any]


class JsonRpcError(Exception):
    """An error a handler can raise to control the JSON-RPC error response."""

    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def to_object(self) -> dict:
        obj = {"code": self.code, "message": self.message}
        if self.data is not None:
            obj["data"] = self.data
        return obj


class Dispatcher:
    """Routes JSON-RPC requests to handlers in a registry."""

    def __init__(self, registry: Mapping[str, Handler]):
        self._registry = registry

    def dispatch(self, request: Any, session: Any) -> Optional[dict]:
        """Process one parsed request; return a response dict or None.

        Notifications (requests without an ``id``) never produce a response,
        even on error, per the JSON-RPC 2.0 specification.
        """
        is_notification = not isinstance(request, dict) or "id" not in request
        request_id = request.get("id") if isinstance(request, dict) else None

        try:
            if not isinstance(request, dict) or "method" not in request:
                raise JsonRpcError(INVALID_REQUEST, "Invalid Request")

            method = request["method"]
            handler = self._registry.get(method)
            if handler is None:
                raise JsonRpcError(METHOD_NOT_FOUND, f"Method not found: {method}")

            params = request.get("params", {})
            result = handler(session, params)
        except JsonRpcError as e:
            if is_notification:
                return None
            return {"jsonrpc": "2.0", "id": request_id, "error": e.to_object()}
        except Exception as e:  # pylint: disable=broad-except
            if is_notification:
                return None
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": INTERNAL_ERROR,
                    "message": str(e) or e.__class__.__name__,
                    "data": {"traceback": traceback.format_exc()},
                },
            }

        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
