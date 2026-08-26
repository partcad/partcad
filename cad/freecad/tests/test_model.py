#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The package/object hierarchy built from an ``items`` notification."""

from partcad_freecad.model import KIND_ASSEMBLY, KIND_PACKAGE, KIND_PART, KIND_SKETCH, Item, parse_items

ITEMS = {
    "name": "//",
    "packages": [{"name": "//pub/examples", "type": "git", "desc": "Examples"}],
    "parts": [
        {"name": "cylinder", "type": "cadquery"},
        {"name": "box", "type": "alias", "source": ":cube"},
        {"name": "cube", "type": "cadquery", "desc": "A cube\nsecond line"},
    ],
    "assemblies": [{"name": "logo", "type": "assy"}],
    "sketches": [{"name": "outline", "type": "dxf"}],
    "interfaces": [{"name": "point"}],
}


def test_sections_are_ordered_packages_assemblies_parts_interfaces_sketches():
    contents = parse_items(ITEMS)

    assert [item.kind for item in contents] == [
        KIND_PACKAGE,
        KIND_ASSEMBLY,
        KIND_PART,
        KIND_PART,
        KIND_PART,
        "interface",
        KIND_SKETCH,
    ]


def test_aliases_are_listed_after_the_objects_they_duplicate():
    parts = parse_items(ITEMS).of_kind(KIND_PART)

    assert [part.name for part in parts] == ["cube", "cylinder", "box"]


def test_objects_carry_the_package_that_defines_them():
    cube = parse_items(ITEMS).of_kind(KIND_PART)[0]

    assert cube.package == "//"
    assert cube.qualified_name == "//:cube"
    assert cube.desc.startswith("A cube")


def test_a_child_package_is_labelled_by_its_last_path_segment():
    package = parse_items(ITEMS).of_kind(KIND_PACKAGE)[0]

    assert package.label == "examples"
    assert package.name == "//pub/examples"
    assert package.qualified_name == "//pub/examples"


def test_only_parts_and_assemblies_are_importable():
    contents = parse_items(ITEMS)

    importable = {item.name for item in contents if item.is_importable}
    assert importable == {"cube", "cylinder", "box", "logo"}


def test_an_empty_payload_yields_an_empty_package():
    contents = parse_items({})

    assert contents.name == "//"
    assert len(contents) == 0
    assert list(contents) == []


def test_entries_without_a_name_are_dropped():
    contents = parse_items({"name": "//", "parts": [{"type": "cadquery"}, "not-a-dict", {"name": "ok"}]})

    assert [item.name for item in contents] == ["ok"]


def test_parameters_and_item_path_come_from_the_config():
    item = Item(KIND_PART, "cube", "//", {"parameters": {"width": {"type": "float"}}, "item_path": "/w/cube.py"})

    assert item.parameters == {"width": {"type": "float"}}
    assert item.item_path == "/w/cube.py"
    assert item.desc == ""
