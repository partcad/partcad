#
# PartCAD, 2026
#
# Author: PartCAD (support@partcad.org)
#
# Licensed under Apache License, Version 2.0.
#

import json
import os
import stat

import brand
import pytest
import verify_bundle
from conftest import COMPONENT_ROOT

PLAN = {
    "install": [
        {"id": "OpenVMP.partcad", "source": "local", "url": None, "path": "partcad.vsix", "required": True},
        {"id": "redhat.vscode-yaml", "source": "gallery", "url": None, "required": False},
    ],
    "skip": [{"id": "ms-python.vscode-pylance", "reason": "proprietary"}],
}


def add_extension(extensions_dir, publisher, name, version="1.0.0"):
    directory = extensions_dir / f"{publisher}.{name}-{version}"
    directory.mkdir(parents=True)
    (directory / "package.json").write_text(
        json.dumps({"publisher": publisher, "name": name, "version": version}), encoding="utf-8"
    )


def make_bundle(tmp_path, with_tools=True):
    """A built IDE, as far as this check can see one."""
    resources = tmp_path / "partcad-ide" / "resources"
    (resources / "app").mkdir(parents=True)

    product = resources / "app" / "product.json"
    product.write_text(
        json.dumps(
            {
                "nameShort": "VSCodium",
                "nameLong": "VSCodium",
                "applicationName": "codium",
                "dataFolderName": ".vscode-oss",
                "updateUrl": "https://example.invalid",
                "extensionsGallery": {"serviceUrl": "https://open-vsx.org/vscode/gallery"},
            }
        ),
        encoding="utf-8",
    )
    brand.brand_product(product, COMPONENT_ROOT / "product.overlay.json", "0.1.2")

    extensions = resources / "app" / "extensions"
    extensions.mkdir()
    add_extension(extensions, "OpenVMP", "partcad")
    add_extension(extensions, "redhat", "vscode-yaml")

    for path in (tmp_path / "partcad-ide" / "partcad-ide", tmp_path / "partcad-ide" / "bin" / "partcad-ide"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\n", encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    if with_tools:
        tools = resources / "partcad-cli"
        tools.mkdir()
        service = tools / "partcad-json-rpc"
        service.write_text("#!/bin/sh\n", encoding="utf-8")
        service.chmod(service.stat().st_mode | stat.S_IXUSR)

    return resources


def run(resources, tmp_path, plan=None, expect_tools=True):
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan or PLAN), encoding="utf-8")
    arguments = [
        "--resources",
        str(resources),
        "--plan",
        str(plan_file),
        "--executable",
        str(resources.parent / "partcad-ide"),
        "--launcher",
        str(resources.parent / "bin" / "partcad-ide"),
    ]
    if expect_tools:
        arguments.append("--expect-tools")
    return verify_bundle.main(arguments)


def test_a_complete_bundle_passes(tmp_path):
    assert run(make_bundle(tmp_path), tmp_path) == 0


def test_a_missing_required_extension_fails(tmp_path, capsys):
    resources = make_bundle(tmp_path)
    for entry in (resources / "app" / "extensions").iterdir():
        if entry.name.startswith("OpenVMP."):
            (entry / "package.json").unlink()
            entry.rmdir()

    assert run(resources, tmp_path) == 1
    assert "required extension OpenVMP.partcad is not installed" in capsys.readouterr().out


def test_a_missing_optional_extension_only_warns(tmp_path, capsys):
    resources = make_bundle(tmp_path)
    for entry in (resources / "app" / "extensions").iterdir():
        if entry.name.startswith("redhat."):
            (entry / "package.json").unlink()
            entry.rmdir()

    assert run(resources, tmp_path) == 0
    assert "optional extension redhat.vscode-yaml is not installed" in capsys.readouterr().out


def test_an_extension_the_policy_skips_must_not_be_there(tmp_path, capsys):
    resources = make_bundle(tmp_path)
    add_extension(resources / "app" / "extensions", "ms-python", "vscode-pylance")

    assert run(resources, tmp_path) == 1
    assert "was installed although the policy skips it" in capsys.readouterr().out


def test_unbranded_is_a_failure(tmp_path, capsys):
    resources = make_bundle(tmp_path)
    product = resources / "app" / "product.json"
    product.write_text(
        json.dumps({"nameLong": "VSCodium", "extensionsGallery": {"serviceUrl": "https://open-vsx.org"}}),
        encoding="utf-8",
    )

    assert run(resources, tmp_path) == 1
    assert "nameLong" in capsys.readouterr().out


def test_tools_are_only_required_when_they_were_asked_for(tmp_path):
    resources = make_bundle(tmp_path, with_tools=False)
    assert run(resources, tmp_path, expect_tools=False) == 0
    assert run(resources, tmp_path, expect_tools=True) == 1


@pytest.mark.skipif(os.name == "nt", reason="permission bits are a POSIX notion")
def test_a_launcher_that_is_not_executable_fails(tmp_path, capsys):
    resources = make_bundle(tmp_path)
    launcher = resources.parent / "bin" / "partcad-ide"
    launcher.chmod(0o644)

    assert run(resources, tmp_path) == 1
    assert "is not executable" in capsys.readouterr().out


def test_the_activity_bar_is_reported(tmp_path, capsys):
    # What the user sees down the side of the window is decided by what the IDE
    # ships with, so the build says what it will be.
    resources = make_bundle(tmp_path)
    extensions = resources / "app" / "extensions"
    manifest = extensions / "OpenVMP.partcad-1.0.0" / "package.json"
    package = json.loads(manifest.read_text(encoding="utf-8"))
    package["contributes"] = {
        "viewsContainers": {"activitybar": [{"id": "partcad-container", "title": "PartCAD (Beta)"}]}
    }
    manifest.write_text(json.dumps(package), encoding="utf-8")

    assert run(resources, tmp_path) == 0
    assert "activity bar: PartCAD (Beta) (partcad-container, from openvmp.partcad)" in capsys.readouterr().out


def test_an_extension_with_no_activity_bar_icon_is_not_reported(tmp_path, capsys):
    assert run(make_bundle(tmp_path), tmp_path) == 0
    assert "activity bar" not in capsys.readouterr().out
