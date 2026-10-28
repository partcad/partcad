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
import shutil
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


def test_an_allowed_name_missing_from_path_is_not_called_disallowed():
    """It is allowed; the image does not have it. Saying "not allowed" beside a list holding it misleads."""
    with pytest.raises(service.ExecuteError) as refused:
        service.handle_execute_command(["no-such-tool-anywhere"], allowed={"no-such-tool-anywhere": None})
    assert refused.value.code == -32602
    assert "not allowed" not in refused.value.message
    assert "no 'no-such-tool-anywhere' on its PATH" in refused.value.message


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
    # Three seconds each: one after another is nine, and the bound below -- two
    # of them -- leaves three seconds for starting three interpreters at once on
    # a runner that may be busy with other work (every pytest-xdist worker is).
    held = 3
    slow = script(tmp_path, "import time; time.sleep(%d)" % held, name="wrapper.py")
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

    assert time.monotonic() - began < 2 * held


def test_the_lock_reaches_the_handler_through_the_protocol(monkeypatch):
    seen = {}
    monkeypatch.setattr(service, "handle_execute_command", lambda **kwargs: seen.update(kwargs) or {})
    service.dispatch(
        {"jsonrpc": "2.0", "id": 1, "method": "execute", "params": {"command": ["x"], "lock": {"path": "/p"}}}
    )
    assert seen["lock"] == {"path": "/p"}


def test_paths_on_two_drives_are_not_one_inside_the_other(monkeypatch):
    """Windows' commonpath raises for them; the answer is "no", not a crash."""

    def two_drives(paths):
        raise ValueError("Paths don't have the same drive")

    monkeypatch.setattr(service.os.path, "commonpath", two_drives)
    assert service._under("C:\\\\sandbox", "D:\\\\x.lock") is False
    with pytest.raises(service.ExecuteError):
        service._lock_path({"path": "/pc-sandbox/v-env-3.11.lock"})


# A command's own environment                                                  #
# --------------------------------------------------------------------------- #


def test_a_command_gets_the_display_it_was_sent(allowed):
    """The display a window opens on is the user's now, not the one the container was made on."""
    result = service.handle_execute_command(
        ["python", "-c", "import os; print(os.environ['DISPLAY'])"], env={"DISPLAY": ":7"}, allowed=allowed
    )
    assert unb64(result["stdout"]).strip() == b":7"


@pytest.mark.parametrize("name", ["LD_PRELOAD", "PYTHONPATH", "PATH", "PC_CONTAINER_TOKEN"])
def test_a_variable_that_could_get_round_the_allowlist_is_refused(allowed, name):
    with pytest.raises(service.ExecuteError, match=name):
        service.handle_execute_command(["python", "-c", "1"], env={name: "x"}, allowed=allowed)


def test_without_env_the_container_environment_is_inherited(allowed, monkeypatch):
    monkeypatch.setenv("PC_SERVICE_TEST", "inherited")
    result = service.handle_execute_command(
        ["python", "-c", "import os; print(os.environ['PC_SERVICE_TEST'])"], allowed=allowed
    )
    assert unb64(result["stdout"]).strip() == b"inherited"


def test_env_travels_over_http(http):
    url = http()
    body = _call(
        url,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "execute",
            "params": {"command": ["python", "-c", "import os; print(os.environ['LANG'])"], "env": {"LANG": "C.UTF-8"}},
        },
    ).json()
    assert unb64(body["result"]["stdout"]).strip() == b"C.UTF-8"


# --------------------------------------------------------------------------- #
# Which of several names an image has                                          #
# --------------------------------------------------------------------------- #


def test_which_answers_for_each_allowed_name(tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("a shebang script is not an executable on Windows")
    tool = tmp_path / "bin" / "freecad"
    tool.parent.mkdir()
    tool.write_text("#!/bin/sh\n")
    tool.chmod(0o755)
    monkeypatch.setenv("PATH", str(tool.parent))
    # The allowed name that is not there is not `FreeCAD`, though FreeCAD goes by
    # that name too: on a filesystem that ignores case -- macOS's, by default --
    # `FreeCAD` is the file `freecad` is, and finding it there is the right answer.
    answer = service.handle_which(
        ["freecad", "freecad-daily", "rm"], allowed={"freecad": None, "freecad-daily": None, "python": sys.executable}
    )
    assert answer == {"freecad": str(tool), "freecad-daily": None, "rm": None}


def test_which_runs_nothing_and_reveals_nothing_unallowed(allowed):
    """A name off the allowlist is None whatever the image has: `which` is not a way to look around."""
    assert service.handle_which(["sh"], allowed=allowed) == {"sh": None}


def test_which_over_http(http):
    url = http()
    body = _call(url, {"jsonrpc": "2.0", "id": 2, "method": "which", "params": {"names": ["python"]}}).json()
    assert body["result"] == {"python": sys.executable}


# --------------------------------------------------------------------------- #
# Frames                                                                       #
# --------------------------------------------------------------------------- #


def _wire(message):
    """``message`` encoded and decoded again, through bytes, as it crosses a socket."""
    return service.decode_frame(b"".join(bytes(memoryview(part)) for part in service.encode_frame(message)))


def test_a_frame_carries_bytes_as_they_are_and_the_rest_as_json():
    message = {
        "id": 3,
        "params": {"stdin": b"\x00\xffraw", "empty": b"", "files": {"/a": bytearray(b"A"), "/b": memoryview(b"B")}},
        "list": [b"x", "text", 1, None, {"nested": b"y"}],
    }
    back = _wire(message)
    assert back["id"] == 3
    assert bytes(back["params"]["stdin"]) == b"\x00\xffraw"
    assert bytes(back["params"]["empty"]) == b""
    assert {k: bytes(v) for k, v in back["params"]["files"].items()} == {"/a": b"A", "/b": b"B"}
    assert [bytes(back["list"][0]), back["list"][1], back["list"][2], back["list"][3]] == [b"x", "text", 1, None]
    assert bytes(back["list"][4]["nested"]) == b"y"


def test_a_frame_does_not_grow_what_it_carries():
    """Base64 inside JSON was a third more on the wire for every byte, and an encode and a decode of it."""
    payload = os.urandom(1 << 20)
    parts = service.encode_frame({"params": {"stdin": payload}})
    assert service.frame_length(parts) - len(payload) < 128
    # Not copied on the way out: the payload is one of the buffers.
    assert any(part is payload for part in parts)


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"PCF2" + b"\x00" * 8,
        b"PCF1\x00\x00\x00\x10{}",
        b"PCF1\x00\x00\x00\x02{}\x00\x00\x00",
        b"PCF1\x00\x00\x00\x02{}\x00\x00\x00\x00\x00\x00\x00\x09short",
        b'PCF1\x00\x00\x00\x0c{"$blob": 0}',
        b'PCF1\x00\x00\x00\x0f{"$blob": true}',
    ],
)
def test_a_body_that_is_not_a_whole_frame_is_refused(body):
    with pytest.raises(ValueError):
        service.decode_frame(body)


# --------------------------------------------------------------------------- #
# The store, and directories by content                                        #
# --------------------------------------------------------------------------- #


@pytest.fixture
def store(tmp_path):
    return service.Store(str(tmp_path / "store"))


def _tree(directory):
    """A directory as a caller sends it: its tree, and the content of every digest in it."""
    files, dirs, blobs = [], [], {}
    for kind, name, real in service.walk(str(directory), []):
        if kind == "dir":
            dirs.append(name)
            continue
        data = open(real, "rb").read()
        digest = service.content_digest(data)
        files.append([name, digest, os.stat(real).st_mode & 0o777])
        blobs[digest] = data
    return {"files": files, "dirs": dirs}, blobs


def _package(tmp_path):
    package = tmp_path / "pkg"
    (package / "sub").mkdir(parents=True)
    (package / "empty").mkdir()
    (package / "helper.py").write_text("WORD = 'sibling'\n")
    (package / "sub" / "data.txt").write_text("deep")
    (package / "main.py").write_text(
        "import os, sys\nsys.path.insert(0, os.path.dirname(__file__))\nimport helper\n"
        "print(helper.WORD, open(os.path.join(os.path.dirname(__file__), 'sub', 'data.txt')).read(),"
        " os.path.isdir(os.path.join(os.path.dirname(__file__), 'empty')))\n"
    )
    return package


def test_a_tree_runs_from_the_store_once_it_has_been_sent(allowed, tmp_path, store):
    package = _package(tmp_path)
    tree, blobs = _tree(package)
    run = ["python", "/callers/pkg/main.py"]

    first = service.handle_execute_frames(
        run, input_trees={"/callers/pkg": tree}, blobs=blobs, allowed=allowed, store=store
    )
    assert first["exit_code"] == 0, first["stderr"]
    assert first["stdout"].strip() == b"sibling deep True"

    # The second time, the tree alone: what is in it is the store's now.
    second = service.handle_execute_frames(run, input_trees={"/callers/pkg": tree}, allowed=allowed, store=store)
    assert second["stdout"].strip() == b"sibling deep True"
    assert service.handle_missing(list(blobs), store) == {"missing": []}


def test_a_tree_naming_what_the_store_lacks_is_refused_naming_it_and_runs_nothing(allowed, tmp_path, store):
    package = _package(tmp_path)
    tree, blobs = _tree(package)
    marker = tmp_path / "ran"
    with pytest.raises(service.ExecuteError) as refused:
        service.handle_execute_frames(
            ["python", "-c", "open(%r, 'w').write('x')" % str(marker)],
            input_trees={"/callers/pkg": tree},
            allowed=allowed,
            store=store,
        )
    assert refused.value.code == service.MISSING
    assert sorted(refused.value.data["missing"]) == sorted(blobs)
    assert not marker.exists()
    assert sorted(service.handle_missing(sorted(blobs) + sorted(blobs), store)["missing"]) == sorted(blobs)


def test_content_that_is_not_what_its_digest_names_is_refused(allowed, store):
    """Or a caller could hand the next caller -- through the remote service, somebody else -- any file it liked."""
    with pytest.raises(service.ExecuteError, match="not what that digest names"):
        service.handle_execute_frames(
            ["python", "-c", "pass"],
            input_trees={"/p": {"files": [["a.py", service.content_digest(b"good"), 0o644]], "dirs": []}},
            blobs={service.content_digest(b"good"): b"evil"},
            allowed=allowed,
            store=store,
        )
    assert store.missing([service.content_digest(b"good")]) == [service.content_digest(b"good")]


@pytest.mark.parametrize("digest", ["../../etc/passwd", "ab", "A" * 64, 7])
def test_a_digest_that_is_not_one_is_refused_before_it_is_a_path(store, digest):
    with pytest.raises(service.ExecuteError, match="Not a content digest"):
        store.missing([digest])


@pytest.mark.parametrize("name", ["../escaped", "a/../../escaped", "/abs", "", "a//b", "./a"])
def test_a_tree_entry_outside_its_directory_is_refused(allowed, tmp_path, store, name):
    data = b"x"
    digest = service.content_digest(data)
    with pytest.raises(service.ExecuteError):
        service.handle_execute_frames(
            ["python", "-c", "pass"],
            input_trees={"/p": {"files": [[name, digest, 0o644]], "dirs": []}},
            blobs={digest: data},
            allowed=allowed,
            store=store,
        )
    assert not (tmp_path / "escaped").exists()


def test_a_command_writing_over_an_input_does_not_change_the_store(allowed, tmp_path, store):
    """A tree is copied out of the store, not linked: a saved board must not become every later caller's board."""
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "board.kicad_pcb").write_text("v1")
    tree, blobs = _tree(package)
    edit = "import sys; open(sys.argv[1], 'w').write('v2')"
    service.handle_execute_frames(
        ["python", "-c", edit, "/p/board.kicad_pcb"],
        input_trees={"/p": tree},
        blobs=blobs,
        allowed=allowed,
        store=store,
    )
    again = service.handle_execute_frames(
        ["python", "-c", "import sys; print(open(sys.argv[1]).read())", "/p/board.kicad_pcb"],
        input_trees={"/p": tree},
        allowed=allowed,
        store=store,
    )
    assert again["stdout"].strip() == b"v1"


@pytest.mark.skipif(os.name == "nt", reason="an execute bit")
def test_a_file_that_runs_still_runs_on_the_far_side(allowed, tmp_path, store):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "tool.sh").write_text("#!/bin/sh\n")
    (package / "tool.sh").chmod(0o755)
    (package / "data.txt").write_text("")
    tree, blobs = _tree(package)
    result = service.handle_execute_frames(
        [
            "python",
            "-c",
            "import os, sys; print([os.access(p, os.X_OK) for p in sys.argv[1:]])",
            "/p/tool.sh",
            "/p/data.txt",
        ],
        input_trees={"/p": tree},
        blobs=blobs,
        allowed=allowed,
        store=store,
    )
    assert result["stdout"].strip() == b"[True, False]"


@pytest.mark.skipif(os.name == "nt", reason="an execute bit")
def test_a_file_made_executable_and_nothing_else_comes_back(allowed, tmp_path, store):
    """What was sent is left out of what comes back, but only while it would still run, or not, as it did."""
    project = tmp_path / "pkg"
    project.mkdir()
    (project / "tool.sh").write_text("#!/bin/sh\n")
    (project / "tool.sh").chmod(0o700)
    (project / "build.sh").write_text("#!/bin/sh\n")
    (project / "same.txt").write_text("")
    tree, blobs = _tree(project)
    result = service.handle_execute_frames(
        ["python", "-c", "import os, sys; os.chmod(sys.argv[1], 0o755)", "/callers/pkg/build.sh"],
        input_trees={"/callers/pkg": tree},
        blobs=blobs,
        output_dirs=["/callers/pkg"],
        allowed=allowed,
        store=store,
    )
    back = result["output_dirs"]["/callers/pkg"]
    # 'tool.sh' was sent as 0o700 and is 0o755 over there: it runs either way.
    assert [(name, bool(mode & 0o111)) for name, mode, _data in back["files"]] == [("build.sh", True)]


def test_an_output_directory_comes_back_as_what_changed_in_it(allowed, tmp_path, store):
    """KiCad opens the project and saves the board beside it: what comes back is the board."""
    project = tmp_path / "board"
    project.mkdir()
    (project / "board.kicad_pro").write_text("{}")
    (project / "board.kicad_pcb").write_text("v1")
    tree, blobs = _tree(project)
    result = service.handle_execute_frames(
        [
            "python",
            "-c",
            "import os, sys; d = os.path.dirname(sys.argv[1]); open(os.path.join(d, 'board.kicad_pcb'), 'w').write('v2');"
            " os.mkdir(os.path.join(d, 'plots')); open(os.path.join(d, 'plots', 'top.svg'), 'w').write('<svg/>')",
            "/callers/board/board.kicad_pro",
        ],
        input_trees={"/callers/board": tree},
        blobs=blobs,
        output_dirs=["/callers/board"],
        allowed=allowed,
        store=store,
    )
    back = result["output_dirs"]["/callers/board"]
    assert {name: bytes(data) for name, _mode, data in back["files"]} == {
        "board.kicad_pcb": b"v2",
        "plots/top.svg": b"<svg/>",
    }
    assert back["dirs"] == ["plots"]


def test_an_output_directory_that_was_not_sent_comes_back_whole(allowed, store):
    result = service.handle_execute_frames(
        ["python", "-c", "import os, sys; open(os.path.join(sys.argv[1], 'a.txt'), 'w').write('A')", "/callers/r"],
        output_dirs=["/callers/r"],
        allowed=allowed,
        store=store,
    )
    assert [(name, bytes(data)) for name, _mode, data in result["output_dirs"]["/callers/r"]["files"]] == [
        ("a.txt", b"A")
    ]


def test_input_files_and_output_files_are_bytes_both_ways(allowed, store):
    caller = "/callers/board.kicad_pcb"
    result = service.handle_execute_frames(
        ["python", "-c", "import sys; p = sys.argv[1]; open(p, 'ab').write(b'\\xff')", caller],
        input_files={caller: b"\x00original"},
        output_files=[caller],
        allowed=allowed,
        store=store,
    )
    assert result["output_files"] == {caller: b"\x00original\xff"}


def test_empty_standard_input_is_none_rather_than_the_services_own(allowed, store):
    result = service.handle_execute_frames(
        ["python", "-c", "import sys; print(repr(sys.stdin.read()))"], stdin=b"", allowed=allowed, store=store
    )
    assert result["stdout"].strip() == b"''"


def test_a_payload_that_is_not_bytes_is_refused_in_frames(allowed, store):
    with pytest.raises(service.ExecuteError, match="blob"):
        service.handle_execute_frames(
            ["python", "-c", "pass"], input_files={"/a": "text"}, allowed=allowed, store=store
        )


def test_nothing_a_frames_call_built_is_left_behind_but_the_store(allowed, tmp_path, monkeypatch):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(service.tempfile, "tempdir", str(scratch))
    kept = service.Store(str(tmp_path / "store"))
    tree, blobs = _tree(_package(tmp_path))
    service.handle_execute_frames(
        ["python", "-c", "pass"],
        input_trees={"/callers/pkg": tree},
        blobs=blobs,
        input_files={"/callers/f": b"f"},
        output_dirs=["/callers/out"],
        allowed=allowed,
        store=kept,
    )
    assert os.listdir(scratch) == []
    assert kept.missing(list(blobs)) == []


def test_the_store_keeps_to_its_limit_by_letting_go_of_what_was_used_least_recently(tmp_path):
    import time

    kept = service.Store(str(tmp_path / "store"), limit=3000)
    old, used, new = (os.urandom(1000) for _ in range(3))
    for data in (old, used):
        kept.add(service.content_digest(data), data)
    time.sleep(0.01)
    assert kept.copy(service.content_digest(used), str(tmp_path / "copy"))
    time.sleep(0.01)
    kept.add(service.content_digest(new), new)
    assert kept.missing([service.content_digest(d) for d in (old, used, new)]) == []

    kept.add(service.content_digest(b"x" * 1500), b"x" * 1500)
    # Over the limit, and trimmed to three quarters of it: the least recently
    # used go first.
    assert kept.missing([service.content_digest(old)]) == [service.content_digest(old)]
    assert kept.missing([service.content_digest(b"x" * 1500)]) == []
    total = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(kept.root) for f in fs)
    assert total <= 3000


def test_content_bigger_than_the_whole_store_is_used_but_not_kept(allowed, tmp_path):
    kept = service.Store(str(tmp_path / "store"), limit=10)
    data = b"y" * 100
    digest = service.content_digest(data)
    result = service.handle_execute_frames(
        ["python", "-c", "import sys; print(len(open(sys.argv[1]).read()))", "/p/big.txt"],
        input_trees={"/p": {"files": [["big.txt", digest, 0o644]], "dirs": []}},
        blobs={digest: data},
        allowed=allowed,
        store=kept,
    )
    assert result["stdout"].strip() == b"100"
    assert kept.missing([digest]) == [digest]


def test_a_store_found_on_disk_is_counted_and_trimmed(tmp_path):
    """A service restarted in a container that kept its filesystem knows what it holds."""
    root = str(tmp_path / "store")
    first = service.Store(root)
    for i in range(4):
        data = bytes([i]) * 1000
        first.add(service.content_digest(data), data)
    again = service.Store(root, limit=2500)
    again.add(service.content_digest(b"z" * 10), b"z" * 10)
    total = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(root) for f in fs)
    assert total <= 2500


# --------------------------------------------------------------------------- #
# Frames over HTTP                                                             #
# --------------------------------------------------------------------------- #


@pytest.fixture
def framed(monkeypatch, tmp_path):
    """A real server on loopback with a store of this test's, and a client of it; and how many connections it took."""
    from partcad_utils import container_files
    from partcad_utils.json_rpc_client import RuntimeJsonRpcClient

    monkeypatch.setattr(service, "ALLOWED_COMMANDS", {"python": sys.executable})
    monkeypatch.setattr(container_files, "_KNOWN", container_files.collections.OrderedDict())
    connections = []

    class Counted(service.Server):
        def process_request(self, request, client_address):
            connections.append(client_address)
            return service.Server.process_request(self, request, client_address)

    token = "frames-%d" % id(tmp_path)
    store = service.Store(str(tmp_path / "store"))
    handler = type("Handler", (service._Handler,), {"token": token, "store": store})
    server = Counted(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = RuntimeJsonRpcClient("127.0.0.1", server.server_address[1], token=token)
    client.connections = connections
    client.store = store
    yield client
    server.shutdown()
    server.server_close()


def test_frames_travel_over_http_and_come_back_as_they_went(framed):
    for size in (0, 1, 5 * 1024 * 1024 + 7):
        payload = os.urandom(size)
        answer = framed.call(
            "execute",
            {
                "command": ["python", "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"],
                "stdin": payload,
            },
            timeout=120,
        )
        assert answer["result"]["exit_code"] == 0, bytes(answer["result"]["stderr"])
        assert bytes(answer["result"]["stdout"]) == payload


def test_one_connection_serves_one_thread_many_commands(framed):
    """A connection per command was a handshake and a server thread per command."""
    for _ in range(4):
        assert framed.call("execute", {"command": ["python", "-c", "pass"]}, timeout=60)["result"]["exit_code"] == 0
    assert len(framed.connections) == 1


def test_a_refusal_in_frames_is_a_json_rpc_error(framed):
    answer = framed.call("execute", {"command": ["rm", "-rf", "/"]}, timeout=30)
    assert answer["error"]["code"] == -32602


def test_a_frame_that_does_not_parse_is_a_parse_error_in_frames(framed):
    response = requests.post(
        framed.url + "/jsonrpc",
        data=b"PCF1\x00\x00\x00\x09not json!",
        headers={"Content-Type": service.FRAME_TYPE, "Authorization": "Bearer %s" % framed.token},
        timeout=10,
    )
    assert service.is_frame(response.headers["Content-Type"])
    assert service.decode_frame(response.content)["error"]["code"] == -32700


def test_a_directory_is_sent_once_and_named_after_that(framed, tmp_path):
    from partcad_utils import container_files

    package = _package(tmp_path)
    sent = []
    original = framed._post_frame

    def recording(parts, timeout):
        payload = service.decode_frame(b"".join(bytes(memoryview(p)) for p in parts))
        sent.append((payload["method"], sorted(payload["params"].get("blobs") or ())))
        return original(parts, timeout)

    framed._post_frame = recording
    run = ["python", str(package / "main.py")]

    answer = framed.run(run, container_files.Request(input_dirs=[str(package)]), timeout=60)
    assert bytes(answer["result"]["stdout"]).strip() == b"sibling deep True"
    digests = sorted(container_files.Request(input_dirs=[str(package)]).digests())
    assert sent == [("missing", []), ("execute", digests)]

    sent.clear()
    answer = framed.run(run, container_files.Request(input_dirs=[str(package)]), timeout=60)
    assert bytes(answer["result"]["stdout"]).strip() == b"sibling deep True"
    assert sent == [("execute", [])]


def test_content_the_store_let_go_of_is_sent_again_when_asked_for(framed, tmp_path):
    """What this process remembers a container has is a hint; the container's answer is the fact."""
    from partcad_utils import container_files

    package = _package(tmp_path)
    run = ["python", str(package / "main.py")]
    assert framed.run(run, container_files.Request(input_dirs=[str(package)]), timeout=60)["result"]["exit_code"] == 0
    shutil.rmtree(framed.store.root)
    framed.store._sizes = None

    answer = framed.run(run, container_files.Request(input_dirs=[str(package)]), timeout=60)
    assert answer["result"]["exit_code"] == 0, bytes(answer["result"]["stderr"])
    assert bytes(answer["result"]["stdout"]).strip() == b"sibling deep True"


# --------------------------------------------------------------------------- #
# What travels in a tree is compressed where that pays                         #
# --------------------------------------------------------------------------- #


def test_content_that_compresses_travels_compressed_and_what_does_not_travels_as_it_is():
    text = b"solid cube\n" * 1000
    noise = os.urandom(4096)
    assert set(service.pack_blob(text)) == {"zlib"}
    assert service.pack_blob(noise) is noise
    assert service.pack_blob(b"tiny") == b"tiny"
    for data in (text, noise, b"tiny"):
        assert bytes(service.unpack_blob(_wire({"b": service.pack_blob(data)})["b"])) == data


def test_a_tree_may_be_sent_compressed(allowed, store):
    data = b"WORD = 'sibling'\n" + b"#" * 4000 + b"\n"
    digest = service.content_digest(data)
    result = service.handle_execute_frames(
        ["python", "-c", "import sys; print(len(open(sys.argv[1]).read()))", "/p/helper.py"],
        input_trees={"/p": {"files": [["helper.py", digest, 0o644]], "dirs": []}},
        blobs=_wire({"b": {digest: service.pack_blob(data)}})["b"],
        allowed=allowed,
        store=store,
    )
    assert result["stdout"].strip() == str(len(data)).encode()
    # Kept as what it is, not as it travelled.
    with open(store.path(digest), "rb") as f:
        assert f.read() == data


def test_compressed_content_that_does_not_decompress_is_refused(allowed, store):
    with pytest.raises(service.ExecuteError, match="does not decompress"):
        service.handle_execute_frames(
            ["python", "-c", "pass"], blobs={"0" * 64: {"zlib": b"not zlib"}}, allowed=allowed, store=store
        )


def test_an_output_directory_comes_back_compressed_and_is_written_as_it_was(allowed, tmp_path, store):
    from partcad_utils import container_files

    board = "(kicad_pcb (version 20240108))\n" * 200
    result = service.handle_execute_frames(
        ["python", "-c", "import os, sys; open(os.path.join(sys.argv[1], 'b.kicad_pcb'), 'w').write(%r)" % board, "/r"],
        output_dirs=["/r"],
        allowed=allowed,
        store=store,
    )
    back = _wire(result)["output_dirs"]["/r"]
    assert set(back["files"][0][2]) == {"zlib"}
    target = tmp_path / "r"
    container_files.write_back({"output_dirs": {str(target): back}}, output_dirs=[str(target)])
    assert (target / "b.kicad_pcb").read_text() == board
