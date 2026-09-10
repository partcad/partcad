#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Run pytest in a throwaway environment layered over this one.

A PartCAD test renders parts, and rendering a part provisions a Python sandbox
and pip-installs the CAD stack into it. Which directory that lands in is the
sandbox's business -- except for the `none` sandbox, whose whole definition is
"the interpreter you are already running", and that is the developer's own
environment. So a test suite that exercises it installs `cadquery`, and with it
the VTK-carrying `cadquery-ocp`, into the checkout's `.venv`: over the
`cadquery-ocp-novtk` that `poetry install` put there, and against the one thing
`pyproject.toml` says about that pair.

That is what this exists to contain, and it does not try to decide which test
was entitled to install what. `.venv-pytest` is an empty virtual environment
that *falls back* to the environment PartCAD is installed in: nothing is
installed in it to begin with, everything resolves through to the real
environment, and anything a test installs lands in it rather than in `.venv`.
Delete it and the next run builds another.

The fallback is one line in a `.pth` file, and the line matters:

    import site; site.addsitedir('<the real environment's site-packages>')

not the bare path a `.pth` more usually holds. A path line is appended to
`sys.path` and nothing else; `addsitedir` *processes* the `.pth` files it finds
in the directory, which is what makes an editable install visible -- and
PartCAD's own install is editable, so a bare path line would give a venv that
cannot import the thing under test.

It also decides the precedence, in the direction that makes the whole idea work.
The fallback is reached from `.venv-pytest`'s own `site-packages`, so that
directory comes first: a package installed here shadows the same package in
`.venv` rather than being shadowed by it, and the real environment is left
exactly as `poetry install` made it.

Usage -- everything after the script name is handed to pytest:

    poetry run python dev-tools/run_pytest.py tests cad/freecad -x --dist no
"""

import os
import shutil
import subprocess
import sys
import sysconfig
import venv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VENV_DIR = REPO_ROOT / ".venv-pytest"

# Named so that it is obvious in a directory listing what put it there, and
# sorts beside nothing else: it is the only file this environment has.
FALLBACK_PTH = "_partcad_fallback.pth"


def _interpreter(venv_dir: Path) -> Path:
    """The interpreter inside a virtual environment, on either layout."""
    for candidate in (venv_dir / "bin" / "python", venv_dir / "Scripts" / "python.exe"):
        if candidate.exists():
            return candidate
    return venv_dir / "bin" / "python"


def _scripts_dir(venv_dir: Path) -> Path:
    """Where that environment's console scripts go."""
    return venv_dir / ("Scripts" if os.name == "nt" else "bin")


def _fallback_line() -> str:
    """What the `.pth` has to say, for the environment this is running in."""
    return "import site; site.addsitedir(%r)\n" % sysconfig.get_paths()["purelib"]


# Its version and its `site-packages`, from the environment itself.
#
# Asked rather than worked out, because working it out is wrong on real
# machines. `sysconfig`'s default scheme is what the *running* interpreter
# installs under, and Debian and Ubuntu patch that to `posix_local`, which puts
# a `local/` segment in the middle -- so a path assembled here would name a
# directory the venv does not have, this would decide the environment was stale,
# and every run would rebuild it. Python 3.11 added a `venv` scheme that says
# exactly this, which would do; 3.10 is still supported here and has none.
_DESCRIBE = "import sys, sysconfig; print('%d.%d' % sys.version_info[:2]); print(sysconfig.get_paths()['purelib'])"


def _describe(interpreter: Path):
    """`(version, site-packages)` of that interpreter, or None if it cannot say."""
    try:
        said = subprocess.run(
            [str(interpreter), "-c", _DESCRIBE],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if said.returncode != 0:
        return None
    lines = said.stdout.splitlines()
    return (lines[0].strip(), Path(lines[1].strip())) if len(lines) >= 2 else None


def _is_current(venv_dir: Path) -> bool:
    """Whether the environment that is there is the one this run wants.

    Three ways it can be stale, and all three are cheap to check and expensive
    to get wrong: no interpreter (a half-made or half-deleted directory), an
    interpreter of another Python version (the checkout moved), or a fallback
    pointing somewhere other than where PartCAD is installed now (`poetry env
    use`, a conda environment on CI, a moved checkout).
    """
    interpreter = _interpreter(venv_dir)
    if not interpreter.exists():
        return False

    described = _describe(interpreter)
    if described is None:
        return False
    version, site_packages = described

    # The version the environment was built with, not the one this process is:
    # a venv whose base interpreter was upgraded in place still answers, and
    # answers for the interpreter it was built from.
    if version != "%d.%d" % sys.version_info[:2]:
        return False

    try:
        return (site_packages / FALLBACK_PTH).read_text() == _fallback_line()
    except OSError:
        return False


def _forget_ambient_sandboxes() -> None:
    """Drop the install guards of the sandbox that installs into this venv.

    PartCAD records what it installed into a sandbox as marker files beside it,
    and skips an install it has a marker for. The `none` sandbox's packages live
    in whichever environment is being run, so a fresh `.venv-pytest` holds none
    of them while the markers still claim they are there -- and the next render
    goes straight to a wrapper that fails on an import of something nobody
    installed. Deleting the markers costs one re-install and says the truth.

    Only `none`. Every other sandbox keeps its packages in its own directory,
    where they still are.

    The state directory is asked of PartCAD rather than assumed to be
    `~/.partcad`: it is configurable, and a second copy of that rule here would
    be a second copy that can disagree. Failing to work it out is not worth
    refusing to run tests over -- the cost is one confusing render, and the
    import failure names what is missing.
    """
    try:
        from partcad_utils.user_config import UserConfig

        sandboxes = Path(UserConfig().internal_state_dir) / "sandbox"
    except Exception as e:  # noqa: BLE001 - see the docstring
        print("Could not find PartCAD's state directory, leaving sandbox markers alone: %s" % e)
        return

    for stale in sorted(sandboxes.glob("pc-py-none-*")):
        print("Forgetting what was installed into the previous %s: %s" % (VENV_DIR.name, stale))
        shutil.rmtree(stale, ignore_errors=True)


def ensure_venv() -> Path:
    """`.venv-pytest`, made if it is not there and remade if it is stale."""
    if _is_current(VENV_DIR):
        return _interpreter(VENV_DIR)

    if VENV_DIR.exists():
        print("Rebuilding %s: it does not match this environment" % VENV_DIR)
        shutil.rmtree(VENV_DIR)

    print("Creating %s, empty, falling back to %s" % (VENV_DIR, sysconfig.get_paths()["purelib"]))
    # No pip of its own: it is reached through the fallback like everything
    # else, and it installs into the environment it is *run* from, which is this
    # one. So the environment really does start with nothing in it.
    venv.EnvBuilder(with_pip=False, clear=True).create(str(VENV_DIR))

    interpreter = _interpreter(VENV_DIR)
    described = _describe(interpreter)
    if described is None:
        raise SystemExit("%s was created but its interpreter does not run" % VENV_DIR)
    site_packages = described[1]
    site_packages.mkdir(parents=True, exist_ok=True)
    (site_packages / FALLBACK_PTH).write_text(_fallback_line())

    # The fallback is one path, worked out from where this interpreter installs
    # things, and if that is not where PartCAD actually is then the environment
    # just built can import nothing at all. Better to say so here, naming the
    # path that was tried, than to hand pytest an environment in which the
    # failure is "No module named pytest" a screen and a half later.
    proof = subprocess.run(
        [str(interpreter), "-c", "import pytest, partcad"],
        capture_output=True,
        text=True,
    )
    if proof.returncode != 0:
        raise SystemExit(
            "%s cannot see the environment it was layered over (%s):\n%s\n"
            "PartCAD and pytest have to be importable from the interpreter this was run with."
            % (VENV_DIR, sysconfig.get_paths()["purelib"], proof.stderr.strip())
        )

    _forget_ambient_sandboxes()
    return _interpreter(VENV_DIR)


def main(argv) -> int:
    # Already in there -- a test that shells out to this, or a developer who
    # activated it by hand. Making a second one inside the first would layer a
    # fallback on a fallback.
    if Path(sys.prefix).resolve() == VENV_DIR.resolve():
        return subprocess.run([sys.executable, "-m", "pytest", *argv]).returncode

    interpreter = ensure_venv()

    env = dict(os.environ)
    # Both halves of "this is the environment now". VIRTUAL_ENV is what a tool
    # asking which environment it is in reads; PATH is what PartCAD's `none`
    # sandbox reads, because it resolves its interpreter with `which python`
    # rather than from `sys.executable` -- so without this the pollution this
    # script exists to contain would go to the environment on PATH regardless.
    env["VIRTUAL_ENV"] = str(VENV_DIR)
    env["PATH"] = str(_scripts_dir(VENV_DIR)) + os.pathsep + env.get("PATH", "")
    env.pop("PYTHONHOME", None)

    # Not `os.exec*`: on Windows it replaces the process in a way the calling
    # shell sees as an immediate exit, and the exit code is what every caller of
    # this script -- the pre-commit hook, the CI job -- goes on to check.
    return subprocess.run([str(interpreter), "-m", "pytest", *argv], env=env).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
