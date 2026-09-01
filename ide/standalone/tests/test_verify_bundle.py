#
# PartCAD, 2026
#
# Author: PartCAD (support@partcad.org)
#
# Licensed under Apache License, Version 2.0.
#

import json
import os
import shutil
import stat

import brand
import pytest
import verify_bundle
from conftest import COMPONENT_ROOT

PLAN = {
    "install": [
        {"id": "PartCAD.partcad", "source": "local", "url": None, "path": "partcad.vsix", "required": True},
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

    # The entry point `build.sh` writes so that the 3D view works without a GPU.
    out = resources / "app" / "out"
    out.mkdir()
    (out / "partcad-main.js").write_text(
        "import { app } from 'electron';\n"
        "app.commandLine.appendSwitch('enable-unsafe-swiftshader');\n"
        "await import('./main.js');\n",
        encoding="utf-8",
    )
    (resources / "app" / "package.json").write_text(
        json.dumps({"name": "Code", "type": "module", "main": "./out/partcad-main.js"}),
        encoding="utf-8",
    )

    extensions = resources / "app" / "extensions"
    extensions.mkdir()
    add_extension(extensions, "PartCAD", "partcad")
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
        if entry.name.startswith("PartCAD.partcad-"):
            (entry / "package.json").unlink()
            entry.rmdir()

    assert run(resources, tmp_path) == 1
    assert "required extension PartCAD.partcad is not installed" in capsys.readouterr().out


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
    manifest = extensions / "PartCAD.partcad-1.0.0" / "package.json"
    package = json.loads(manifest.read_text(encoding="utf-8"))
    package["contributes"] = {
        "viewsContainers": {"activitybar": [{"id": "partcad-container", "title": "PartCAD"}]}
    }
    manifest.write_text(json.dumps(package), encoding="utf-8")

    assert run(resources, tmp_path) == 0
    assert "activity bar: PartCAD (partcad-container, from partcad.partcad)" in capsys.readouterr().out


def test_an_extension_with_no_activity_bar_icon_is_not_reported(tmp_path, capsys):
    assert run(make_bundle(tmp_path), tmp_path) == 0
    assert "activity bar" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The software-WebGL entry point. Both halves matter: `package.json` has to
# point at the wrapper and the wrapper has to be there and contain the switch.
# Getting one without the other leaves an application that either starts with no
# software WebGL (and a dead 3D view on a machine with no GPU driver) or does not
# start at all.
# ---------------------------------------------------------------------------


def test_the_entry_point_is_reported(tmp_path, capsys):
    assert run(make_bundle(tmp_path), tmp_path) == 0
    assert "software WebGL enabled" in capsys.readouterr().out


def test_an_unpatched_entry_point_is_a_problem(tmp_path, capsys):
    resources = make_bundle(tmp_path)
    (resources / "app" / "package.json").write_text(json.dumps({"main": "./out/main.js"}), encoding="utf-8")

    assert run(resources, tmp_path) != 0
    assert "not the PartCAD entry point" in capsys.readouterr().out


def test_a_missing_wrapper_is_a_problem(tmp_path, capsys):
    resources = make_bundle(tmp_path)
    (resources / "app" / "out" / "partcad-main.js").unlink()

    assert run(resources, tmp_path) != 0
    assert "no file at" in capsys.readouterr().out


def test_a_wrapper_that_does_not_enable_it_is_a_problem(tmp_path, capsys):
    resources = make_bundle(tmp_path)
    (resources / "app" / "out" / "partcad-main.js").write_text("await import('./main.js');\n", encoding="utf-8")

    assert run(resources, tmp_path) != 0
    assert "does not enable software WebGL" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The welcome window. It is a walkthrough contributed by the bootstrap
# extension: a manifest entry pointing at files packaged beside it, which fails
# by rendering nothing rather than by failing.
# ---------------------------------------------------------------------------


EXAMPLES = [
    {"package": "a_part", "label": "A part", "detail": "...", "open": "cube.py"},
    {"package": "an_assembly", "label": "An assembly", "detail": "...", "open": "it.assy", "requires": ["a_part"]},
]


def add_example(directory, name, files):
    package = directory / "examples" / name
    package.mkdir(parents=True)
    (package / "partcad.yaml").write_text("parts:\n", encoding="utf-8")
    for name in files:
        (package / name).write_text("# example\n", encoding="utf-8")


def add_bootstrap(extensions_dir, steps, examples=EXAMPLES, with_examples=True):
    directory = extensions_dir / "PartCAD.partcad-ide-bootstrap-1.0.0"
    directory.mkdir(parents=True)
    (directory / "package.json").write_text(
        json.dumps(
            {
                "publisher": "PartCAD",
                "name": "partcad-ide-bootstrap",
                "version": "1.0.0",
                "contributes": {
                    "walkthroughs": [{"id": "partcadStart", "title": "Start with PartCAD", "steps": steps}]
                },
            }
        ),
        encoding="utf-8",
    )
    if examples is not None:
        (directory / "examples.json").write_text(json.dumps({"examples": examples}), encoding="utf-8")
    if with_examples:
        add_example(directory, "a_part", ["cube.py"])
        add_example(directory, "an_assembly", ["it.assy"])
    return directory


def test_the_welcome_window_is_reported(tmp_path, capsys):
    resources = make_bundle(tmp_path)
    directory = add_bootstrap(
        resources / "app" / "extensions", [{"id": "package", "media": {"markdown": "media/package.md"}}]
    )
    (directory / "media").mkdir()
    (directory / "media" / "package.md").write_text("# hello\n", encoding="utf-8")

    assert run(resources, tmp_path) == 0
    assert "welcome window: Start with PartCAD (1 steps" in capsys.readouterr().out


def test_a_walkthrough_step_whose_media_was_not_packaged_fails(tmp_path, capsys):
    # What a `.vscodeignore`, or a build that copies the manifest and not the
    # directory beside it, produces: a welcome window of empty pages.
    resources = make_bundle(tmp_path)
    add_bootstrap(resources / "app" / "extensions", [{"id": "package", "media": {"markdown": "media/package.md"}}])

    assert run(resources, tmp_path) == 1
    assert "step package shows media/package.md, which is not in the extension" in capsys.readouterr().out


def test_a_bootstrap_extension_with_no_walkthrough_fails(tmp_path, capsys):
    resources = make_bundle(tmp_path)
    add_bootstrap(resources / "app" / "extensions", [])
    manifest = resources / "app" / "extensions" / "PartCAD.partcad-ide-bootstrap-1.0.0" / "package.json"
    package = json.loads(manifest.read_text(encoding="utf-8"))
    package["contributes"] = {}
    manifest.write_text(json.dumps(package), encoding="utf-8")

    assert run(resources, tmp_path) == 1
    assert "contributes no walkthrough" in capsys.readouterr().out


def test_the_examples_are_reported(tmp_path, capsys):
    resources = make_bundle(tmp_path)
    directory = add_bootstrap(
        resources / "app" / "extensions", [{"id": "package", "media": {"markdown": "media/package.md"}}]
    )
    (directory / "media").mkdir()
    (directory / "media" / "package.md").write_text("# hello\n", encoding="utf-8")

    assert run(resources, tmp_path) == 0
    assert "welcome window: 2 example package(s) to open" in capsys.readouterr().out


def test_an_example_whose_packages_were_not_copied_fails(tmp_path, capsys):
    # The welcome window would offer it and opening it would find nothing.
    resources = make_bundle(tmp_path)
    add_bootstrap(resources / "app" / "extensions", [], with_examples=False)

    assert run(resources, tmp_path) == 1
    assert "the a_part example is offered, but a_part was not packaged with it" in capsys.readouterr().out


def test_an_assembly_example_without_its_parts_fails(tmp_path, capsys):
    # An example that names other packages is only shipped if they are too:
    # an assembly whose parts were left behind loads no better than a missing one.
    resources = make_bundle(tmp_path)
    directory = add_bootstrap(resources / "app" / "extensions", [])
    shutil.rmtree(directory / "examples" / "a_part")

    assert run(resources, tmp_path) == 1
    assert "the an_assembly example is offered, but a_part was not packaged with it" in capsys.readouterr().out


def test_an_example_missing_the_file_it_opens_fails(tmp_path, capsys):
    resources = make_bundle(tmp_path)
    directory = add_bootstrap(resources / "app" / "extensions", [])
    (directory / "examples" / "a_part" / "cube.py").unlink()

    assert run(resources, tmp_path) == 1
    assert "the a_part example has no cube.py to open" in capsys.readouterr().out


def test_a_bootstrap_extension_with_no_examples_manifest_fails(tmp_path, capsys):
    resources = make_bundle(tmp_path)
    add_bootstrap(resources / "app" / "extensions", [], examples=None)

    assert run(resources, tmp_path) == 1
    assert "no examples.json" in capsys.readouterr().out
