#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The Lockwire plugin ('plugins/qual-lockwire'): what Lockwire's document becomes in PartCAD.

Lockwire itself is not installed here; a stand-in 'lockwire.api' answers the way
'lockwire check --json' documents its answer.
"""

import os
import runpy
import sys
import types

import pytest

PLUGIN = os.path.join(os.path.dirname(__file__), "..", "..", "..", "plugins", "qual-lockwire", "lockwire_qual.py")

VIOLATION = {
    "severity": "violation",
    "quantity": "budgets/bud.power.servo-5v",
    "observed": "32.10 W",
    "expected": "<= 15.00 W",
    "delta": "+17.10 W (+114%)",
    "dependent": "dev.pi5, dev.servo1",
    "action": "raise the rail",
}
WARNING = {"severity": "warning", "quantity": "budgets/bud.mass", "observed": "1.2 kg", "expected": "<= 1.0 kg"}
NOT_SCORED = {"severity": "not_scored", "quantity": "budgets/bud.bus"}


@pytest.fixture
def plugin():
    return runpy.run_path(PLUGIN)


@pytest.fixture
def lockwire(monkeypatch):
    answers = {}
    api = types.ModuleType("lockwire.api")

    def check(path):
        answers["path"] = path
        if "error" in answers:
            raise ValueError(answers["error"])
        return answers["document"]

    api.check = check
    package = types.ModuleType("lockwire")
    package.api = api
    monkeypatch.setitem(sys.modules, "lockwire", package)
    monkeypatch.setitem(sys.modules, "lockwire.api", api)
    return answers


def _request(tmp_path, **extra):
    (tmp_path / "lockwire.yaml").write_text("schema_version: '0.4'\n")
    return {"package_dir": str(tmp_path), "lockfile": "lockwire.yaml", **extra}


def test_a_no_go_fails_with_every_violation_in_lockwires_words(plugin, lockwire, tmp_path):
    lockwire["document"] = {
        "robot": "rover",
        "verdict": "NO-GO",
        "exit_code": 1,
        "counts": {"violation": 1, "warning": 0, "not_scored": 1},
        "findings": [VIOLATION, NOT_SCORED],
    }
    answer = plugin["process"](str(tmp_path), _request(tmp_path))
    assert lockwire["path"] == str(tmp_path / "lockwire.yaml")
    assert answer["passed"] is False
    assert answer["findings"][0] == {
        "level": "error",
        "text": "VIOLATION budgets/bud.power.servo-5v — observed 32.10 W, expected <= 15.00 W (Δ +17.10 W (+114%)); "
        "dependent: dev.pi5, dev.servo1; action: raise the rail",
    }
    assert answer["findings"][1]["level"] == "info"
    assert answer["report"]["title"] == "Lockwire: rover"
    assert answer["report"]["verdict"] == "NO-GO"
    assert [row["severity"] for row in answer["report"]["rows"]] == ["violation", "not_scored"]


def test_go_with_notes_passes_unless_strict(plugin, lockwire, tmp_path):
    lockwire["document"] = {"verdict": "GO_WITH_NOTES", "exit_code": 0, "counts": {"warning": 1}, "findings": [WARNING]}
    assert plugin["process"](str(tmp_path), _request(tmp_path))["passed"] is True
    strict = plugin["process"](str(tmp_path), _request(tmp_path, strict=True))
    assert strict["passed"] is False
    assert strict["findings"][-1]["text"] == "GO with notes, and 'strict' fails it"


def test_nothing_scored_is_a_skip(plugin, lockwire, tmp_path):
    lockwire["document"] = {"verdict": "NOT_SCORED", "exit_code": 3, "findings": [NOT_SCORED]}
    answer = plugin["process"](str(tmp_path), _request(tmp_path))
    assert answer["passed"] is None
    assert "scored nothing" in answer["skipped"]


def test_a_refused_lockfile_fails_saying_why(plugin, lockwire, tmp_path):
    lockwire["error"] = "contract declares schema_version '0.99'"
    answer = plugin["process"](str(tmp_path), _request(tmp_path))
    assert answer["passed"] is False
    assert "schema_version '0.99'" in answer["findings"][0]["text"]


def test_no_lockfile_fails_saying_how_to_make_one(plugin, tmp_path):
    answer = plugin["process"](str(tmp_path), {"package_dir": str(tmp_path), "lockfile": "rover.yaml"})
    assert answer["passed"] is False
    assert "lockwire start" in answer["findings"][0]["text"]


def test_the_plugin_is_declared_as_an_other_test_with_its_parameters():
    import yaml

    with open(os.path.join(os.path.dirname(PLUGIN), "partcad.yaml")) as stream:
        declaration = yaml.safe_load(stream)["qual"]["lockwire"]
    assert declaration["subtype"] == "other"
    assert declaration["path"] == "lockwire_qual.py"
    assert (declaration["lockfile"], declaration["strict"]) == ("lockwire.yaml", False)
