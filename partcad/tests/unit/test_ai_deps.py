#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

"""Tests for partcad.ai_deps.import_optional().

These verify that import_optional() only reports a "missing optional extra"
(AiProviderDependencyError) when the module that failed to import is the
requested module itself or an ancestor package of it. When a deeper submodule
of an otherwise-installed SDK fails to import (same root package, but not an
ancestor of the requested module), the original ModuleNotFoundError must
propagate untouched instead of being masked as a missing extra.
"""

import importlib
import sys
import textwrap

import pytest

from partcad.ai_deps import AiProviderDependencyError, import_optional


def test_missing_top_level_module_raises_dependency_error():
    """A wholly absent top-level module is reported as a missing extra."""
    module_name = "partcad_totally_absent_sdk_xyz"
    # Make sure the module really is not importable.
    assert module_name not in sys.modules

    with pytest.raises(AiProviderDependencyError) as excinfo:
        import_optional(module_name, "Fake", "ai-fake")

    # The original ModuleNotFoundError is chained for context.
    assert isinstance(excinfo.value.__cause__, ModuleNotFoundError)
    # The install command names the extra.
    assert "ai-fake" in str(excinfo.value)


def test_missing_parent_package_of_submodule_raises_dependency_error():
    """Requesting a submodule whose parent package is absent is a missing extra."""
    parent = "partcad_absent_parent_pkg_xyz"
    module_name = parent + ".Image"
    assert parent not in sys.modules

    with pytest.raises(AiProviderDependencyError) as excinfo:
        import_optional(module_name, "Fake", "ai-fake")

    cause = excinfo.value.__cause__
    assert isinstance(cause, ModuleNotFoundError)
    # The failure was the parent package, which is an ancestor of the request.
    assert cause.name == parent


def test_installed_package_with_broken_internal_import_reraises_original(tmp_path):
    """An installed package that internally imports a missing same-root submodule
    must surface the ORIGINAL ModuleNotFoundError, not AiProviderDependencyError.
    """
    # Build a real, installed package on sys.path whose __init__ imports a
    # sibling submodule that does not exist. Its root matches the requested
    # module's root, but the missing module is NOT an ancestor of the request.
    pkg_name = "partcad_broken_sdk_xyz"
    pkg_dir = tmp_path / pkg_name
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text(
        textwrap.dedent(
            f"""
            import {pkg_name}.missing_sub  # noqa: F401  (this submodule does not exist)
            """
        )
    )

    sys.path.insert(0, str(tmp_path))
    try:
        # Sanity check: the package directory exists and is importable as a
        # location, but the internal import fails deep inside.
        with pytest.raises(ModuleNotFoundError) as excinfo:
            import_optional(pkg_name, "Fake", "ai-fake")

        # The original error propagated untouched...
        assert not isinstance(excinfo.value, AiProviderDependencyError)
        # ...and it points at the broken internal submodule, not the package.
        assert excinfo.value.name == f"{pkg_name}.missing_sub"
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop(pkg_name, None)
        importlib.invalidate_caches()


def test_broken_internal_import_reraises_via_monkeypatch(monkeypatch):
    """Same guarantee as above, proven deterministically without a real package:
    if import_module raises ModuleNotFoundError(name="pkg.sub") for module "pkg",
    the original error must propagate (pkg.sub is not an ancestor of pkg).
    """

    def fake_import(name, *args, **kwargs):
        raise ModuleNotFoundError("No module named 'pkg.sub'", name="pkg.sub")

    monkeypatch.setattr(importlib, "import_module", fake_import)

    with pytest.raises(ModuleNotFoundError) as excinfo:
        import_optional("pkg", "Fake", "ai-fake")

    assert not isinstance(excinfo.value, AiProviderDependencyError)
    assert excinfo.value.name == "pkg.sub"
