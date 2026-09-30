#!/usr/bin/env python3
#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import partcad as pc


def _write_package(path, body):
    path.mkdir(parents=True, exist_ok=True)
    (path / "partcad.yaml").write_text(body, encoding="utf-8")


def test_package_is_addressed_by_its_location(tmp_path):
    """The same package vendored twice yields two independent instances."""
    _write_package(tmp_path, "desc: root\n")
    _write_package(tmp_path / "vendor", "desc: vendor\n")
    _write_package(tmp_path / "other", "desc: other\n")
    # Both copies claim the same identity, as a package taken from a
    # repository would.
    for location in ("vendor/widget", "other/widget"):
        _write_package(tmp_path / location, "name: //pub/parts/widget\ndesc: widget\n")

    ctx = pc.Context(str(tmp_path))
    vendored = ctx.get_project("//vendor/widget")
    other = ctx.get_project("//other/widget")

    assert vendored is not None and other is not None
    # Two separate instances, each reachable only at its own location
    assert vendored is not other
    assert vendored.name == "//vendor/widget"
    assert other.name == "//other/widget"
    # ...even though both declare the same identity
    assert vendored.declared_name == "//pub/parts/widget"
    assert other.declared_name == "//pub/parts/widget"
    # Nothing was pulled in from the location they claim to belong at
    assert "//pub/parts/widget" not in ctx.projects


def test_relocation_of_self_references(tmp_path):
    """References a package makes to itself follow it to where it was loaded."""
    _write_package(tmp_path, "desc: root\n")
    _write_package(tmp_path / "vendor", "desc: vendor\n")
    _write_package(tmp_path / "vendor/widget", "name: //pub/parts/widget\ndesc: widget\n")

    ctx = pc.Context(str(tmp_path))
    widget = ctx.get_project("//vendor/widget")

    # A reference written against the declared name lands on this instance
    assert widget.normalize("//pub/parts/widget:base") == "//vendor/widget:base"
    # ...including references into its sub-packages
    assert widget.normalize("//pub/parts/widget/sub:base") == "//vendor/widget/sub:base"
    # Relative references keep working as before
    assert widget.normalize(":base") == "//vendor/widget:base"
    # References to anything else are left alone
    assert widget.normalize("//pub/parts/other:base") == "//pub/parts/other:base"
    # A package path that merely shares a prefix is not a match
    assert widget.normalize("//pub/parts/widgetry:base") == "//pub/parts/widgetry:base"


def test_root_adopts_its_declared_name(tmp_path):
    """A package developed standalone uses the name its consumers will see."""
    _write_package(tmp_path / "widget", "name: //pub/parts/widget\ndesc: widget\n")

    ctx = pc.Context(str(tmp_path / "widget"))

    assert ctx.name == "//pub/parts/widget"
    assert ctx.root.name == "//pub/parts/widget"
    # Loaded exactly where it says it belongs, so relocation is a no-op
    assert ctx.root.normalize("//pub/parts/widget:base") == "//pub/parts/widget:base"
