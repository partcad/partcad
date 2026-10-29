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

import base64
import os
import types

import pytest

from partcad import runtime, runtime_python_remote
from partcad_utils import container_files, container_service

IMAGE = "ghcr.io/x/solver:abc"


def _ctx(tmp_path, endpoint="127.0.0.1:5050"):
    return types.SimpleNamespace(
        user_config=types.SimpleNamespace(internal_state_dir=str(tmp_path / "state"), remote_sandbox=endpoint),
        root_path=str(tmp_path / "pkg"),
    )


def _runtime(tmp_path, **kwargs):
    return runtime_python_remote.RemotePythonRuntime(_ctx(tmp_path, **kwargs), "3.11", image=IMAGE)


class _Service:
    """The remote service, reduced to what it was asked: one of this release, which takes frames."""

    def __init__(self, result=None):
        self.command = None
        self.params = None
        self.token = None
        self.scheme = None
        self.asked = []
        self.result = result or {"stdout": b"", "stderr": b"", "exit_code": 0, "output_files": {}}

    def __call__(self, host, port, token=None, scheme="http"):
        self.endpoint = "%s:%d" % (host, port)
        self.token = token
        self.scheme = scheme
        return self

    def protocol(self):
        return container_service.PROTOCOL

    def call(self, method, params, timeout=None):
        self.asked.append(method)
        if method == "missing":
            return {"jsonrpc": "2.0", "id": 1, "result": {"missing": list(params["digests"])}}
        self.command = params["command"]
        self.params = params
        return {"jsonrpc": "2.0", "id": 1, "result": self.result}

    def run(self, command, request, timeout=None, route=None):
        self.route = route
        return container_files.execute(self.call, ("test", id(self)), command, request, timeout=timeout, route=route)


class _OldService(_Service):
    """A service of a release from before frames: no `GET /`, and the JSON dialect."""

    def protocol(self):
        return 1

    def call(self, method, params, timeout=None):
        raise AssertionError("a service that predates frames was sent one")

    def execute(self, command, params, timeout=None):
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


def test_a_filesystem_root_is_never_sent():
    """The same guard, asked in a way that is true on every platform.

    The names in `NEVER_SEND` are POSIX, so on Windows the test above only
    passes by accident -- `/usr` and `/etc` resolve to directories that do not
    exist and are dropped for that reason. `/` is the one that does resolve:
    to `D:\\` on a runner, a root the set does not name. That is how a whole
    drive became eligible to be packed and sent, and this is the case that
    says so wherever it runs.
    """
    assert runtime_python_remote.input_dirs_for([os.path.abspath(os.sep)]) == []


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
    # The base stack first, as every sandbox installs it, then what was asked
    # for -- each once.
    from partcad import runtime_python

    sent = service.params["requirements"]
    base = runtime_python.base_requirements(made.version)
    assert sent[-2:] == ["numpy==2.4.1", "trimesh"]
    assert [r for r in sent if r in base] == base
    assert len(sent) == len(set(sent))


def test_stdin_travels_as_the_bytes_it_is(tmp_path, monkeypatch):
    """Not base64: a wrapper's request is a frame of raw payloads, and base64 was a third more of it to send."""
    service = _Service()
    monkeypatch.setattr(runtime_python_remote, "RuntimeJsonRpcClient", service)

    _runtime(tmp_path).run(["-c", "pass"], stdin="a request")
    assert bytes(service.params["stdin"]) == b"a request"


def test_a_directory_travels_by_content_and_what_the_service_lacks_with_it(tmp_path, monkeypatch):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "part.py").write_text("import helper\n")
    (package / "helper.py").write_text("")
    service = _Service()
    monkeypatch.setattr(runtime_python_remote, "RuntimeJsonRpcClient", service)

    _runtime(tmp_path).run(["-u", str(package / "part.py")])

    tree = service.params["input_trees"][str(package)]
    assert [name for name, _digest, _mode in tree["files"]] == ["helper.py", "part.py"]
    # Asked first, about the image the command runs in, and sent what it said
    # it lacked -- here, everything.
    assert service.asked == ["missing", "execute"]
    assert service.route == {"image": IMAGE}
    assert set(service.params["blobs"]) == {digest for _name, digest, _mode in tree["files"]}
    assert "input_dirs" not in service.params


def test_a_service_from_before_frames_is_sent_json(tmp_path, monkeypatch):
    """It runs on another machine and is installed there on its own: an older one is still a service.

    Base64, because the far end decodes base64 and does not complain if it is not.
    """
    service = _OldService()
    monkeypatch.setattr(runtime_python_remote, "RuntimeJsonRpcClient", service)
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "part.py").write_text("")

    _runtime(tmp_path).run(["-c", "pass", str(package / "part.py")], stdin="a request")

    assert base64.b64decode(service.params["stdin"]).decode() == "a request"
    assert service.params["input_dirs"][str(package)] == container_service.pack_directory(str(package))
    assert service.params["image"] == IMAGE
    assert service.command == ["-c", "pass", str(package / "part.py")]


def test_an_older_services_answer_is_read_as_it_was(tmp_path, monkeypatch):
    wanted = str(tmp_path / "out.glb")
    (tmp_path / "already-here.txt").write_text("", encoding="utf-8")
    service = _OldService(
        result={
            "stdout": base64.b64encode(b"said").decode(),
            "stderr": None,
            "exit_code": 0,
            "output_files": {wanted: base64.b64encode(b"glTF").decode()},
        }
    )
    monkeypatch.setattr(runtime_python_remote, "RuntimeJsonRpcClient", service)

    assert _runtime(tmp_path).run(["-c", "pass"], output_files=[wanted]) == (0, "said", "")
    with open(wanted, "rb") as f:
        assert f.read() == b"glTF"


@pytest.mark.parametrize("older", [False, True], ids=["frames", "json"])
def test_a_wrappers_frame_crosses_as_the_bytes_it_is_both_ways(tmp_path, monkeypatch, older):
    """A Python wrapper is asked in a frame and answers in one, its payloads raw (see 'shape_envelope.serialize').

    So its standard output comes back as the bytes it is, in either dialect of
    the service (see 'process_output.answer'): decoded as text, as what a
    command prints is, every byte of a payload that was not UTF-8 was lost, and
    the answer with it. The same '_answer' reads what the 'docker' sandbox in
    'upload' mode is answered.
    """
    from partcad import shape_envelope

    request = shape_envelope.serialize({"name": "//pkg:p", "blob": b"\x00\xff"})
    answer = {
        "success": True,
        "shape": {"name": "p", "label": "p", shape_envelope.KEY_BREP: b"\x28\xb5\x2f\xfd\xff\x00"},
    }
    printed = b"progress, which is not the answer\n" + shape_envelope.serialize(answer)
    if older:
        service = _OldService(result={"stdout": base64.b64encode(printed).decode(), "stderr": None, "exit_code": 0})
    else:
        service = _Service(result={"stdout": printed, "stderr": b"", "exit_code": 0, "output_files": {}})
    monkeypatch.setattr(runtime_python_remote, "RuntimeJsonRpcClient", service)

    exitcode, stdout, stderr = _runtime(tmp_path).run(["-c", "pass"], stdin=request)

    sent = base64.b64decode(service.params["stdin"]) if older else bytes(service.params["stdin"])
    assert sent == request
    assert (exitcode, stderr) == (0, "")
    assert stdout == printed
    assert shape_envelope.deserialize(stdout) == answer


# --------------------------------------------------------------------------- #
# What comes back                                                              #
# --------------------------------------------------------------------------- #


def test_an_output_file_is_written_where_the_caller_asked(tmp_path, monkeypatch):
    """The file was written over there, under a name of the container's choosing."""
    # Into a directory that holds something already, which a file comes back
    # to alone (see 'outputs_for').
    (tmp_path / "already-here.txt").write_text("", encoding="utf-8")
    wanted = str(tmp_path / "out.glb")
    service = _Service(
        result={
            "stdout": b"",
            "stderr": b"",
            "exit_code": 0,
            "output_files": {wanted: b"glTF"},
        }
    )
    monkeypatch.setattr(runtime_python_remote, "RuntimeJsonRpcClient", service)

    exitcode, _, _ = _runtime(tmp_path).run(["-c", "pass"], output_files=[wanted])

    assert exitcode == 0
    with open(wanted, "rb") as f:
        assert f.read() == b"glTF"


def test_an_output_directory_comes_back_whole_where_the_caller_asked(tmp_path, monkeypatch):
    """For a command whose results are whatever it wrote into a directory -- a
    simulation plugin's pictures -- rather than a file it was told the name of."""
    written = tmp_path / "over-there"
    written.mkdir()
    (written / "snapshot-after.png").write_bytes(b"PNG")
    wanted = tmp_path / "run"
    wanted.mkdir()
    (wanted / "scene.xml").write_text("<mujoco/>", encoding="utf-8")
    elsewhere = str(tmp_path / "not-asked-for")
    back = container_service.tree_back(str(written))
    service = _Service(
        result={
            "stdout": b"",
            "stderr": b"",
            "exit_code": 0,
            "output_files": {},
            "output_dirs": {str(wanted): back, elsewhere: back},
        }
    )
    monkeypatch.setattr(runtime_python_remote, "RuntimeJsonRpcClient", service)

    exitcode, _, _ = _runtime(tmp_path).run(["-c", "pass"], output_dirs=[str(wanted)])

    assert exitcode == 0
    assert service.params["output_dirs"] == [str(wanted)]
    assert (wanted / "snapshot-after.png").read_bytes() == b"PNG"
    # What was there already is left alone, and a directory nobody asked for
    # is not written.
    assert (wanted / "scene.xml").exists()
    assert not os.path.exists(elsewhere)


def test_a_file_written_into_an_empty_directory_comes_back_with_what_was_written_beside_it(tmp_path, monkeypatch):
    """A world's meshes are written next to the world, named after it; sent back alone, it points at nothing."""
    run = tmp_path / "run"
    run.mkdir()
    wanted = run / "scene.world"
    over_there = tmp_path / "over-there"
    (over_there / "scene_meshes").mkdir(parents=True)
    (over_there / "scene.world").write_text("<sdf/>", encoding="utf-8")
    (over_there / "scene_meshes" / "bottom.stl").write_bytes(b"solid")
    service = _Service(
        result={
            "stdout": b"",
            "stderr": b"",
            "exit_code": 0,
            "output_files": {},
            "output_dirs": {str(run): container_service.tree_back(str(over_there))},
        }
    )
    monkeypatch.setattr(runtime_python_remote, "RuntimeJsonRpcClient", service)

    exitcode, _, _ = _runtime(tmp_path).run(["-c", "pass", str(wanted)], output_files=[str(wanted)])

    assert exitcode == 0
    assert service.params["output_dirs"] == [str(run)]
    assert str(wanted) not in service.params.get("output_files", [])
    assert wanted.read_text(encoding="utf-8") == "<sdf/>"
    assert (run / "scene_meshes" / "bottom.stl").read_bytes() == b"solid"


def test_a_file_comes_back_alone_into_a_directory_that_holds_anything_or_is_sent(tmp_path):
    """Somebody's directory is not packed and written back; nor is the package the command reads."""
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "theirs.txt").write_text("", encoding="utf-8")
    package = tmp_path / "package"
    package.mkdir()
    fresh = tmp_path / "fresh"
    missing = tmp_path / "not-there-yet"
    fresh.mkdir()

    files, directories = runtime_python_remote.outputs_for(
        [str(occupied / "a.stl"), str(package / "b.stl"), str(fresh / "c.stl"), str(missing / "d.stl")],
        None,
        [str(package)],
    )

    assert files == [str(occupied / "a.stl"), str(package / "b.stl")]
    assert directories == [str(fresh), str(missing)]


def test_two_files_in_one_fresh_directory_bring_it_back_once(tmp_path):
    files, directories = runtime_python_remote.outputs_for(
        [str(tmp_path / "run" / "a.world"), str(tmp_path / "run" / "b.world")], [str(tmp_path / "run")], []
    )
    assert files == []
    assert directories == [str(tmp_path / "run")]


def test_a_command_that_asks_for_no_directory_sends_no_such_field(tmp_path, monkeypatch):
    """So that every other request a container is sent stays exactly as it was."""
    service = _Service()
    monkeypatch.setattr(runtime_python_remote, "RuntimeJsonRpcClient", service)

    _runtime(tmp_path).run(["-c", "pass"])

    assert "output_dirs" not in service.params


def test_a_command_that_printed_nothing_reports_empty_strings(tmp_path, monkeypatch):
    """As a process run here does: a CadQuery part measures its stderr, and None has no length."""
    service = _Service()
    monkeypatch.setattr(runtime_python_remote, "RuntimeJsonRpcClient", service)

    exitcode, stdout, stderr = _runtime(tmp_path).run(["-c", "pass"])
    assert (exitcode, stdout, stderr) == (0, "", "")


def test_an_error_from_the_service_is_reported_rather_than_swallowed(tmp_path, monkeypatch):
    class _Broken(_Service):
        def call(self, method, params, timeout=None):
            return {"jsonrpc": "2.0", "id": 1, "error": {"code": -32603, "message": "no such image"}}

    service = _Broken()
    monkeypatch.setattr(runtime_python_remote, "RuntimeJsonRpcClient", service)

    exitcode, _, stderr = _runtime(tmp_path).run(["-c", "pass"])
    assert exitcode != 0
    assert "no such image" in stderr


def test_an_answer_with_neither_result_nor_error_is_a_failure(tmp_path, monkeypatch):
    """Reading 'result' blind turned that into a KeyError several layers away."""

    class _Odd(_Service):
        def call(self, method, params, timeout=None):
            return {"jsonrpc": "2.0", "id": 1}

    monkeypatch.setattr(runtime_python_remote, "RuntimeJsonRpcClient", _Odd())

    exitcode, _, stderr = _runtime(tmp_path).run(["-c", "pass"])
    assert exitcode != 0
    assert "without a result" in stderr


def test_no_answer_at_all_is_a_failure_that_says_so(tmp_path, monkeypatch):
    class _Silent(_Service):
        def call(self, method, params, timeout=None):
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


# --------------------------------------------------------------------------- #
# What may cross a network                                                     #
# --------------------------------------------------------------------------- #


def test_a_remote_host_may_not_be_reached_in_the_clear(tmp_path, monkeypatch):
    """Every request carries the shared secret and the package's own source.

    Plain HTTP carries both where anybody on the path can read them, so a
    deployment that has not got as far as TLS is told so rather than having its
    token shipped across a network on its behalf.
    """
    service = _Service()
    monkeypatch.setattr(runtime_python_remote, "RuntimeJsonRpcClient", service)

    made = _runtime(tmp_path, endpoint="build-farm.example:5050")
    with pytest.raises(runtime.SandboxUnavailable, match="in the clear"):
        made.run(["-c", "pass"])


def test_a_remote_host_over_https_is_allowed(tmp_path, monkeypatch):
    """Which is the deployment behind a TLS-terminating proxy."""
    service = _Service()
    monkeypatch.setattr(runtime_python_remote, "RuntimeJsonRpcClient", service)

    _runtime(tmp_path, endpoint="https://build-farm.example:5050").run(["-c", "pass"])

    assert service.endpoint == "build-farm.example:5050"
    assert service.scheme == "https"


def test_loopback_stays_plain(tmp_path, monkeypatch):
    """A container on this machine, or the near end of a tunnel.

    Neither is anybody else's business, and a certificate between a process and
    its own container would secure nothing.
    """
    service = _Service()
    monkeypatch.setattr(runtime_python_remote, "RuntimeJsonRpcClient", service)

    _runtime(tmp_path).run(["-c", "pass"])

    assert service.scheme == "http"


# --------------------------------------------------------------------------- #
# What every sandbox has before anything runs in it                           #
# --------------------------------------------------------------------------- #


def test_the_base_stack_is_asked_for_before_anything_else(tmp_path):
    """Every wrapper deserializes its request with OCP; an environment without it runs nothing."""
    from partcad import runtime_python

    made = _runtime(tmp_path)
    made.once()
    base = runtime_python.base_requirements(made.version)
    assert made.requirements[-len(base) :] == base


def test_the_base_ends_with_the_ocp_build_build123d_depends_on():
    """The one environment here gets the VTK build only when a CadQuery run asks for it, after this."""
    from partcad import runtime_python, sandbox_versions

    order = runtime_python.base_requirements("3.11")
    assert order.index(sandbox_versions.OCP) > order.index(sandbox_versions.BUILD123D)
    assert order[-1] == sandbox_versions.OCP
    assert sandbox_versions.CADQUERY_OCP not in order


def test_no_python_gets_cadquery_in_the_base():
    """It comes with the runs that import it, on every version that has a release of it."""
    from partcad import runtime_python, sandbox_versions

    assert sandbox_versions.CADQUERY not in runtime_python.base_requirements("3.10")
    assert sandbox_versions.CADQUERY not in runtime_python.base_requirements("3.11")


def test_a_command_brings_the_base_stack_with_it_even_without_once(tmp_path, monkeypatch):
    """'once()' was dead code here: every override skipped it, so nothing ever asked for OCP."""
    from partcad import runtime_python

    made = _runtime(tmp_path)
    sent = {}

    class _Service:
        def execute(self, command, params, timeout=None):
            sent.update(params)
            return {"result": {"exit_code": 0, "stdout": "", "stderr": ""}}

    monkeypatch.setattr(made, "_client", lambda: _Service())
    made.run(["x.py"])
    for requirement in runtime_python.base_requirements(made.version):
        assert requirement in sent["requirements"]
