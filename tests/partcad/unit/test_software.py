#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The 'software' objects a package ships beside its parts and assemblies.

The fixture package ('data/software') declares software of every shape the
feature has: a file it carries, the short form, a defaulted path, a file pulled
in with 'fileFrom' and pinned by a hash, and one pulled in with nothing pinning
it. A part and an assembly say what they ship with, and a child package's part
says so about software of its own - which is what tells "resolved against the
package that declared it" apart from "resolved against whoever is reading".
"""

import asyncio
import os

import pytest
import yaml

import partcad as pc
from partcad import factory
from partcad.lint.lint import Severity
from partcad.lint.software import SoftwareLinting
from partcad.shape import Shape

DATA = "tests/partcad/unit/data/software"

FIRMWARE = "//:firmware"
SERVICE_TOOL = "//:service-tool"
VENDOR_BLOB = "//:vendor-blob"
DIAGNOSTICS = "//sub:diagnostics"
CONTROLLER = "//:controller"
SENSOR = "//sub:sensor"


@pytest.fixture
def ctx():
    return pc.Context(DATA)


@pytest.fixture
def root(ctx):
    return ctx.get_project(ctx.get_current_project_path())


#
# The object kind
#


def test_the_raw_factory_is_registered():
    assert "raw" in factory.all["software"]


def test_software_is_enumerated_as_an_object_kind(root):
    assert sorted(root.object_names("software")) == [
        "bootloader",
        "firmware",
        "service-tool",
        "unpinned-blob",
        "vendor-blob",
    ]
    # It is a kind of its own: nothing here is a part.
    assert "firmware" not in root.object_names("part")


def test_software_is_not_a_shape(root):
    software = root.get_software("firmware")
    assert software is not None
    assert not isinstance(software, Shape)
    # Nothing of a shape's surface is inherited by accident.
    for attribute in ("get_wrapped", "get_cache_key_async", "render_svg", "shape_info"):
        assert not hasattr(software, attribute)


def test_the_default_type_is_raw(root):
    # Read from the file rather than from the loaded configuration: normalizing
    # a declaration is what fills the default in, in place.
    declared = yaml.safe_load(open(os.path.join(DATA, "partcad.yaml")))["software"]
    assert "type" not in (declared["bootloader"] or {})

    assert root.get_software_config("bootloader")["type"] == "raw"
    assert root.get_software("bootloader").type == "raw"


def test_an_unknown_type_is_reported(tmp_path):
    (tmp_path / "partcad.yaml").write_text("software:\n  fw:\n    type: uf2\n")
    (tmp_path / "fw").write_text("image")
    project = pc.Context(str(tmp_path)).get_project("//")
    assert project.get_software("fw") is None
    assert "uf2" in project.get_broken_object_reason("software", "fw")


#
# The file every software object stands for
#


def test_the_path_defaults_to_the_object_name(root):
    software = root.get_software("bootloader")
    assert os.path.basename(software.path) == "bootloader"
    assert software.is_fetched


def test_an_explicit_path_is_honoured(root):
    software = root.get_software("firmware")
    assert os.path.basename(software.path) == "firmware.bin"
    assert software.is_fetched


def test_the_short_form_is_the_path(root):
    software = root.get_software("service-tool")
    assert os.path.basename(software.path) == "service-tool.sh"
    assert software.type == "raw"
    assert software.is_fetched


def test_a_missing_local_file_is_a_broken_object(tmp_path):
    (tmp_path / "partcad.yaml").write_text("software:\n  fw:\n    path: nowhere.bin\n")
    project = pc.Context(str(tmp_path)).get_project("//")
    assert project.get_software("fw") is None
    assert "must exist" in project.get_broken_object_reason("software", "fw")


def test_a_downloaded_file_need_not_be_there_yet(root):
    # 'fileFrom' is fetched lazily, so the package loads with the file absent.
    software = root.get_software("vendor-blob")
    assert software is not None
    assert not software.is_local_file()
    assert not software.is_fetched
    assert software.declared_hash().startswith("sha256:")


def test_a_carried_file_is_local(root):
    assert root.get_software("firmware").is_local_file()
    assert root.get_software("firmware").declared_hash() is None


def test_info_reports_what_identifies_the_file(root):
    info = root.get_software("firmware").info()
    assert info["Type"] == "raw"
    assert info["Version"] == "1.0.0"
    assert info["Desc"] == "The controller firmware"
    assert info["File"].endswith("firmware.bin")


#
# What an object ships with
#


def test_references_are_resolved_against_the_declaring_package(ctx, root):
    controller = root.get_part("controller")
    assert controller.config["software_resolved"] == [FIRMWARE, VENDOR_BLOB]

    # The child package's part says 'diagnostics', meaning its own.
    sensor = ctx.get_part(SENSOR)
    assert sensor.config["software_resolved"] == [DIAGNOSTICS]


def test_a_reference_resolves_to_the_object(ctx):
    project, software = pc.software.lookup(ctx, DIAGNOSTICS)
    assert project.name == "//sub"
    assert software.name == "diagnostics"


#
# The bill of materials
#


def _detailed(ctx):
    device = ctx._get_assembly(":device")
    assert device is not None
    return asyncio.run(device.get_bom_detailed_async(ctx))


def test_the_bom_lists_the_software_of_every_part(ctx):
    bom = _detailed(ctx)
    assert sorted(bom.keys()) == sorted([CONTROLLER, FIRMWARE, SERVICE_TOOL, VENDOR_BLOB, DIAGNOSTICS, SENSOR])
    assert bom[FIRMWARE]["kind"] == "software"
    # One image per board that runs it, the way two of anything else count two.
    assert bom[FIRMWARE]["count"] == 2
    assert bom[DIAGNOSTICS]["count"] == 1
    # The assembly's own software is listed too, not only its parts'.
    assert bom[SERVICE_TOOL]["count"] == 1


def test_a_software_line_item_names_its_package_and_revision(ctx):
    bom = _detailed(ctx)
    entry = bom[FIRMWARE]
    assert entry["package"] == "//"
    # This fixture is read out of this repository, so there is a commit to name.
    assert entry["revision"] and len(entry["revision"]) == 40
    assert entry["version"] == "1.0.0"
    assert entry["hash"] is None
    # The same package, so the same revision, whichever object asked.
    assert bom[SERVICE_TOOL]["revision"] == entry["revision"]


def test_a_software_line_item_carries_what_pins_the_file(ctx):
    bom = _detailed(ctx)
    assert bom[VENDOR_BLOB]["hash"].startswith("sha256:")
    # And the shape of a line item is the same whatever kind it is.
    for entry in bom.values():
        assert set(("kind", "count", "desc", "vendor", "sku", "count_per_sku")) <= set(entry)


def test_the_bom_without_a_context_lists_no_software(ctx):
    # Resolving a reference needs the package graph; without one the software
    # section is empty rather than filled with names nothing was read from.
    device = ctx._get_assembly(":device")
    bom = asyncio.run(device.get_bom_detailed_async(None))
    assert [name for name, entry in bom.items() if entry["kind"] == "software"] == []


def test_the_grouped_bom_groups_software_by_package(ctx):
    device = ctx._get_assembly(":device")
    grouped = asyncio.run(device.get_bom_grouped_async(ctx))
    assert sorted(grouped["software"].keys()) == ["//", "//sub"]
    assert grouped["software"]["//"]["firmware"]["count"] == 2
    assert grouped["software"]["//"]["firmware"]["version"] == "1.0.0"
    assert grouped["software"]["//sub"]["diagnostics"]["count"] == 1
    assert len(grouped["software"]["//"]["firmware"]["revision"]) == 40


def test_software_is_not_something_to_procure(ctx):
    """The flat BoM feeds procurement, and nobody sells a firmware image."""
    device = ctx._get_assembly(":device")
    flat = asyncio.run(device.get_bom())
    assert sorted(flat.keys()) == [CONTROLLER, SENSOR]


#
# The package's README
#


def test_the_package_readme_lists_the_software(ctx, root, tmp_path):
    root.render_readme_async({"readme": {}}, str(tmp_path))
    readme = (tmp_path / "README.md").read_text()

    assert "## Software" in readme
    # The file this package carries is linked; the one it pulls in is not, and
    # says where it comes from instead.
    assert "[firmware.bin](firmware.bin)" in readme
    assert "| firmware | 1.0.0 |" in readme
    assert "`vendor-blob` from [url](https://example.com/vendor/blob.bin)" in readme
    assert "`sha256:0000" in readme


#
# The check: in this repository, or hashed
#


def _lint(ctx, package):
    check = SoftwareLinting("Software")
    targets = check.get_targets(ctx, package)
    assert targets, "the package's own configuration is what declares its software"
    report = asyncio.run(check.validate(ctx, package, targets[0]))
    return report.messages


def test_the_lint_check_wants_a_hash_for_what_is_not_in_the_repository(ctx, root):
    messages = _lint(ctx, root)
    assert len(messages) == 1
    severity, message = messages[0]
    assert severity == Severity.FAILED
    assert "unpinned-blob" in message
    assert "hash" in message
    # The pinned one and the ones this package carries are not complained about.
    for name in ("vendor-blob", "firmware", "service-tool", "bootloader"):
        assert name not in message


def test_the_lint_check_passes_a_package_that_carries_its_software(ctx):
    assert _lint(ctx, ctx.get_project("//sub")) == []


def test_the_lint_check_is_registered():
    from partcad.lint.all import get_linting_checks

    assert "Software" in [check.name for check in get_linting_checks(4)]
