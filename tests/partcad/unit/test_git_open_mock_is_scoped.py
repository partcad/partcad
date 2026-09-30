#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""A guard for the 'mocked_git_open' fixture in 'tests/partcad/conftest.py'.

The git tests mock the clone, so the guard file that 'project_factory_git'
writes beside it has to be mocked away too. Doing that with a 'builtins.open'
mock hands the mock to the standard library as well, and 'pc.Context()' reads a
file through the standard library on macOS: 'Context.__init__' computes the host
tags, 'platform.mac_ver()' parses '/System/Library/CoreServices/SystemVersion.plist',
and 'plistlib' reads it in binary mode. A mock handing back 'str' fails there
with "TypeError: startswith first arg must be str or a tuple of str, not bytes",
which is what turned the 'Pytest' job red on every macOS cell and on no other.

The same 'plistlib' read reproduces the failure on any platform, so this keeps
the mock's scope covered where the tests actually run.
"""

import plistlib


def test_the_git_open_mock_does_not_reach_the_standard_library(tmp_path, mocked_git_open):
    """The standard library still opens files for real while the fixture is active."""
    plist = tmp_path / "SystemVersion.plist"
    plist.write_bytes(plistlib.dumps({"ProductVersion": "26.0"}))

    with mocked_git_open():
        # Exactly what 'platform.mac_ver()' does on macOS.
        with open(plist, "rb") as f:
            assert plistlib.load(f)["ProductVersion"] == "26.0"
