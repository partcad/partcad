#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Catch the one thing a parallel `poetry install` can get wrong: a file two wheels both own.

Two distributions are allowed to install the same path, and pip will let the
second overwrite the first without complaint. That is only safe while the two
installs happen one after the other. `poetry install` runs its installer with
several workers, so two of them can write that one path *at the same time*, and
what lands is neither wheel's file: a blend of both, of whichever length the
last writer left behind, with the other's bytes in the middle of it.

Nothing notices. pip records both RECORDs as installed, the file is present and
the right size, and `poetry install` reports success. The failure comes later
and somewhere else. For a native module it is the worst kind: the `import` hands
a corrupt ELF to the dynamic loader, which walks a relocation table that no
longer means anything and dies in `_dl_relocate_object` -- SIGSEGV, with no
Python traceback and no message at all. When something imports it at module
scope, as `tests/partcad/unit/test_assembly.py` imports build123d, that is a
whole pytest *collection* killed by a segmentation fault, which is a very long
way from "one file is corrupt".

That is what happened here, to `OCP/OCP.cpython-*.so`: `cadquery-ocp` and
`cadquery-ocp-novtk` are separate distributions that ship the very same 160 MB
native module, and `poetry.lock` put both in one install batch. `cadquery-ocp`
is no longer declared in `pyproject.toml` -- see the comment on the `partcad`
dependency group -- so that particular file has one owner again and cannot be
written twice. This stays because the next such pair will not announce itself
either, and because a *sandbox* still installs both (ordered, one `pip install`
at a time, by `partcad.sandbox_versions.GUARD_INVALIDATED_BY`).

So this reads what pip already recorded. Every `RECORD` names the hash of every
file its wheel installed; a path claimed by two distributions with two different
hashes is a file one of them overwrote, and the installed bytes must hash to one
of the two. Matching neither is the blend above, and is the only thing this
reports.

    poetry run python dev-tools/check_installed_files.py         # report
    poetry run python dev-tools/check_installed_files.py --fix   # report and reinstall

Through `poetry run`, and not a bare `python3`: the environment this reads is
whichever interpreter runs it, so a bare `python3` inspects and repairs the
host's `site-packages` while leaving the project's `.venv` -- the one
`poetry install` damaged -- exactly as it was.

`--fix` reinstalls the distribution that has to win where `GUARD_INVALIDATED_BY`
names one, rather than restating that here, and `--no-deps` so that repairing
one file cannot re-resolve the environment around it. A contested path no rule
covers is reported and left alone: which copy should survive is not something to
guess at.

Run it after `poetry install` on any machine that installs natively -- a cloud
agent session, a CI runner outside the dev container. The dev container's image
installs from `.devcontainer/requirements.txt` with pip, one wheel at a time,
which is why this has never been the container's problem.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import importlib.util
import pathlib
import subprocess
import sys
import sysconfig

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def record_hash(data: bytes) -> str:
    """The hash as a `RECORD` spells it: urlsafe base64 of the digest, unpadded."""
    return base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()


def load_pinned_winners() -> set[str]:
    """The distributions `sandbox_versions` says must be installed last.

    Loaded by path rather than imported as `partcad.sandbox_versions`, because
    importing the package pulls in the whole CAD stack -- including the very
    module whose corruption this script exists to diagnose. `sandbox_versions`
    itself imports nothing but `re`.
    """
    module_path = REPO_ROOT / "src" / "partcad" / "sandbox_versions.py"
    spec = importlib.util.spec_from_file_location("_pc_sandbox_versions", module_path)
    if spec is None or spec.loader is None:
        return set()
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    winners = set()
    for requirements in getattr(module, "GUARD_INVALIDATED_BY", {}).values():
        for requirement in requirements:
            winners.add(requirement)
    return winners


def distribution_name(requirement: str) -> str:
    """'cadquery-ocp==7.9.3.1.1' -> 'cadquery-ocp', normalised the way a RECORD is."""
    name = requirement.split("==")[0].split(">")[0].split("<")[0].strip()
    return name.replace("_", "-").lower()


def read_records(site_packages: pathlib.Path) -> dict[str, dict[str, str]]:
    """Map each installed path to the distributions that claim it and the hash each recorded.

    Keyed by the path as the RECORD spells it (relative to site-packages), then
    by the dist-info directory it came from.
    """
    claims: dict[str, dict[str, str]] = {}
    for dist_info in sorted(site_packages.glob("*.dist-info")):
        record = dist_info / "RECORD"
        if not record.exists():
            continue
        for row in csv.reader(record.read_text(encoding="utf-8", errors="replace").splitlines()):
            if len(row) < 2 or not row[1].startswith("sha256="):
                continue
            claims.setdefault(row[0], {})[dist_info.name] = row[1][len("sha256=") :]
    return claims


def contested_paths(claims: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    """Only the paths two or more distributions install with *different* contents.

    Two wheels shipping a byte-identical `__init__.py` overwrite each other
    harmlessly and forever; there is nothing to get wrong there, and reporting
    it would bury the one case that matters.
    """
    return {path: owners for path, owners in claims.items() if len(owners) > 1 and len(set(owners.values())) > 1}


def site_packages_dir() -> pathlib.Path:
    """Where the interpreter running this would import from."""
    return pathlib.Path(sysconfig.get_paths()["purelib"])


def check(site_packages: pathlib.Path) -> list[tuple[str, dict[str, str]]]:
    """Every contested path whose installed bytes match no wheel that ships it."""
    broken = []
    for path, owners in sorted(contested_paths(read_records(site_packages)).items()):
        installed = site_packages / path
        if not installed.exists():
            broken.append((path, owners))
            continue
        digest = record_hash(installed.read_bytes())
        if digest not in owners.values():
            broken.append((path, owners))
    return broken


def missing_files(site_packages: pathlib.Path) -> dict[str, list[str]]:
    """Distributions with a file they recorded installing that is no longer there.

    The other half of two wheels owning one path, and the half that shows up
    when one of them is *removed*: uninstalling a distribution deletes the files
    its RECORD names, including the ones the wheel beside it also installed, so
    a `poetry sync` that drops one leaves the other believing it owns files that
    are gone. That is what `poetry sync` does to `OCP/` when it removes
    `cadquery-ocp` from a checkout that predates its removal from
    `pyproject.toml` -- `cadquery-ocp-novtk` stays installed and `import OCP`
    stops working, with nothing in the output of either command about it.

    Existence only, no hashing: this walks every RECORD in the environment, and
    the question here is not whether a file was overwritten but whether anything
    is there at all.
    """
    gone: dict[str, list[str]] = {}
    for path, owners in read_records(site_packages).items():
        if (site_packages / path).exists():
            continue
        for dist in owners:
            gone.setdefault(dist, []).append(path)
    return gone


def dist_info_requirement(dist_info: str) -> str:
    """'cadquery_ocp_novtk-7.9.3.1.1.dist-info' -> 'cadquery-ocp-novtk==7.9.3.1.1'."""
    stem = dist_info[: -len(".dist-info")] if dist_info.endswith(".dist-info") else dist_info
    name, _, version = stem.rpartition("-")
    return "%s==%s" % (name.replace("_", "-"), version)


def reinstall(requirement: str) -> int:
    """`--no-deps`, so that putting one distribution's files back cannot re-resolve the rest."""
    print("Reinstalling %s" % requirement)
    return subprocess.run(
        [sys.executable, "-m", "pip", "install", "--force-reinstall", "--no-deps", requirement],
        check=False,
    ).returncode


def repair(broken: list[tuple[str, dict[str, str]]], winners: set[str]) -> int:
    """Reinstall the distribution that has to end up owning each damaged path."""
    wanted = {}
    for path, owners in broken:
        claimants = {dist.split("-")[0].replace("_", "-").lower() for dist in owners}
        for requirement in winners:
            if distribution_name(requirement) in claimants:
                wanted[requirement] = path

    if not wanted:
        print(
            "No pinned winner covers the damaged files above, so there is nothing safe to\n"
            "reinstall automatically. Reinstall the distributions named beside each path by\n"
            "hand, one at a time, ending with the one whose copy of the file should survive.",
            file=sys.stderr,
        )
        return 1

    for requirement, path in sorted(wanted.items()):
        print("%s owns %s, so it goes in last" % (requirement, path))
        code = reinstall(requirement)
        if code != 0:
            return code
    return 0


def main() -> int:
    """Report, and with `--fix` repair, whatever the two checks above find."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--fix",
        action="store_true",
        help="reinstall the distribution whose copy of a damaged file has to win",
    )
    parser.add_argument(
        "--site-packages",
        type=pathlib.Path,
        default=None,
        help="the directory to check; defaults to the running interpreter's own",
    )
    args = parser.parse_args()

    site_packages = args.site_packages or site_packages_dir()
    broken = check(site_packages)
    gone = missing_files(site_packages)
    if not broken and not gone:
        print("%s: every file two wheels share is one wheel's file, and nothing is missing." % site_packages)
        return 0

    if broken:
        print("Files below were written by two wheels at once and match neither:", file=sys.stderr)
        for path, owners in broken:
            installed = site_packages / path
            size = installed.stat().st_size if installed.exists() else 0
            print("  %s (%d bytes on disk)" % (path, size), file=sys.stderr)
            for dist, digest in sorted(owners.items()):
                print("      claimed by %s, sha256=%s" % (dist, digest), file=sys.stderr)

    if gone:
        print("Distributions below recorded installing files that are not there:", file=sys.stderr)
        for dist, paths in sorted(gone.items()):
            print("  %s is missing %d of its files, among them:" % (dist, len(paths)), file=sys.stderr)
            for path in sorted(paths)[:3]:
                print("      %s" % path, file=sys.stderr)

    if not args.fix:
        print(
            "\nRerun with --fix, or reinstall those distributions by hand. Until then an\n"
            "import of an affected module either fails outright or, where the file is a\n"
            "corrupt native module, takes the interpreter down with SIGSEGV and no traceback.",
            file=sys.stderr,
        )
        return 1

    # The overwritten files first: repairing those reinstalls a whole
    # distribution, which may well put back the missing ones too.
    if broken:
        code = repair(broken, load_pinned_winners())
        if code != 0:
            return code

    for dist in sorted(missing_files(site_packages)):
        code = reinstall(dist_info_requirement(dist))
        if code != 0:
            return code

    still_broken = check(site_packages)
    still_gone = missing_files(site_packages)
    if still_broken or still_gone:
        names = [p for p, _ in still_broken] + sorted(still_gone)
        print("Still damaged after the reinstall: %s" % ", ".join(names), file=sys.stderr)
        return 1
    print("Repaired.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
