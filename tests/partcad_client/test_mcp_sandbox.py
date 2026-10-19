#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Which paths an agent may name through `pc mcp`."""

import os

import pytest

from partcad_client.mcp_server.sandbox import OutsideScope, PathScope


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "ws"
    (root / "parts").mkdir(parents=True)
    return root


def test_a_relative_path_is_relative_to_the_workspace_and_not_the_working_directory(workspace, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert PathScope([str(workspace)]).check("parts/box.step") == (workspace / "parts" / "box.step").resolve()


def test_an_absolute_path_inside_the_workspace_is_fine(workspace):
    target = workspace / "parts" / "box.step"
    assert PathScope([str(workspace)]).check(str(target)) == target.resolve()


@pytest.mark.parametrize("path", ["../box.step", "parts/../../box.step", "/etc/passwd", "~/box.step"])
def test_a_path_out_of_the_workspace_is_refused(workspace, path):
    with pytest.raises(OutsideScope, match="--allow-path"):
        PathScope([str(workspace)]).check(path)


@pytest.mark.skipif(not hasattr(os, "symlink") or os.name == "nt", reason="needs symlinks")
def test_a_link_out_of_the_workspace_is_out_of_it(workspace, tmp_path):
    (tmp_path / "outside").mkdir()
    os.symlink(tmp_path / "outside", workspace / "parts" / "escape")
    with pytest.raises(OutsideScope):
        PathScope([str(workspace)]).check("parts/escape/box.step")


@pytest.mark.parametrize("path", [".git/config", ".env", "parts/.secret/box.step"])
def test_a_hidden_entry_is_refused(workspace, path):
    with pytest.raises(OutsideScope, match="hidden"):
        PathScope([str(workspace)]).check(path)


def test_a_workspace_inside_a_hidden_directory_is_still_usable(tmp_path):
    root = tmp_path / ".cache" / "ws"
    root.mkdir(parents=True)
    assert PathScope([str(root)]).check("box.step") == (root / "box.step").resolve()


def test_an_allowed_path_is_usable_too(workspace, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    assert PathScope([str(workspace), str(other)]).check(str(other / "x.stl")) == (other / "x.stl").resolve()


def test_any_path_is_usable_when_the_user_said_so(workspace):
    assert PathScope([str(workspace)], unrestricted=True).check("/etc/passwd").is_absolute()


@pytest.mark.parametrize("path", ["", "   ", None, 3])
def test_a_path_has_to_be_a_path(workspace, path):
    with pytest.raises(OutsideScope):
        PathScope([str(workspace)]).check(path)


def test_paths_are_shown_relative_to_the_workspace(workspace, tmp_path):
    scope = PathScope([str(workspace)])
    assert scope.relative((workspace / "parts" / "box.step").resolve()) == "parts/box.step"
    assert scope.relative(tmp_path / "x") == str(tmp_path / "x")
