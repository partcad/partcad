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
import subprocess
import sys

import pytest
from packaging.requirements import Requirement

import partcad as pc
from partcad import sandbox_versions
from partcad.runtime_python import (
    BASE_SITE_DIRS_COMMAND,
    LAYER_GUARD,
    LAYER_PTH,
    LINK_LAYER_COMMAND,
    PIP_CONSTRAINTS,
    VENV_PREFIX,
    PythonRuntime,
    base_requirements,
    clear_reassert,
    describe_exit_code,
    get_guard_path,
    invalidate_dependent_guards,
    layer_created,
    layer_linked,
    needs_reassert,
    read_site_dirs,
)

# PartCAD's own sources, which a few tests below read.
_SRC = pathlib.Path(__file__).resolve().parents[3] / "src" / "partcad"


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


def test_numba_is_capped_on_intel_macos_and_nowhere_else():
    """The one constraint that must NOT apply everywhere.

    numba and llvmlite stopped publishing macOS x86_64 wheels at 0.63.0/0.46.0,
    and both still publish an sdist -- so without a bound pip builds llvmlite
    from source there, finds no LLVM, and the cadquery install dies with it. The
    cap has to be scoped by marker: every other platform still resolves numba
    freely, and a cap that leaked onto them would hold the whole fleet at a
    release chosen for a runner none of them are.

    Asserted on the parsed requirement, not on the text: the marker has to
    actually evaluate that way, and the specifier has to actually admit the last
    Intel-macOS release while excluding the first one without a wheel.
    """
    capped = [c for c in PIP_CONSTRAINTS if Requirement(c).name == "numba"]
    assert len(capped) == 1, capped
    requirement = Requirement(capped[0])

    assert requirement.marker is not None
    assert requirement.marker.evaluate({"sys_platform": "darwin", "platform_machine": "x86_64"})
    for elsewhere in (
        {"sys_platform": "darwin", "platform_machine": "arm64"},
        {"sys_platform": "linux", "platform_machine": "x86_64"},
        {"sys_platform": "linux", "platform_machine": "aarch64"},
        {"sys_platform": "win32", "platform_machine": "AMD64"},
    ):
        assert not requirement.marker.evaluate(elsewhere), elsewhere

    # The last numba with an Intel macOS wheel, and the first without one.
    assert "0.62.1" in requirement.specifier
    assert "0.63.0" not in requirement.specifier


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


def test_only_what_imports_cadquery_asks_for_its_ocp():
    """CadQuery's OCP build is what puts a run in CadQuery's layer.

    Everything else asks for 'OCP', the build the sandbox's own environment
    holds. Asking for CadQuery's to get OCP alone provisions a layer carrying
    VTK for nothing -- and in the 'remote' sandbox, which has one environment,
    writes the VTK build over the base's.
    """
    assert _SRC.is_dir(), _SRC
    offenders = []
    for path in sorted(_SRC.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        asks_for_its_ocp = re.search(r"sandbox_versions\.CADQUERY_OCP\b", text)
        asks_for_cadquery = re.search(r"sandbox_versions\.CADQUERY\b(?!_)", text)
        if asks_for_its_ocp and not asks_for_cadquery:
            offenders.append(path.name)
    assert offenders == [], offenders


def test_the_base_holds_one_ocp_build_and_no_cadquery():
    """The two OCP builds write one native module, so one environment holds one of them."""
    for version in ("3.10", "3.11", "3.14"):
        base = base_requirements(version)
        assert sandbox_versions.OCP in base
        assert sandbox_versions.BUILD123D in base
        assert sandbox_versions.CADQUERY_OCP not in base
        assert sandbox_versions.CADQUERY not in base
    assert sandbox_versions.OCP == sandbox_versions.CADQUERY_OCP_NOVTK


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


def _provisioned_runtime(tmp_path):
    """A bare runtime whose own environment holds what 'once()' gives it."""
    runtime = _bare_runtime(tmp_path / "sandbox")
    runtime.version = "3.11"
    os.makedirs(runtime.path, exist_ok=True)
    for requirement in base_requirements(runtime.version) + [sandbox_versions.ZSTD]:
        pathlib.Path(get_guard_path(runtime.path, requirement)).touch()
    return runtime


def _ask(runtime, session, *requirements):
    for requirement in requirements:
        PythonRuntime.ensure_onced(runtime, requirement, session=session)


def test_a_session_asking_only_for_the_base_has_no_layer(tmp_path):
    """Which is every build123d part, and every projection to SVG."""
    runtime = _provisioned_runtime(tmp_path)
    session = PythonRuntime.get_session(runtime, "//some:part")

    _ask(runtime, session, sandbox_versions.OCP_TESSELLATE, sandbox_versions.BUILD123D, sandbox_versions.OCP)

    assert session["dirty"] is False
    assert session["missing"] == []
    assert session["path"] is None
    assert PythonRuntime.environment_path(runtime, session) == runtime.path


def test_what_the_base_lacks_names_the_layer(tmp_path):
    runtime = _provisioned_runtime(tmp_path)
    session = PythonRuntime.get_session(runtime, "//some:part")

    _ask(runtime, session, sandbox_versions.NLOPT, sandbox_versions.CADQUERY, sandbox_versions.CADQUERY_OCP)

    assert session["dirty"] is True
    assert session["missing"] == [sandbox_versions.CADQUERY, sandbox_versions.CADQUERY_OCP]
    assert os.path.dirname(session["path"]) == runtime.path
    assert os.path.basename(session["path"]) == VENV_PREFIX + session["hash"]
    assert PythonRuntime.environment_path(runtime, session) == session["path"]


def test_runs_adding_the_same_packages_share_a_layer(tmp_path):
    """Every CadQuery part, whatever its package, and the 3MF export: one layer, provisioned once."""
    runtime = _provisioned_runtime(tmp_path)
    part = PythonRuntime.get_session(runtime, "//one:part")
    export = PythonRuntime.get_session(runtime, "export:3mf")
    other = PythonRuntime.get_session(runtime, "//other:part")

    _ask(runtime, part, sandbox_versions.CADQUERY, sandbox_versions.CADQUERY_OCP)
    _ask(runtime, export, sandbox_versions.CADQUERY_OCP, sandbox_versions.CADQUERY)
    _ask(runtime, other, sandbox_versions.CADQUERY, sandbox_versions.CADQUERY_OCP, "requests")

    assert part["path"] == export["path"]
    assert other["path"] != part["path"]


def test_a_session_never_installs_into_the_base(tmp_path, monkeypatch):
    """What it lacks is noted, and installed into its layer when it runs."""
    runtime = _provisioned_runtime(tmp_path)

    def refuse(*_args, **_kwargs):
        raise AssertionError("a session's requirement was installed into the sandbox's own environment")

    monkeypatch.setattr(type(runtime), "install_onced_locked", refuse, raising=False)
    session = PythonRuntime.get_session(runtime, "//some:part")

    _ask(runtime, session, sandbox_versions.CADQUERY)
    asyncio.run(PythonRuntime.ensure_async_onced(runtime, sandbox_versions.SVGLIB, session=session))

    assert session["missing"] == [sandbox_versions.CADQUERY, sandbox_versions.SVGLIB]


def test_an_install_into_the_base_after_provisioning_is_a_warning(tmp_path, monkeypatch):
    """The canary for a caller that should have used a session."""
    runtime = _locking_runtime(tmp_path)
    os.makedirs(runtime.path, exist_ok=True)
    warned = []
    monkeypatch.setattr(
        pc.logging, "warning", lambda message, *args: warned.append(message % args if args else message)
    )
    monkeypatch.setattr(type(runtime), "install_onced_locked", lambda *a, **k: None, raising=False)

    PythonRuntime.ensure_onced(runtime, sandbox_versions.SVGLIB)
    PythonRuntime.ensure_onced(runtime, sandbox_versions.SVGLIB, path=os.path.join(runtime.path, VENV_PREFIX + "x"))

    assert len(warned) == 1
    assert sandbox_versions.SVGLIB in warned[0]


def test_read_site_dirs_keeps_each_directory_once():
    """purelib and platlib are one directory nearly everywhere."""
    assert read_site_dirs(0, "/base/site\n/base/site\n", "") == ["/base/site"]
    assert read_site_dirs(0, "/base/lib\r\n/base/lib64\r\n", "") == ["/base/lib", "/base/lib64"]


def test_read_site_dirs_refuses_no_answer():
    with pytest.raises(Exception, match="no such interpreter"):
        read_site_dirs(1, "", "no such interpreter")
    with pytest.raises(Exception, match="exit code 0"):
        read_site_dirs(0, "", "")


def test_a_layer_that_could_not_be_made_says_why(tmp_path):
    with pytest.raises(Exception, match="disk full"):
        layer_created(str(tmp_path), 1, "disk full")
    with pytest.raises(Exception, match="exit code 2"):
        layer_linked(str(tmp_path), 2, "")
    assert not os.path.exists(get_guard_path(str(tmp_path), LAYER_GUARD))

    layer_linked(str(tmp_path), 0, "")
    assert os.path.exists(get_guard_path(str(tmp_path), LAYER_GUARD))


def _venv_python(venv):
    if os.name == "nt":
        return os.path.join(venv, "Scripts", "python.exe")
    return os.path.join(venv, "bin", "python")


def test_a_layer_sees_the_base_after_its_own_packages(tmp_path):
    """The mechanism itself, with a real interpreter: what makes a layer a layer.

    A module only the base has is found through the .pth file, and one both
    have is the layer's -- which is how CadQuery's OCP build in its layer wins
    over the build the base holds.
    """
    base = tmp_path / "base"
    base.mkdir()
    (base / "only_in_base.py").write_text("WHERE = 'base'\n")
    (base / "in_both.py").write_text("WHERE = 'base'\n")
    layer = tmp_path / (VENV_PREFIX + "layer")
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(layer)], check=True)
    python = _venv_python(str(layer))

    linked = subprocess.run([python, *LINK_LAYER_COMMAND, str(base)], capture_output=True, text=True)
    assert linked.returncode == 0, linked.stderr
    purelib = subprocess.run(
        [python, "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert (pathlib.Path(purelib) / LAYER_PTH).read_text().splitlines() == [str(base)]
    (pathlib.Path(purelib) / "in_both.py").write_text("WHERE = 'layer'\n")

    found = subprocess.run(
        [python, "-c", "import only_in_base, in_both; print(only_in_base.WHERE, in_both.WHERE)"],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    assert found.returncode == 0, found.stderr
    assert found.stdout.split() == ["base", "layer"]


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
    assert _SRC.is_dir(), _SRC
    offenders = []
    for path in sorted(_SRC.rglob("*.py")):
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
    runtime.sandbox = "conda"
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


def test_a_session_with_a_layer_locks_the_layer(tmp_path):
    runtime = _locking_runtime(tmp_path)
    session = PythonRuntime.get_session(runtime, "//some:package")
    _ask(runtime, session, sandbox_versions.CADQUERY)

    assert PythonRuntime.environment_path(runtime, session) == session["path"]
    assert PythonRuntime.environment_lock(runtime, session).lock_path.endswith(
        ".pc-py-conda-3.11.%s.lock" % session["hash"]
    )
    assert PythonRuntime.environment_lock(runtime, session) is not PythonRuntime.environment_lock(runtime, None)


def test_a_session_needs_its_layer_for_writing_only_until_it_is_provisioned(tmp_path):
    """Which is what lets the parts sharing a layer render together rather than in turn.

    Read from the layer's guards, which every session asking for the layer
    sees, rather than from what one session has seen installed: a part's
    first run must not take the layer for writing because some other part
    provisioned it.
    """
    runtime = _locking_runtime(tmp_path)
    session = PythonRuntime.get_session(runtime, "//some:package")

    assert not PythonRuntime.session_needs_install(runtime, None)
    assert not PythonRuntime.session_needs_install(runtime, session)

    _ask(runtime, session, sandbox_versions.CADQUERY)
    assert PythonRuntime.session_needs_install(runtime, session)

    os.makedirs(session["path"])
    pathlib.Path(get_guard_path(session["path"], sandbox_versions.CADQUERY)).touch()
    assert PythonRuntime.session_needs_install(runtime, session), "a layer not linked to its base yet"
    pathlib.Path(get_guard_path(session["path"], LAYER_GUARD)).touch()
    assert not PythonRuntime.session_needs_install(runtime, session)

    another = PythonRuntime.get_session(runtime, "//another:package")
    _ask(runtime, another, sandbox_versions.CADQUERY)
    assert not PythonRuntime.session_needs_install(runtime, another)

    _ask(runtime, session, "something-else==1.0")
    assert PythonRuntime.session_needs_install(runtime, session)


def _record_provisioning(runtime, monkeypatch):
    """What provisioning a layer runs and installs, without running or installing it."""
    done = []

    def run(self, cmd, stdin="", cwd=None, session=None, path=None):
        done.append(("run", list(cmd), path))
        if list(cmd)[: len(LINK_LAYER_COMMAND)] == list(LINK_LAYER_COMMAND):
            return 0, "", ""
        if list(cmd)[:2] == ["-m", "venv"]:
            os.makedirs(cmd[-1])
            return 0, "", ""
        return 0, "/base/site-packages\n", ""

    async def run_async(self, cmd, stdin="", cwd=None, session=None, path=None):
        return run(self, cmd, stdin, cwd, session, path)

    def ensure(self, package, session=None, path=None, force=False):
        done.append(("install", package, path))
        pathlib.Path(get_guard_path(path, package)).touch()

    async def ensure_async(self, package, session=None, path=None, force=False):
        ensure(self, package, session, path, force)

    def check(self, path=None):
        done.append(("check", path))

    async def check_async(self, path=None):
        check(self, path)

    monkeypatch.setattr(type(runtime), "run_onced_locked", run, raising=False)
    monkeypatch.setattr(type(runtime), "run_async_onced_locked", run_async, raising=False)
    monkeypatch.setattr(type(runtime), "ensure_onced_locked", ensure, raising=False)
    monkeypatch.setattr(type(runtime), "ensure_async_onced_locked", ensure_async, raising=False)
    monkeypatch.setattr(type(runtime), "check_deps_onced_locked", check, raising=False)
    monkeypatch.setattr(type(runtime), "check_deps_async_onced_locked", check_async, raising=False)
    return done


@pytest.mark.parametrize("asynchronous", [False, True])
def test_a_layer_is_made_linked_and_given_what_it_adds(tmp_path, monkeypatch, asynchronous):
    runtime = _locking_runtime(tmp_path)
    runtime.base_site_dirs = None
    done = _record_provisioning(runtime, monkeypatch)
    session = PythonRuntime.get_session(runtime, "//some:package")
    _ask(runtime, session, sandbox_versions.CADQUERY, sandbox_versions.CADQUERY_OCP)

    def provision(session):
        if asynchronous:
            asyncio.run(PythonRuntime.provision_layer_async_onced_locked(runtime, session))
        else:
            PythonRuntime.provision_layer_onced_locked(runtime, session)

    provision(session)

    layer = session["path"]
    assert done == [
        ("run", ["-m", "venv", "--upgrade-deps", layer], None),
        ("run", list(BASE_SITE_DIRS_COMMAND), None),
        ("run", [*LINK_LAYER_COMMAND, "/base/site-packages"], layer),
        ("install", sandbox_versions.CADQUERY, layer),
        ("install", sandbox_versions.CADQUERY_OCP, layer),
        ("check", layer),
    ]
    assert not PythonRuntime.session_needs_install(runtime, session)

    # A layer whose directory is there already -- its creation was interrupted
    # before it was linked -- is linked and given what it adds, and the base
    # is not asked where its packages are a second time.
    del done[:]
    other = PythonRuntime.get_session(runtime, "//other:package")
    _ask(runtime, other, sandbox_versions.CADQUERY, "something-else==1.0")
    os.makedirs(other["path"])
    provision(other)
    assert done == [
        ("run", [*LINK_LAYER_COMMAND, "/base/site-packages"], other["path"]),
        ("install", sandbox_versions.CADQUERY, other["path"]),
        ("install", "something-else==1.0", other["path"]),
    ]


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
