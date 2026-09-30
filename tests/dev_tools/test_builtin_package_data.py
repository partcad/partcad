#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Every file a '//builtin' package is made of has to be in the wheel.

`src/partcad/builtin/` holds no Python that is ever *imported*: a 'partcad.yaml'
that is read as a package, and scripts that are executed by path inside a
sandbox. So nothing about them is a module reference that a build would notice
breaking -- they are data, and data reaches an installation only if
`[tool.setuptools.package-data]` names a pattern that matches it.

A directory added there without an entry is therefore absent from the wheel,
silently: the source checkout and the editable install go on working (they read
the working tree), the PyInstaller bundles go on working (the spec copies the
whole directory), and only an installed wheel fails -- at the moment PartCAD
tries to load the package, with a path into site-packages and nothing to say why
it is not there. That is what `Examples (PartCAD)` failed on for `//builtin/import`
on #637, after two entries were added to this table and two were not.
"""

import os
import sys

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - the repository's floor is 3.10
    tomllib = pytest.importorskip("tomli")

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BUILTIN_DIR = os.path.join(REPO_ROOT, "src", "partcad", "builtin")


def package_data():
    with open(os.path.join(REPO_ROOT, "pyproject.toml"), "rb") as f:
        return tomllib.load(f)["tool"]["setuptools"]["package-data"]


def builtin_packages():
    return sorted(
        entry
        for entry in os.listdir(BUILTIN_DIR)
        if os.path.isdir(os.path.join(BUILTIN_DIR, entry)) and entry != "__pycache__"
    )


def test_every_builtin_package_is_named():
    """A directory with no entry of its own ships nothing at all."""
    declared = package_data()

    for name in builtin_packages():
        assert "partcad.builtin.%s" % name in declared, (
            "src/partcad/builtin/%s/ has no '[tool.setuptools.package-data]' entry, "
            "so none of it lands in the wheel" % name
        )


def test_every_extension_in_them_is_covered():
    """And an entry that names the directory but not the file is the same bug."""
    declared = package_data()

    for name in builtin_packages():
        patterns = declared.get("partcad.builtin.%s" % name, [])
        covered = {pattern[1:] for pattern in patterns if pattern.startswith("*.")}
        directory = os.path.join(BUILTIN_DIR, name)
        for entry in sorted(os.listdir(directory)):
            if entry == "__pycache__" or os.path.isdir(os.path.join(directory, entry)):
                continue
            assert (
                os.path.splitext(entry)[1] in covered
            ), "src/partcad/builtin/%s/%s is not matched by any pattern in " "'[tool.setuptools.package-data]'" % (
                name,
                entry,
            )


def test_the_bundle_carries_the_whole_directory_instead():
    """Why the bundles never saw this, stated so that it stays true.

    The PyInstaller spec copies `builtin/` wholesale rather than file by file,
    which is why a missing pattern is a wheel-only failure. If that ever becomes
    a per-package list, it needs the same check as the table above.
    """
    with open(os.path.join(REPO_ROOT, "dev-tools", "pyinstaller", "partcad.spec"), encoding="utf-8") as f:
        spec = f.read()

    assert 'SRC / "partcad" / "builtin"' in spec
