#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The proxy that runs containers on this machine for a client elsewhere.

No Docker here. What the service does that is worth pinning is that it forwards
a request unchanged to the container for the image the request names, releases
the container afterwards however the request ended, and answers a bad request
with something the caller can read. The container itself is
`partcad.remote_docker`'s business, and is tested there.
"""

import json
import threading
import types
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from partcad import remote_docker, remote_sandbox
from partcad_service_json_rpc import remote_docker_service as service


@pytest.fixture
def pool():
    """A pool whose containers are nothing at all."""
    started = []

    def start(image):
        started.append(image)
        container = types.SimpleNamespace()
        container.remove = lambda force=False: None
        return remote_docker.Lease(image, container, "127.0.0.1:5999")

    made = remote_docker.ContainerPool(start)
    made.started = started
    return made


@pytest.fixture
def environments():
    """Environments that believe everything is already provisioned.

    The version probe is answered, because creating one checks that the image
    carries the version that was asked for.
    """

    def run(image, command):
        if "sys.version_info" in " ".join(command):
            return 0, command[0].split("v-env-")[1].split("/")[0], ""
        return 0, "", ""

    return remote_sandbox.Environments(run)


@pytest.fixture
def upstream(monkeypatch):
    """What the container's own service would have been asked."""
    seen = {}

    class _Client:
        def __init__(self, host, port):
            seen["endpoint"] = "%s:%d" % (host, port)

        def execute(self, command, params):
            seen["command"] = command
            seen["params"] = params
            return {"jsonrpc": "2.0", "id": 1, "result": {"stdout": "ok", "stderr": "", "exit_code": 0}}

    monkeypatch.setattr(service, "RuntimeJsonRpcClient", _Client)
    return seen


# --------------------------------------------------------------------------- #
# Forwarding                                                                   #
# --------------------------------------------------------------------------- #


def test_the_request_reaches_the_container_unchanged(pool, environments, upstream):
    """A proxy that reshaped the request would be a second place to get it wrong."""
    result = service.execute(
        pool,
        environments,
        {
            "image": "ghcr.io/x/solver:abc",
            "python_version": "3.11",
            "command": ["python", "-c", "pass"],
            "stdin": "hello",
            "cwd": "/work",
            "input_dirs": {"/work": "<tar>"},
            "output_files": ["/work/out.glb"],
        },
    )

    assert result == {"stdout": "ok", "stderr": "", "exit_code": 0}
    # The caller sent no interpreter and never learns where the environment is;
    # the service puts its own in front.
    assert upstream["command"] == [remote_sandbox.interpreter_path("3.11"), "python", "-c", "pass"]
    assert upstream["params"]["stdin"] == "hello"
    assert upstream["params"]["cwd"] == "/work"
    assert upstream["params"]["input_dirs"] == {"/work": "<tar>"}
    assert upstream["params"]["output_files"] == ["/work/out.glb"]
    # 'image' is the proxy's own parameter and is not passed on: the container
    # it reached is the answer to it.
    assert "image" not in upstream["params"]


def test_the_image_decides_which_container(pool, environments, upstream):
    service.execute(pool, environments, {"image": "ghcr.io/x/a:1", "python_version": "3.11", "command": ["python"]})
    service.execute(pool, environments, {"image": "ghcr.io/x/b:1", "python_version": "3.11", "command": ["python"]})
    service.execute(pool, environments, {"image": "ghcr.io/x/a:1", "python_version": "3.11", "command": ["python"]})

    assert pool.started == ["ghcr.io/x/a:1", "ghcr.io/x/b:1"]


def test_the_container_is_released_when_the_request_ends(pool, environments, upstream):
    service.execute(
        pool, environments, {"image": "ghcr.io/x/solver:abc", "python_version": "3.11", "command": ["python"]}
    )
    assert [lease.in_flight for lease in pool.leases()] == [0]


def test_the_container_is_released_even_when_the_request_fails(pool, environments, monkeypatch):
    """Or a container that failed once would never be retired again."""

    class _Angry:
        def __init__(self, host, port):
            pass

        def execute(self, command, params):
            raise RuntimeError("the container said no")

    monkeypatch.setattr(service, "RuntimeJsonRpcClient", _Angry)

    with pytest.raises(RuntimeError, match="said no"):
        service.execute(
            pool, environments, {"image": "ghcr.io/x/solver:abc", "python_version": "3.11", "command": ["python"]}
        )
    assert [lease.in_flight for lease in pool.leases()] == [0]


# --------------------------------------------------------------------------- #
# Reading what the container said                                              #
# --------------------------------------------------------------------------- #


def _answers(monkeypatch, payload):
    """A container that replies with exactly ``payload``."""

    class _Client:
        def __init__(self, host, port):
            pass

        def execute(self, command, params):
            return payload

    monkeypatch.setattr(service, "RuntimeJsonRpcClient", _Client)


def test_what_a_command_wrote_is_decoded(pool, monkeypatch):
    """The container sends base64 inside a JSON-RPC envelope.

    Read off the envelope instead of out of it, 'exit_code' was never there --
    so every command, a pip install included, was reported as having succeeded
    with nothing to say, and 'Environments' recorded packages it had not
    installed.
    """
    import base64

    _answers(
        monkeypatch,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "exit_code": 2,
                "stdout": base64.b64encode(b"what it printed").decode(),
                "stderr": base64.b64encode(b"what went wrong").decode(),
            },
        },
    )

    exitcode, stdout, stderr = service._forward(pool, "ghcr.io/x/a:1", ["python"])

    assert exitcode == 2
    assert stdout == "what it printed"
    assert stderr == "what went wrong"


def test_a_container_that_refused_the_command_is_a_failure(pool, monkeypatch):
    """And says why: it is the sentence somebody has to read to fix it."""
    _answers(
        monkeypatch,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32000, "message": "Server error", "data": {"message": "'python3' is not allowed"}},
        },
    )

    exitcode, _, stderr = service._forward(pool, "ghcr.io/x/a:1", ["python3"])

    assert exitcode != 0
    assert "not allowed" in stderr


def test_an_error_from_the_container_is_not_returned_as_a_result(pool, environments, monkeypatch):
    """The client unwraps a result and reads 'stdout' out of it.

    Handing it an error object under that name turned a command the container
    refused into a malformed answer, several layers from the refusal.
    """
    _answers(monkeypatch, {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "no such interpreter"}})

    with pytest.raises(RuntimeError, match="no such interpreter"):
        service.execute(pool, environments, {"image": "ghcr.io/x/a:1", "python_version": "3.11", "command": ["python"]})


# --------------------------------------------------------------------------- #
# Bad requests                                                                 #
# --------------------------------------------------------------------------- #


def test_a_request_naming_no_image_says_what_is_missing(pool, environments):
    with pytest.raises(ValueError, match="image"):
        service.execute(pool, environments, {"command": ["python"]})


def test_a_request_with_no_command_says_so(pool, environments):
    with pytest.raises(ValueError, match="command"):
        service.execute(pool, environments, {"image": "ghcr.io/x/solver:abc", "python_version": "3.11"})


# --------------------------------------------------------------------------- #
# Over the wire                                                                #
# --------------------------------------------------------------------------- #


@pytest.fixture
def served(pool, environments):
    """The service, actually listening, on a port the OS chose."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), service.Handler)
    server.pool = pool
    server.environments = environments
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:%d/jsonrpc" % server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _post(url, payload, headers=None):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_a_call_over_http_reaches_the_container(served, upstream):
    status, answer = _post(
        served,
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "execute",
            "params": {"image": "ghcr.io/x/a:1", "python_version": "3.11", "command": ["python"]},
        },
    )

    assert status == 200
    assert answer["id"] == 7
    assert answer["result"]["exit_code"] == 0
    assert upstream["command"] == [remote_sandbox.interpreter_path("3.11"), "python"]


def test_an_unknown_method_is_an_error_the_caller_can_read(served):
    status, answer = _post(served, {"jsonrpc": "2.0", "id": 1, "method": "shutdown", "params": {}})

    assert status == 500
    assert "shutdown" in answer["error"]["message"]
    assert answer["id"] == 1


def test_a_failure_keeps_the_request_id(served):
    """So a client multiplexing several calls knows which one failed."""
    status, answer = _post(served, {"jsonrpc": "2.0", "id": 42, "method": "execute", "params": {}})

    assert status == 500
    assert answer["id"] == 42
    assert "image" in answer["error"]["message"]


# --------------------------------------------------------------------------- #
# Waiting for a container to be ready                                          #
# --------------------------------------------------------------------------- #


def test_a_service_that_answers_is_what_is_waited_for(served):
    """Any JSON counts, an error included.

    A published port is not an answer: Docker publishes it the moment the
    container starts and the service behind it binds seconds later, so the
    first request used to land in the gap and come back as "the container
    returned no response".
    """
    assert service._answering(served.split("//")[1].split("/")[0]) is True


def test_nothing_listening_is_not_an_answer():
    # Port 1 on loopback: privileged, and nothing this test could have started.
    assert service._answering("127.0.0.1:1") is False


# --------------------------------------------------------------------------- #
# Who may ask                                                                  #
# --------------------------------------------------------------------------- #
#
# A request names the image, the requirements and the command, and the sandbox
# interpreter runs whatever Python it is handed. On a reachable address that is
# a shell for anybody who can reach the port, so the service binds loopback by
# default and refuses anything wider without a shared secret.


@pytest.fixture
def guarded(pool, environments):
    """The same service, started with a token."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), service.Handler)
    server.pool = pool
    server.environments = environments
    server.token = "s3cret"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:%d/jsonrpc" % server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _execute(id=1):
    return {
        "jsonrpc": "2.0",
        "id": id,
        "method": "execute",
        "params": {"image": "ghcr.io/x/a:1", "python_version": "3.11", "command": ["python"]},
    }


def test_a_request_without_the_token_is_refused(guarded, upstream):
    status, answer = _post(guarded, _execute())

    assert status == 401
    assert "Authentication" in answer["error"]["message"]
    # And nothing ran: a refusal that had already started a container would be
    # the resource exhaustion the token exists to prevent. The fixture records a
    # command only when one reached it, so its absence is the assertion.
    assert "command" not in upstream


def test_a_request_with_the_token_is_served(guarded, upstream):
    status, answer = _post(guarded, _execute(7), headers={"Authorization": "Bearer s3cret"})

    assert status == 200
    assert answer["id"] == 7
    assert upstream["command"] == [remote_sandbox.interpreter_path("3.11"), "python"]


def test_the_wrong_token_is_refused(guarded, upstream):
    status, _ = _post(guarded, _execute(), headers={"Authorization": "Bearer s3cre"})
    assert status == 401
    assert "command" not in upstream


def test_another_scheme_is_not_a_token(guarded, upstream):
    status, _ = _post(guarded, _execute(), headers={"Authorization": "Basic s3cret"})
    assert status == 401
    assert "command" not in upstream


def test_a_refused_request_leaves_the_connection_usable(guarded, upstream):
    """The body has to be read even when it is not acted on.

    HTTP/1.1 keeps the connection alive, so a body left in the socket is the
    start of the next request as far as the parser is concerned -- and the
    client is then answering questions nobody asked.
    """
    assert _post(guarded, _execute())[0] == 401
    assert _post(guarded, _execute(2), headers={"Authorization": "Bearer s3cret"})[0] == 200


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.5", "::1", "localhost", "LOCALHOST"])
def test_a_loopback_address_needs_no_token(host):
    """The whole of 127.0.0.0/8, both families, and the name a person types."""
    assert service._loopback(host) is True


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "", "192.168.1.4", "example.com"])
def test_anything_reachable_is_not_loopback(host):
    """Including the empty host, which means every interface."""
    assert service._loopback(host) is False


def test_serving_a_reachable_address_without_a_token_is_refused(monkeypatch, caplog):
    """Refused at start-up, not warned about.

    Somebody who passed '--host 0.0.0.0' is not going to read the log of a
    service that came up and appeared to work.
    """
    started = []
    monkeypatch.setattr(service, "ThreadingHTTPServer", lambda *a, **k: started.append(a) or None)
    monkeypatch.delenv("PC_REMOTE_SANDBOX_TOKEN", raising=False)

    with caplog.at_level("ERROR"):
        assert service.main(["--host", "0.0.0.0"]) == 1

    assert not started
    assert "--token" in caplog.text
