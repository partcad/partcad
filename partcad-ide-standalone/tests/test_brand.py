#
# PartCAD, 2026
#
# Author: PartCAD (support@partcad.org)
#
# Licensed under Apache License, Version 2.0.
#

import json
import plistlib

import brand
import pytest
from conftest import COMPONENT_ROOT

VSCODIUM_GALLERY = {"serviceUrl": "https://open-vsx.org/vscode/gallery", "itemUrl": "https://open-vsx.org/vscode/item"}


def write_product(directory, **extra):
    product = {
        "nameShort": "VSCodium",
        "nameLong": "VSCodium",
        "applicationName": "codium",
        "dataFolderName": ".vscode-oss",
        "updateUrl": "https://raw.githubusercontent.com/VSCodium/versions",
        "extensionsGallery": VSCODIUM_GALLERY,
        "configurationDefaults": {"extensions.gallery.useUnpkgResourceApi": False},
    }
    product.update(extra)
    path = directory / "product.json"
    path.write_text(json.dumps(product), encoding="utf-8")
    return path


def test_merge_replaces_and_recurses():
    assert brand.merge({"a": 1, "b": {"c": 1, "d": 2}}, {"b": {"c": 9}}) == {"a": 1, "b": {"c": 9, "d": 2}}


def test_a_null_in_the_overlay_removes_the_key():
    assert brand.merge({"a": 1, "b": 2}, {"b": None}) == {"a": 1}


def test_substitution_reaches_nested_values():
    assert brand.substitute({"a": ["v${VERSION}"]}, {"VERSION": "1.2.3"}) == {"a": ["v1.2.3"]}


def test_the_shipped_overlay_brands_a_vscodium_product(tmp_path):
    path = write_product(tmp_path)
    branded = brand.brand_product(path, COMPONENT_ROOT / "product.overlay.json", "0.1.2")

    assert branded["nameLong"] == "PartCAD IDE"
    assert branded["applicationName"] == "partcad-ide"
    assert branded["dataFolderName"] == ".partcad-ide"
    assert branded["win32NameVersion"] == "PartCAD IDE 0.1.2"
    # Removed rather than set: an IDE that updates itself into a plain VSCodium
    # loses everything this build added.
    assert "updateUrl" not in branded
    # The editor still has somewhere to install extensions from...
    assert branded["extensionsGallery"] == VSCODIUM_GALLERY
    # ...and VSCodium's own defaults survive alongside the ones added here.
    assert branded["configurationDefaults"]["extensions.gallery.useUnpkgResourceApi"] is False
    assert branded["configurationDefaults"]["partcad.backend"] == "service"

    assert json.loads(path.read_text(encoding="utf-8"))["nameLong"] == "PartCAD IDE"


def test_branding_stops_when_the_upstream_build_has_no_gallery(tmp_path):
    path = write_product(tmp_path, extensionsGallery={})
    with pytest.raises(SystemExit, match="no extension gallery"):
        brand.brand_product(path, COMPONENT_ROOT / "product.overlay.json", "0.1.2")


def test_the_launcher_is_repointed_at_the_renamed_executable(tmp_path):
    shim = tmp_path / "codium"
    shim.write_text('APP_NAME="codium"\nELECTRON="$VSCODE_PATH/$APP_NAME"\n', encoding="utf-8")

    assert brand.brand_shim(shim, "codium", "partcad-ide")
    assert shim.read_text(encoding="utf-8") == 'APP_NAME="partcad-ide"\nELECTRON="$VSCODE_PATH/$APP_NAME"\n'


def test_the_launcher_keeps_names_that_only_contain_the_old_one(tmp_path):
    # `.vscodium` is a data directory, not the executable; renaming it here
    # would move where a user's state lives.
    shim = tmp_path / "codium"
    shim.write_text('DATA="$HOME/.vscodium"\nAPP_NAME="codium"\n', encoding="utf-8")

    brand.brand_shim(shim, "codium", "partcad-ide")
    assert ".vscodium" in shim.read_text(encoding="utf-8")


def test_the_windows_launcher_is_repointed(tmp_path):
    shim = tmp_path / "codium.cmd"
    shim.write_text('call "%~dp0..\\VSCodium.exe" "%~dp0..\\resources\\app\\out\\cli.js" %*\n', encoding="utf-8")

    assert not brand.brand_shim(shim, "codium", "partcad-ide", allow_missing=True)
    assert brand.brand_shim(shim, "VSCodium.exe", "partcad-ide.exe", allow_missing=True)
    assert "partcad-ide.exe" in shim.read_text(encoding="utf-8")


def test_a_launcher_that_names_no_executable_stops_the_build(tmp_path):
    shim = tmp_path / "codium"
    shim.write_text("nothing to see here\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="changed upstream"):
        brand.brand_shim(shim, "codium", "partcad-ide")


def test_the_macos_bundle_is_rebranded(tmp_path):
    path = tmp_path / "Info.plist"
    with open(path, "wb") as handle:
        plistlib.dump(
            {
                "CFBundleName": "VSCodium",
                "CFBundleDisplayName": "VSCodium",
                "CFBundleIdentifier": "com.vscodium",
                "CFBundleExecutable": "Electron",
                "CFBundleDocumentTypes": [{"CFBundleTypeName": "VSCodium", "CFBundleTypeIconFile": "code_file"}],
                "CFBundleURLTypes": [{"CFBundleURLName": "VSCodium", "CFBundleURLSchemes": ["vscodium"]}],
            },
            handle,
        )

    brand.brand_plist(path, "PartCAD IDE", "org.partcad.ide", "0.1.2", "partcad-ide")

    with open(path, "rb") as handle:
        info = plistlib.load(handle)
    assert info["CFBundleName"] == "PartCAD IDE"
    assert info["CFBundleIdentifier"] == "org.partcad.ide"
    assert info["CFBundleIconFile"] == "partcad-ide"
    assert info["CFBundleShortVersionString"] == "0.1.2"
    # The executable inside the bundle is not renamed, so this has to stay.
    assert info["CFBundleExecutable"] == "Electron"
    # A `vscodium://` link must not open the PartCAD IDE, and the other way
    # around.
    assert info["CFBundleURLTypes"][0]["CFBundleURLSchemes"] == ["partcad-ide"]
