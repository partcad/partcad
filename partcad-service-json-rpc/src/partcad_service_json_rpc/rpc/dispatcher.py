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

import logging
import traceback
from typing import Any, Callable, Mapping, Optional

_logger = logging.getLogger(__name__)

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

    def __init__(self, registry: Mapping[str, Handler], include_traceback: bool = True):
        self._registry = registry
        # Whether an unexpected handler exception returns its traceback to the
        # caller. True for the local transports (stdio/socket/pipe), whose
        # client is the user's own CLI or IDE and for whom it is a debugging
        # aid; the HTTP transport passes False, since it has no authentication
        # and may be bound to a non-loopback address. The traceback is logged
        # server-side either way, so nothing is lost.
        self._include_traceback = include_traceback

    def dispatch(self, request: Any, session: Any) -> Optional[dict]:
        """Process one parsed request; return a response dict or None.

        Notifications (requests without an ``id``) never produce a response,
        even on error, per the JSON-RPC 2.0 specification.
        """
        is_notification = not isinstance(request, dict) or "id" not in request
        request_id = request.get("id") if isinstance(request, dict) else None

        try:
            # Validate the envelope before dispatching: JSON-RPC 2.0 requires
            # the "jsonrpc": "2.0" member, a string "method", and - when
            # present - "params" to be a structured value (object or array).
            if not isinstance(request, dict) or "method" not in request:
                raise JsonRpcError(INVALID_REQUEST, "Invalid Request")
            if request.get("jsonrpc") != "2.0":
                raise JsonRpcError(INVALID_REQUEST, "Invalid Request: expected 'jsonrpc': '2.0'")
            if not isinstance(request["method"], str):
                raise JsonRpcError(INVALID_REQUEST, "Invalid Request: 'method' must be a string")
            if "params" in request and not isinstance(request["params"], (dict, list)):
                raise JsonRpcError(INVALID_PARAMS, "Invalid params: expected an object or an array")

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
            detail = traceback.format_exc()
            method_name = request.get("method") if isinstance(request, dict) else None
            _logger.error("Unhandled error in JSON-RPC method %r: %s", method_name, detail)
            if is_notification:
                return None
            error = {"code": INTERNAL_ERROR, "message": str(e) or e.__class__.__name__}
            if self._include_traceback:
                error["data"] = {"traceback": detail}
            return {"jsonrpc": "2.0", "id": request_id, "error": error}

        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
