#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""Regression tests for the ruff optional-dependency guard in ``partcad.lint.python``.

``ruff_once()`` resolves the ``ruff`` executable by importing ``ruff.__main__``.
When that import fails it has to tell two situations apart:

  * the ``ruff`` extra is not installed -> raise ``LintDependencyError`` naming
    the install command, and
  * ``ruff`` is installed but internally broken (it fails to import one of its
    own submodules, or an unrelated dependency) -> let the original
    ``ModuleNotFoundError`` propagate untouched.

The latent bug guarded against here (the same one flagged on PR #436) compared
only the *root* package, so an installed-but-broken ``ruff`` that failed to
import one of its own ``ruff.<submodule>`` modules was misreported as a missing
extra. The fix treats the failure as a missing extra only when the module that
actually failed to import IS the requested module or an ancestor of it.

The tests monkeypatch ``importlib.import_module`` so they never depend on whether
``ruff`` is really installed in the environment.
"""

import importlib

import pytest

from partcad.lint import python as lint_python
from partcad.lint.python import LintDependencyError


@pytest.fixture(autouse=True)
def _reset_ruff_cache(monkeypatch):
    """``ruff_once()`` memoizes its result in module globals; clear them per test.

    Without this, a cached ``ruff_main``/``ruff_bin`` from a real import earlier
    in the session would short-circuit the import and the monkeypatched
    ``import_module`` below would never run.
    """
    monkeypatch.setattr(lint_python, "ruff_main", None)
    monkeypatch.setattr(lint_python, "ruff_bin", None)


def _import_module_missing(missing_name):
    """A stand-in for ``importlib.import_module`` that always fails on ``missing_name``."""

    def fake_import_module(name):
        raise ModuleNotFoundError(f"No module named {missing_name!r}", name=missing_name)

    return fake_import_module


def test_missing_top_level_package_reports_missing_extra(monkeypatch):
    # `ruff` itself is absent: importing `ruff.__main__` fails naming `ruff`,
    # which is an ancestor of the requested module -> missing extra.
    monkeypatch.setattr(importlib, "import_module", _import_module_missing("ruff"))

    with pytest.raises(LintDependencyError):
        lint_python.ruff_once()


def test_missing_requested_submodule_reports_missing_extra(monkeypatch):
    # The requested module `ruff.__main__` is itself the one reported missing
    # -> missing extra.
    monkeypatch.setattr(importlib, "import_module", _import_module_missing("ruff.__main__"))

    with pytest.raises(LintDependencyError):
        lint_python.ruff_once()


def test_installed_but_broken_package_propagates_original_error(monkeypatch):
    # `ruff` is installed but internally fails to import one of its own
    # same-root submodules. That is real breakage, not a missing extra, so the
    # original ModuleNotFoundError must propagate unchanged.
    monkeypatch.setattr(importlib, "import_module", _import_module_missing("ruff.foo"))

    with pytest.raises(ModuleNotFoundError) as excinfo:
        lint_python.ruff_once()

    assert not isinstance(excinfo.value, LintDependencyError)
    assert excinfo.value.name == "ruff.foo"
