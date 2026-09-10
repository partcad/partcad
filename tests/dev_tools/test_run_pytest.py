#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The empty environment the suite is run in, and what makes it work.

`dev-tools/run_pytest.py` layers a `.venv-pytest` with nothing in it over the
environment PartCAD is installed in, so that a test which provisions the `none`
sandbox -- whose packages go into whichever interpreter is running -- installs
there rather than into the checkout's `.venv`.

Two things about it are load-bearing and neither is obvious from reading it, so
they are pinned here. The `.pth` has to *execute* `site.addsitedir` rather than
name a path, or an editable install on the other side is invisible and the
environment cannot import the thing under test. And the layering has to resolve
in one direction: the empty environment first, the real one behind it, so that
what a test installs shadows what is already there instead of the reverse.

The module is loaded by path, like `test_session_verdict.py` beside it and for
the same reason: it is not on `sys.path` and is not meant to be.
"""

import importlib.util
import pathlib
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "dev-tools" / "run_pytest.py"


def load():
    spec = importlib.util.spec_from_file_location("partcad_run_pytest", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# The fallback line                                                            #
# --------------------------------------------------------------------------- #


def test_the_fallback_executes_rather_than_naming_a_path():
    """A bare path line would leave an editable install unreachable.

    Python appends a path line to 'sys.path' and stops there. 'addsitedir' also
    *processes* the '.pth' files it finds in that directory, and an editable
    install is one of those -- so the difference between the two spellings is
    whether the environment can import PartCAD itself.
    """
    line = load()._fallback_line()

    assert line.startswith("import site; site.addsitedir(")
    assert line.endswith("\n")


def test_the_fallback_names_where_this_interpreter_installs_things():
    import sysconfig

    assert sysconfig.get_paths()["purelib"] in load()._fallback_line()


# --------------------------------------------------------------------------- #
# When it is rebuilt                                                           #
# --------------------------------------------------------------------------- #


def test_an_environment_that_is_not_there_is_not_current(tmp_path):
    assert load()._is_current(tmp_path / "nothing-here") is False


def test_an_interpreter_that_does_not_run_is_not_current(tmp_path):
    """A half-made or half-deleted directory, which is what an interrupted run leaves."""
    interpreter = tmp_path / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text("not an interpreter")
    interpreter.chmod(0o755)

    assert load()._is_current(tmp_path) is False


# --------------------------------------------------------------------------- #
# The layering, actually built                                                 #
# --------------------------------------------------------------------------- #


@pytest.mark.slow
def test_the_environment_is_empty_and_sees_through_to_this_one(tmp_path):
    """Both halves of the claim, from the environment itself.

    Empty: one file, the '.pth'. Seeing through: pytest resolves, and so does
    PartCAD -- which is installed editable here, so it is the assertion the
    spelling of the '.pth' is really about.
    """
    module = load()
    module.VENV_DIR = tmp_path / ".venv-pytest"
    # Not the real one: this is a temporary environment, and the markers of the
    # sandbox that installs into the *real* one are none of its business.
    module._forget_ambient_sandboxes = lambda: None

    interpreter = module.ensure_venv()
    site_packages = module._describe(interpreter)[1]

    assert [f.name for f in site_packages.iterdir()] == [module.FALLBACK_PTH]

    seen = subprocess.run(
        [str(interpreter), "-c", "import pytest, partcad; print(pytest.__file__); print(partcad.__file__)"],
        capture_output=True,
        text=True,
    )
    assert seen.returncode == 0, seen.stderr
    assert str(REPO_ROOT / "src" / "partcad") in seen.stdout, seen.stdout


@pytest.mark.slow
def test_what_is_installed_here_shadows_what_is_installed_there(tmp_path):
    """The direction of the layering, which is the whole point of it.

    'sys.path' has to reach the empty environment before the real one, or an
    install a test makes would be shadowed by the copy in '.venv' and the test
    would go on seeing the version it was trying to replace.
    """
    module = load()
    module.VENV_DIR = tmp_path / ".venv-pytest"
    module._forget_ambient_sandboxes = lambda: None

    interpreter = module.ensure_venv()
    mine, theirs = module._describe(interpreter)[1], pathlib.Path(_purelib())

    order = subprocess.run(
        [str(interpreter), "-c", "import sys; print('\\n'.join(sys.path))"],
        capture_output=True,
        text=True,
    )
    assert order.returncode == 0, order.stderr
    path = [p for p in order.stdout.splitlines() if p]

    assert str(mine) in path, path
    assert str(theirs) in path, path
    assert path.index(str(mine)) < path.index(str(theirs)), path


def _purelib():
    import sysconfig

    return sysconfig.get_paths()["purelib"]


# --------------------------------------------------------------------------- #
# Running inside it                                                            #
# --------------------------------------------------------------------------- #


def test_running_from_inside_it_does_not_layer_a_second_one(tmp_path, monkeypatch):
    """A test that shells out to this, or a developer who activated it by hand."""
    module = load()
    module.VENV_DIR = tmp_path / ".venv-pytest"
    monkeypatch.setattr(sys, "prefix", str(module.VENV_DIR))

    def refuse():
        raise AssertionError("built a second environment inside the first")

    module.ensure_venv = refuse
    calls = []
    module.subprocess = _recording(calls)

    module.main(["-q", "somewhere"])

    assert calls and calls[0][0][0] == sys.executable
    assert calls[0][0][1:] == ["-m", "pytest", "-q", "somewhere"]


def _recording(calls):
    class _Subprocess:
        @staticmethod
        def run(argv, **kwargs):
            calls.append((argv, kwargs))

            class _Completed:
                returncode = 0

            return _Completed()

    return _Subprocess
