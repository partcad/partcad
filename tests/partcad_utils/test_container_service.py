#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The service inside every container, driven the way a caller drives it.

Two layers. `handle_execute_command` is the protocol -- what is rewritten, what
is run, what comes back -- and is called directly with what a client sends.
Under it, a real server on loopback answers real HTTP, because the transport is
part of the contract too: the readiness probe, the token, the JSON-RPC envelope.

The files here are real, the commands are real (this interpreter, run as
"python"), and nothing is mocked but the absence of a container -- which the
service cannot tell from being in one.
"""

import base64
import json
import os
import sys
import threading

import pytest
import requests

from partcad_utils import container_service as service


@pytest.fixture
def allowed():
    """This interpreter as "python", the way an image's allowlist names its own."""
    return {"python": sys.executable}


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("utf-8")


def unb64(data: str) -> bytes:
    return base64.b64decode(data)


def script(tmp_path, body, name="tool.py"):
    """A command for the service to run, written where an `input_dirs` package would be."""
    path = tmp_path / name
    path.write_text(body)
    return path


# --------------------------------------------------------------------------- #
# Running and refusing                                                         #
# --------------------------------------------------------------------------- #


def test_a_command_runs_and_its_output_comes_back(allowed):
    result = service.handle_execute_command(["python", "-c", "print('hello')"], allowed=allowed)
    assert result["exit_code"] == 0
    assert unb64(result["stdout"]).strip() == b"hello"


def test_standard_input_reaches_the_command(allowed):
    result = service.handle_execute_command(
        ["python", "-c", "import sys; print(sys.stdin.read().upper())"],
        stdin=b64(b"shout"),
        allowed=allowed,
    )
    assert unb64(result["stdout"]).strip() == b"SHOUT"


def test_no_standard_input_is_an_empty_one_rather_than_the_services_own(allowed):
    """A command that reads stdin when none was sent must not hang on the service's."""
    result = service.handle_execute_command(
        ["python", "-c", "import sys; print(repr(sys.stdin.read()))"], allowed=allowed
    )
    assert unb64(result["stdout"]).strip() == b"''"


def test_the_exit_code_is_reported(allowed):
    result = service.handle_execute_command(["python", "-c", "raise SystemExit(7)"], allowed=allowed)
    assert result["exit_code"] == 7


def test_a_command_outside_the_allowlist_is_refused(allowed):
    with pytest.raises(service.ExecuteError) as refused:
        service.handle_execute_command(["sh", "-c", "true"], allowed=allowed)
    assert refused.value.code == -32602
    assert "not allowed" in refused.value.message


def test_a_null_allowlist_entry_is_looked_up_on_path(tmp_path, monkeypatch):
    """An application's install location is the image's business; the name is what is allowed."""
    tool = tmp_path / "bin" / "greet"
    tool.parent.mkdir()
    tool.write_text("#!%s\nprint('found on PATH')\n" % sys.executable)
    tool.chmod(0o755)
    monkeypatch.setenv("PATH", str(tool.parent) + os.pathsep + os.environ.get("PATH", ""))
    if os.name == "nt":
        pytest.skip("a shebang script is not an executable on Windows")

    result = service.handle_execute_command(["greet"], allowed={"greet": None})
    assert unb64(result["stdout"]).strip() == b"found on PATH"


def test_a_null_allowlist_entry_that_is_not_on_path_is_refused():
    with pytest.raises(service.ExecuteError):
        service.handle_execute_command(["no-such-tool-anywhere"], allowed={"no-such-tool-anywhere": None})


def test_the_allowlist_is_read_from_the_environment_once():
    allowed = service.load_allowlist({"PC_CONTAINER_ALLOWED_COMMANDS": json.dumps({"python": "/x/py", "app": None})})
    assert allowed["python"] == "/x/py"
    assert allowed["app"] is None
    # The defaults a KiCad image started by hand has always had are kept.
    assert allowed["kicad-cli"] == "/usr/bin/kicad-cli"


def test_a_non_string_argument_is_refused(allowed):
    with pytest.raises(service.ExecuteError):
        service.handle_execute_command(["python", 1], allowed=allowed)


# --------------------------------------------------------------------------- #
# Files that travel                                                            #
# --------------------------------------------------------------------------- #


def test_an_input_file_is_written_and_its_argument_rewritten(allowed, tmp_path):
    caller = "/somewhere/on/the/callers/machine/model.step"
    result = service.handle_execute_command(
        ["python", "-c", "import sys; print(open(sys.argv[1]).read())", caller],
        input_files={caller: b64(b"the model")},
        allowed=allowed,
    )
    assert unb64(result["stdout"]).strip() == b"the model"


def test_an_output_file_comes_back_under_the_callers_name(allowed):
    caller = "/callers/out.stl"
    result = service.handle_execute_command(
        ["python", "-c", "import sys; open(sys.argv[1], 'w').write('mesh')", caller],
        output_files=[caller],
        allowed=allowed,
    )
    assert unb64(result["output_files"][caller]) == b"mesh"


def test_an_output_the_command_did_not_write_is_not_reported(allowed):
    caller = "/callers/out.stl"
    result = service.handle_execute_command(["python", "-c", "pass", caller], output_files=[caller], allowed=allowed)
    assert result["output_files"] == {}


def test_an_in_place_edit_comes_back(allowed):
    """Opened and saved: a file that is both input and output.

    The service used to rewrite the argument for the input and then look for the
    *rewritten* name among the outputs, which it never was -- so an application
    that saved over the file it was given lost the edit without a word.
    """
    caller = "/callers/board.kicad_pcb"
    result = service.handle_execute_command(
        ["python", "-c", "import sys; p = sys.argv[1]; open(p, 'a').write(' + edit')", caller],
        input_files={caller: b64(b"original")},
        output_files=[caller],
        allowed=allowed,
    )
    assert unb64(result["output_files"][caller]) == b"original + edit"


def test_a_directory_travels_whole_and_an_argument_inside_it_is_rewritten(allowed, tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "helper.py").write_text("WORD = 'sibling'\n")
    (package / "main.py").write_text(
        "import os, sys\nsys.path.insert(0, os.path.dirname(__file__))\nimport helper\nprint(helper.WORD)\n"
    )
    caller = "/callers/pkg"
    result = service.handle_execute_command(
        ["python", caller + "/main.py"],
        input_dirs={caller: service.pack_directory(str(package))},
        allowed=allowed,
    )
    assert result["exit_code"] == 0, unb64(result["stderr"])
    assert unb64(result["stdout"]).strip() == b"sibling"


def test_a_windows_callers_paths_are_rewritten_too(allowed, tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "main.py").write_text("print('ran')\n")
    result = service.handle_execute_command(
        ["python", "D:\\work\\pkg\\main.py"],
        input_dirs={"D:\\work\\pkg": service.pack_directory(str(package))},
        allowed=allowed,
    )
    assert unb64(result["stdout"]).strip() == b"ran"


def test_a_sent_directory_comes_back_with_what_the_command_changed(allowed, tmp_path):
    """KiCad opens the project and saves the board beside it: the directory is what was edited."""
    project = tmp_path / "board"
    project.mkdir()
    (project / "board.kicad_pro").write_text("{}")
    (project / "board.kicad_pcb").write_text("v1")
    caller = "/callers/board"
    result = service.handle_execute_command(
        [
            "python",
            "-c",
            "import os, sys; open(os.path.join(os.path.dirname(sys.argv[1]), 'board.kicad_pcb'), 'w').write('v2')",
            caller + "/board.kicad_pro",
        ],
        input_dirs={caller: service.pack_directory(str(project))},
        output_dirs=[caller],
        allowed=allowed,
    )
    back = tmp_path / "back"
    back.mkdir()
    service.unpack_directory(result["output_dirs"][caller], str(back))
    assert (back / "board.kicad_pcb").read_text() == "v2"
    assert (back / "board.kicad_pro").read_text() == "{}"


def test_an_output_directory_that_was_not_sent_starts_empty(allowed, tmp_path):
    caller = "/callers/results"
    result = service.handle_execute_command(
        ["python", "-c", "import os, sys; open(os.path.join(sys.argv[1], 'a.txt'), 'w').write('A')", caller],
        output_dirs=[caller],
        allowed=allowed,
    )
    back = tmp_path / "back"
    back.mkdir()
    service.unpack_directory(result["output_dirs"][caller], str(back))
    assert sorted(os.listdir(back)) == ["a.txt"]


def test_cwd_inside_a_sent_directory_is_rewritten(allowed, tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "marker").write_text("here")
    caller = "/callers/pkg"
    result = service.handle_execute_command(
        ["python", "-c", "print(open('marker').read())"],
        cwd=caller,
        input_dirs={caller: service.pack_directory(str(package))},
        allowed=allowed,
    )
    assert unb64(result["stdout"]).strip() == b"here"


def test_a_cwd_that_does_not_exist_here_is_not_fatal(allowed):
    result = service.handle_execute_command(
        ["python", "-c", "print('ran anyway')"], cwd="/callers/nowhere", allowed=allowed
    )
    assert result["exit_code"] == 0


def test_an_archive_member_escaping_its_directory_is_refused(tmp_path):
    import io
    import tarfile

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        info = tarfile.TarInfo("../escaped")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(service.ExecuteError):
        service.unpack_directory(b64(buffer.getvalue()), str(tmp_path / "target"))
    assert not (tmp_path / "escaped").exists()


def test_an_archive_link_is_refused(tmp_path):
    import io
    import tarfile

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        info = tarfile.TarInfo("link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)
    (tmp_path / "target").mkdir()
    with pytest.raises(service.ExecuteError):
        service.unpack_directory(b64(buffer.getvalue()), str(tmp_path / "target"))


def test_packing_is_deterministic(tmp_path):
    (tmp_path / "a").write_text("1")
    (tmp_path / "b").write_text("2")
    assert service.pack_directory(str(tmp_path)) == service.pack_directory(str(tmp_path))


def _round_trip(source, tmp_path):
    target = tmp_path / "unpacked"
    target.mkdir()
    service.unpack_directory(service.pack_directory(str(source)), str(target))
    return target


@pytest.mark.skipif(not hasattr(os, "symlink") or sys.platform == "win32", reason="symbolic links")
def test_a_link_inside_the_package_arrives_as_what_it_points_at(tmp_path):
    """A package with a link in it must still be sendable: the unpacking side refuses links."""
    package = tmp_path / "pkg"
    (package / "parts").mkdir(parents=True)
    (package / "parts" / "cube.step").write_text("solid")
    os.symlink("parts/cube.step", package / "cube.step")
    os.symlink("parts", package / "shortcut")

    target = _round_trip(package, tmp_path)

    assert (target / "cube.step").read_text() == "solid"
    assert not (target / "cube.step").is_symlink()
    assert (target / "shortcut" / "cube.step").read_text() == "solid"


@pytest.mark.skipif(not hasattr(os, "symlink") or sys.platform == "win32", reason="symbolic links")
def test_a_link_out_of_the_package_is_not_followed(tmp_path, caplog):
    """Following it would send a file nobody asked to send -- a key, a password store."""
    secret = tmp_path / "secret"
    secret.write_text("key")
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "part.py").write_text("x")
    os.symlink(str(secret), package / "leak")
    os.symlink(str(package / "nowhere"), package / "dangling")

    with caplog.at_level("WARNING"):
        target = _round_trip(package, tmp_path)

    assert sorted(os.listdir(target)) == ["part.py"]
    assert "dangling" in caplog.text and "leak" in caplog.text


@pytest.mark.skipif(not hasattr(os, "symlink") or sys.platform == "win32", reason="symbolic links")
def test_a_link_to_a_directory_holding_it_ends(tmp_path):
    package = tmp_path / "pkg"
    (package / "sub").mkdir(parents=True)
    os.symlink("..", package / "sub" / "up")

    target = _round_trip(package, tmp_path)

    assert (target / "sub").is_dir()
    assert not (target / "sub" / "up").exists()


@pytest.mark.skipif(not hasattr(os, "link") or sys.platform == "win32", reason="hard links")
def test_a_hard_linked_file_arrives_twice_as_a_file(tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "a.txt").write_text("same")
    os.link(package / "a.txt", package / "b.txt")

    target = _round_trip(package, tmp_path)

    assert (target / "b.txt").read_text() == "same"


def test_nothing_a_call_unpacked_is_left_behind(allowed, tmp_path, monkeypatch):
    """One container serves every command a machine sends; a directory per call that stays is a full disk."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(service.tempfile, "tempdir", str(scratch))
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "x").write_text("x")
    service.handle_execute_command(
        ["python", "-c", "pass"],
        input_dirs={"/callers/pkg": service.pack_directory(str(package))},
        input_files={"/callers/f": b64(b"f")},
        allowed=allowed,
    )
    assert os.listdir(scratch) == []


# --------------------------------------------------------------------------- #
# Over HTTP                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture
def http(monkeypatch):
    """A real server on a loopback port, with this interpreter allowed as "python"."""
    monkeypatch.setattr(service, "ALLOWED_COMMANDS", {"python": sys.executable})
    started = []

    def start(token=None):
        server = service.serve("127.0.0.1", 0, token)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        started.append(server)
        return "http://127.0.0.1:%d" % server.server_address[1]

    yield start
    for server in started:
        server.shutdown()
        server.server_close()


def _call(url, payload, token=None):
    headers = {"Authorization": "Bearer %s" % token} if token else {}
    return requests.post(url + "/jsonrpc", json=payload, headers=headers, timeout=30)


def test_readiness_is_answered_without_a_token(http):
    url = http(token="secret")
    answer = requests.get(url + "/", timeout=5).json()
    assert answer == {"ok": True, "protocol": service.PROTOCOL}


def test_execute_answers_with_a_json_rpc_envelope(http):
    url = http()
    response = _call(
        url, {"jsonrpc": "2.0", "id": 9, "method": "execute", "params": {"command": ["python", "-c", "print(1)"]}}
    )
    body = response.json()
    assert body["id"] == 9
    assert body["result"]["exit_code"] == 0


def test_a_request_without_the_token_is_refused(http):
    url = http(token="secret")
    response = _call(
        url, {"jsonrpc": "2.0", "id": 1, "method": "execute", "params": {"command": ["python", "-c", "1"]}}
    )
    assert response.status_code == 401


def test_a_request_with_the_token_is_served(http):
    url = http(token="secret")
    response = _call(
        url, {"jsonrpc": "2.0", "id": 1, "method": "execute", "params": {"command": ["python", "-c", "1"]}}, "secret"
    )
    assert response.status_code == 200
    assert response.json()["result"]["exit_code"] == 0


def test_a_refusal_is_a_json_rpc_error_rather_than_a_crash(http):
    url = http()
    body = _call(
        url, {"jsonrpc": "2.0", "id": 1, "method": "execute", "params": {"command": ["rm", "-rf", "/"]}}
    ).json()
    assert body["error"]["code"] == -32602


def test_an_unknown_method_is_reported_as_one(http):
    url = http()
    body = _call(url, {"jsonrpc": "2.0", "id": 1, "method": "format_disk", "params": {}}).json()
    assert body["error"]["code"] == -32601


def test_a_body_that_is_not_json_is_a_parse_error(http):
    url = http()
    response = requests.post(url + "/jsonrpc", data=b"{not json", timeout=5)
    assert response.json()["error"]["code"] == -32700


def test_a_long_command_does_not_hold_up_the_readiness_probe(http):
    """One thread per request: an application open for an hour must not make the container look dead."""
    url = http()
    slow = threading.Thread(
        target=_call,
        args=(
            url,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "execute",
                "params": {"command": ["python", "-c", "import time; time.sleep(3)"]},
            },
        ),
        daemon=True,
    )
    slow.start()
    assert requests.get(url + "/", timeout=2).json()["ok"] is True
    slow.join()


def test_the_service_imports_nothing_outside_the_standard_library():
    """It runs on whatever python3 an image has; a dependency is one that image may not have."""
    import ast

    with open(service.__file__, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            imported.add(node.module.split(".")[0])
    standard = set(sys.stdlib_module_names)
    assert imported <= standard, imported - standard


def test_the_copy_images_carry_is_this_file_byte_for_byte():
    """One implementation of the protocol, kept in two places for two readers.

    The wheel's copy is what PartCAD puts into every container it starts. The
    copy under tools/containers is what an image built there carries for anybody
    running that image by hand, and a Docker build cannot reach outside its
    context to read the wheel's. Two copies are only one implementation while
    they are the same bytes -- the service used to exist in two dialects, and a
    KiCad image refusing `input_dirs` is what that cost.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    baked = root / "tools" / "containers" / "_common" / "pc-container-json-rpc.py"
    assert baked.read_bytes() == pathlib.Path(service.__file__).read_bytes(), (
        "copy src/partcad_utils/container_service.py over %s" % baked
    )


# --------------------------------------------------------------------------- #
# A lock held around a command                                                 #
# --------------------------------------------------------------------------- #


@pytest.fixture
def sandbox_root(tmp_path, monkeypatch):
    root = tmp_path / "pc-sandbox"
    root.mkdir()
    monkeypatch.setattr(service, "SANDBOX_ROOT", str(root))
    return root


@pytest.mark.parametrize("path", ["/etc/x.lock", "relative.lock", "{root}", "{root}/../escape.lock"])
def test_a_lock_outside_the_sandbox_root_is_refused(allowed, sandbox_root, tmp_path, path):
    """The lock file is created when it is not there: a path anywhere is a file created anywhere."""
    with pytest.raises(service.ExecuteError):
        service.handle_execute_command(
            ["python", "-c", "pass"], allowed=allowed, lock={"path": path.format(root=sandbox_root)}
        )
    assert not (tmp_path / "escape.lock").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="the service runs on Linux; flock is POSIX")
def test_a_shared_holder_waits_for_an_exclusive_one(allowed, sandbox_root, tmp_path):
    """Nothing runs out of an environment while something installs into it."""
    import time

    lock = str(sandbox_root / "v-env-3.11.lock")
    order = []
    started = threading.Event()
    slow = script(tmp_path, "import time; time.sleep(1)", name="install.py")

    def install():
        started.set()
        service.handle_execute_command(["python", str(slow)], allowed=allowed, lock={"path": lock, "exclusive": True})
        order.append("installed")

    installer = threading.Thread(target=install)
    installer.start()
    started.wait()
    time.sleep(0.3)  # let it take the lock
    service.handle_execute_command(["python", "-c", "pass"], allowed=allowed, lock={"path": lock})
    order.append("ran")
    installer.join()

    assert order == ["installed", "ran"]


@pytest.mark.skipif(sys.platform == "win32", reason="the service runs on Linux; flock is POSIX")
def test_shared_holders_do_not_wait_for_each_other(allowed, sandbox_root, tmp_path):
    import time

    lock = {"path": str(sandbox_root / "v-env-3.11.lock")}
    slow = script(tmp_path, "import time; time.sleep(1)", name="wrapper.py")
    threads = [
        threading.Thread(
            target=service.handle_execute_command,
            args=(["python", str(slow)],),
            kwargs={"allowed": allowed, "lock": lock},
        )
        for _ in range(3)
    ]
    began = time.monotonic()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert time.monotonic() - began < 2.5


def test_the_lock_reaches_the_handler_through_the_protocol(monkeypatch):
    seen = {}
    monkeypatch.setattr(service, "handle_execute_command", lambda **kwargs: seen.update(kwargs) or {})
    service.dispatch(
        {"jsonrpc": "2.0", "id": 1, "method": "execute", "params": {"command": ["x"], "lock": {"path": "/p"}}}
    )
    assert seen["lock"] == {"path": "/p"}
