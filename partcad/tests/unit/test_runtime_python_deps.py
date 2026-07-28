#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import os
import pathlib
import re
import signal

import pytest

import partcad as pc
from partcad import sandbox_versions
from partcad.runtime_python import (
    PIP_CONSTRAINTS,
    PythonRuntime,
    clear_reassert,
    describe_exit_code,
    get_guard_path,
    invalidate_dependent_guards,
    needs_reassert,
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
    """Every edge that can drag a second OCP build in has to stay bounded."""
    joined = " ".join(PIP_CONSTRAINTS)
    # Since 7.9 the native library is in 'cadquery-ocp-proxy'; both
    # 'cadquery-ocp' and 'cadquery-ocp-novtk' are wrappers over it, so the
    # proxy is the one that has to be pinned
    assert "cadquery-ocp-proxy" in joined
    assert "<8.0" in joined
    assert "ocpsvg" in joined
    assert "<0.7" in joined


def test_build123d_install_demands_a_cadquery_ocp_reassert(tmp_path):
    """build123d overwrites the OCP that cadquery-ocp installed.

    It depends on 'cadquery-ocp-novtk', which ships the same native module
    built without VTK. Leaving that in place makes "import cadquery" fail
    inside the sandbox, so the install guard has to go and the next install of
    cadquery-ocp has to be forced.
    """
    guard = get_guard_path(str(tmp_path), sandbox_versions.CADQUERY_OCP)
    open(guard, "w").close()
    assert not needs_reassert(str(tmp_path), sandbox_versions.CADQUERY_OCP)

    invalidate_dependent_guards(str(tmp_path), sandbox_versions.BUILD123D)

    assert not os.path.exists(guard)
    assert needs_reassert(str(tmp_path), sandbox_versions.CADQUERY_OCP)


def test_reassert_is_cleared_once_satisfied(tmp_path):
    invalidate_dependent_guards(str(tmp_path), sandbox_versions.BUILD123D)

    clear_reassert(str(tmp_path), sandbox_versions.CADQUERY_OCP)

    assert not needs_reassert(str(tmp_path), sandbox_versions.CADQUERY_OCP)


def test_unrelated_install_invalidates_nothing(tmp_path):
    guard = get_guard_path(str(tmp_path), sandbox_versions.CADQUERY_OCP)
    open(guard, "w").close()

    invalidate_dependent_guards(str(tmp_path), sandbox_versions.OCP_TESSELLATE)

    assert os.path.exists(guard)
    assert not needs_reassert(str(tmp_path), sandbox_versions.CADQUERY_OCP)


def test_cadquery_ocp_is_installed_after_build123d_everywhere():
    """Order matters: the re-assert has to happen in the same sequence.

    Any install list that has both must end with cadquery-ocp, otherwise the
    sandbox is left holding the VTK-less OCP build until something else
    happens to install it again.
    """
    src = pathlib.Path(__file__).parent.parent.parent / "src" / "partcad"
    offenders = []
    for path in sorted(src.rglob("*.py")):
        text = path.read_text()
        ocp = [m.start() for m in re.finditer(r"sandbox_versions\.CADQUERY_OCP", text)]
        b3d = [m.start() for m in re.finditer(r"sandbox_versions\.BUILD123D", text)]
        if ocp and b3d and max(ocp) < max(b3d):
            offenders.append(path.name)
    assert offenders == [], offenders


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


def _record_warnings(monkeypatch):
    """Collect pc_logging.warning() calls.

    The 'partcad' logger sets propagate=False, so the caplog fixture (which
    attaches to the root logger) sees nothing on the pytest version used in CI.
    Recording the call directly keeps this independent of that.
    """
    recorded = []
    monkeypatch.setattr(pc.logging, "warning", lambda *args, **kwargs: recorded.append(" ".join(str(a) for a in args)))
    return recorded


def test_report_dependency_conflicts_reports_pip_check_output(tmp_path, monkeypatch):
    runtime = _bare_runtime(tmp_path / "sandbox")
    conflict = "cadquery 2.5.2 has requirement cadquery-ocp<7.8, but you have cadquery-ocp 7.9.3.1.1."
    recorded = _record_warnings(monkeypatch)

    runtime.report_dependency_conflicts(1, conflict, "", path=str(tmp_path))

    assert any(conflict in message for message in recorded), recorded


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


def test_report_dependency_conflicts_silent_when_consistent(tmp_path, monkeypatch):
    runtime = _bare_runtime(tmp_path / "sandbox")
    recorded = _record_warnings(monkeypatch)

    runtime.report_dependency_conflicts(0, "", "", path=str(tmp_path))

    assert recorded == []


def test_session_deps_start_with_zstd(tmp_path):
    """A v-env has to install zstd itself.

    "python -m venv" without --system-site-packages leaves the v-env blind to
    what the sandbox around it has installed, so a wrapper running there could
    not read the compressed BREP the host sends it.
    """
    runtime = _bare_runtime(tmp_path / "sandbox")
    runtime.version = "3.11"

    session = PythonRuntime.get_session(runtime, "//some:package")

    assert session["deps"] == [sandbox_versions.ZSTD]
    # Seeding the list must not by itself demand that a v-env be created.
    assert session["dirty"] is False


def test_session_deps_skip_zstd_where_the_stdlib_has_it(tmp_path):
    runtime = _bare_runtime(tmp_path / "sandbox")
    runtime.version = "3.14"

    assert PythonRuntime.get_session(runtime, "//some:package")["deps"] == []
