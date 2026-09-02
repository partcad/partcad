#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The repository releases everything under one version. This checks it.

`pc upgrade` asks `partcad_client.__version__` what is installed and compares it
against the newest release. A version constant that stopped moving is therefore
not cosmetic: it makes the CLI either never upgrade or upgrade forever. Two of
them had stopped moving -- `partcad-utils` and `partcad-service-json-rpc` were
added to the monorepo without being added to `dev-tools/bumpversion.toml` -- and
nothing noticed, because nothing read them.

Most of what this file guarded against went with the packaging. There used to be
five distributions pinning each other at `==`, so a stale pin meant an
unsatisfiable install; there is one now, and within it a pin is an import. What
remains is the per-package `__version__` constants -- still six of them, because
six packages still report a version at runtime -- and the places outside Python
that state the release.

It reads `bumpversion.toml` rather than hardcoding a list, so a package added
later is covered the moment it is declared there, and is caught if it is not.
"""

import json
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
import partcad_ide_client
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
    "partcad_cli": partcad_cli,
    "partcad_client": partcad_client,
    "partcad_utils": partcad_utils,
    "partcad_service_json_rpc": partcad_service_json_rpc,
    "partcad_ide_client": partcad_ide_client,
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
    expected = "src/%s/__init__.py" % name
    assert expected in filenames, "%s is not in dev-tools/bumpversion.toml" % expected


def test_every_package_under_src_reports_a_version():
    """The map above is hand-written; this is what notices a new package.

    Adding one to `src/` without a version constant is easy to do and impossible
    to see: nothing imports it for its version, so nothing complains until a
    release reports the wrong one.
    """
    found = sorted(p.name for p in (REPO_ROOT / "src").iterdir() if (p / "__init__.py").is_file())
    assert found == sorted(PACKAGES), (
        "src/ and the PACKAGES map above disagree. Add the new package to both, and to "
        "dev-tools/bumpversion.toml, or the release will report its version wrong."
    )


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


# The Claude Code plugin, which ships from this repository as the `pc` plugin of
# the `partcad` marketplace. None of the tests above can see it: `PACKAGES` maps
# importable modules, and the self-pin scan reads requirements files. Nothing
# imports a plugin manifest and nothing pins it, which is why it sat at the
# 0.1.0 it was created with while twenty-three releases went out around it.
CLAUDE_PLUGIN_MANIFEST = REPO_ROOT / "ai-agents" / "claude" / ".claude-plugin" / "plugin.json"


def test_the_claude_plugin_states_the_release_version():
    """The plugin is published by the release, so it states the release."""
    version = json.loads(CLAUDE_PLUGIN_MANIFEST.read_text(encoding="utf-8"))["version"]
    assert version == _bumpversion()["current_version"], (
        "ai-agents/claude/.claude-plugin/plugin.json is out of step with the release. The plugin is "
        "published by the same release as the wheel and states the same version."
    )


def test_the_claude_plugin_is_declared_in_bumpversion():
    """Declared, so that it moves; the test above only says that it has."""
    filenames = {entry["filename"] for entry in _bumpversion()["files"]}
    expected = "ai-agents/claude/.claude-plugin/plugin.json"
    assert expected in filenames, "%s is not in dev-tools/bumpversion.toml" % expected


# The two distributions this repository publishes. Scoped deliberately: an
# unrelated third-party dependency that happens to sit at the same version number
# today must not be swept in and then start failing on the day it makes a release
# of its own.
#
# `partcad-cli` is the compatibility shim in `dev-tools/shim/`, which pins `partcad` at
# exactly this version. That pin is the only intra-repository one left -- the
# rest became imports when the five distributions became one.
PARTCAD_DISTRIBUTIONS = (
    "partcad",
    "partcad-cli",
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

# The pinned files and the pip-compile inputs alike. The inputs are not merely
# scanned early: `requirements-dev.in` has no compiled counterpart at all -- CI
# installs it with `pip install -r` directly -- so a pin added there would be read
# by nothing here if only ".txt" were globbed. `pyproject.toml` is globbed too,
# because the shim states its pin there rather than in a requirements file.
REQUIREMENTS_GLOBS = ("*requirements*.txt", "*requirements*.in", "**/pyproject.toml")


def _self_pins():
    """Every PartCAD self-pin in the tree, as (relative path, "name[extras]==", version)."""
    found = []
    for path in sorted(candidate for glob in REQUIREMENTS_GLOBS for candidate in REPO_ROOT.rglob(glob)):
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
    the FreeCAD addon's two constants, and `partcad_ide_client`.

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
