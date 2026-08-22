#
# PartCAD, 2026
#
# Author: PartCAD (support@partcad.org)
#
# Licensed under Apache License, Version 2.0.
#

"""
Rebrand a VSCodium build as the PartCAD IDE.

Three edits, one subcommand each, because they are three different file formats
and each has its own way of going wrong:

  product  merge `product.overlay.json` into the application's `product.json`
  plist    rewrite the macOS `Info.plist` of the application bundle
  shim     point the `bin/` command line launcher at the renamed executable

Every subcommand fails loudly rather than leaving a half-branded application:
a bundle that starts but still calls itself VSCodium is worse than a build that
stopped.
"""

import argparse
import json
import pathlib
import plistlib
import re
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import jsonc  # noqa: E402  (the path has to be set up first)


def merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge `overlay` into `base`. A `null` in the overlay removes the key."""
    result = dict(base)
    for key, value in overlay.items():
        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = value
    return result


def substitute(value: Any, variables: dict[str, str]) -> Any:
    """Replace `${NAME}` in every string of a JSON-shaped value."""
    if isinstance(value, str):
        for name, replacement in variables.items():
            value = value.replace("${" + name + "}", replacement)
        return value
    if isinstance(value, dict):
        return {key: substitute(item, variables) for key, item in value.items()}
    if isinstance(value, list):
        return [substitute(item, variables) for item in value]
    return value


def brand_product(product_path: pathlib.Path, overlay_path: pathlib.Path, version: str) -> dict[str, Any]:
    product = jsonc.load(product_path)
    overlay = substitute(jsonc.load(overlay_path), {"VERSION": version})

    # Not a formality: without a gallery the Extensions view cannot install
    # anything, and the IDE would be a dead end for a user who wants one more
    # extension. VSCodium sets this to Open VSX and the overlay leaves it alone,
    # so an empty value here means the upstream build changed underneath us.
    if not product.get("extensionsGallery", {}).get("serviceUrl"):
        raise SystemExit(f"error: {product_path} has no extension gallery; the IDE could not install extensions")

    branded = merge(product, overlay)
    product_path.write_text(json.dumps(branded, indent=2) + "\n", encoding="utf-8")
    return branded


def brand_plist(plist_path: pathlib.Path, name: str, identifier: str, version: str, icon: str | None) -> None:
    with open(plist_path, "rb") as handle:
        info = plistlib.load(handle)

    info["CFBundleName"] = name
    info["CFBundleDisplayName"] = name
    info["CFBundleIdentifier"] = identifier
    info["CFBundleShortVersionString"] = version
    info["CFBundleVersion"] = version
    if icon:
        info["CFBundleIconFile"] = icon

    # The document types and the URL scheme carry the old application's name and
    # bundle identifier, which is how a file association or a `vscodium://` link
    # ends up pointing at the wrong application.
    for document_type in info.get("CFBundleDocumentTypes", []):
        if "CFBundleTypeName" in document_type:
            document_type["CFBundleTypeName"] = name
        if icon:
            document_type.pop("CFBundleTypeIconFile", None)
    for url_type in info.get("CFBundleURLTypes", []):
        url_type["CFBundleURLName"] = name
        url_type["CFBundleURLSchemes"] = ["partcad-ide"]

    with open(plist_path, "wb") as handle:
        plistlib.dump(info, handle)


def brand_shim(shim_path: pathlib.Path, old_name: str, new_name: str, allow_missing: bool = False) -> bool:
    """Rewrite the `bin/` launcher script for the renamed executable.

    The launcher is a small shell (or `.cmd`) script that runs the application's
    executable with the CLI entry point. It names that executable, so renaming
    the executable without rewriting the script leaves a `partcad-ide` command
    that cannot find `partcad-ide`.
    """
    text = shim_path.read_text(encoding="utf-8")

    # Whole words only: `codium` inside `.vscodium-data` or a URL is not the
    # executable's name, and a substring replacement there changes where user
    # data goes or breaks a link.
    replaced = re.sub(rf"(?<![\w.-]){re.escape(old_name)}(?![\w-])", new_name, text)

    if replaced == text:
        if allow_missing:
            return False
        raise SystemExit(f"error: {shim_path} does not mention {old_name!r}; the launcher layout changed upstream")
    shim_path.write_text(replaced, encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    product = subparsers.add_parser("product", help="merge the branding overlay into product.json")
    product.add_argument("--path", type=pathlib.Path, required=True, help="the application's product.json")
    product.add_argument("--overlay", type=pathlib.Path, required=True, help="product.overlay.json")
    product.add_argument("--version", required=True, help="the PartCAD version being built")

    plist = subparsers.add_parser("plist", help="rebrand the macOS Info.plist")
    plist.add_argument("--path", type=pathlib.Path, required=True, help="Contents/Info.plist")
    plist.add_argument("--name", required=True)
    plist.add_argument("--identifier", required=True)
    plist.add_argument("--version", required=True)
    plist.add_argument("--icon", help="the CFBundleIconFile name, without the .icns suffix")

    shim = subparsers.add_parser("shim", help="repoint the bin/ launcher at the renamed executable")
    shim.add_argument("--path", type=pathlib.Path, required=True)
    shim.add_argument("--from", dest="old_name", required=True)
    shim.add_argument("--to", dest="new_name", required=True)
    shim.add_argument(
        "--allow-missing",
        action="store_true",
        help="report, rather than fail, when the launcher does not mention the old name. For the names that only "
        "appear on one platform's launcher.",
    )

    args = parser.parse_args(argv)

    if args.command == "product":
        branded = brand_product(args.path, args.overlay, args.version)
        print(f"{args.path}: {branded['nameLong']} ({branded['applicationName']})")
    elif args.command == "plist":
        brand_plist(args.path, args.name, args.identifier, args.version, args.icon)
        print(f"{args.path}: {args.name} ({args.identifier})")
    else:
        changed = brand_shim(args.path, args.old_name, args.new_name, args.allow_missing)
        outcome = f"{args.old_name} -> {args.new_name}" if changed else f"no {args.old_name} to replace"
        print(f"{args.path}: {outcome}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
