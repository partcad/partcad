#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a walk over a subtree leaves out when it is told to ('pc test -x').

The reason to have it is a package whose children are expensive to so much as
load - the LDraw library is ninety-two categories served by a repository plugin,
each a round trip - so leaving one out has to mean the walk never imports it,
not that it imports it and then does not list it.
"""

import yaml

import partcad as pc


def _package(path, config):
    path.mkdir(parents=True, exist_ok=True)
    (path / "partcad.yaml").write_text(yaml.safe_dump(config))


def _tree(tmp_path):
    _package(tmp_path, {"name": "//test"})
    _package(tmp_path / "kept", {"desc": "kept"})
    _package(tmp_path / "gone", {"desc": "gone"})
    _package(tmp_path / "gone" / "below", {"desc": "below"})
    # A neighbour whose name starts with the excluded one's: a package name is a
    # path, and excluding '//test/gone' says nothing about '//test/goner'.
    _package(tmp_path / "goner", {"desc": "goner"})
    return pc.Context(str(tmp_path))


def test_an_excluded_package_is_neither_imported_nor_listed(tmp_path):
    ctx = _tree(tmp_path)

    listed = [p["name"] for p in ctx.get_all_packages(has_stuff=False, exclude=["//test/gone"])]

    assert "//test/kept" in listed and "//test/goner" in listed
    assert "//test/gone" not in listed and "//test/gone/below" not in listed
    assert "//test/gone" not in ctx.projects
    assert "//test/gone/below" not in ctx.projects


def test_a_package_loaded_some_other_way_is_still_left_out_of_the_walk(tmp_path):
    """An assembly elsewhere in the tree may use a part of an excluded package,
    which loads it. That does not put it back into the walk."""
    ctx = _tree(tmp_path)
    assert ctx.get_project("//test/gone/below") is not None

    listed = [p["name"] for p in ctx.get_all_packages(has_stuff=False, exclude=["//test/gone"])]

    assert not any(name.startswith("//test/gone/") or name == "//test/gone" for name in listed)


def test_excluding_where_the_walk_starts_leaves_nothing_to_walk(tmp_path):
    ctx = _tree(tmp_path)
    assert ctx.get_project("//test/gone") is not None  # as every operation does before it walks

    assert ctx.get_all_packages(parent_name="//test/gone", has_stuff=False, exclude=["//test/gone"]) == []
    assert "//test/gone/below" not in ctx.projects


def test_without_an_exclusion_the_walk_is_what_it_was(tmp_path):
    ctx = _tree(tmp_path)

    listed = {p["name"] for p in ctx.get_all_packages(has_stuff=False)}

    assert {"//test", "//test/kept", "//test/gone", "//test/gone/below", "//test/goner"} <= listed
