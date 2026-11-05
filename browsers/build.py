#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Packages the PartCAD login extension for the browser stores.

    python browsers/build.py [--out DIRECTORY] [--check]

writes, into `browsers/dist` unless told otherwise:

* `partcad-login-chromium-<version>.zip` -- `browsers/chromium`, which the
  Chrome Web Store and Microsoft Edge Add-ons both take as it is;
* `partcad-login-firefox-<version>.xpi` -- `browsers/firefox`, for
  addons.mozilla.org, or for a Firefox that installs unsigned extensions.

Neither directory needs building to be used -- `pc login` loads them unpacked --
so all this does is check them and zip them. The checks are the ones that would
otherwise only show in a browser: the two manifests stating different versions,
and the files the two directories share having drifted apart. Every file but
`manifest.json` is shared, and a copy that differs is a fix made for one browser
and not the other.

The archives are reproducible: the entries are sorted and carry a fixed
timestamp and mode, so the same tree gives the same archive -- the same bytes,
given the same zlib -- and a store upload can be compared with the build that
made it.

Only the standard library, so that CI can run it on a bare Python.
"""

import argparse
import json
import pathlib
import sys
import zipfile

HERE = pathlib.Path(__file__).resolve().parent

# Each browser, and the extension its store expects the archive to carry.
PACKAGES = {"chromium": "zip", "firefox": "xpi"}

# The one file each browser has its own of. Everything else is shared.
PER_BROWSER = frozenset({"manifest.json"})

# The earliest timestamp a zip entry can hold, for every entry.
TIMESTAMP = (1980, 1, 1, 0, 0, 0)


class BuildError(Exception):
    pass


def files(directory):
    """Every file an extension directory ships, as sorted POSIX paths relative to it.

    Hidden files are what an editor or an operating system leaves behind, never
    part of the extension. A symbolic link is refused rather than followed: it
    would be packaged as whatever it points at on this machine, and checked out
    on Windows it is a text file holding a path.
    """
    found = []
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if any(part.startswith(".") for part in relative.parts):
            continue
        if path.is_symlink():
            raise BuildError("%s is a symbolic link; the extension has to hold the file itself" % path)
        if path.is_file():
            found.append(relative.as_posix())
    return found


def manifest(root, browser):
    return json.loads((root / browser / "manifest.json").read_text(encoding="utf-8"))


def check(root=HERE):
    """The problems that would make the two packages disagree, as sentences; empty when there are none."""
    problems = []
    listings = {}
    for browser in PACKAGES:
        try:
            listings[browser] = files(root / browser)
        except BuildError as error:
            problems.append(str(error))
            listings[browser] = []
    shared = {browser: set(listing) - PER_BROWSER for browser, listing in listings.items()}
    chromium, firefox = shared["chromium"], shared["firefox"]
    for name in sorted(chromium ^ firefox):
        where = "chromium" if name in chromium else "firefox"
        problems.append("%s is in browsers/%s only; every file but manifest.json is in both" % (name, where))
    for name in sorted(chromium & firefox):
        if (root / "chromium" / name).read_bytes() != (root / "firefox" / name).read_bytes():
            problems.append(
                "browsers/chromium/%s and browsers/firefox/%s differ; they are one file kept twice" % (name, name)
            )
    versions = {browser: manifest(root, browser).get("version") for browser in PACKAGES}
    if len(set(versions.values())) != 1:
        problems.append("the manifests state different versions: %s" % versions)
    return problems


def version(root=HERE):
    problems = check(root)
    if problems:
        raise BuildError("\n".join(problems))
    return manifest(root, "chromium")["version"]


def archive_name(browser, version_, suffix):
    return "partcad-login-%s-%s.%s" % (browser, version_, suffix)


def package(directory, destination):
    """Zip one extension directory, its manifest at the root of the archive."""
    with zipfile.ZipFile(destination, "w") as archive:
        for name in files(directory):
            entry = zipfile.ZipInfo(name, date_time=TIMESTAMP)
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.create_system = 3  # Unix, so the mode below means the same thing everywhere.
            entry.external_attr = 0o644 << 16
            archive.writestr(entry, (directory / name).read_bytes())


def build(root=HERE, out=None):
    """Check and package both extensions; returns the paths written."""
    version_ = version(root)
    out = pathlib.Path(out) if out else root / "dist"
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for browser, suffix in PACKAGES.items():
        destination = out / archive_name(browser, version_, suffix)
        package(root / browser, destination)
        written.append(destination)
    return written


def main(argv=None):
    parser = argparse.ArgumentParser(description="Package the PartCAD login extension for the browser stores.")
    parser.add_argument("--out", type=pathlib.Path, help="where to write the packages (default: browsers/dist)")
    parser.add_argument("--check", action="store_true", help="only check the two extension directories")
    args = parser.parse_args(argv)
    try:
        if args.check:
            print("PartCAD login extension %s: both directories agree" % version())
            return 0
        for path in build(out=args.out):
            print(path)
    except BuildError as error:
        print("error: %s" % error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
