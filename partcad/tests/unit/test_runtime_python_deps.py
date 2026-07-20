#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import os
import signal

import pytest

import partcad as pc
from partcad.runtime_python import (
    PIP_CONSTRAINTS,
    PythonRuntime,
    describe_exit_code,
)


def _bare_runtime(path):
    """A PythonRuntime with just the attributes these helpers touch.

    __init__ wants a full context and a sandbox on disk, which is far more than
    the dependency helpers need.
    """
    runtime = PythonRuntime.__new__(PythonRuntime)
    runtime.path = str(path)
    runtime.constraints_path = None
    return runtime


def test_describe_exit_code_names_the_signal():
    assert "SIGSEGV" in describe_exit_code(-int(signal.SIGSEGV))
    assert "SIGABRT" in describe_exit_code(-int(signal.SIGABRT))


def test_describe_exit_code_handles_unknown_signal():
    # Must not raise even when the number is not a signal we know
    assert "unknown signal" in describe_exit_code(-99)


def test_describe_exit_code_names_windows_faults():
    assert "EXCEPTION_ACCESS_VIOLATION" in describe_exit_code(3221225477)
    assert "STATUS_HEAP_CORRUPTION" in describe_exit_code(3221226356)


def test_describe_exit_code_plain_failure():
    assert describe_exit_code(1) == "exit code 1"


def test_constraints_bound_ocp_and_ocpsvg():
    """Both unbounded edges out of build123d 0.8.0 have to stay bounded."""
    joined = " ".join(PIP_CONSTRAINTS)
    assert "cadquery-ocp" in joined
    assert "<7.8" in joined
    # ocpsvg moved to the cadquery-ocp-proxy package in 0.4, which only exists
    # for OCP 7.9+, so letting it float reintroduces the conflict
    assert "ocpsvg" in joined
    assert "<0.4" in joined


def test_get_constraints_flags_writes_the_file(tmp_path):
    runtime = _bare_runtime(tmp_path / "sandbox")

    flags = runtime.get_constraints_flags()

    assert flags[0] == "--constraint"
    written = open(flags[1]).read()
    for constraint in PIP_CONSTRAINTS:
        assert constraint in written


def test_get_constraints_flags_is_cached(tmp_path):
    runtime = _bare_runtime(tmp_path / "sandbox")

    assert runtime.get_constraints_flags() == runtime.get_constraints_flags()


def test_get_constraints_flags_survives_unwritable_path(tmp_path, monkeypatch):
    """A constraints file we cannot write must not break installs."""
    runtime = _bare_runtime(tmp_path / "sandbox")

    def deny(*_args, **_kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr(os, "makedirs", deny)

    # Falls back to the previous behavior rather than raising
    assert runtime.get_constraints_flags() == []


def test_report_dependency_conflicts_reports_pip_check_output(tmp_path, caplog):
    runtime = _bare_runtime(tmp_path / "sandbox")
    conflict = "cadquery 2.5.2 has requirement cadquery-ocp<7.8, but you have cadquery-ocp 7.9.3.1.1."

    runtime.report_dependency_conflicts(1, conflict, "", path=str(tmp_path))

    assert conflict in caplog.text


def test_report_dependency_conflicts_does_not_fail_the_run(tmp_path):
    """Reporting a conflict must not make the CLI exit non-zero.

    pc_logging.error() sets the global had_errors flag that the CLI turns into
    an exit code, so reporting a pre-existing conflict at error level breaks
    runs that otherwise pass. This is a diagnostic, not a verdict.
    """
    pc.logging.reset_errors()
    runtime = _bare_runtime(tmp_path / "sandbox")

    runtime.report_dependency_conflicts(1, "some 1.0 has requirement other<2, but you have other 3.", "")

    assert pc.logging.had_errors is False


def test_report_dependency_conflicts_silent_when_consistent(tmp_path, caplog):
    runtime = _bare_runtime(tmp_path / "sandbox")

    runtime.report_dependency_conflicts(0, "", "", path=str(tmp_path))

    assert caplog.text == ""
