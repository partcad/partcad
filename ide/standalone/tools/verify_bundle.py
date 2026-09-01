#
# PartCAD, 2026
#
# Author: PartCAD (support@partcad.org)
#
# Licensed under Apache License, Version 2.0.
#

"""
Check that a built PartCAD IDE is actually a PartCAD IDE.

Every failure this looks for is one that produces a bundle that starts and looks
right: an extension that quietly failed to install, a `product.json` that was
merged into the wrong file, tools that were never embedded. None of them would
be noticed before a user hit them, which is why the build runs this itself
rather than leaving it to a reviewer.

Required extensions missing, or branding not applied, is an error. An optional
extension missing is reported and does not fail the build -- see
`../extensions.json` for what that distinction means.
"""

import argparse
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import jsonc  # noqa: E402  (the path has to be set up first)

SERVICE_EXECUTABLES = ("partcad-json-rpc", "partcad-json-rpc.exe")

# The extension that carries the welcome window (`../bootstrap`).
BOOTSTRAP_EXTENSION = "partcad.partcad-ide-bootstrap"


def installed_extension_entries(extensions_dir: pathlib.Path) -> dict[str, tuple[pathlib.Path, dict]]:
    """Map `publisher.name` (lowercased) to (directory, manifest), for every extension found."""
    found: dict[str, tuple[pathlib.Path, dict]] = {}
    if not extensions_dir.is_dir():
        return found
    for entry in sorted(extensions_dir.iterdir()):
        manifest = entry / "package.json"
        if not manifest.is_file():
            continue
        try:
            package = jsonc.load(manifest)
        except (ValueError, UnicodeDecodeError) as error:
            raise SystemExit(f"error: {manifest} is not readable: {error}")
        publisher = package.get("publisher")
        name = package.get("name")
        if publisher and name:
            found[f"{publisher}.{name}".lower()] = (entry, package)
    return found


def installed_extensions(extensions_dir: pathlib.Path) -> dict[str, dict]:
    """Map `publisher.name` (lowercased) to its manifest, for every extension found."""
    return {identifier: package for identifier, (_, package) in installed_extension_entries(extensions_dir).items()}


def media_files(step: dict) -> list[str]:
    """The files a walkthrough step's media points at.

    `image` may be one path or one per theme, `svg` and `markdown` are a path,
    and `altText` is text rather than a file.
    """
    files = []
    for kind, value in (step.get("media") or {}).items():
        if kind == "altText":
            continue
        if isinstance(value, dict):
            files.extend(str(path) for path in value.values())
        else:
            files.append(str(value))
    return files


def check_welcome(extensions_dir: pathlib.Path, problems: list[str], notes: list[str]) -> None:
    """The welcome window: the walkthrough the IDE opens the first time it starts.

    A walkthrough is data in a manifest pointing at files beside it, so it fails
    the way data fails -- the editor renders an empty step and says nothing. The
    check is that the extension carrying it shipped both halves: a packaging
    rule that took the manifest and left the media behind produces an IDE whose
    welcome window is a list of empty pages.
    """
    entry = installed_extension_entries(extensions_dir).get(BOOTSTRAP_EXTENSION)
    if entry is None:
        # Absent altogether is reported against the plan, with the reason.
        return
    directory, manifest = entry

    walkthroughs = manifest.get("contributes", {}).get("walkthroughs", [])
    if not walkthroughs:
        problems.append(f"{BOOTSTRAP_EXTENSION} contributes no walkthrough; the IDE has no welcome window")
        return

    for walkthrough in walkthroughs:
        for step in walkthrough.get("steps", []):
            for name in media_files(step):
                if not (directory / name).is_file():
                    problems.append(
                        f"welcome window: step {step.get('id')} shows {name}, which is not in the extension"
                    )
        notes.append(
            f"welcome window: {walkthrough.get('title')} ({len(walkthrough.get('steps', []))} steps, "
            f"from {BOOTSTRAP_EXTENSION})"
        )


def activity_bar_containers(extensions: dict[str, dict]) -> list[tuple[str, str, str]]:
    """The view containers the shipped extensions add to the activity bar.

    The activity bar is the strip of icons down the side of the window, one per
    view container, and it is what a user sees first. Which icons are on it is
    decided by what the IDE ships with, so the build reports it: an extension
    added to the recommendations can put an icon there, and nobody would
    otherwise notice until the IDE was installed.

    Returns (title, container id, extension id), sorted by title.
    """
    containers = []
    for identifier, package in extensions.items():
        for container in package.get("contributes", {}).get("viewsContainers", {}).get("activitybar", []):
            containers.append((container.get("title", "?"), container.get("id", "?"), identifier))
    return sorted(containers)


def check_product(product_path: pathlib.Path, problems: list[str], notes: list[str]) -> None:
    if not product_path.is_file():
        problems.append(f"no product.json at {product_path}")
        return
    product = jsonc.load(product_path)

    expected = {
        "nameLong": "PartCAD IDE",
        "nameShort": "PartCAD IDE",
        "applicationName": "partcad-ide",
        "dataFolderName": ".partcad-ide",
    }
    for key, value in expected.items():
        if product.get(key) != value:
            problems.append(f"product.json: {key} is {product.get(key)!r}, expected {value!r}")

    if "updateUrl" in product:
        problems.append("product.json: updateUrl is still set; the IDE would offer to update itself into VSCodium")
    if not product.get("extensionsGallery", {}).get("serviceUrl"):
        problems.append("product.json: no extension gallery; users could not install any extension")
    if product.get("configurationDefaults", {}).get("partcad.backend") != "service":
        problems.append("product.json: partcad.backend does not default to 'service'")

    notes.append(
        f"product.json: {product.get('nameLong')} ({product.get('applicationName')}), gallery "
        f"{product.get('extensionsGallery', {}).get('serviceUrl')}"
    )


def check_entry_point(app_dir: pathlib.Path, problems: list[str], notes: list[str]) -> None:
    """The entry point that turns software WebGL on.

    Without it the 3D view is dead on any machine whose GPU process does not
    start, and dead silently -- Chromium reports "webgl: disabled_off" and the
    viewer sees only a failed context. The build writes `out/partcad-main.js`
    and points `package.json` at it; both halves are checked, because either one
    alone leaves the application running with the switch absent (or, worse,
    pointing at a file that is not there).
    """
    manifest_path = app_dir / "package.json"
    if not manifest_path.is_file():
        problems.append(f"no package.json at {manifest_path}")
        return

    manifest = jsonc.load(manifest_path)
    main = manifest.get("main") or ""
    if "partcad-main" not in main:
        problems.append(
            f"package.json: main is {main!r}, not the PartCAD entry point; "
            "the 3D view will not work without a GPU driver"
        )
        return

    wrapper = app_dir / pathlib.PurePosixPath(main.lstrip("./")).as_posix()
    if not wrapper.is_file():
        problems.append(f"package.json points main at {main!r}, but there is no file at {wrapper}")
        return
    if "enable-unsafe-swiftshader" not in wrapper.read_text(encoding="utf-8"):
        problems.append(f"{wrapper} does not enable software WebGL")
        return

    notes.append(f"entry point: {main} (software WebGL enabled)")


def check_executable(path: pathlib.Path, description: str, problems: list[str], notes: list[str]) -> None:
    if not path.is_file():
        problems.append(f"no {description} at {path}")
        return
    if os.name != "nt" and not os.access(path, os.X_OK):
        problems.append(f"{description} at {path} is not executable")
        return
    notes.append(f"{description}: {path.name} ({path.stat().st_size} bytes)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--resources",
        type=pathlib.Path,
        required=True,
        help="the application's resources directory (holds app/product.json)",
    )
    parser.add_argument("--plan", type=pathlib.Path, required=True, help="the plan from resolve_extensions.py")
    parser.add_argument("--executable", type=pathlib.Path, required=True, help="the renamed application executable")
    parser.add_argument("--launcher", type=pathlib.Path, required=True, help="the bin/ command line launcher")
    parser.add_argument(
        "--expect-tools",
        action="store_true",
        help="require the PartCAD command line tools to be embedded in the application",
    )
    args = parser.parse_args(argv)

    problems: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []

    check_product(args.resources / "app" / "product.json", problems, notes)
    check_entry_point(args.resources / "app", problems, notes)
    check_executable(args.executable, "application executable", problems, notes)
    check_executable(args.launcher, "command line launcher", problems, notes)

    extensions_dir = args.resources / "app" / "extensions"
    present = installed_extensions(extensions_dir)
    plan = json.loads(args.plan.read_text(encoding="utf-8"))

    for entry in plan["install"]:
        identifier = entry["id"].lower()
        if identifier in present:
            notes.append(f"extension: {entry['id']} {present[identifier].get('version', '?')}")
        elif entry["required"]:
            problems.append(f"required extension {entry['id']} is not installed")
        else:
            warnings.append(f"optional extension {entry['id']} is not installed")

    for entry in plan["skip"]:
        if entry["id"].lower() in present:
            problems.append(f"extension {entry['id']} was installed although the policy skips it: {entry['reason']}")

    check_welcome(extensions_dir, problems, notes)

    if args.expect_tools:
        tools = args.resources / "partcad-cli"
        service = next((tools / name for name in SERVICE_EXECUTABLES if (tools / name).is_file()), None)
        if service is None:
            problems.append(f"the PartCAD command line tools are not embedded at {tools}")
        else:
            check_executable(service, "bundled PartCAD service", problems, notes)

    for title, container, identifier in activity_bar_containers(present):
        notes.append(f"activity bar: {title} ({container}, from {identifier})")

    for note in notes:
        print(f"  ok       {note}")
    for warning in warnings:
        print(f"  warning  {warning}")
    for problem in problems:
        print(f"  FAILED   {problem}")

    if problems:
        print(f"\n{len(problems)} problem(s) found in {args.resources.parent}", file=sys.stderr)
        return 1
    print(f"\nVerified {len(notes)} item(s), {len(warnings)} warning(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
