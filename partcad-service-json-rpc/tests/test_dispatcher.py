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
