#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What reaches a container, and how, in every way PartCAD sends it there -- with the container taken out.

The service that runs inside every container (`partcad_utils.container_service`)
is the standard library and nothing else, so it can run here: on a loopback
port, in this process, with this interpreter as the image's. Everything else is
the shipping code -- `partcad-service-remote-docker`'s handler on a port of its
own, the ``remote`` sandbox and the ``docker`` sandbox in ``upload`` mode as the
clients -- so what is pinned is what crosses each hop: frames rather than
base64, a directory sent once and named after that, a store that let go of
something being sent it again, and the two halves of a release skew with the
remote service.

The live suites (`tests/partcad_utils/test_containers_live.py`) run the same
code against real containers; they need a Docker daemon, and this does not.
"""

import asyncio
import base64
import json
import os
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from partcad import remote_docker, remote_sandbox, runtime, runtime_python_docker, runtime_python_remote
from partcad_service_json_rpc import remote_docker_service
from partcad_utils import container_files, container_service, containers, json_rpc_client

VERSION = "%d.%d" % sys.version_info[:2]
IMAGE = "ghcr.io/x/solver:abc"

# The service holds a shared flock around a sandbox command and runs the
# environment's interpreter through a link under its sandbox root: both POSIX,
# which is what a container is.
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the container service runs on Linux; flock is POSIX")


@pytest.fixture
def container(tmp_path, monkeypatch):
    """The service a container runs, on loopback, with an environment's interpreter where a sandbox puts one."""
    root = tmp_path / "pc-sandbox"
    root.mkdir()
    monkeypatch.setattr(container_service, "SANDBOX_ROOT", str(root))
    monkeypatch.setattr(remote_sandbox, "SANDBOX_ROOT", str(root))
    monkeypatch.setattr(container_service, "ALLOWED_COMMANDS", {"python": sys.executable})
    # What this process remembers the containers it talks to have, which must
    # not be another test's: a port can be handed out twice.
    monkeypatch.setattr(container_files, "_KNOWN", container_files.collections.OrderedDict())
    monkeypatch.setattr(json_rpc_client, "_PROTOCOLS", {})
    interpreter = remote_sandbox.interpreter_path(VERSION)
    os.makedirs(os.path.dirname(interpreter))
    os.symlink(sys.executable, interpreter)

    store = container_service.Store(str(tmp_path / "pc-store"))
    seen = []

    class Handler(container_service._Handler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length)
            if container_service.is_frame(self.headers.get("Content-Type")):
                payload = container_service.decode_frame(body)
                seen.append((payload["method"], "frames", sum(1 for _ in (payload["params"].get("blobs") or ()))))
            else:
                seen.append((json.loads(body)["method"], "json", 0))
            connection, self.rfile = self.rfile, _Replay(body)
            try:
                container_service._Handler.do_POST(self)
            finally:
                self.rfile = connection

    Handler.token = "container-token"
    Handler.store = store
    server = container_service.Server(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    made = types.SimpleNamespace(
        port=server.server_address[1], token="container-token", store=store, seen=seen, interpreter=interpreter
    )
    yield made
    server.shutdown()
    server.server_close()


class _Replay:
    """A body already read, read again by the handler it was read for."""

    def __init__(self, body):
        self.body = body

    def read(self, length):
        return self.body


class _Container:
    status = "running"
    attrs = {"State": {}}

    def reload(self):
        pass

    def remove(self, force=False):
        pass


class _Environments:
    """Every environment built already: provisioning is `test_remote_sandbox.py`'s."""

    def ensure(self, image, version, requirements=None):
        return remote_sandbox.interpreter_path(version)

    def forget(self, image):
        pass


def _pool(container):
    return remote_docker.ContainerPool(
        lambda image: remote_docker.Lease(image, _Container(), "127.0.0.1:%d" % container.port, container.token)
    )


@pytest.fixture
def service(container):
    """`partcad-service-remote-docker`, on loopback, holding the container above for every image."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), remote_docker_service.Handler)
    server.pool = _pool(container)
    server.environments = _Environments()
    server.token = None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "127.0.0.1:%d" % server.server_address[1]
    server.shutdown()
    server.server_close()


def _ctx(tmp_path, endpoint):
    return types.SimpleNamespace(
        user_config=types.SimpleNamespace(
            internal_state_dir=str(tmp_path / "state"),
            remote_sandbox=endpoint,
            remote_sandbox_token=None,
            use_docker_remote=True,
        ),
        root_path=str(tmp_path),
    )


@pytest.fixture
def package(tmp_path):
    """A script that imports a sibling, reads its request, and writes a file it was told the name of."""
    directory = tmp_path / "pkg"
    directory.mkdir()
    (directory / "helper.py").write_text("WORD = 'sibling'\n")
    (directory / "solve.py").write_text(
        "import os, sys\n"
        "sys.path.insert(0, os.path.dirname(__file__))\n"
        "import helper\n"
        "request = sys.stdin.buffer.read()\n"
        "open(sys.argv[1], 'wb').write(request)\n"
        "print(helper.WORD, len(request))\n"
    )
    return directory


def _solve(made, package, tmp_path, stdin=b"a request"):
    """Run the package's script through ``made``; what it printed, and what it wrote."""
    out = tmp_path / "out" / "result.bin"
    out.parent.mkdir(exist_ok=True)
    (out.parent / "keep").write_text("")  # a directory that holds something: the file comes back alone
    code, stdout, stderr = made.run([str(package / "solve.py"), str(out)], stdin=stdin, output_files=[str(out)])
    assert code == 0, stderr
    written = out.read_bytes()
    # Gone again, or the next command would name an existing file, and its
    # directory would be inferred to be one to send.
    out.unlink()
    return stdout.strip(), written


# --------------------------------------------------------------------------- #
# The remote sandbox, through the service                                      #
# --------------------------------------------------------------------------- #


def test_the_remote_sandbox_speaks_frames_through_the_service(service, container, package, tmp_path):
    made = runtime_python_remote.RemotePythonRuntime(_ctx(tmp_path, service), VERSION, image=IMAGE)

    assert _solve(made, package, tmp_path) == ("sibling 9", b"a request")
    # Both hops in frames: asked what the container lacks, then sent it.
    assert [(method, dialect) for method, dialect, _ in container.seen] == [
        ("missing", "frames"),
        ("execute", "frames"),
    ]
    assert container.seen[1][2] == 2

    container.seen.clear()
    assert _solve(made, package, tmp_path, b"again") == ("sibling 5", b"again")
    # The package the container has is named, not sent.
    assert container.seen == [("execute", "frames", 0)]


@pytest.mark.parametrize("size", [0, 1, 5 * 1024 * 1024])
def test_a_payload_crosses_both_hops_as_the_bytes_it_is(service, container, package, tmp_path, monkeypatch, size):
    """Large, empty and in between, byte for byte, and no bigger on the wire than it is."""
    made = runtime_python_remote.RemotePythonRuntime(_ctx(tmp_path, service), VERSION, image=IMAGE)
    payload = os.urandom(size)
    bodies = []
    original = json_rpc_client.RuntimeJsonRpcClient._post_frame

    def measured(self, parts, timeout):
        bodies.append(container_service.frame_length(parts))
        return original(self, parts, timeout)

    monkeypatch.setattr(json_rpc_client.RuntimeJsonRpcClient, "_post_frame", measured)
    printed, written = _solve(made, package, tmp_path, payload)
    assert printed == "sibling %d" % size
    assert written == payload
    # Two execute bodies, one per hop, each the payload and a few kilobytes of
    # header -- not the third more base64 made it, twice over.
    executes = sorted(bodies)[-2:]
    assert all(size <= body < size + 16 * 1024 for body in executes), (size, bodies)


def test_what_the_container_let_go_of_is_sent_again_through_the_service(service, container, package, tmp_path):
    made = runtime_python_remote.RemotePythonRuntime(_ctx(tmp_path, service), VERSION, image=IMAGE)
    _solve(made, package, tmp_path)
    # The container's store emptied -- trimmed, or the container replaced --
    # while this process still believes it has the package.
    import shutil

    shutil.rmtree(container.store.root)
    container.store._sizes = None
    container.seen.clear()

    assert _solve(made, package, tmp_path, b"after") == ("sibling 5", b"after")
    # Refused naming what it lacked, relayed by the service with its code, and
    # sent again with it.
    assert [(m, blobs) for m, _, blobs in container.seen] == [("execute", 0), ("execute", 2)]


def test_a_file_that_changed_while_it_was_being_sent_is_sent_as_it_is_now(service, container, package, tmp_path):
    made = runtime_python_remote.RemotePythonRuntime(_ctx(tmp_path, service), VERSION, image=IMAGE)
    made.once()
    request = container_files.Request(input_dirs=[str(package)], output_files=[str(tmp_path / "x")])
    request.params.update(made._what_is_wanted())
    # Hashed above, changed here, read to be sent below.
    (package / "helper.py").write_text("WORD = 'changed'\n")

    answer = made._client().run(
        [str(package / "solve.py"), str(tmp_path / "x")], request, route={"image": IMAGE}, timeout=60
    )
    assert answer["result"]["exit_code"] == 0, bytes(answer["result"]["stderr"])
    assert bytes(answer["result"]["stdout"]).split()[0] == b"changed"


# --------------------------------------------------------------------------- #
# A service and a client of different releases                                 #
# --------------------------------------------------------------------------- #


def test_a_service_from_before_frames_is_spoken_to_in_json(container, package, tmp_path):
    """Installed on another machine, on its own: it may well be older than the client. It has no `GET /`."""
    old = type(
        "OldHandler",
        (BaseHTTPRequestHandler,),
        {
            k: v
            for k, v in vars(remote_docker_service.Handler).items()
            if k not in ("do_GET", "__dict__", "__weakref__")
        },
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), old)
    server.pool = _pool(container)
    server.environments = _Environments()
    server.token = None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        made = runtime_python_remote.RemotePythonRuntime(
            _ctx(tmp_path, "127.0.0.1:%d" % server.server_address[1]), VERSION, image=IMAGE
        )
        assert _solve(made, package, tmp_path) == ("sibling 9", b"a request")
    finally:
        server.shutdown()
        server.server_close()
    # Forwarded in the dialect it came in, which the container still speaks.
    assert [(method, dialect) for method, dialect, _ in container.seen] == [("execute", "json")]


def test_a_client_from_before_frames_is_served_by_this_service(service, container, package, tmp_path):
    """What an older `RemotePythonRuntime` sends: base64, and a gzipped tar of the package."""
    import requests

    out = str(tmp_path / "result.bin")
    params = {
        "stdin": base64.b64encode(b"old").decode(),
        "cwd": None,
        "input_files": {},
        "output_files": [out],
        "input_dirs": {str(package): container_service.pack_directory(str(package))},
        "image": IMAGE,
        "python_version": VERSION,
        "requirements": [],
    }
    response = requests.post(
        "http://%s/jsonrpc" % service,
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "execute",
            "params": dict(params, command=[str(package / "solve.py"), out]),
        },
        timeout=60,
    )
    answer = response.json()
    assert answer["id"] == 4
    assert base64.b64decode(answer["result"]["stdout"]).strip() == b"sibling 3"
    assert base64.b64decode(answer["result"]["output_files"][out]) == b"old"
    assert [(method, dialect) for method, dialect, _ in container.seen] == [("execute", "json")]


def test_the_service_says_what_it_speaks_without_being_asked_for_a_token(container):
    server = ThreadingHTTPServer(("127.0.0.1", 0), remote_docker_service.Handler)
    server.pool = _pool(container)
    server.environments = _Environments()
    server.token = "s3cret"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = json_rpc_client.RuntimeJsonRpcClient("127.0.0.1", server.server_address[1])
        assert client.protocol() == container_service.PROTOCOL
    finally:
        server.shutdown()
        server.server_close()


def test_a_service_that_cannot_be_reached_is_asked_again_rather_than_remembered_as_old(monkeypatch):
    monkeypatch.setattr(json_rpc_client, "_PROTOCOLS", {})
    import socket

    with socket.socket() as probe:
        # Bound and not listening: nothing answers on it while it is held.
        probe.bind(("127.0.0.1", 0))
        client = json_rpc_client.RuntimeJsonRpcClient("127.0.0.1", probe.getsockname()[1])
        assert client.protocol(timeout=5) is None
    assert json_rpc_client._PROTOCOLS == {}


# --------------------------------------------------------------------------- #
# The docker sandbox in upload mode                                            #
# --------------------------------------------------------------------------- #


def test_the_docker_upload_sandbox_takes_the_same_path_without_the_hop(container, package, tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "docker_available", lambda: True)
    monkeypatch.setattr(runtime_python_docker, "_LOCAL", (_pool(container), _Environments()))
    made = runtime_python_docker.DockerUploadPythonRuntime(_ctx(tmp_path, None), VERSION, image=IMAGE)

    assert _solve(made, package, tmp_path) == ("sibling 9", b"a request")
    assert [(m, d) for m, d, _ in container.seen] == [("missing", "frames"), ("execute", "frames")]
    container.seen.clear()
    assert _solve(made, package, tmp_path, b"xy") == ("sibling 2", b"xy")
    assert container.seen == [("execute", "frames", 0)]


def test_an_endpoint_in_upload_mode_sends_a_directory_once(container, package, tmp_path):
    """KiCad's, a plugin's, `pc ide open`'s: an `Endpoint` straight to the container."""
    spec = containers.ContainerSpec(role="test", image=IMAGE, mode=containers.UPLOAD)
    endpoint = containers.Endpoint(
        name="partcad-test", spec=spec, container=None, host="127.0.0.1", port=container.port, token=container.token
    )
    out = str(tmp_path / "out.bin")
    for stdin in (b"one", b"two"):
        code, stdout, stderr = endpoint.run(
            ["python", str(package / "solve.py"), out], stdin=stdin, input_dirs=[str(package)], output_files=[out]
        )
        assert (code, stdout.strip()) == (0, "sibling 3"), stderr
        with open(out, "rb") as f:
            assert f.read() == stdin
    assert [(m, blobs) for m, _, blobs in container.seen] == [("missing", 0), ("execute", 2), ("execute", 0)]


# --------------------------------------------------------------------------- #
# Off the event loop                                                           #
# --------------------------------------------------------------------------- #


def test_the_remote_sandbox_does_its_file_work_on_a_thread_and_resolves_its_request_on_the_loop(tmp_path, monkeypatch):
    """Walking, hashing and writing back are a package's worth of file I/O; the loop has other parts to render."""
    made = runtime_python_remote.RemotePythonRuntime(_ctx(tmp_path, "127.0.0.1:1"), VERSION, image=IMAGE)
    seen = {}

    def send(cmd, stdin, cwd, timeout, *rest):
        seen["send"] = threading.current_thread()
        seen["stdin"] = stdin
        return 0, "", ""

    def request():
        seen["request"] = threading.current_thread()
        return b"serialized"

    monkeypatch.setattr(made, "_send", send)

    async def main():
        seen["loop"] = threading.current_thread()
        return await made.run_async(["x.py"], request)

    assert asyncio.run(main()) == (0, "", "")
    assert seen["request"] is seen["loop"]
    assert seen["send"] is not seen["loop"]
    assert seen["stdin"] == b"serialized"


def test_an_endpoint_runs_the_whole_command_on_a_thread(monkeypatch):
    spec = containers.ContainerSpec(role="test", image=IMAGE, mode=containers.UPLOAD)
    endpoint = containers.Endpoint(name="t", spec=spec, container=None, host="127.0.0.1", port=1, token=None)
    seen = {}

    def run(*args, **kwargs):
        seen["run"] = threading.current_thread()
        return 0, "", ""

    monkeypatch.setattr(endpoint, "run", run)

    async def main():
        seen["loop"] = threading.current_thread()
        return await endpoint.run_async(["python"], stdin=b"x")

    assert asyncio.run(main()) == (0, "", "")
    assert seen["run"] is not seen["loop"]
