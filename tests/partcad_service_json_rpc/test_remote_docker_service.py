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
    """Environments that believe everything is already provisioned."""
    return remote_sandbox.Environments(lambda image, command: (0, "", ""))


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


def _post(url, payload):
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
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
