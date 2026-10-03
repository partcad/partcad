#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A folder that is not a package does not hide a dependency of the same name.

A package keeps files of its own in folders - a repository plugin's code, the
images a README shows - and one of them can share a name with a dependency the
package declares. Resolving '<package>/<name>' used to find the folder, see no
'partcad.yaml' in it, and stop there without ever looking at the dependencies:
so every reference to the dependency from an assembly failed as "Package not
found", while the traversal behind 'pc list packages -r', which does check for
a 'partcad.yaml', imported it without complaint. The case that found it was a
store serving its catalog from a plugin, as '<store>/catalog', with the plugin's
files in a folder called 'catalog'.
"""

import partcad as pc


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _store(tmp_path, folder_is_a_package=False):
    """A package with a dependency 'catalog' declared elsewhere, and a folder 'catalog' beside it."""
    _write(
        tmp_path / "partcad.yaml",
        "name: //store\n" "dependencies:\n" "  catalog:\n" "    type: local\n" "    path: vendor/catalog\n",
    )
    _write(tmp_path / "vendor" / "catalog" / "partcad.yaml", "desc: The declared dependency\n")
    _write(tmp_path / "catalog" / "catalog_repo.py", "# The files of the package's own plugin.\n")
    if folder_is_a_package:
        _write(tmp_path / "catalog" / "partcad.yaml", "desc: The sub-folder package\n")
    return pc.Context(str(tmp_path))


def test_a_folder_with_no_package_in_it_does_not_hide_the_dependency(tmp_path):
    ctx = _store(tmp_path)
    catalog = ctx.get_project("//store/catalog")
    assert catalog is not None
    assert catalog.desc == "The declared dependency"


def test_a_folder_that_is_a_package_is_still_the_package(tmp_path):
    # What a sub-folder package has always been: found by its name, before the
    # dependencies. Only a folder that is not one stopped being in the way.
    ctx = _store(tmp_path, folder_is_a_package=True)
    assert ctx.get_project("//store/catalog").desc == "The sub-folder package"


def test_a_name_that_is_neither_is_still_not_found(tmp_path):
    ctx = _store(tmp_path)
    assert ctx.get_project("//store/nothing") is None
