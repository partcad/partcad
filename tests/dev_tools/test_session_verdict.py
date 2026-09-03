#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The repository-root `conftest.py` hook that records a pytest session's verdict.

Two gates read that verdict instead of pytest's exit code -- the pre-commit hook
and the `Pytest` job in CI -- so what it writes decides whether a commit lands
and whether a build is green. The property that keeps that safe is narrow: it
may forgive an exit code that contradicts a clean session, and nothing else. So
these check both halves, and in particular that every way a run can be *not*
clean still writes "failure".

Most of it is checked by driving the hook directly, which is quick and lets a
session be posed in states that are awkward to produce for real. The last two
run pytest for real, in a subprocess, because what they are about is *when* the
hook runs relative to pytest's own -- something no stand-in can show.

The module is loaded by path rather than imported by name. `pyproject.toml` puts
`ide/standalone/tests` on `pythonpath` so its own tests can do
`from conftest import REPO_ROOT`, which means a bare `import conftest` here would
find that file instead of this one.
"""

import importlib.util
import os
import pathlib
import subprocess
import sys
import textwrap
import types

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CONFTEST = REPO_ROOT / "conftest.py"


def load_root_conftest():
    """The real repository-root conftest, as a module of its own."""
    spec = importlib.util.spec_from_file_location("partcad_root_conftest", CONFTEST)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def root_conftest():
    """Module-scoped: the file is read once, and nothing here mutates it."""
    return load_root_conftest()


def session(exitstatus=0, testsfailed=0, invocation_dir=None, worker=False):
    """The parts of a `pytest.Session` the hook actually reads."""
    config = types.SimpleNamespace(
        invocation_params=types.SimpleNamespace(dir=invocation_dir or pathlib.Path.cwd()),
    )
    if worker:
        config.workerinput = {}
    return types.SimpleNamespace(config=config, exitstatus=exitstatus, testsfailed=testsfailed)


def run_hook(root_conftest, session_obj, argument_exitstatus=0):
    """Drive the hook the way pluggy drives a wrapper: run to the yield, then resume.

    The default `argument_exitstatus` is deliberately the *clean* one, so that a
    caller passing an unclean `session.exitstatus` is asking whether the hook
    reads the session rather than the argument.
    """
    generator = root_conftest.pytest_sessionfinish(session_obj, argument_exitstatus)
    next(generator)
    try:
        generator.send(None)
    except StopIteration:
        pass


def test_the_hook_is_a_no_op_without_a_marker_path(root_conftest, tmp_path, monkeypatch):
    """Nobody asked for a verdict, so nothing is written anywhere."""
    monkeypatch.delenv("PYTEST_RESULT_MARKER", raising=False)
    monkeypatch.chdir(tmp_path)

    run_hook(root_conftest, session())

    assert list(tmp_path.iterdir()) == []


def test_a_clean_session_is_recorded_as_a_success(root_conftest, tmp_path, monkeypatch):
    """The only case that may write "success", and the only one a gate accepts."""
    marker = tmp_path / "verdict"
    monkeypatch.setenv("PYTEST_RESULT_MARKER", str(marker))

    run_hook(root_conftest, session(exitstatus=0, testsfailed=0))

    assert marker.read_text() == "success"


@pytest.mark.parametrize(
    "exitstatus, testsfailed, why",
    [
        (1, 1, "a test failed"),
        (2, 0, "the run was interrupted, which is also how a collection error ends"),
        (3, 0, "an internal error"),
        (4, 0, "pytest was misused"),
        (5, 0, "no tests were collected, so nothing passed"),
        (6, 0, "more warnings than --max-warnings allows"),
        (0, 1, "exit status 0 with a failed test, which is why this hook exists"),
    ],
)
def test_anything_but_a_clean_session_is_recorded_as_a_failure(
    root_conftest, tmp_path, monkeypatch, exitstatus, testsfailed, why
):
    """Every other way a session can end, including the two that look like success.

    Exit status 5 means nothing was collected, which a gate must not read as a
    pass; and exit status 0 with a failed test is the Windows behaviour #444 was
    written for. Between them they are why the verdict needs both halves rather
    than either alone.
    """
    marker = tmp_path / "verdict"
    monkeypatch.setenv("PYTEST_RESULT_MARKER", str(marker))

    run_hook(root_conftest, session(exitstatus=exitstatus, testsfailed=testsfailed))

    assert marker.read_text() == "failure", why


def test_the_session_decides_the_verdict_rather_than_the_argument(root_conftest, tmp_path, monkeypatch):
    """The `exitstatus` argument can be stale by the time this hook writes.

    pytest's terminal reporter raises `session.exitstatus` after the inner
    session hooks have run, so the argument is the status *before* that. Reading
    the argument is what would let a `--max-warnings` failure be recorded as a
    success; this pins the hook to the session instead.
    """
    marker = tmp_path / "verdict"
    monkeypatch.setenv("PYTEST_RESULT_MARKER", str(marker))

    run_hook(root_conftest, session(exitstatus=6), argument_exitstatus=0)

    assert marker.read_text() == "failure"


def test_an_xdist_worker_writes_no_verdict(root_conftest, tmp_path, monkeypatch):
    """Only the controller sees the aggregate result.

    A worker's `testsfailed` counts its own subset, so letting one write would
    let the last worker to finish overwrite the controller's verdict with a
    "success" that speaks for a fraction of the run.
    """
    marker = tmp_path / "verdict"
    monkeypatch.setenv("PYTEST_RESULT_MARKER", str(marker))

    run_hook(root_conftest, session(worker=True))

    assert not marker.exists()


def test_a_relative_marker_is_anchored_to_the_invocation_directory(root_conftest, tmp_path, monkeypatch):
    """CI passes a relative path, and a test may have changed directory since.

    The two have to name the same file: on Windows the caller is Git Bash and
    the session is a native interpreter, and the one thing they agree on is the
    directory pytest was started in.
    """
    invocation_dir = tmp_path / "workspace"
    invocation_dir.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv("PYTEST_RESULT_MARKER", "results/verdict")
    monkeypatch.chdir(elsewhere)

    run_hook(root_conftest, session(invocation_dir=invocation_dir))

    assert (invocation_dir / "results" / "verdict").read_text() == "success"
    assert not (elsewhere / "results").exists()


def test_the_hook_is_the_outermost_wrapper(root_conftest):
    """A wrapper, and `tryfirst`, so that it writes after every other session hook.

    pytest's terminal reporter is a wrapper here too, and it can still raise
    `session.exitstatus` after the inner hooks return. Only the outermost
    wrapper's code after the yield is guaranteed to see that final status.
    """
    options = root_conftest.pytest_sessionfinish.pytest_impl
    assert options["wrapper"] is True
    assert options["tryfirst"] is True


def test_the_repository_root_is_where_the_hook_lives():
    """It used to live beside one package's tests, and recorded nothing for a
    run that did not collect that directory. Both gates now pass paths of their
    own choosing, so the hook has to be somewhere every run loads."""
    assert CONFTEST.is_file()
    assert "pytest_sessionfinish" not in (REPO_ROOT / "tests" / "partcad" / "conftest.py").read_text()


def test_it_needs_nothing_from_partcad(root_conftest):
    """The gate must record a verdict even for a run that could not import the
    package under test, so the hook imports only the standard library and
    pytest."""
    assert CONFTEST.is_file()
    source = CONFTEST.read_text()
    for line in source.splitlines():
        if line.startswith(("import ", "from ")):
            module = line.split()[1].split(".")[0]
            assert module in sys.stdlib_module_names or module == "pytest", line


def real_pytest_run(tmp_path, *arguments):
    """Run pytest for real, in its own process, with the repository's own hook.

    A stand-in session cannot show *when* this hook runs relative to pytest's
    own, which is the whole of what the two tests below are about. The copy is
    the real file; `cwd` is a directory with no `pyproject.toml`, so the
    repository's `addopts` do not follow it in.
    """
    (tmp_path / "conftest.py").write_text(CONFTEST.read_text())
    (tmp_path / "test_warns.py").write_text(textwrap.dedent("""
            import warnings

            def test_warns():
                warnings.warn("a warning", UserWarning)
            """))
    marker = tmp_path / "verdict"
    environment = dict(os.environ, PYTEST_RESULT_MARKER=str(marker))
    environment.pop("PYTEST_ADDOPTS", None)

    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", *arguments],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )
    return completed, marker.read_text() if marker.exists() else None


def test_a_real_clean_run_records_a_success(tmp_path):
    """The control for the regression below: without the flag, this run passes.

    Without it the test below would pass even if the hook had stopped writing
    anything at all.
    """
    completed, verdict = real_pytest_run(tmp_path)

    assert completed.returncode == 0, completed.stdout
    assert verdict == "success"


def test_a_real_max_warnings_failure_records_a_failure(tmp_path):
    """The regression: pytest raises the status after the inner session hooks run.

    The same run, with `--max-warnings=0`, exits 6 while every test passed. A
    hook reading its `exitstatus` argument records "success" here and the gate
    accepts a session pytest called a failure.
    """
    completed, verdict = real_pytest_run(tmp_path, "--max-warnings=0")

    assert completed.returncode == 6, completed.stdout
    assert verdict == "failure"
