#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Catch the one thing a parallel `poetry install` can get wrong: a file two wheels both own.

`cadquery-ocp` and `cadquery-ocp-novtk` are separate distributions that ship the
very same native module, `OCP/OCP.cpython-*.so` -- 160 MB of it. That much is
known and deliberate; `partcad.sandbox_versions.GUARD_INVALIDATED_BY` exists
because of it, and orders the installs inside a sandbox so the build with VTK in
it is the one that survives.

What that ordering assumes is that the two installs happen one after the other.
`poetry install` runs its installer with several workers, and `poetry.lock` puts
both distributions in the same install batch, so on a machine slow enough to
lose the race the two workers write that one path *at the same time*. What lands
is neither wheel's file: a blend of both, of whichever length the last writer
left behind, with the other's bytes in the middle of it.

Nothing notices. pip records both RECORDs as installed, the file is present and
executable and the right size, and `poetry install` reports success. The failure
comes later and somewhere else: `import OCP` hands a corrupt ELF to the dynamic
loader, which walks a relocation table that no longer means anything and dies in
`_dl_relocate_object`. The process takes SIGSEGV with no Python traceback and no
message at all -- and since `tests/partcad/unit/test_assembly.py` imports
build123d at module scope, that is a whole pytest *collection* killed by a
segmentation fault, which is a very long way from "one file is corrupt".

So this reads what pip already recorded. Every `RECORD` names the hash of every
file its wheel installed; a path claimed by two distributions with two different
hashes is a file one of them overwrote, and the installed bytes must hash to one
of the two. Matching neither is the blend above, and is the only thing this
reports.

    python3 dev-tools/check_installed_files.py           # report
    python3 dev-tools/check_installed_files.py --fix     # report and reinstall

`--fix` reinstalls the distribution that has to win, taking that from
`GUARD_INVALIDATED_BY` rather than restating it here, and `--no-deps` so that
repairing one file cannot re-resolve the environment around it.

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
        print("Reinstalling %s so that its copy of %s is the one that survives" % (requirement, path))
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--force-reinstall", "--no-deps", requirement],
            check=False,
        )
        if result.returncode != 0:
            return result.returncode
    return 0


def main() -> int:
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
    if not broken:
        print("%s: every file two wheels share is one wheel's file." % site_packages)
        return 0

    print("Files below were written by two wheels at once and match neither:", file=sys.stderr)
    for path, owners in broken:
        installed = site_packages / path
        size = installed.stat().st_size if installed.exists() else 0
        print("  %s (%d bytes on disk)" % (path, size), file=sys.stderr)
        for dist, digest in sorted(owners.items()):
            print("      claimed by %s, sha256=%s" % (dist, digest), file=sys.stderr)

    if not args.fix:
        print(
            "\nRerun with --fix, or reinstall those distributions by hand. Until then an\n"
            "import of the affected module can take the interpreter down with SIGSEGV and\n"
            "no traceback.",
            file=sys.stderr,
        )
        return 1

    code = repair(broken, load_pinned_winners())
    if code != 0:
        return code

    still_broken = check(site_packages)
    if still_broken:
        print("Still damaged after the reinstall: %s" % ", ".join(p for p, _ in still_broken), file=sys.stderr)
        return 1
    print("Repaired.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
