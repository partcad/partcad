#
# PartCAD, 2026
#
# Author: PartCAD (support@partcad.org)
#
# Licensed under Apache License, Version 2.0.
#

"""Checks that the built application fits under Windows' MAX_PATH wherever Setup may put it.

Inno Setup's Setup cannot install a file whose full path is longer than
MAX_PATH, and nothing can be configured to change that: Setup.exe carries no
`longPathAware` manifest, so Windows holds it to 260 characters whatever the
machine's `LongPathsEnabled` says, and it refuses the `\\\\?\\` prefix that
would get around the limit as an invalid directory name. A file over the limit
is not skipped or reported up front: Setup stops at it, partway through
copying, and rolls the whole installation back.

So the limit is met here instead, before the installer is compiled. The
application has a fixed layout and Setup puts it in one of two places
(`DefaultAppDir` in `installer/partcad-ide.iss`); the only part of the path
that varies is the user name in the per-user one, so this measures every file
against the longest user name Windows allows. A file that does not fit fails
the build and is named, with the extension it came from -- in practice it is
always a third-party extension's deepest file, and the answer is to hold that
extension at a version that fits (`"version"` in `extensions.json`).

One more directory is reported rather than enforced: the per-user directory
Setup used before it was shortened, where an earlier installation stays when it
is upgraded. See `RETAINED`.

    check_install_paths.py --root <the application directory> [--location <directory>]...

`--location` adds a directory to check besides the two Setup uses: `build.sh`
passes the one the compiler reads the application from, since the compiler is
not long-path aware either.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

# MAX_PATH is 260 including the terminating NUL.
MAX_FILE = 259
# CreateDirectory leaves room for an 8.3 file name in the directory it makes:
# MAX_PATH less 12, including the NUL.
MAX_DIRECTORY = 247

# The longest user name Windows accepts (a SAM account name) is 20 characters,
# and a profile directory is normally named after it. One that is not -- a
# `<name>.<DOMAIN>` made when two accounts share a name -- can be longer, and is
# the case this cannot promise anything about.
LONGEST_USER_NAME = 20

APP_NAME = "PartCAD IDE"

# A profile directory, either side of the user name.
PROFILE = "C:\\Users\\"
PER_USER = "\\AppData\\Local\\" + APP_NAME

# Where `DefaultAppDir` in the .iss puts the application: `{localappdata}` for
# one user, `{commonpf}` for everyone. A test holds the two to each other.
INSTALL_LOCATIONS = {
    "for one user": PROFILE + "u" * LONGEST_USER_NAME + PER_USER,
    "for all users": "C:\\Program Files\\" + APP_NAME,
}

# Where the application went for one user before that: `{autopf}`, nine
# characters longer. An installation there stays there when it is upgraded
# (`UsePreviousAppDir`), so it is a third place Setup writes to. It is reported
# rather than enforced: at the longest user name nothing fits there -- that is
# why it was left -- and an installation can only be there if the release that
# made it fitted, for that user. What is reported is the longest user name an
# upgrade there still fits.
RETAINED = "%LOCALAPPDATA%\\Programs\\" + APP_NAME
RETAINED_PER_USER = "\\AppData\\Local\\Programs\\" + APP_NAME

# How many offending paths to name before summing up the rest.
SHOWN = 10


def entries(root: pathlib.Path) -> tuple[list[str], list[str]]:
    """Every file and every directory under `root`, as Windows spells it relative to `root`."""
    files: list[str] = []
    directories: list[str] = []
    for directory, subdirectories, names in os.walk(root):
        relative = pathlib.Path(directory).relative_to(root)
        for name in subdirectories:
            directories.append("\\".join((*relative.parts, name)))
        for name in names:
            files.append("\\".join((*relative.parts, name)))
    return files, directories


def origin(relative: str) -> str:
    """The extension a path belongs to, when it belongs to one."""
    parts = relative.split("\\")
    if parts[:3] == ["resources", "app", "extensions"] and len(parts) > 3:
        return f" (extension {parts[3]})"
    return ""


def longest_user_name(files: list[str], directories: list[str], per_user: str) -> int:
    """The longest user name for which every entry fits below `PROFILE<name><per_user>`."""
    fixed = len(PROFILE) + len(per_user) + 1
    return min(
        [MAX_FILE - fixed - len(path) for path in files] + [MAX_DIRECTORY - fixed - len(path) for path in directories]
    )


def check(root: pathlib.Path, locations: dict[str, str]) -> tuple[list[str], list[str]]:
    """Problems and notes for the application at `root` installed into each of `locations`."""
    files, directories = entries(root)
    problems: list[str] = []
    notes: list[str] = []

    for label, location in locations.items():
        prefix = len(location.rstrip("\\")) + 1
        too_long = sorted(
            [(prefix + len(path), path, MAX_FILE) for path in files if prefix + len(path) > MAX_FILE]
            + [(prefix + len(path), path, MAX_DIRECTORY) for path in directories if prefix + len(path) > MAX_DIRECTORY],
            reverse=True,
        )
        for length, path, limit in too_long[:SHOWN]:
            problems.append(f"{length} characters {label}, over {limit}: {location}\\{path}{origin(path)}")
        if len(too_long) > SHOWN:
            problems.append(f"... and {len(too_long) - SHOWN} more {label}")

        if files:
            deepest = max(files, key=len)
            notes.append(
                f"deepest file {label}: {prefix + len(deepest)} of {MAX_FILE} characters, "
                f"{MAX_FILE - prefix - len(deepest)} to spare: {location}\\{deepest}{origin(deepest)}"
            )

    if files:
        fits = longest_user_name(files, directories, RETAINED_PER_USER)
        if fits >= LONGEST_USER_NAME:
            notes.append(f"an upgrade of an installation in {RETAINED} fits any user name")
        else:
            notes.append(
                f"warning: an upgrade of an installation in {RETAINED}, which stays there, "
                f"fits a user name of up to {max(fits, 0)} characters"
            )

    return problems, notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=pathlib.Path, required=True, help="the built application directory")
    parser.add_argument(
        "--location",
        action="append",
        default=[],
        help="another directory the application is read from or written to, as Windows spells it",
    )
    args = parser.parse_args(argv)

    if not args.root.is_dir():
        print(f"error: {args.root} is not a directory", file=sys.stderr)
        return 2

    locations = dict(INSTALL_LOCATIONS)
    for location in args.location:
        locations[f"in {location}"] = location

    problems, notes = check(args.root, locations)
    for note in notes:
        print(f"  {note}")
    if problems:
        print(
            "error: Setup cannot install a path longer than MAX_PATH, and these would be. "
            'Hold the extension at a version that fits ("version" in extensions.json):'
        )
        for problem in problems:
            print(f"  {problem}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
