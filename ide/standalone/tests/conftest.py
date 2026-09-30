#
# PartCAD, 2026
#
# Author: PartCAD (support@partcad.org)
#
# Licensed under Apache License, Version 2.0.
#

import pathlib
import sys

# The tools are scripts rather than an installed package: they run inside a
# build, from a checkout, with nothing installed but their dependencies.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

# So that the test modules beside this one can `from conftest import ...`.
#
# Under pytest's default "prepend" import mode this file is already in
# `sys.modules` as `conftest` and the line does nothing. Under `--import-mode
# importlib` -- which is what `pyproject.toml` sets repository-wide, and what
# every `pytest` run that does not pass `-o addopts=` therefore uses -- it is
# imported under a generated name instead, no directory goes on `sys.path`, and
# every module here dies at collection with `ModuleNotFoundError: No module
# named 'conftest'`. Codecov has been recording exactly that against `main`.
sys.modules.setdefault("conftest", sys.modules[__name__])

# Three levels up: this file is <repo>/ide/standalone/tests/conftest.py. The
# component used to sit one level shallower, at <repo>/partcad-ide-standalone/.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
COMPONENT_ROOT = pathlib.Path(__file__).resolve().parents[1]
