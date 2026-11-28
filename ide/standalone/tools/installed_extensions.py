#
# PartCAD, 2026
#
# Author: PartCAD (support@partcad.org)
#
# Licensed under Apache License, Version 2.0.
#

"""Names the directories of the extensions the editor says are installed.

`build.sh` has the application install its extensions into a staging directory,
then copies them into the application from there. What it copies has to be what
the application says is installed, and not every directory it finds: replacing
an extension with another version takes the old one out of the editor's list but
leaves its directory where it was, marked for deletion the next time the editor
starts -- and the build never starts it.

That is what holding an extension at a version does whenever something installed
before it depends on it. `ms-python.black-formatter` depends on
`ms-python.python`, so installing it brings in the newest `ms-python.python`,
and the held one then replaces it. Copied by directory, the IDE carried both,
and the newer one was the file too deep for the Windows installer that the hold
exists to keep out.

    installed_extensions.py --extensions <directory> --listed <file>

`--listed` holds what `--list-extensions --show-versions` printed for that
directory: one `<id>@<version>` per line. The name of each listed extension's
directory is printed, one per line. A listed extension with no directory, or
with more than one, is an error: the copy would be missing it, or would not know
which to take.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import jsonc  # noqa: E402  (the path has to be set up first)


def parse_listing(text: str) -> list[tuple[str, str]]:
    """The `(id, version)` of each `<id>@<version>` line, the id lowercased as the editor compares it."""
    listed: list[tuple[str, str]] = []
    # `splitlines` rather than `split("\n")`: on Windows the listing may end
    # each line with "\r\n".
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        identifier, separator, version = line.rpartition("@")
        if not separator or "." not in identifier or not version:
            raise ValueError(f"not `<id>@<version>`: {line!r}")
        listed.append((identifier.lower(), version))
    return listed


def extension_directories(extensions_dir: pathlib.Path) -> dict[tuple[str, str], list[str]]:
    """Map the `(id, version)` of every directory holding an extension to the directories that do."""
    found: dict[tuple[str, str], list[str]] = {}
    for entry in sorted(extensions_dir.iterdir()):
        manifest = entry / "package.json"
        if not entry.is_dir() or not manifest.is_file():
            continue
        package = jsonc.load(manifest)
        publisher, name, version = package.get("publisher"), package.get("name"), package.get("version")
        if publisher and name and version:
            found.setdefault((f"{publisher}.{name}".lower(), version), []).append(entry.name)
    return found


def select(extensions_dir: pathlib.Path, listing: str) -> list[str]:
    """The directories to copy, one per listed extension. Raises `ValueError` naming what does not add up."""
    found = extension_directories(extensions_dir)
    selected: list[str] = []
    problems: list[str] = []
    for identifier, version in parse_listing(listing):
        directories = found.get((identifier, version), [])
        if len(directories) == 1:
            selected.append(directories[0])
        elif not directories:
            problems.append(f"{identifier}@{version} is listed as installed, and no directory holds it")
        else:
            problems.append(f"{identifier}@{version} is in more than one directory: {', '.join(directories)}")
    if problems:
        raise ValueError("\n  ".join(problems))
    return selected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--extensions", type=pathlib.Path, required=True, help="the directory installed into")
    parser.add_argument(
        "--listed",
        type=pathlib.Path,
        required=True,
        help="a file holding what `--list-extensions --show-versions` printed",
    )
    args = parser.parse_args(argv)

    try:
        selected = select(args.extensions, args.listed.read_text(encoding="utf-8"))
    except ValueError as error:
        print(f"error: the extensions the editor lists do not match {args.extensions}:\n  {error}", file=sys.stderr)
        return 1
    for name in selected:
        print(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
