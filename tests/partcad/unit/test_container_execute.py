#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""An implementation run the way a container runs it, minus the container.

`Runtime.run_async()` and `tools/containers/_common/pc-container-json-rpc.py`
are two halves of one protocol, and until an implementation declared a
`container:` nothing exercised the half that carries code: whole directories,
a request on standard input, an output file coming back. What is checked here is
that the two halves agree, by driving the *real* server function with what the
*real* client sends and running a real wrapper under it.

The container itself is the one thing not here. Pulling an image needs a
registry, and a unit test that needs one is a unit test that is skipped -- so
what is stubbed is Docker and nothing else: the packing, the path rewriting, the
allowlist, the base64 on both sides and the wrapper are all the shipping code.
"""

import asyncio
import base64
import importlib.util
import json
import os
import sys
import types

import pytest

from partcad import runtime as pc_runtime
from partcad import wrapper as pc_wrapper

# Where the wrappers are, asked the way the core asks: 'partcad.wrappers' is a
# namespace package and has no '__file__', and in a frozen bundle the directory
# is not beside the source at all.
WRAPPERS = os.path.dirname(pc_wrapper.get("export.py"))
SERVER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "tools",
    "containers",
    "_common",
    "pc-container-json-rpc.py",
)

# An implementation, as small as one can be: it writes the file it was told to
# write and answers with a finding, so that both halves of what an analysis
# produces have to survive the trip.
IMPLEMENTATION = """
import os
import sys

# The convention every sibling-importing implementation follows: 'runpy' does
# not put a script's own directory on 'sys.path'. Here it also asserts the
# point of 'input_dirs' -- '__file__' is the path the container unpacked the
# package to, so the sibling is found only because the whole directory came.
sys.path.append(os.path.dirname(__file__))
import helper


def process(path, request):
    with open(path, "w") as f:
        f.write(helper.MODEL)
    return {"success": True, "findings": [request["question"]]}
"""

# Beside it, and imported by it. A package's scripts share a module, which is
# why the whole directory is sent rather than the one file the command names.
HELPER = "MODEL = 'a model, as bytes would be'\n"


@pytest.fixture
def server(monkeypatch, tmp_path):
    """The container's RPC server, imported without Flask and without a container."""

    def _module(name, **attributes):
        module = types.ModuleType(name)
        for key, value in attributes.items():
            setattr(module, key, value)
        return module

    class _App:
        def errorhandler(self, _exception):
            return lambda handler: handler

    class _JsonRpc:
        def __init__(self, *args, **kwargs):
            pass

        def method(self, _name):
            return lambda handler: handler

    monkeypatch.setitem(
        sys.modules,
        "flask",
        _module("flask", Flask=lambda _name: _App(), request=None, jsonify=lambda payload: payload),
    )
    monkeypatch.setitem(sys.modules, "flask_jsonrpc", _module("flask_jsonrpc", JSONRPC=_JsonRpc))
    # The allowlist is the whole of the server's isolation and is a property of
    # the image, read once at start-up -- so it is set before the import, the
    # way a Dockerfile sets it.
    monkeypatch.setenv("PC_CONTAINER_ALLOWED_COMMANDS", json.dumps({"python": sys.executable}))
    # Where a `remote` sandbox's environments are mounted, told to the server
    # the way `partcad-service-remote-docker` tells it, and read at start-up for
    # the same reason the allowlist is.
    monkeypatch.setenv("PC_CONTAINER_SANDBOX_ROOT", str(tmp_path / "pc-sandbox"))

    spec = importlib.util.spec_from_file_location("pc_container_json_rpc", SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def package(tmp_path):
    """A package holding an implementation and the module it imports."""
    directory = tmp_path / "the-package"
    directory.mkdir()
    (directory / "solve.py").write_text(IMPLEMENTATION)
    (directory / "helper.py").write_text(HELPER)
    return directory


def _serialize(request):
    sys.path.insert(0, WRAPPERS)
    try:
        import ocp_serialize
    finally:
        sys.path.remove(WRAPPERS)
    return ocp_serialize.serialize(request)


def _deserialize(data):
    sys.path.insert(0, WRAPPERS)
    try:
        import ocp_serialize
    finally:
        sys.path.remove(WRAPPERS)
    return ocp_serialize.deserialize(data)


def _run(server, package, tmp_path, request=None):
    """Ask the server to run the implementation, exactly as the client does.

    The command, the directories and the encodings are what
    `Shape._run_implementation_locked()` and `Runtime.run_async()` build.
    """
    output = str(tmp_path / "result.glb")
    command = [
        "python",
        os.path.join(WRAPPERS, "wrapper_export.py"),
        output,
        str(package),
        str(package / "solve.py"),
    ]
    serialized = _serialize(request if request is not None else {"question": "how thin is too thin"})
    return output, server.handle_execute_command(
        command=command,
        stdin=base64.b64encode(serialized.encode("utf-8")).decode("utf-8"),
        input_files={},
        output_files=[output],
        input_dirs={
            WRAPPERS: pc_runtime.pack_directory(WRAPPERS),
            str(package): pc_runtime.pack_directory(str(package)),
        },
    )


def test_an_implementation_runs_and_answers(server, package, tmp_path):
    """The whole round trip: directories in, a request in, an answer out."""
    output, result = _run(server, package, tmp_path)

    assert result["exit_code"] == 0, base64.b64decode(result["stderr"]).decode("utf-8")
    answer = _deserialize(base64.b64decode(result["stdout"]).decode("utf-8"))
    assert answer["success"] is True
    assert answer["findings"] == ["how thin is too thin"]


def test_the_file_it_wrote_comes_back(server, package, tmp_path):
    """An analysis has two outputs and the model is the one that is a file.

    It is written inside the container, under a name of the container's
    choosing, and comes back keyed by the name the caller asked for.
    """
    output, result = _run(server, package, tmp_path)

    assert result["exit_code"] == 0, base64.b64decode(result["stderr"]).decode("utf-8")
    assert list(result["output_files"]) == [output]
    written = base64.b64decode(result["output_files"][output]).decode("utf-8")
    assert written == "a model, as bytes would be"


def test_the_script_reaches_it_by_a_path_that_exists_here(server, package, tmp_path):
    """The paths a command names are the caller's, and are rewritten on arrival.

    This is why the implementation script is an argument rather than part of the
    request: the request is one opaque string on standard input and cannot be
    rewritten, so a script named in it would name a directory on another
    machine. The check is that nothing under the caller's own paths was read --
    the implementation's answer proves it ran, and the package here is deleted
    before the answer is read.
    """
    output = str(tmp_path / "result.glb")
    command = [
        "python",
        os.path.join(WRAPPERS, "wrapper_export.py"),
        output,
        str(package),
        str(package / "solve.py"),
    ]
    packed = {WRAPPERS: pc_runtime.pack_directory(WRAPPERS), str(package): pc_runtime.pack_directory(str(package))}
    # Gone before the run: whatever runs, it is not this.
    for name in os.listdir(package):
        os.remove(os.path.join(package, name))

    result = server.handle_execute_command(
        command=command,
        stdin=base64.b64encode(_serialize({"question": "still here?"}).encode("utf-8")).decode("utf-8"),
        output_files=[output],
        input_dirs=packed,
    )
    assert result["exit_code"] == 0, base64.b64decode(result["stderr"]).decode("utf-8")
    answer = _deserialize(base64.b64decode(result["stdout"]).decode("utf-8"))
    assert answer["findings"] == ["still here?"]


def test_a_command_outside_the_allowlist_is_refused(server, package, tmp_path):
    """The allowlist is the whole of the server's isolation."""
    with pytest.raises(Exception, match="not allowed"):
        server.handle_execute_command(
            command=["sh", "-c", "echo no"],
            input_dirs={},
        )


# --------------------------------------------------------------------------- #
# Both halves, over the wire the client actually writes                       #
# --------------------------------------------------------------------------- #


class _Wire:
    """The RPC client, with the socket taken out.

    Everything the client encodes and everything the server decodes stays in;
    what is skipped is the HTTP request and the container it would reach. The
    parameters are round-tripped through JSON first, because that is what they
    do in the real thing and it is where a value that is not JSON survives here
    and does not there.
    """

    def __init__(self, server):
        self.server = server
        self.sent = None

    async def execute_async(self, command, params=None):
        self.sent = json.loads(json.dumps({"command": list(command), **(params or {})}))
        return {"result": self.server.handle_execute_command(**self.sent)}


@pytest.fixture
def runtime(server, monkeypatch, tmp_path):
    """A container runtime whose container is the server function above."""
    from partcad_utils.user_config import user_config

    monkeypatch.setattr(user_config, "internal_state_dir", str(tmp_path / "state"))
    made = pc_runtime.Runtime(types.SimpleNamespace(user_config=user_config), "test-container")
    made.rpc_client = _Wire(server)
    return made


def test_the_client_and_the_server_agree(runtime, package, tmp_path):
    """`Runtime.run_async()` against the real server, with nothing hand-built.

    This is the half that had never run. Between them these three assertions
    cover what was wrong with it: the request arrived as noise because it was
    sent unencoded and decoded as base64; the exit code was invented from
    whether anything reached stderr; and the file the implementation wrote was
    the only part that worked.
    """
    output = str(tmp_path / "result.glb")
    exitcode, stdout, errors = asyncio.run(
        runtime.run_async(
            [
                "python",
                os.path.join(WRAPPERS, "wrapper_export.py"),
                output,
                str(package),
                str(package / "solve.py"),
            ],
            _serialize({"question": "how thin is too thin"}),
            output_files=[output],
            input_dirs=[WRAPPERS, str(package)],
        )
    )

    assert exitcode == 0, errors
    assert not errors
    answer = _deserialize(stdout)
    assert answer["success"] is True, answer.get("exception")
    assert answer["findings"] == ["how thin is too thin"]
    # And the model is where the caller asked for it, not in the container.
    assert open(output).read() == "a model, as bytes would be"


def test_what_the_implementation_printed_is_a_warning_and_not_a_failure(runtime, package, tmp_path):
    """A library that prints is not a library that failed.

    The wrapper moves everything that prints onto stderr precisely so that it
    cannot corrupt the answer, which makes stderr the normal case rather than
    the exceptional one -- and the exit code the only thing that says whether
    the run succeeded.
    """
    (package / "solve.py").write_text(
        "import sys\n"
        "\n"
        "\n"
        "def process(path, request):\n"
        "    print('OCCT: Transferring Shape, ShapeType = 2')\n"
        "    open(path, 'w').write('a model, as bytes would be')\n"
        "    return {'success': True, 'findings': []}\n"
    )
    output = str(tmp_path / "result.glb")
    exitcode, stdout, errors = asyncio.run(
        runtime.run_async(
            [
                "python",
                os.path.join(WRAPPERS, "wrapper_export.py"),
                output,
                str(package),
                str(package / "solve.py"),
            ],
            _serialize({}),
            output_files=[output],
            input_dirs=[WRAPPERS, str(package)],
        )
    )

    assert exitcode == 0
    assert not errors
    assert _deserialize(stdout)["success"] is True


# --------------------------------------------------------------------------- #
# The caller's paths are the caller's                                         #
# --------------------------------------------------------------------------- #


def test_within_is_separator_agnostic(server):
    """The prefix test, on both spellings and on neither."""
    assert server._within("/pkg", "/pkg") == ()
    assert server._within("/pkg/solve.py", "/pkg") == ("solve.py",)
    assert server._within("D:\\pkg\\a\\solve.py", "D:\\pkg") == ("a", "solve.py")
    # A path that merely starts with the same characters is not below it.
    assert server._within("/pkgs/solve.py", "/pkg") is None
    assert server._within("/other", "/pkg") is None


def test_a_windows_client_reaches_a_posix_container(server, package, tmp_path):
    """The case the container exists for: no gmsh here, so run it over there.

    A Windows machine is one of the two that cannot install the mesher the
    CalculiX analyses need, so it is exactly the machine that reaches for a
    container -- and every path it sends is spelled with a backslash while the
    image it reaches is Linux. Matching on the *server's* separator left those
    unsubstituted, so the command still named `D:\\...` inside the container.
    """
    output = "D:\\work\\result.glb"
    command = [
        "python",
        os.path.join(WRAPPERS, "wrapper_export.py"),
        output,
        "D:\\pkg",
        "D:\\pkg\\solve.py",
    ]
    result = server.handle_execute_command(
        command=command,
        stdin=base64.b64encode(_serialize({"question": "over there"}).encode("utf-8")).decode("utf-8"),
        output_files=[output],
        input_dirs={WRAPPERS: pc_runtime.pack_directory(WRAPPERS), "D:\\pkg": pc_runtime.pack_directory(str(package))},
    )

    assert result["exit_code"] == 0, base64.b64decode(result["stderr"]).decode("utf-8")
    assert _deserialize(base64.b64decode(result["stdout"]).decode("utf-8"))["findings"] == ["over there"]
    # And the model comes back under the name the caller asked for, backslashes
    # and all -- that is the name it will write it to at its end.
    assert list(result["output_files"]) == [output]


def test_a_failed_implementation_reports_no_output_file(server, package, tmp_path):
    """A file the command never wrote is not one to hand back.

    Returning an empty one would be a path to nothing where the caller checks
    for the model's existence to decide whether the analysis delivered.
    """
    (package / "solve.py").write_text("def process(path, request):\n    return {'success': False}\n")
    output, result = _run(server, package, tmp_path)

    assert result["exit_code"] == 0
    assert result["output_files"] == {}
    assert _deserialize(base64.b64decode(result["stdout"]).decode("utf-8"))["success"] is False


# --------------------------------------------------------------------------- #
# The interpreter of an environment the image was not built with               #
# --------------------------------------------------------------------------- #
#
# A `remote` sandbox builds its virtual environment inside the container at run
# time, so the interpreter it then wants to run cannot be in an allowlist that
# was written when the image was built: its path carries a Python version
# nobody knew about. The server recognises it by where it is instead.


def _environment(server, version="3.11"):
    """A virtual environment's interpreter, where the sandbox root would put it."""
    interpreter = os.path.join(server.SANDBOX_ROOT, "v-env-%s" % version, "bin", "python")
    os.makedirs(os.path.dirname(interpreter))
    os.symlink(sys.executable, interpreter)
    return interpreter


def test_an_environments_interpreter_may_run(server):
    """Which is the whole of what the 'remote' sandbox asks a container to do."""
    interpreter = _environment(server)

    result = server.handle_execute_command([interpreter, "-c", "print('over here')"])

    assert result["exit_code"] == 0
    assert base64.b64decode(result["stdout"]).decode().strip() == "over here"


def test_something_else_in_that_directory_may_not(server):
    """A wheel can drop any console script into an environment's 'bin'."""
    _environment(server)
    intruder = os.path.join(server.SANDBOX_ROOT, "v-env-3.11", "bin", "curl")
    os.symlink(sys.executable, intruder)

    with pytest.raises(Exception, match="not allowed"):
        server.handle_execute_command([intruder, "-c", "pass"])


def test_an_interpreter_outside_the_sandbox_root_may_not(server, tmp_path):
    elsewhere = tmp_path / "elsewhere" / "bin"
    elsewhere.mkdir(parents=True)
    intruder = str(elsewhere / "python")
    os.symlink(sys.executable, intruder)

    with pytest.raises(Exception, match="not allowed"):
        server.handle_execute_command([intruder, "-c", "pass"])


def test_a_path_that_is_not_there_is_refused_rather_than_run(server):
    """The shape is not the permission: it has to be an environment that exists."""
    with pytest.raises(Exception, match="not allowed"):
        server.handle_execute_command([os.path.join(server.SANDBOX_ROOT, "v-env-3.11", "bin", "python"), "-c", "pass"])
