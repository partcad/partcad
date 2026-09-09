#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The sandbox on a machine that is not this one.

Two things are worth pinning without a service to talk to. What the client
*sends* -- which is where the design decision lives, since the directories a
command needs are inferred from the command rather than named by the caller --
and what it does with the answer.

Nothing here provisions anything, because that is the whole point of the split:
the service owns the environment, and this says what it wants run.
"""

import os
import types

import pytest

from partcad import runtime, runtime_python_remote

IMAGE = "ghcr.io/x/solver:abc"


def _ctx(tmp_path, endpoint="127.0.0.1:5050"):
    return types.SimpleNamespace(
        user_config=types.SimpleNamespace(internal_state_dir=str(tmp_path / "state"), remote_sandbox=endpoint),
        root_path=str(tmp_path / "pkg"),
    )


def _runtime(tmp_path, **kwargs):
    return runtime_python_remote.RemotePythonRuntime(_ctx(tmp_path, **kwargs), "3.11", image=IMAGE)


class _Service:
    """The remote service, reduced to what it was asked."""

    def __init__(self, result=None):
        self.command = None
        self.params = None
        self.token = None
        self.result = result or {"stdout": None, "stderr": None, "exit_code": 0, "output_files": {}}

    def __call__(self, host, port, token=None):
        self.endpoint = "%s:%d" % (host, port)
        self.token = token
        return self

    def execute(self, command, params):
        self.command = command
        self.params = params
        return {"jsonrpc": "2.0", "id": 1, "result": self.result}


# --------------------------------------------------------------------------- #
# Which directories a command needs                                            #
# --------------------------------------------------------------------------- #


def test_a_script_brings_the_directory_it_lives_in(tmp_path):
    """A script imports its siblings; sending the one file it names is not enough."""
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "part.py").write_text("import helper\n")
    (package / "helper.py").write_text("")

    assert runtime_python_remote.input_dirs_for(["-u", str(package / "part.py")]) == [str(package)]


def test_an_argument_that_is_not_a_path_contributes_nothing(tmp_path):
    assert runtime_python_remote.input_dirs_for(["-c", "import sys", "--json"]) == []


def test_a_directory_argument_is_sent_whole(tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()
    assert runtime_python_remote.input_dirs_for([str(package)]) == [str(package)]


def test_a_directory_inside_another_is_not_sent_twice(tmp_path):
    """One answer for the far end's longest-prefix substitution, not two."""
    outer = tmp_path / "pkg"
    inner = outer / "sub"
    inner.mkdir(parents=True)
    (inner / "part.py").write_text("")

    assert runtime_python_remote.input_dirs_for([str(outer), str(inner / "part.py")]) == [str(outer)]


def test_the_working_directory_comes_too(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    assert runtime_python_remote.input_dirs_for(["-c", "pass"], cwd=str(work)) == [str(work)]


def test_a_system_path_is_never_sent():
    """'/usr/bin/python' must not pack '/usr/bin', and '/' least of all."""
    assert runtime_python_remote.input_dirs_for(["/usr", "/etc", "/"]) == []


# --------------------------------------------------------------------------- #
# What is sent                                                                 #
# --------------------------------------------------------------------------- #


def test_the_request_names_the_image_and_the_version(tmp_path, monkeypatch):
    """The service decides which container and which environment from these."""
    service = _Service()
    monkeypatch.setattr(runtime_python_remote, "RuntimeJsonRpcClient", service)

    _runtime(tmp_path).run(["-c", "pass"])

    assert service.params["image"] == IMAGE
    assert service.params["python_version"] == "3.11"


def test_the_command_carries_no_interpreter(tmp_path, monkeypatch):
    """The service prepends its own: the client never learns where it is."""
    service = _Service()
    monkeypatch.setattr(runtime_python_remote, "RuntimeJsonRpcClient", service)

    _runtime(tmp_path).run(["-c", "pass"])
    assert service.command == ["-c", "pass"]


def test_requirements_accumulate_and_travel_with_every_request(tmp_path, monkeypatch):
    """Nothing is installed here, so asking is a note to self until a request goes."""
    import asyncio

    service = _Service()
    monkeypatch.setattr(runtime_python_remote, "RuntimeJsonRpcClient", service)

    made = _runtime(tmp_path)
    asyncio.run(made.ensure_async("numpy==2.4.1"))
    asyncio.run(made.ensure_async("trimesh"))
    asyncio.run(made.ensure_async("numpy==2.4.1"))  # said twice, sent once

    made.run(["-c", "pass"])
    assert service.params["requirements"] == ["numpy==2.4.1", "trimesh"]


def test_stdin_is_encoded_the_way_the_container_reads_it(tmp_path, monkeypatch):
    """Base64, because the far end decodes base64 and does not complain if it is not."""
    import base64

    service = _Service()
    monkeypatch.setattr(runtime_python_remote, "RuntimeJsonRpcClient", service)

    _runtime(tmp_path).run(["-c", "pass"], stdin="a request")
    assert base64.b64decode(service.params["stdin"]).decode() == "a request"


# --------------------------------------------------------------------------- #
# What comes back                                                              #
# --------------------------------------------------------------------------- #


def test_an_output_file_is_written_where_the_caller_asked(tmp_path, monkeypatch):
    """The file was written over there, under a name of the container's choosing."""
    import base64

    wanted = str(tmp_path / "out.glb")
    service = _Service(
        result={
            "stdout": None,
            "stderr": None,
            "exit_code": 0,
            "output_files": {wanted: base64.b64encode(b"glTF").decode()},
        }
    )
    monkeypatch.setattr(runtime_python_remote, "RuntimeJsonRpcClient", service)

    exitcode, _, _ = _runtime(tmp_path).run(["-c", "pass"], output_files=[wanted])

    assert exitcode == 0
    with open(wanted, "rb") as f:
        assert f.read() == b"glTF"


def test_an_error_from_the_service_is_reported_rather_than_swallowed(tmp_path, monkeypatch):
    class _Broken(_Service):
        def execute(self, command, params):
            return {"jsonrpc": "2.0", "id": 1, "error": {"code": -32603, "message": "no such image"}}

    service = _Broken()
    monkeypatch.setattr(runtime_python_remote, "RuntimeJsonRpcClient", service)

    exitcode, _, stderr = _runtime(tmp_path).run(["-c", "pass"])
    assert exitcode != 0
    assert "no such image" in stderr


def test_an_answer_with_neither_result_nor_error_is_a_failure(tmp_path, monkeypatch):
    """Reading 'result' blind turned that into a KeyError several layers away."""

    class _Odd(_Service):
        def execute(self, command, params):
            return {"jsonrpc": "2.0", "id": 1}

    monkeypatch.setattr(runtime_python_remote, "RuntimeJsonRpcClient", _Odd())

    exitcode, _, stderr = _runtime(tmp_path).run(["-c", "pass"])
    assert exitcode != 0
    assert "without a result" in stderr


def test_no_answer_at_all_is_a_failure_that_says_so(tmp_path, monkeypatch):
    class _Silent(_Service):
        def execute(self, command, params):
            return None

    monkeypatch.setattr(runtime_python_remote, "RuntimeJsonRpcClient", _Silent())

    exitcode, _, stderr = _runtime(tmp_path).run(["-c", "pass"])
    assert exitcode != 0
    assert "no response" in stderr.lower()


# --------------------------------------------------------------------------- #
# Being told where the service is                                              #
# --------------------------------------------------------------------------- #


def test_without_a_service_the_sandbox_says_which_knob_is_missing(tmp_path):
    """There is no default: guessing at a service that runs commands is not on."""
    with pytest.raises(runtime.SandboxUnavailable, match="remoteSandbox"):
        runtime_python_remote.RemotePythonRuntime(_ctx(tmp_path, endpoint=None), "3.11", image=IMAGE)


@pytest.mark.parametrize("endpoint", ["127.0.0.1:", "127.0.0.1:nonsense", "5050"])
def test_an_endpoint_that_is_not_a_host_and_a_port_says_so(tmp_path, endpoint):
    """It is something a person typed, so it reaches here malformed.

    Without checking the port, that arrived as a ValueError traceback rather
    than as the sentence this method already has for it.
    """
    made = runtime_python_remote.RemotePythonRuntime(_ctx(tmp_path, endpoint=endpoint), "3.11", image=IMAGE)
    with pytest.raises(runtime.SandboxUnavailable, match="does not name a host and a port"):
        made._client()


def test_two_images_are_two_sandboxes(tmp_path):
    one = runtime_python_remote.RemotePythonRuntime(_ctx(tmp_path), "3.11", image="ghcr.io/x/a:1")
    two = runtime_python_remote.RemotePythonRuntime(_ctx(tmp_path), "3.11", image="ghcr.io/x/b:1")
    assert one.path != two.path


def test_it_asks_to_be_told_what_a_command_writes(tmp_path):
    """Inference covers what a command reads; nothing can infer what it writes."""
    assert _runtime(tmp_path).EXCHANGES_FILES is True
    assert os.path.basename(_runtime(tmp_path).path).startswith("pc-py-remote-")


# --------------------------------------------------------------------------- #
# The shared secret                                                            #
# --------------------------------------------------------------------------- #


def test_the_configured_token_reaches_the_client(tmp_path, monkeypatch):
    """The service refuses a reachable bind without one, so it has to travel."""
    service = _Service()
    monkeypatch.setattr(runtime_python_remote, "RuntimeJsonRpcClient", service)

    made = _runtime(tmp_path)
    made.ctx.user_config.remote_sandbox_token = "s3cret"
    made.run(["-c", "pass"])

    assert service.token == "s3cret"


def test_no_token_configured_sends_none(tmp_path, monkeypatch):
    """The loopback case, and the one nothing has to be set up for."""
    service = _Service()
    monkeypatch.setattr(runtime_python_remote, "RuntimeJsonRpcClient", service)

    _runtime(tmp_path).run(["-c", "pass"])

    assert service.token is None
