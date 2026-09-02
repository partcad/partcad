#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for `directory_size`, the walk behind both status reports.

What it walks is PartCAD's internal state directory, which other processes are
writing to while it walks: conda sandboxes being built and torn down, git clones
being replaced. So the case that matters here is not the arithmetic -- it is a
name that `os.walk` listed and that is gone by the time the size is asked for.
That raised out of the walk and took the whole report with it, which is how
`pc system status` came back without its "Total internal data storage size:"
line on a CI machine that was provisioning a sandbox at the same time.
"""

import os
import pathlib

import pytest
from partcad_utils.utils import directory_size, directory_size_mb


@pytest.fixture
def tree(tmp_path: pathlib.Path) -> pathlib.Path:
    """A small directory tree with a known size, nested one level down."""
    (tmp_path / "nested").mkdir()
    (tmp_path / "one").write_bytes(b"a" * 100)
    (tmp_path / "nested" / "two").write_bytes(b"b" * 200)
    return tmp_path


def test_counts_every_regular_file(tree: pathlib.Path) -> None:
    assert directory_size(tree) == 300


def test_reports_megabytes(tree: pathlib.Path) -> None:
    assert directory_size_mb(tree) == pytest.approx(300 / 1048576.0)


def test_a_missing_directory_is_empty_rather_than_an_error(tmp_path: pathlib.Path) -> None:
    """`os.walk` yields nothing for a path that is not there, and that is right:
    the git or tar cache simply has not been created yet."""
    assert directory_size(tmp_path / "never-created") == 0


def test_a_symlink_is_not_counted(tree: pathlib.Path) -> None:
    """Its target is either counted where it lives or outside this tree."""
    try:
        (tree / "link").symlink_to(tree / "one")
    except (OSError, NotImplementedError):  # pragma: no cover - Windows without privilege
        pytest.skip("this platform will not create a symlink here")
    assert directory_size(tree) == 300


def test_a_dangling_symlink_is_not_an_error(tree: pathlib.Path) -> None:
    try:
        (tree / "dangling").symlink_to(tree / "gone")
    except (OSError, NotImplementedError):  # pragma: no cover - Windows without privilege
        pytest.skip("this platform will not create a symlink here")
    assert directory_size(tree) == 300


def test_a_file_that_vanishes_mid_walk_is_skipped(tree: pathlib.Path, monkeypatch) -> None:
    """The race this exists for: `os.walk` listed the name, and by the time
    `getsize` asks, whatever was writing the tree has removed it."""
    real_getsize = os.path.getsize

    def vanishing_getsize(path):
        if os.path.basename(path) == "two":
            raise FileNotFoundError(2, "No such file or directory", str(path))
        return real_getsize(path)

    monkeypatch.setattr(os.path, "getsize", vanishing_getsize)
    # The 100-byte file still counts: one unreadable name must not abort the walk.
    assert directory_size(tree) == 100


def test_an_unreadable_file_is_skipped(tree: pathlib.Path, monkeypatch) -> None:
    """Same treatment for a file this process may not stat: a status report is
    worth more with one file missing from the total than not printed at all."""
    real_getsize = os.path.getsize

    def denied_getsize(path):
        if os.path.basename(path) == "one":
            raise PermissionError(13, "Permission denied", str(path))
        return real_getsize(path)

    monkeypatch.setattr(os.path, "getsize", denied_getsize)
    assert directory_size(tree) == 200
