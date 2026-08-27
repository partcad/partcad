#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import asyncio
import contextlib
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


def _record_ensures(runtime, monkeypatch):
    """Capture what a runtime asks to be installed, without installing it."""
    requested = []
    monkeypatch.setattr(
        type(runtime),
        "ensure_onced_locked",
        lambda self, package, **kwargs: requested.append(package),
        raising=False,
    )

    async def ensure_async_onced_locked(self, package, **kwargs):
        requested.append(package)

    monkeypatch.setattr(type(runtime), "ensure_async_onced_locked", ensure_async_onced_locked, raising=False)
    return requested


def test_ensure_zstd_installs_the_backport(tmp_path, monkeypatch):
    """Both once() paths have to provision zstd, not just the asynchronous one."""
    runtime = _bare_runtime(tmp_path / "sandbox")
    runtime.version = "3.11"
    requested = _record_ensures(runtime, monkeypatch)

    PythonRuntime.ensure_zstd_onced_locked(runtime)
    asyncio.run(PythonRuntime.ensure_zstd_onced_locked_async(runtime))

    assert requested == [sandbox_versions.ZSTD, sandbox_versions.ZSTD]


def test_ensure_zstd_installs_nothing_where_the_stdlib_has_it(tmp_path, monkeypatch):
    runtime = _bare_runtime(tmp_path / "sandbox")
    runtime.version = "3.14"
    requested = _record_ensures(runtime, monkeypatch)

    PythonRuntime.ensure_zstd_onced_locked(runtime)
    asyncio.run(PythonRuntime.ensure_zstd_onced_locked_async(runtime))

    assert requested == []


def test_reconcile_requirement_forces_the_pinned_cad_stack():
    """A part asking for its own CAD version gets the sandbox-wide pin instead.

    These three are the versions part_factory_sdf.py used to pin. Installed into
    a session v-env they downgraded the stack under every other part of the same
    package, and the next CadQuery render died on OCP 7.7 with "type object
    'OCP.TopoDS.TopoDS' has no attribute 'Vertex'".
    """
    for stale, pinned in [
        ("cadquery-ocp==7.7.2", sandbox_versions.CADQUERY_OCP),
        ("ocp-tessellate==3.0.9", sandbox_versions.OCP_TESSELLATE),
        ("build123d==0.8.0", sandbox_versions.BUILD123D),
    ]:
        assert sandbox_versions.reconcile_requirement(stale) == (pinned, stale)


def test_reconcile_requirement_normalizes_the_distribution_name():
    """Full PEP 503 normalization, so no spelling of a pinned name slips past.

    pip accepts '.', '-' and '_' interchangeably and collapses runs of them, so
    anything less than the whole rule leaves a way to name the pinned CAD stack
    and still get an arbitrary version installed.
    """
    for spelling, expected in [
        ("cadquery_ocp==7.7.2", sandbox_versions.CADQUERY_OCP),
        ("CadQuery-OCP==7.7.2", sandbox_versions.CADQUERY_OCP),
        ("cadquery.ocp==7.7.2", sandbox_versions.CADQUERY_OCP),
        ("cadquery--ocp==7.7.2", sandbox_versions.CADQUERY_OCP),
        ("cadquery_.-ocp==7.7.2", sandbox_versions.CADQUERY_OCP),
        ("OCP_Tessellate==3.0.9", sandbox_versions.OCP_TESSELLATE),
        ("build123d[ocp]==0.8.0", sandbox_versions.BUILD123D),
    ]:
        assert sandbox_versions.reconcile_requirement(spelling) == (expected, spelling)


def test_reconcile_requirement_keeps_the_environment_marker():
    """Only the version is overridden; the caller's condition is preserved.

    Dropping the marker would install the package unconditionally, which is not
    what a requirement guarded by one asked for.
    """
    marked = 'build123d==0.8.0; sys_platform == "linux"'
    reconciled, superseded = sandbox_versions.reconcile_requirement(marked)

    assert superseded == marked
    assert reconciled == '%s; sys_platform == "linux"' % sandbox_versions.BUILD123D


def test_reconcile_requirement_leaves_a_pinned_requirement_with_a_marker_alone():
    """Already at the pinned version, marker and all -> nothing to report."""
    already = '%s; sys_platform == "linux"' % sandbox_versions.BUILD123D

    assert sandbox_versions.reconcile_requirement(already) == (already, None)


def test_reconcile_requirement_leaves_everything_else_alone():
    """Only the co-dependent CAD stack is pinned; other packages are the package's own business."""
    for untouched in ["sdf-fork", "numpy>=2.2,<3", "requests", sandbox_versions.CADQUERY_OCP]:
        assert sandbox_versions.reconcile_requirement(untouched) == (untouched, None)


def test_runtime_reconciles_a_requirement_and_warns_once(tmp_path, monkeypatch):
    """The substitution is visible, but does not repeat for every part."""
    runtime = _bare_runtime(tmp_path / "sandbox")
    runtime.superseded_requirements = set()
    recorded = _record_warnings(monkeypatch)

    assert runtime.reconcile_requirement("cadquery-ocp==7.7.2") == sandbox_versions.CADQUERY_OCP
    assert runtime.reconcile_requirement("cadquery-ocp==7.7.2") == sandbox_versions.CADQUERY_OCP

    assert len(recorded) == 1
    assert "cadquery-ocp==7.7.2" in recorded[0]
    assert sandbox_versions.CADQUERY_OCP in recorded[0]


def test_no_factory_pins_its_own_version_of_the_shared_cad_stack():
    """Regression guard for the bug this file's reconciliation exists to prevent.

    A session v-env is shared by every part of a package, so a factory that
    hardcodes its own version of a pinned distribution corrupts that environment
    for the other parts. Everything must go through sandbox_versions.
    """
    pinned_names = {sandbox_versions.distribution_name(req) for req in sandbox_versions.PINNED_REQUIREMENTS}
    src = pathlib.Path(__file__).parent.parent.parent / "src" / "partcad"
    offenders = []
    for path in sorted(src.rglob("*.py")):
        if path.name == "sandbox_versions.py":
            continue
        for literal in re.findall(r"""["']([A-Za-z0-9_.\-\[\]]+==[^"']+)["']""", path.read_text()):
            if sandbox_versions.distribution_name(literal) in pinned_names:
                offenders.append("%s: %s" % (path.name, literal))
    assert offenders == [], offenders


class _StubUserConfig:
    def __init__(self, internal_state_dir):
        self.internal_state_dir = str(internal_state_dir)


class _StubContext:
    def __init__(self, internal_state_dir):
        self.user_config = _StubUserConfig(internal_state_dir)


def _locking_runtime(tmp_path):
    """A bare runtime with the little more that the environment lock reads."""
    runtime = _bare_runtime(tmp_path / "sandbox")
    runtime.version = "3.11"
    runtime.sandbox_dir = "pc-py-conda-3.11"
    runtime.ctx = _StubContext(tmp_path)
    runtime.superseded_requirements = set()
    runtime.pip_flags = []
    runtime.pip_install_flags = []
    return runtime


def test_the_environment_locked_is_the_one_run_in(tmp_path):
    """A lock over an environment nobody runs in locks nothing.

    The v-env lock this replaces was keyed on the session, but a session whose
    package asks for nothing of its own runs the runtime's own interpreter --
    so two such packages took two different locks over the one environment they
    were both reading, and an install into it took a third.
    """
    runtime = _locking_runtime(tmp_path)
    session = PythonRuntime.get_session(runtime, "//some:package")

    assert PythonRuntime.environment_path(runtime, session) == runtime.path
    assert PythonRuntime.environment_path(runtime, None) == runtime.path
    assert PythonRuntime.environment_lock(runtime, session) is PythonRuntime.environment_lock(runtime, None)
    assert PythonRuntime.environment_lock(runtime, session).lock_path.endswith(
        os.path.join("", ".pc-py-conda-3.11.default.lock")
    )


def test_a_session_with_a_venv_locks_the_venv(tmp_path):
    runtime = _locking_runtime(tmp_path)
    session = PythonRuntime.get_session(runtime, "//some:package")
    session["dirty"] = True

    assert PythonRuntime.environment_path(runtime, session) == session["path"]
    # The name the per-session lock used, so a PartCAD of either vintage
    # running beside this one contends over the same file.
    assert PythonRuntime.environment_lock(runtime, session).lock_path.endswith(
        ".pc-py-conda-3.11.%s.lock" % session["hash"]
    )
    assert PythonRuntime.environment_lock(runtime, session) is not PythonRuntime.environment_lock(runtime, None)


def test_a_session_needs_the_environment_for_writing_only_until_it_is_provisioned(tmp_path):
    """Which is what lets a package's parts render together rather than in turn."""
    runtime = _locking_runtime(tmp_path)
    session = PythonRuntime.get_session(runtime, "//some:package")

    assert not PythonRuntime.session_needs_install(runtime, None)
    assert not PythonRuntime.session_needs_install(runtime, session)

    session["dirty"] = True
    assert PythonRuntime.session_needs_install(runtime, session)

    session["installed"].update(session["deps"])
    assert not PythonRuntime.session_needs_install(runtime, session)

    session["deps"].append("something-else==1.0")
    assert PythonRuntime.session_needs_install(runtime, session)


def _forbid_locking(runtime, monkeypatch):
    """Make taking the environment lock a test failure."""

    def refuse(*_args, **_kwargs):
        raise AssertionError("the environment lock was taken with nothing to install")

    monkeypatch.setattr(type(runtime), "sync_lock", refuse, raising=False)
    monkeypatch.setattr(type(runtime), "async_lock", refuse, raising=False)


def test_an_installed_requirement_takes_no_lock(tmp_path, monkeypatch):
    """The fast path: a warm sandbox renders without ever queueing on it."""
    runtime = _locking_runtime(tmp_path)
    os.makedirs(runtime.path, exist_ok=True)
    pathlib.Path(get_guard_path(runtime.path, sandbox_versions.CADQUERY_OCP)).touch()
    _forbid_locking(runtime, monkeypatch)

    PythonRuntime.ensure_onced(runtime, sandbox_versions.CADQUERY_OCP)
    asyncio.run(PythonRuntime.ensure_async_onced(runtime, sandbox_versions.CADQUERY_OCP))


def test_a_missing_requirement_still_takes_the_lock_for_writing(tmp_path, monkeypatch):
    runtime = _locking_runtime(tmp_path)
    os.makedirs(runtime.path, exist_ok=True)
    taken = []

    @contextlib.contextmanager
    def sync_lock(self, session=None, path=None, write=False):
        taken.append(write)
        yield

    monkeypatch.setattr(type(runtime), "sync_lock", sync_lock, raising=False)
    monkeypatch.setattr(type(runtime), "install_onced_locked", lambda *a, **k: None, raising=False)

    PythonRuntime.ensure_onced(runtime, sandbox_versions.CADQUERY_OCP)

    assert taken == [True]


def test_ensure_does_not_reassert_what_it_did_not_install(tmp_path, monkeypatch):
    """Regression guard for a forced reinstall of OCP per rendered file.

    Every image file type installs build123d and then cadquery-ocp, and
    build123d's install is what demands that cadquery-ocp be re-asserted. When
    that demand was raised whether or not build123d had just been installed,
    the cadquery-ocp that followed it was force-reinstalled every single time.
    """
    runtime = _locking_runtime(tmp_path)
    os.makedirs(runtime.path, exist_ok=True)
    pathlib.Path(get_guard_path(runtime.path, sandbox_versions.BUILD123D)).touch()
    ocp_guard = get_guard_path(runtime.path, sandbox_versions.CADQUERY_OCP)
    pathlib.Path(ocp_guard).touch()
    _forbid_locking(runtime, monkeypatch)

    PythonRuntime.ensure_onced(runtime, sandbox_versions.BUILD123D)
    asyncio.run(PythonRuntime.ensure_async_onced(runtime, sandbox_versions.BUILD123D))

    assert os.path.exists(ocp_guard)
    assert not needs_reassert(runtime.path, sandbox_versions.CADQUERY_OCP)


def test_an_install_still_reasserts_what_it_clobbered(tmp_path, monkeypatch):
    """The other half: a build123d that really is installed must demand it."""
    runtime = _locking_runtime(tmp_path)
    os.makedirs(runtime.path, exist_ok=True)
    ocp_guard = get_guard_path(runtime.path, sandbox_versions.CADQUERY_OCP)
    pathlib.Path(ocp_guard).touch()
    monkeypatch.setattr(type(runtime), "run_onced_locked", lambda *a, **k: (0, "", ""), raising=False)

    PythonRuntime.install_onced_locked(runtime, sandbox_versions.BUILD123D, runtime.path)

    assert os.path.exists(get_guard_path(runtime.path, sandbox_versions.BUILD123D))
    assert not os.path.exists(ocp_guard)
    assert needs_reassert(runtime.path, sandbox_versions.CADQUERY_OCP)
