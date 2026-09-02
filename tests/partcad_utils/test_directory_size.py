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


def test_a_special_file_is_not_counted(tree: pathlib.Path) -> None:
    """`os.walk` hands back every non-directory entry, a FIFO included, and
    `st_size` does not mean disk usage for one. It occupies no space worth
    reporting, so it contributes nothing rather than whatever that field held."""
    if not hasattr(os, "mkfifo"):  # pragma: no cover - Windows
        pytest.skip("this platform has no FIFOs")
    try:
        os.mkfifo(tree / "fifo")
    except OSError:  # pragma: no cover - a filesystem that will not hold one
        pytest.skip("this filesystem will not create a FIFO")
    assert directory_size(tree) == 300


def _lstat_raising_on(monkeypatch, name: str, error: OSError) -> None:
    """Make `os.lstat` fail for one basename and behave for every other.

    Patched at `os.lstat` because that is the one question `directory_size` asks
    of each name; a test that patched something it no longer calls would pass
    without exercising anything.
    """
    real_lstat = os.lstat

    def failing_lstat(path, *args, **kwargs):
        if os.path.basename(os.fspath(path)) == name:
            raise error
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", failing_lstat)


def test_a_file_that_vanishes_mid_walk_is_skipped(tree: pathlib.Path, monkeypatch) -> None:
    """The race this exists for: `os.walk` listed the name, and by the time its
    size is asked for, whatever was writing the tree has removed it."""
    _lstat_raising_on(monkeypatch, "two", FileNotFoundError(2, "No such file or directory"))
    # The 100-byte file still counts: one unreadable name must not abort the walk.
    assert directory_size(tree) == 100


def test_an_unreadable_file_is_skipped(tree: pathlib.Path, monkeypatch) -> None:
    """Same treatment for a file this process may not stat: a status report is
    worth more with one file missing from the total than not printed at all."""
    _lstat_raising_on(monkeypatch, "one", PermissionError(13, "Permission denied"))
    assert directory_size(tree) == 200
