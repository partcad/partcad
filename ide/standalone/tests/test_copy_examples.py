#
# PartCAD, 2026
#
# Author: PartCAD (support@partcad.org)
#
# Licensed under Apache License, Version 2.0.
#

"""
The examples the IDE's welcome window offers, and what has to travel with them.
"""

import json

import copy_examples
import pytest
from conftest import COMPONENT_ROOT, REPO_ROOT
from copy_examples import ManifestError

MANIFEST = COMPONENT_ROOT / "bootstrap" / "examples.json"


def write_manifest(tmp_path, examples):
    path = tmp_path / "examples.json"
    path.write_text(json.dumps({"examples": examples}), encoding="utf-8")
    return path


def make_example(root, name, configuration="parts:\n", files=("cube.py",)):
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "partcad.yaml").write_text(configuration, encoding="utf-8")
    for file in files:
        (directory / file).write_text("# example\n", encoding="utf-8")
    return directory


def entry(name, **overrides):
    return {"package": name, "label": name, "detail": "...", "open": "cube.py", **overrides}


def test_an_entry_has_to_say_what_it_is(tmp_path):
    with pytest.raises(ManifestError, match="label"):
        copy_examples.load_manifest(write_manifest(tmp_path, [{"package": "a", "detail": "...", "open": "a.py"}]))


def test_an_unknown_key_is_an_error(tmp_path):
    # A misspelled `requires` would silently ship an example without its parts.
    with pytest.raises(ManifestError, match="unknown key"):
        copy_examples.load_manifest(write_manifest(tmp_path, [entry("a", require=["b"])]))


def test_an_example_listed_twice_is_an_error(tmp_path):
    with pytest.raises(ManifestError, match="listed twice"):
        copy_examples.load_manifest(write_manifest(tmp_path, [entry("a"), entry("a")]))


def test_an_example_that_is_not_in_the_repository_is_an_error(tmp_path):
    with pytest.raises(ManifestError, match="not a PartCAD package"):
        copy_examples.validate([entry("gone")], tmp_path)


def test_the_file_the_welcome_window_opens_has_to_be_there(tmp_path):
    make_example(tmp_path, "a", files=())
    with pytest.raises(ManifestError, match="has no cube.py to open"):
        copy_examples.validate([entry("a")], tmp_path)


def test_a_sibling_an_example_references_has_to_travel_with_it(tmp_path):
    # The failure this exists to prevent: an assembly copied out of `examples/`
    # on its own, placing parts from a package that is not beside it any more.
    make_example(tmp_path, "assembly")
    (tmp_path / "assembly" / "it.assy").write_text("links:\n  - package: ../parts\n", encoding="utf-8")
    make_example(tmp_path, "parts")

    with pytest.raises(ManifestError, match="would be copied without parts"):
        copy_examples.validate([entry("assembly")], tmp_path)

    copy_examples.validate([entry("assembly", requires=["parts"])], tmp_path)


def test_what_a_required_package_references_travels_too(tmp_path):
    # One level is not enough: the package an assembly's parts come from may
    # itself name a third.
    make_example(tmp_path, "assembly")
    (tmp_path / "assembly" / "it.assy").write_text("links:\n  - package: ../parts\n", encoding="utf-8")
    make_example(tmp_path, "parts", configuration="parts:\n  x:\n    source: ../shapes:y\n")
    make_example(tmp_path, "shapes")

    with pytest.raises(ManifestError, match="would be copied without shapes"):
        copy_examples.validate([entry("assembly", requires=["parts"])], tmp_path)

    copy_examples.validate([entry("assembly", requires=["parts", "shapes"])], tmp_path)


def test_a_package_that_names_itself_is_self_contained(tmp_path):
    # `../<its own name>:part` is what an alias or an enrich writes, and it is
    # still a reference to itself wherever the directory is copied to.
    make_example(tmp_path, "a", configuration="parts:\n  b:\n    source: ../a:cube\n")
    copy_examples.validate([entry("a")], tmp_path)


def test_a_reference_in_a_source_file_is_not_a_package_reference(tmp_path):
    # `../` in a script or a README is a path in somebody's code or a link in a
    # document, and neither says anything about packages.
    make_example(tmp_path, "a")
    (tmp_path / "a" / "cube.py").write_text("open('../elsewhere/data.json')\n", encoding="utf-8")
    (tmp_path / "a" / "README.md").write_text("[up](../index.md)\n", encoding="utf-8")
    copy_examples.validate([entry("a")], tmp_path)


def test_copying_takes_an_example_and_what_it_needs(tmp_path):
    examples_root = tmp_path / "examples"
    make_example(examples_root, "assembly")
    make_example(examples_root, "parts")
    make_example(examples_root, "unused")
    output = tmp_path / "out"

    copied = copy_examples.copy([entry("assembly", requires=["parts"])], examples_root, output)

    assert copied == ["assembly", "parts"]
    assert (output / "parts" / "partcad.yaml").is_file()
    assert not (output / "unused").exists()


def test_copying_replaces_what_was_there(tmp_path):
    # The build runs into a staging directory it may have used before; an
    # example that was removed from the manifest must not survive in it.
    examples_root = tmp_path / "examples"
    make_example(examples_root, "a")
    output = tmp_path / "out"
    (output / "gone").mkdir(parents=True)

    copy_examples.copy([entry("a")], examples_root, output)
    assert not (output / "gone").exists()


def test_the_shipped_manifest_matches_the_repositorys_examples():
    # The check that catches an example renamed or removed under `examples/`,
    # and one whose configuration grew a reference to a package the welcome
    # window would not copy with it. The build runs exactly this.
    examples = copy_examples.load_manifest(MANIFEST)
    copy_examples.validate(examples, REPO_ROOT / "examples")
    assert examples, "the welcome window offers no examples"
