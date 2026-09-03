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

The module is loaded by path rather than imported by name. `pyproject.toml` puts
`ide/standalone/tests` on `pythonpath` so its own tests can do
`from conftest import REPO_ROOT`, which means a bare `import conftest` here would
find that file instead of this one.
"""

import importlib.util
import pathlib
import sys
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


def session(testsfailed=0, invocation_dir=None, worker=False):
    """The parts of a `pytest.Session` the hook actually reads."""
    config = types.SimpleNamespace(
        invocation_params=types.SimpleNamespace(dir=invocation_dir or pathlib.Path.cwd()),
    )
    if worker:
        config.workerinput = {}
    return types.SimpleNamespace(config=config, testsfailed=testsfailed)


def test_the_hook_is_a_no_op_without_a_marker_path(root_conftest, tmp_path, monkeypatch):
    """Nobody asked for a verdict, so nothing is written anywhere."""
    monkeypatch.delenv("PYTEST_RESULT_MARKER", raising=False)
    monkeypatch.chdir(tmp_path)

    root_conftest.pytest_sessionfinish(session(), 0)

    assert list(tmp_path.iterdir()) == []


def test_a_clean_session_is_recorded_as_a_success(root_conftest, tmp_path, monkeypatch):
    """The only case that may write "success", and the only one a gate accepts."""
    marker = tmp_path / "verdict"
    monkeypatch.setenv("PYTEST_RESULT_MARKER", str(marker))

    root_conftest.pytest_sessionfinish(session(testsfailed=0), 0)

    assert marker.read_text() == "success"


@pytest.mark.parametrize(
    "exitstatus, testsfailed, why",
    [
        (1, 1, "a test failed"),
        (2, 0, "the run was interrupted"),
        (3, 0, "an internal error"),
        (4, 0, "pytest was misused"),
        (5, 0, "no tests were collected, so nothing passed"),
        (0, 1, "pytest exited 0 with a failed test, which is why this hook exists"),
    ],
)
def test_anything_but_a_clean_session_is_recorded_as_a_failure(
    root_conftest, tmp_path, monkeypatch, exitstatus, testsfailed, why
):
    """Every other way a session can end, including the two that look like success.

    Exit status 5 means nothing was collected, which a gate must not read as a
    pass; and exit status 0 with a failed test is the Windows behaviour #444 was
    written for, which is why the verdict needs both halves rather than either.
    """
    marker = tmp_path / "verdict"
    monkeypatch.setenv("PYTEST_RESULT_MARKER", str(marker))

    root_conftest.pytest_sessionfinish(session(testsfailed=testsfailed), exitstatus)

    assert marker.read_text() == "failure", why


def test_an_xdist_worker_writes_no_verdict(root_conftest, tmp_path, monkeypatch):
    """Only the controller sees the aggregate result.

    A worker's `testsfailed` counts its own subset, so letting one write would
    let the last worker to finish overwrite the controller's verdict with a
    "success" that speaks for a fraction of the run.
    """
    marker = tmp_path / "verdict"
    monkeypatch.setenv("PYTEST_RESULT_MARKER", str(marker))

    root_conftest.pytest_sessionfinish(session(testsfailed=0, worker=True), 0)

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

    root_conftest.pytest_sessionfinish(session(invocation_dir=invocation_dir), 0)

    assert (invocation_dir / "results" / "verdict").read_text() == "success"
    assert not (elsewhere / "results").exists()


def test_the_hook_runs_last(root_conftest):
    """`trylast` so the verdict is written after every other session hook.

    One of those writes the HTML report the job uploads; a verdict recorded
    before them would be a verdict for a session that had not finished.
    """
    assert root_conftest.pytest_sessionfinish.pytest_impl["trylast"] is True


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
