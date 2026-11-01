#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Which connection `json_rpc_client` sends a request down.

With real sockets and the real container service, in this process: what went
wrong was a connection the client kept, to a server that had stopped listening
and went on answering anyway.
"""

import sys
import threading

import pytest

from partcad_utils import container_service as service
from partcad_utils import json_rpc_client
from partcad_utils.json_rpc_client import RuntimeJsonRpcClient


class _Served(service.Server):
    """A container service that says when it has finished with a connection."""

    def __init__(self, address, token):
        handler = type("Handler", (service._Handler,), {"token": token, "store": None})
        super().__init__(address, handler)
        self.finished = threading.Event()

    def shutdown_request(self, request):
        super().shutdown_request(request)
        self.finished.set()


def _serve(port, token):
    server = _Served(("127.0.0.1", port), token)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _stop(server):
    server.shutdown()
    server.server_close()


def _echo(client, text):
    """What the server ``client`` reaches prints for ``text``, or the error it answered with."""
    answer = client.call("execute", {"command": ["python", "-c", "print(%r)" % text]}, timeout=30)
    if "error" in answer:
        return answer["error"]["message"]
    return bytes(answer["result"]["stdout"]).decode().strip()


@pytest.fixture(autouse=True)
def python_allowed(monkeypatch):
    monkeypatch.setattr(service, "ALLOWED_COMMANDS", {"python": sys.executable})
    json_rpc_client.close_sessions()


def test_a_port_published_again_is_not_reached_down_a_connection_to_the_server_before():
    """Docker publishing a container on a port an earlier server of this process had.

    The earlier one has stopped listening, but its thread still answers the
    connection the client kept to it. The new server's request must not go
    down that connection: it would be refused with the old server's token.
    """
    for _ in range(5):
        earlier = _serve(0, "earlier-token")
        port = earlier.server_address[1]
        assert _echo(RuntimeJsonRpcClient("127.0.0.1", port, token="earlier-token"), "earlier") == "earlier"
        _stop(earlier)
        try:
            later = _serve(port, "later-token")
        except OSError:
            # Another process took the port in between; try another.
            continue
        try:
            assert _echo(RuntimeJsonRpcClient("127.0.0.1", port, token="later-token"), "later") == "later"
        finally:
            _stop(later)
        return
    pytest.fail("Never got the same port back twice running")


def test_a_server_is_sent_requests_down_one_kept_connection():
    server = _serve(0, "token")
    try:
        client = RuntimeJsonRpcClient("127.0.0.1", server.server_address[1], token="token")
        for text in ("one", "two", "three"):
            assert _echo(client, text) == text
        assert not server.finished.is_set()
    finally:
        _stop(server)


def test_sessions_are_kept_per_server_and_only_so_many_of_them():
    url = "http://127.0.0.1:1"
    first = json_rpc_client._session(url, "a")
    assert json_rpc_client._session(url, "a") is first
    assert json_rpc_client._session(url, "b") is not first
    assert json_rpc_client._session("http://127.0.0.1:2", "a") is not first

    closed = []
    first.close = lambda: closed.append(first)
    for n in range(json_rpc_client.MAX_SESSIONS):
        json_rpc_client._session("http://127.0.0.1:%d" % (100 + n), None)
    assert closed == [first]
    assert json_rpc_client._session(url, "a") is not first


def test_closing_the_sessions_ends_what_the_server_was_doing_for_them():
    """What `tests/conftest.py` does after every test: no thread left answering a server that is gone."""
    server = _serve(0, "token")
    try:
        assert _echo(RuntimeJsonRpcClient("127.0.0.1", server.server_address[1], token="token"), "hi") == "hi"
        assert not server.finished.is_set()
        json_rpc_client.close_sessions()
        assert server.finished.wait(timeout=30)
    finally:
        _stop(server)
