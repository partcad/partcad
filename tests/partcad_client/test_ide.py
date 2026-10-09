#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for `partcad_client.ide`: the editor, the extension, and the workspace request.

No editor is started here. What is pinned is what an editor would be asked --
the command line, the package, the request file the extension reads -- and the
two places a launch can go wrong. The editor itself is exercised by
`tests/ide/test_ide_e2e.py`.
"""

import json
import os
import sys

import pytest

from partcad_client import ide, selfupdate


@pytest.fixture
def editors(monkeypatch, tmp_path):
    """A PATH holding the editors named, and nothing else."""

    def install(*names):
        found = {name: str(tmp_path / "bin" / name) for name in names}
        monkeypatch.setattr(ide.shutil, "which", lambda name: found.get(name))
        return found

    return install


@pytest.fixture
def ran(monkeypatch):
    calls = []

    def run(command, log):
        calls.append(command)
        return ""

    monkeypatch.setattr(ide, "_run", run)
    return calls


@pytest.fixture
def launched(monkeypatch):
    calls = []
    monkeypatch.setattr(ide, "_launch", calls.append)
    return calls


def test_the_partcad_ide_is_preferred_over_the_editors_it_is_built_on(editors):
    found = editors("code", "codium", "partcad-ide")
    assert ide.find_editor() == found["partcad-ide"]


def test_the_first_editor_on_the_path_is_taken(editors):
    found = editors("code")
    assert ide.find_editor() == found["code"]


def test_no_editor_says_what_to_install(editors):
    editors()
    with pytest.raises(ide.IdeError, match="install.sh --ide"):
        ide.find_editor()


def test_an_editor_named_is_looked_up_on_the_path(editors):
    found = editors("code", "codium")
    assert ide.find_editor("codium") == found["codium"]
    with pytest.raises(ide.IdeError, match="'cursor' is not on the PATH"):
        ide.find_editor("cursor")


def test_an_editor_named_by_path_has_to_be_an_executable(tmp_path):
    with pytest.raises(ide.IdeError, match="not an executable file"):
        ide.find_editor(str(tmp_path / "nothing" / "codium"))
    assert ide.find_editor(sys.executable) == os.path.abspath(sys.executable)


def test_the_package_is_the_one_the_release_publishes(monkeypatch):
    monkeypatch.delenv("PARTCAD_BASE_URL", raising=False)
    monkeypatch.delenv("PARTCAD_REPOSITORY", raising=False)
    assert (
        ide.vsix_url("0.8.159") == "https://github.com/partcad/partcad/releases/download/0.8.159/partcad-0.8.159.vsix"
    )


def test_a_mirror_replaces_the_release_directory(monkeypatch):
    monkeypatch.setenv("PARTCAD_BASE_URL", "file:///mirror/")
    assert ide.vsix_url("1.2.3") == "file:///mirror/partcad-1.2.3.vsix"


def test_install_downloads_the_latest_release_and_forces_it_in(editors, ran, monkeypatch):
    found = editors("codium")
    downloaded = []
    monkeypatch.setattr(selfupdate, "_latest_release_tag", lambda repo: "0.8.159")

    def download(url, dest):
        downloaded.append(url)
        with open(dest, "wb") as f:
            f.write(b"PK")

    monkeypatch.setattr(selfupdate, "_download", download)
    monkeypatch.delenv("PARTCAD_BASE_URL", raising=False)

    result = ide.install_extension(editor_args=("--extensions-dir", "/x"))

    assert downloaded == ["https://github.com/partcad/partcad/releases/download/0.8.159/partcad-0.8.159.vsix"]
    ((command),) = ran
    assert command[:3] == [found["codium"], "--extensions-dir", "/x"]
    assert command[3] == "--install-extension"
    assert os.path.basename(command[4]) == "partcad-0.8.159.vsix"
    assert command[5] == "--force"
    assert result["extension"] == ide.EXTENSION_ID


def test_install_takes_a_version_asked_for(editors, ran, monkeypatch):
    editors("code")
    downloaded = []
    monkeypatch.setattr(selfupdate, "_latest_release_tag", lambda repo: pytest.fail("the latest was asked for"))
    monkeypatch.setattr(selfupdate, "_download", lambda url, dest: downloaded.append(url))
    ide.install_extension(version="0.8.131")
    assert downloaded[0].endswith("/0.8.131/partcad-0.8.131.vsix")


def test_install_a_local_package_downloads_nothing(editors, ran, monkeypatch, tmp_path):
    editors("code")
    monkeypatch.setattr(selfupdate, "_download", lambda url, dest: pytest.fail("downloaded"))
    package = tmp_path / "partcad.vsix"
    package.write_bytes(b"PK")
    ide.install_extension(vsix=str(package))
    assert ran[0][-2:] == [str(package), "--force"]


def test_a_release_without_the_package_says_so(editors, ran, monkeypatch):
    editors("code")

    def missing(url, dest):
        raise selfupdate.SelfUpdateError("no build was published at %s" % url)

    monkeypatch.setattr(selfupdate, "_download", missing)
    with pytest.raises(ide.IdeError, match="could not be downloaded"):
        ide.install_extension(version="0.0.1")
    assert ran == []


def test_an_editor_that_fails_the_install_fails_it(editors, monkeypatch, tmp_path):
    editors("code")
    monkeypatch.setattr(
        ide.subprocess,
        "run",
        lambda *a, **k: ide.subprocess.CompletedProcess(a[0], 1, stdout="Failed Installing Extensions"),
    )
    package = tmp_path / "partcad.vsix"
    package.write_bytes(b"PK")
    lines = []
    with pytest.raises(ide.IdeError, match="exited with status 1"):
        ide.install_extension(vsix=str(package), log=lines.append)
    assert lines[-1] == "Failed Installing Extensions"


def test_the_request_names_the_folder_and_is_read_by_name(tmp_path):
    path = ide.write_request(str(tmp_path / "pkg"), home=str(tmp_path / "home"), now=1000.0)
    assert os.path.dirname(path) == str(tmp_path / "home" / ".partcad" / "ide" / "requests")
    assert path.endswith(".json")
    with open(path, encoding="utf-8") as f:
        assert json.load(f) == {"folder": str(tmp_path / "pkg"), "view": "workbench", "requested": 1000.0}
    # Nothing half-written is left beside it.
    assert os.listdir(os.path.dirname(path)) == [os.path.basename(path)]


def test_open_writes_the_request_before_opening_the_folder(editors, launched, monkeypatch, tmp_path):
    found = editors("codium")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    folder = tmp_path / "pkg"
    folder.mkdir()

    result = ide.open_workspace(str(folder), editor_args=("--user-data-dir", "/u"))

    assert launched == [[found["codium"], "--user-data-dir", "/u", str(folder)]]
    (request,) = os.listdir(ide.requests_dir())
    with open(os.path.join(ide.requests_dir(), request), encoding="utf-8") as f:
        assert json.load(f)["folder"] == str(folder)
    assert result == {"ok": True, "editor": found["codium"], "path": str(folder), "workbench": True}


def test_a_launch_that_fails_takes_its_request_back(editors, monkeypatch, tmp_path):
    editors("code")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    def fail(command):
        raise ide.IdeError("code exited with status 1")

    monkeypatch.setattr(ide, "_launch", fail)
    with pytest.raises(ide.IdeError):
        ide.open_workspace(str(tmp_path))
    assert os.listdir(ide.requests_dir()) == []


def test_only_a_directory_is_opened_as_a_workspace(tmp_path):
    with pytest.raises(ide.IdeError, match="not a directory"):
        ide.open_workspace(str(tmp_path / "missing"))


def test_a_launcher_that_exits_with_an_error_is_reported():
    with pytest.raises(ide.IdeError, match="status 3: no display"):
        ide._launch([sys.executable, "-c", "import sys; sys.stderr.write('no display'); sys.exit(3)"])


def test_a_launcher_that_hands_the_folder_over_and_exits_is_fine():
    ide._launch([sys.executable, "-c", "pass"])


def test_an_application_that_keeps_running_is_left_running(monkeypatch):
    monkeypatch.setattr(ide, "LAUNCH_SETTLE", 0.2)
    ide._launch([sys.executable, "-c", "import time; time.sleep(2)"])
