#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The monorepo releases every component under one version. This checks it.

`pc upgrade` asks `partcad_client.__version__` what is installed and compares it
against the newest release. A version constant that stopped moving is therefore
not cosmetic: it makes the CLI either never upgrade or upgrade forever. Two of
them had stopped moving -- `partcad-utils` and `partcad-service-json-rpc` were
added to the monorepo without being added to `dev-tools/bumpversion.toml` -- and
nothing noticed, because nothing read them.

This test reads `bumpversion.toml` rather than hardcoding a list, so a component
added later is covered the moment it is declared there, and is caught if it is
not.
"""

import re
from pathlib import Path

# `tomllib` is only in the standard library from Python 3.11. This repo still
# supports 3.10 (`requires-python = ">=3.10,<3.15"`, and the CI matrix runs it),
# and pytest is run with `-x`, so a bare `import tomllib` here is not one failing
# test -- it is a collection error that aborts the entire run on every 3.10 job.
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

import partcad_cli
import partcad_client
import partcad_service_json_rpc
import partcad_utils
import pytest

import partcad

REPO_ROOT = Path(__file__).resolve().parents[3]
BUMPVERSION = REPO_ROOT / "dev-tools" / "bumpversion.toml"

# Every package that reports a version at runtime. `partcad_client` is the
# one `pc upgrade` actually reads.
PACKAGES = {
    "partcad": partcad,
    "partcad-cli": partcad_cli,
    "partcad-client": partcad_client,
    "partcad-utils": partcad_utils,
    "partcad-service-json-rpc": partcad_service_json_rpc,
}


def _bumpversion() -> dict:
    return tomllib.loads(BUMPVERSION.read_text(encoding="utf-8"))["tool"]["bumpversion"]


@pytest.mark.parametrize("name", sorted(PACKAGES))
def test_package_version_matches_the_release_version(name):
    assert PACKAGES[name].__version__ == _bumpversion()["current_version"], (
        "%s.__version__ is out of step. Add it to dev-tools/bumpversion.toml if it is missing there." % name
    )


@pytest.mark.parametrize("name", sorted(PACKAGES))
def test_every_package_is_declared_in_bumpversion(name):
    """A package missing from the config silently stops being bumped."""
    filenames = {entry["filename"] for entry in _bumpversion()["files"]}
    module_dir = name.replace("-", "_")
    assert any(
        "%s/src/%s/__init__.py" % (name, module_dir) == filename for filename in filenames
    ), "%s/src/%s/__init__.py is not in dev-tools/bumpversion.toml" % (name, module_dir)


def test_every_bumpversion_search_string_still_matches():
    """A renamed or moved file leaves its entry silently doing nothing.

    That is how the extension's minimum-version bound stopped moving: the check
    was migrated into the operations core and the entry kept naming the file it
    had left.
    """
    config = _bumpversion()
    current = config["current_version"]
    unmatched = []
    for entry in config["files"]:
        text = (REPO_ROOT / entry["filename"]).read_text(encoding="utf-8")
        if entry["search"].replace("{current_version}", current) not in text:
            unmatched.append("%s: %s" % (entry["filename"], entry["search"]))
    assert not unmatched, "bumpversion entries that match nothing:\n  " + "\n  ".join(unmatched)


# Every distribution this monorepo publishes under the one version. Scoped
# deliberately: an unrelated third-party dependency that happens to sit at the
# same version number today must not be swept in and then start failing on the
# day it makes a release of its own.
PARTCAD_DISTRIBUTIONS = (
    "partcad",
    "partcad-cli",
    "partcad-client",
    "partcad-utils",
    "partcad-service-json-rpc",
    "partcad-ide-client",
)

# "partcad[lint]==0.7.146" and friends: a pin on ourselves, with or without extras.
SELF_PIN = re.compile(
    r"^(?P<name>%s)(?P<extras>\[[a-z,]+\])?==(?P<version>[^\s;#]+)" % "|".join(PARTCAD_DISTRIBUTIONS),
    re.MULTILINE,
)

# Vendored, installed or generated trees. Nothing under them is ours to bump:
# "bundled" is where the VS Code extension packages third-party wheels, and the
# rest are dependency and build directories.
SKIPPED_DIRS = frozenset({".git", ".venv", ".nox", ".tox", "node_modules", "bundled", "build", "dist"})


def _self_pins():
    """Every PartCAD self-pin in the tree, as (relative path, "name[extras]==", version)."""
    found = []
    for path in sorted(REPO_ROOT.rglob("*requirements*.txt")):
        relative = path.relative_to(REPO_ROOT)
        if SKIPPED_DIRS.intersection(relative.parts):
            continue
        for match in SELF_PIN.finditer(path.read_text(encoding="utf-8")):
            token = "%s%s==" % (match.group("name"), match.group("extras") or "")
            found.append((relative.as_posix(), token, match.group("version")))
    return found


def test_no_partcad_self_pin_is_stale():
    """A pin on ourselves that stopped moving is a broken install, not a typo.

    `partcad-cli/requirements.txt` pins `partcad=={current_version}`, and the
    pass-through extras re-state that same pin as `partcad[lint]==...` and so on.
    Both are requirements of one install, so the moment the two disagree
    `pip install partcad-cli[lint]` is unsatisfiable. That is what had happened:
    the three `partcad-cli` extras files sat at 0.7.146, 0.7.158 and 0.7.158 while
    everything around them moved, because none of them was named in
    `dev-tools/bumpversion.toml`.

    The tests above are all driven either by the hardcoded `PACKAGES` map or by
    what `bumpversion.toml` already declares, so none of them can see a file that
    file does not mention. This one reads the tree instead.
    """
    current = _bumpversion()["current_version"]
    stale = [
        "%s: %s%s (expected %s)" % (filename, token, version, current)
        for filename, token, version in _self_pins()
        if version != current
    ]
    assert not stale, "PartCAD self-pins left behind by the version bump:\n  " + "\n  ".join(stale)


def test_every_partcad_self_pin_is_declared_in_bumpversion():
    """Undeclared is how they go stale; the release after is when it shows.

    `dev-tools/bumpversion.toml` warns about exactly this in its own comment: a
    thing added to the monorepo without being added there keeps whatever version
    it was created with while everything else moves. It has now happened four
    times -- `partcad/requirements.txt`, the three `partcad-cli` extras files,
    the FreeCAD addon's two constants, and `partcad-ide-client`.

    A new file is correct on the day it is written, so the staleness test above
    only starts failing one release later, in a commit that touches nothing near
    it. This checks the declaration rather than the value, so it fails while the
    author is still looking at the file they just added.
    """
    current = _bumpversion()["current_version"]
    declared = {
        (entry["filename"], entry["search"].replace("{current_version}", current)) for entry in _bumpversion()["files"]
    }
    undeclared = [
        "%s: %s%s" % (filename, token, version)
        for filename, token, version in _self_pins()
        if not any(
            entry_filename == filename and "%s%s" % (token, current) in entry_search
            for entry_filename, entry_search in declared
        )
    ]
    assert not undeclared, (
        "PartCAD self-pins that no [[tool.bumpversion.files]] entry moves:\n  "
        + "\n  ".join(undeclared)
        + "\nAdd an entry naming the file to dev-tools/bumpversion.toml."
    )
