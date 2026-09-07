#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The third sandbox mechanism: a container an implementation declares.

A Python sandbox can only bring what pip can install. Some implementations need
more -- a native solver, a mesher with no wheel for this platform, a whole
third-party application -- and the point of letting them declare a container is
that such a plugin becomes responsible for its own dependencies instead of
asking every user to install them.

Nothing here starts a container. What is checked is the part that decides *what*
would be started and what would be sent to it, plus the one absence that is
allowed to excuse a check: no container runtime at all.
"""

import base64
import io
import os
import tarfile

import pytest

from partcad import output, runtime


# --------------------------------------------------------------------------- #
# What an implementation declares                                             #
# --------------------------------------------------------------------------- #


class _Package:
    """Stands in for the implementing package's own configuration."""

    def __init__(self, declared):
        self.config_obj = {"cae": {"fea": {"container": declared}}} if declared is not None else {"cae": {"fea": {}}}


def _implementation(declared):
    return output.Implementation("cae", "fea", {}, project=_Package(declared))


def test_an_implementation_that_declares_nothing_runs_in_a_python_sandbox():
    """The default, and what every implementation shipping with PartCAD is."""
    assert _implementation(None).container is None
    assert output.Implementation("cae", "fea", {}).container is None


def test_a_bare_string_is_the_image():
    """The short form, for the common case of an image and no other opinion."""
    assert _implementation("ghcr.io/partcad/x:1").container == {"image": "ghcr.io/partcad/x:1"}


def test_the_long_form_carries_the_port_and_the_name():
    declared = {"image": "ghcr.io/partcad/x:1", "port": 5001, "name": "pc-x"}
    assert _implementation(declared).container == declared


def test_a_container_that_names_no_image_is_refused():
    """Half a declaration is worse than none: it would start nothing, quietly."""
    with pytest.raises(ValueError, match="names no 'image:'"):
        _implementation({"port": 5001}).container


def test_the_container_is_read_from_the_implementing_package():
    """Not from the caller, for the reason `python_version()` gives at length.

    This describes what *that* package's script needs to run. A package asking
    for an analysis may have no code in it at all, so its opinion about images
    is not one worth reading.
    """
    # No project: nothing declared it, so there is nothing to read.
    assert output.Implementation("cae", "fea", {"container": {"image": "from-the-caller"}}).container is None


# --------------------------------------------------------------------------- #
# What is sent to it                                                          #
# --------------------------------------------------------------------------- #


@pytest.fixture
def package_dir(tmp_path):
    """A package shaped like a real implementation: a script and its sibling."""
    (tmp_path / "solve.py").write_text("import common\n")
    (tmp_path / "common.py").write_text("X = 1\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "data.txt").write_text("hello\n")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "junk.pyc").write_text("junk")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    return tmp_path


def _members(packed):
    with tarfile.open(fileobj=io.BytesIO(base64.b64decode(packed)), mode="r:gz") as tar:
        return sorted(m.name for m in tar.getmembers())


def test_a_package_travels_with_its_siblings(package_dir):
    """The whole reason directories are sent rather than the named file.

    An implementation script imports the module it shares with the rest of its
    package -- `fea_calculix.py` opens with `import calculix_common` -- so
    sending only the file the command names leaves it unable to start.
    """
    members = _members(runtime.pack_directory(str(package_dir)))
    assert "solve.py" in members
    assert "common.py" in members
    assert "sub/data.txt" in members


def test_what_a_sandbox_never_wants_is_left_out(package_dir):
    """'.git' alone can be most of what a package weighs."""
    members = _members(runtime.pack_directory(str(package_dir)))
    assert not [name for name in members if name.startswith((".git", "__pycache__", ".venv"))]


def test_packing_is_deterministic(package_dir):
    """So a difference between two runs is the package, not the clock."""
    assert runtime.pack_directory(str(package_dir)) == runtime.pack_directory(str(package_dir))


def test_the_archive_carries_no_timestamps_or_ownership(package_dir):
    """What makes it deterministic, asserted rather than inferred."""
    with tarfile.open(fileobj=io.BytesIO(base64.b64decode(runtime.pack_directory(str(package_dir)))), mode="r:gz") as t:
        for member in t.getmembers():
            assert member.mtime == 0
            assert member.uid == 0 and member.gid == 0
            assert member.uname == "" and member.gname == ""


def test_a_directory_is_substituted_by_prefix(package_dir, tmp_path):
    """One directory covers the script named in the command and the package.

    The server's rule, exercised here because it is what makes a single
    `input_dirs` entry enough: the command carries both `<pkg>/solve.py` and
    `<pkg>`, and both have to land inside the extracted copy.
    """
    extracted = str(tmp_path / "extracted")
    host = str(package_dir)
    command = ["python", os.path.join(host, "solve.py"), "/out.glb", host]

    for i in range(1, len(command)):
        for prefix in sorted({host: extracted}, key=len, reverse=True):
            if command[i] == prefix or command[i].startswith(prefix + os.sep):
                command[i] = extracted + command[i][len(prefix) :]
                break

    assert command[1] == os.path.join(extracted, "solve.py")
    assert command[3] == extracted
    # An argument that is not a path into the package is left alone.
    assert command[2] == "/out.glb"


# --------------------------------------------------------------------------- #
# The one absence that excuses a check                                        #
# --------------------------------------------------------------------------- #


def test_no_container_runtime_is_reported_as_such(monkeypatch):
    """`SandboxUnavailable`, and not some other failure.

    `pc test` skips on this one and fails on everything else, so it has to be
    distinguishable rather than "an exception happened while starting".
    """
    import asyncio

    import partcad as pc

    monkeypatch.setattr(runtime, "docker_available", lambda: False)
    ctx = pc.Context("examples")
    with pytest.raises(runtime.SandboxUnavailable, match="no container runtime"):
        asyncio.run(ctx.get_container_runtime({"image": "ghcr.io/partcad/nothing:1"}))


def test_the_message_names_the_image_that_could_not_be_started(monkeypatch):
    """A user who has no Docker still has to learn what wanted it."""
    import asyncio

    import partcad as pc

    monkeypatch.setattr(runtime, "docker_available", lambda: False)
    ctx = pc.Context("examples")
    with pytest.raises(runtime.SandboxUnavailable, match="ghcr.io/partcad/nothing:1"):
        asyncio.run(ctx.get_container_runtime({"image": "ghcr.io/partcad/nothing:1"}))


def test_docker_availability_is_asked_once(monkeypatch):
    """A run over a package tree must not ping the daemon per part."""
    calls = []

    class _Client:
        def ping(self):
            calls.append(1)
            return True

    monkeypatch.setattr(runtime, "_docker_available", None)
    monkeypatch.setattr(runtime.docker, "from_env", lambda: _Client())
    assert runtime.docker_available() is True
    assert runtime.docker_available() is True
    assert len(calls) == 1


def test_a_daemon_that_does_not_answer_is_not_available(monkeypatch):
    """Deliberately a real ping: a socket can exist with nothing behind it."""

    def _raise():
        raise RuntimeError("Cannot connect to the Docker daemon")

    monkeypatch.setattr(runtime, "_docker_available", None)
    monkeypatch.setattr(runtime.docker, "from_env", _raise)
    assert runtime.docker_available() is False
