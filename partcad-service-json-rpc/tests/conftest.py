#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Shared fixtures for the JSON-RPC service tests."""

import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def socket_dir():
    """A directory short enough to hold an AF_UNIX socket path.

    ``sun_path`` is a fixed-size field -- 104 bytes on macOS, 108 on Linux --
    and pytest's ``tmp_path`` spends most of that budget before the socket name
    is even appended: on macOS it sits under
    ``/private/var/folders/<hash>/T/pytest-of-<user>/pytest-<n>/<test-name><n>/``,
    where a descriptive test name is enough to push a bind over the limit and
    fail with "AF_UNIX path too long". ``/tmp`` keeps the prefix to a few
    characters, which is also what a real daemon socket looks like (it lives
    under ``~/.partcad/workspaces/<hash>/``).
    """
    path = tempfile.mkdtemp(prefix="pcs", dir="/tmp")
    try:
        yield Path(path)
    finally:
        shutil.rmtree(path, ignore_errors=True)
