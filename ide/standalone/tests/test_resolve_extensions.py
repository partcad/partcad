#
# PartCAD, 2026
#
# Author: PartCAD (support@partcad.org)
#
# Licensed under Apache License, Version 2.0.
#

import pytest
import resolve_extensions
from conftest import COMPONENT_ROOT, REPO_ROOT
from resolve_extensions import PolicyError, build_plan


def test_a_recommendation_is_installed_from_the_gallery_by_default():
    plan = build_plan(["a.b"], {})
    (entry,) = plan["install"]
    assert entry == {
        "id": "a.b",
        "origin": "recommended",
        "action": "install",
        "source": "gallery",
        "url": None,
        "required": False,
        "reason": None,
    }


def test_skipping_needs_a_reason():
    with pytest.raises(PolicyError, match="why it cannot ship"):
        build_plan(["a.b"], {"extensions": {"a.b": {"action": "skip"}}})


def test_a_skipped_extension_is_not_installed():
    plan = build_plan(["a.b"], {"extensions": {"a.b": {"action": "skip", "reason": "proprietary"}}})
    assert plan["install"] == []
    assert plan["skip"][0]["reason"] == "proprietary"


def test_an_override_for_something_no_longer_recommended_is_an_error():
    # Otherwise removing an extension from .vscode/extensions.json leaves a
    # policy entry that reads as if it were still in force.
    with pytest.raises(PolicyError, match="no longer recommends"):
        build_plan(["a.b"], {"extensions": {"gone.away": {"required": True}}})


def test_an_extra_that_is_already_recommended_is_an_error():
    with pytest.raises(PolicyError, match="recommended already"):
        build_plan(["a.b"], {"extra": {"a.b": {}}})


def test_a_vsix_source_needs_a_url():
    with pytest.raises(PolicyError, match="needs a"):
        build_plan(["a.b"], {"extensions": {"a.b": {"source": "vsix"}}})


def test_an_unknown_key_is_an_error():
    with pytest.raises(PolicyError, match="unknown key"):
        build_plan(["a.b"], {"extensions": {"a.b": {"requried": True}}})


def test_locally_built_extensions_are_required():
    plan = build_plan(["a.b"], {}, local={"PartCAD.partcad-official": "/tmp/partcad.vsix"})
    (entry,) = [item for item in plan["install"] if item["id"] == "PartCAD.partcad-official"]
    assert entry["required"] and entry["source"] == "local" and entry["path"] == "/tmp/partcad.vsix"


def test_the_shipped_policy_matches_the_shipped_recommendations():
    # The check that catches a recommendation added to .vscode/extensions.json
    # that the policy contradicts, and a policy entry left behind by one that
    # was removed.
    plan = resolve_extensions.load_plan(
        REPO_ROOT,
        COMPONENT_ROOT / "extensions.json",
        {"PartCAD.partcad-official": "partcad.vsix", "PartCAD.partcad-ide-bootstrap": "bootstrap.vsix"},
    )
    installed = {entry["id"] for entry in plan["install"]}
    required = {entry["id"] for entry in plan["install"] if entry["required"]}

    assert "PartCAD.partcad-official" in required, "the IDE has to ship the PartCAD extension"
    assert "PartCAD.partcad-ide-bootstrap" in required, "without it the IDE does not open the PartCAD workbench"
    # An `extensionDependency` of the PartCAD extension: it does not activate
    # without it. The viewer used to be a second one; it is built into the
    # PartCAD extension now, so nothing third-party has to be there to draw.
    assert "ms-python.python" in required
    assert "ms-python.vscode-pylance" not in installed, "it cannot be redistributed"
