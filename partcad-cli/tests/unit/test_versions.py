#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The monorepo releases every component under one version. This checks it.

`pc upgrade` asks `partcad_client_utils.__version__` what is installed and compares it
against the newest release. A version constant that stopped moving is therefore
not cosmetic: it makes the CLI either never upgrade or upgrade forever. Two of
them had stopped moving -- `partcad-utils` and `partcad-service-json-rpc` were
added to the monorepo without being added to `dev-tools/bumpversion.toml` -- and
nothing noticed, because nothing read them.

This test reads `bumpversion.toml` rather than hardcoding a list, so a component
added later is covered the moment it is declared there, and is caught if it is
not.
"""

import tomllib
from pathlib import Path

import partcad_cli
import partcad_client_utils
import partcad_service_json_rpc
import partcad_utils
import pytest

import partcad

REPO_ROOT = Path(__file__).resolve().parents[3]
BUMPVERSION = REPO_ROOT / "dev-tools" / "bumpversion.toml"

# Every package that reports a version at runtime. `partcad_client_utils` is the
# one `pc upgrade` actually reads.
PACKAGES = {
    "partcad": partcad,
    "partcad-cli": partcad_cli,
    "partcad-client-utils": partcad_client_utils,
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
