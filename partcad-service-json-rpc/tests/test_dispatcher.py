#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for the JSON-RPC 2.0 dispatcher."""

import pytest
from partcad_service_json_rpc.rpc import dispatcher as d
from partcad_service_json_rpc.rpc.dispatcher import Dispatcher, JsonRpcError


@pytest.fixture
def registry():
    def echo(session, params):
        return {"session": session, "params": params}

    def boom(session, params):
        raise RuntimeError("kaboom")

    def bad_params(session, params):
        raise JsonRpcError(d.INVALID_PARAMS, "need a name")

    return {"echo": echo, "boom": boom, "bad_params": bad_params}


def test_request_to_registered_method_returns_result_with_matching_id(registry):
    disp = Dispatcher(registry)
    resp = disp.dispatch({"jsonrpc": "2.0", "id": 5, "method": "echo", "params": {"a": 1}}, session="S")
    assert resp == {"jsonrpc": "2.0", "id": 5, "result": {"session": "S", "params": {"a": 1}}}


def test_missing_params_defaults_to_empty_dict(registry):
    disp = Dispatcher(registry)
    resp = disp.dispatch({"jsonrpc": "2.0", "id": 1, "method": "echo"}, session=None)
    assert resp["result"]["params"] == {}


def test_unknown_method_returns_method_not_found(registry):
    disp = Dispatcher(registry)
    resp = disp.dispatch({"jsonrpc": "2.0", "id": 2, "method": "nope"}, session=None)
    assert resp["error"]["code"] == d.METHOD_NOT_FOUND
    assert resp["id"] == 2
    assert "result" not in resp


def test_notification_without_id_returns_none_even_when_handler_runs(registry):
    disp = Dispatcher(registry)
    ran = []
    disp = Dispatcher({"note": lambda s, p: ran.append(p)})
    resp = disp.dispatch({"jsonrpc": "2.0", "method": "note", "params": {"x": 1}}, session=None)
    assert resp is None
    assert ran == [{"x": 1}]


def test_notification_to_unknown_method_returns_none(registry):
    disp = Dispatcher(registry)
    assert disp.dispatch({"jsonrpc": "2.0", "method": "nope"}, session=None) is None


def test_handler_jsonrpc_error_is_reported_with_its_code(registry):
    disp = Dispatcher(registry)
    resp = disp.dispatch({"jsonrpc": "2.0", "id": 3, "method": "bad_params"}, session=None)
    assert resp["error"]["code"] == d.INVALID_PARAMS
    assert resp["error"]["message"] == "need a name"


def test_handler_unexpected_exception_becomes_internal_error(registry):
    disp = Dispatcher(registry)
    resp = disp.dispatch({"jsonrpc": "2.0", "id": 4, "method": "boom"}, session=None)
    assert resp["error"]["code"] == d.INTERNAL_ERROR
    assert "kaboom" in resp["error"]["message"]


def test_request_without_method_is_invalid_request(registry):
    disp = Dispatcher(registry)
    resp = disp.dispatch({"jsonrpc": "2.0", "id": 8}, session=None)
    assert resp["error"]["code"] == d.INVALID_REQUEST


# ---- JSON-RPC 2.0 envelope conformance -------------------------------------
# A malformed envelope must be rejected *before* the handler runs, otherwise a
# non-conforming client silently gets real work done on an invalid request.


@pytest.mark.parametrize(
    "request_obj",
    [
        {"id": 1, "method": "echo", "params": {}},  # no "jsonrpc" member
        {"jsonrpc": "1.0", "id": 1, "method": "echo", "params": {}},  # wrong version
        {"jsonrpc": 2.0, "id": 1, "method": "echo", "params": {}},  # number, not "2.0"
        {"jsonrpc": "2.0", "id": 1, "method": 42},  # method is not a string
    ],
)
def test_malformed_envelope_is_rejected_without_calling_the_handler(request_obj):
    called = []
    disp = Dispatcher({"echo": lambda s, p: called.append(p)})
    resp = disp.dispatch(request_obj, session=None)
    assert resp["error"]["code"] == d.INVALID_REQUEST
    assert called == []


@pytest.mark.parametrize("params", ["a string", 42, True])
def test_scalar_params_are_rejected_as_invalid_params(params):
    called = []
    disp = Dispatcher({"echo": lambda s, p: called.append(p)})
    resp = disp.dispatch({"jsonrpc": "2.0", "id": 1, "method": "echo", "params": params}, session=None)
    assert resp["error"]["code"] == d.INVALID_PARAMS
    assert called == []


def test_positional_params_are_passed_through(registry):
    """An array is a valid JSON-RPC parameter structure and must reach the handler."""
    seen = []
    disp = Dispatcher({"echo": lambda s, p: seen.append(p) or p})
    resp = disp.dispatch({"jsonrpc": "2.0", "id": 1, "method": "echo", "params": [1, 2]}, session=None)
    assert seen == [[1, 2]]
    assert resp["result"] == [1, 2]


def test_malformed_notification_still_returns_nothing():
    """Errors on notifications must stay silent, even envelope errors."""
    disp = Dispatcher({"echo": lambda s, p: p})
    assert disp.dispatch({"method": "echo", "params": {}}, session=None) is None


# ---- traceback disclosure ---------------------------------------------------


def test_traceback_is_returned_to_local_transports_by_default(registry):
    disp = Dispatcher(registry)
    resp = disp.dispatch({"jsonrpc": "2.0", "id": 4, "method": "boom"}, session=None)
    assert "kaboom" in resp["error"]["data"]["traceback"]


def test_traceback_is_withheld_when_disabled(registry):
    """The HTTP transport builds its dispatcher this way: no auth, so no stack frames."""
    disp = Dispatcher(registry, include_traceback=False)
    resp = disp.dispatch({"jsonrpc": "2.0", "id": 4, "method": "boom"}, session=None)
    assert resp["error"]["code"] == d.INTERNAL_ERROR
    assert "kaboom" in resp["error"]["message"]
    assert "data" not in resp["error"]
