#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What the repository-root `conftest.py` does about a test that never returns.

`pyproject.toml` gives every test a timeout (pytest-timeout) and a later
watchdog (faulthandler), so that a hung test fails naming itself instead of
running into the job's `timeout-minutes`, which names nothing. Each of these
runs pytest for real, in its own process, with the real conftest: what they are
about is where a report goes and whether a watch is still set, which only a
real run shows.
"""

import os
import pathlib
import subprocess
import sys
import textwrap

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CONFTEST = REPO_ROOT / "conftest.py"


def run_pytest(tmp_path, test_source, *arguments, timeout):
    """Run one test file under the repository's conftest, without its `addopts`.

    `cwd` is a directory with no `pyproject.toml`, so the repository's `addopts`
    and its own `timeout` do not follow the run in; each test passes what it is
    about on the command line.
    """
    (tmp_path / "conftest.py").write_text(CONFTEST.read_text())
    (tmp_path / "test_stuck.py").write_text(textwrap.dedent(test_source))
    environment = dict(os.environ)
    environment.pop("PYTEST_ADDOPTS", None)
    environment.pop("PYTEST_RESULT_MARKER", None)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *arguments, "test_stuck.py"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def test_a_worker_ended_by_the_thread_method_says_where_it_was(tmp_path):
    """The thread method's report reaches the log from an xdist worker.

    pytest-timeout's thread method -- the only one on Windows -- writes its
    report to stdout before it ends the process, and a worker's stdout is the
    null device. `Pytest (windows-2022, 3.14)` lost three tests that way at
    once, reported as nothing but the workers that crashed. Written where
    faulthandler writes, the report names the test and shows what it had
    logged, what it had printed and the line it was stuck on.
    """
    pytest.importorskip("pytest_timeout")
    pytest.importorskip("xdist")

    completed = run_pytest(
        tmp_path,
        """
        import logging
        import time

        def test_never_returns():
            logging.getLogger("partcad").warning("making the sandbox")
            print("waiting for it")
            time.sleep(600)  # the line it is stuck on
        """,
        "-n",
        "1",
        "--timeout",
        "2",
        "--timeout-method",
        "thread",
        timeout=120,
    )

    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert "crashed while running 'test_stuck.py::test_never_returns'" in completed.stdout
    assert "test_stuck.py::test_never_returns ran for more than 2s" in completed.stderr
    assert "making the sandbox" in completed.stderr
    assert "waiting for it" in completed.stderr
    assert "time.sleep(600)  # the line it is stuck on" in completed.stderr


def test_the_teardown_of_a_failed_test_is_still_watched(tmp_path):
    """faulthandler's watch is set again for what is left of a test that failed.

    Both plugins cancel their timer when a test fails, so that a debugger is not
    interrupted, and neither sets it again: a fixture that then hung in its
    teardown ran until the job's own limit. Here it is dumped and ended at the
    watchdog's two seconds; without the conftest's hook this run outlives the
    subprocess timeout instead.
    """
    completed = run_pytest(
        tmp_path,
        """
        import time

        import pytest

        @pytest.fixture
        def stuck_on_the_way_out():
            yield
            time.sleep(600)

        def test_fails(stuck_on_the_way_out):
            assert False
        """,
        "-p",
        "no:timeout",
        "-o",
        "faulthandler_timeout=2",
        "-o",
        "faulthandler_exit_on_timeout=true",
        timeout=120,
    )

    assert completed.returncode != 0, completed.stdout + completed.stderr
    assert "Timeout (0:00:02)!" in completed.stderr
    assert "stuck_on_the_way_out" in completed.stderr
