#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The PythonVersion healthcheck agrees with `requires-python` in `pyproject.toml`.

The two are separate statements of one fact, and they drifted: `pyproject.toml`
moved to ">=3.10,<3.15" while the healthcheck stayed at 3.12, so the standalone
bundle -- which carries its own 3.14 -- warned on every start that the
interpreter PartCAD ships is unsupported, and told the user to change a system
Python that has no bearing on it. This reads the one and checks the other.
"""

import collections
import pathlib
import re
import sys

import pytest

from partcad.healthcheck.python_version import PythonVersionCheck

PYPROJECT = pathlib.Path(__file__).resolve().parents[3] / "pyproject.toml"


def requires_python() -> str:
    """The `requires-python` line of `pyproject.toml`, as written."""
    for line in PYPROJECT.read_text(encoding="utf-8").splitlines():
        match = re.match(r'\s*requires-python\s*=\s*"([^"]+)"', line)
        if match:
            return match.group(1)
    raise AssertionError(f"no requires-python in {PYPROJECT}")


@pytest.mark.skipif(not PYPROJECT.is_file(), reason="not run from a source checkout")
def test_bounds_match_pyproject():
    spec = requires_python()
    lower = re.search(r">=\s*(\d+)\.(\d+)", spec)
    upper = re.search(r"<\s*(\d+)\.(\d+)", spec)
    assert lower and upper, f"cannot read bounds from {spec!r}"

    check = PythonVersionCheck()
    assert check.min_version == (int(lower.group(1)), int(lower.group(2)))
    # `< 3.15` is "3.14 and any patch release of it" once it has to be compared
    # against `sys.version_info`, which is what the healthcheck holds.
    assert check.latest_version[:2] == (int(upper.group(1)), int(upper.group(2)) - 1)
    assert check.latest_version[2] == float("inf")


def test_running_interpreter_passes():
    """Whatever runs the test suite is an interpreter PartCAD supports."""
    assert PythonVersionCheck().test().findings == []


# `sys.version_info` compares as a tuple but is read as an object -- the check
# reports `.major` and `.minor` -- so a bare tuple is not a stand-in for it.
VersionInfo = collections.namedtuple("VersionInfo", "major minor micro releaselevel serial")


@pytest.mark.parametrize(
    "version, supported",
    [
        ((3, 9, 18, "final", 0), False),
        ((3, 10, 0, "final", 0), True),
        ((3, 12, 7, "final", 0), True),
        # The version the standalone bundle ships, which used to be reported as
        # unsupported by the bundle carrying it.
        ((3, 14, 0, "final", 0), True),
        ((3, 14, 9, "final", 0), True),
        ((3, 15, 0, "alpha", 1), False),
    ],
)
def test_bounds_accept_and_reject(monkeypatch, version, supported):
    monkeypatch.setattr(sys, "version_info", VersionInfo(*version))
    findings = PythonVersionCheck().test().findings
    assert (findings == []) is supported
