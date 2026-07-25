#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#
"""Tests the CSV-backed repository plugin script directly, without PartCAD."""

import importlib.util
import os

# Load 'csv.py' under a unique module name (other examples ship plugin scripts
# too, and the file is named after the repository, not the module).
_here = os.path.dirname(__file__)
_spec = importlib.util.spec_from_file_location("basic_csv", os.path.join(_here, "csv.py"))
plugin = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(plugin)


def _get(key):
    plugin.request = {"parameters": {"filename": os.path.join(_here, "example.csv")}}
    return plugin.get(key)


def test_lists_parts():
    parts = _get("objects/part")
    assert set(parts.keys()) == {"bolt", "cube"}
    assert parts["bolt"]["type"] == "step"


def test_gets_single_part():
    assert _get("objects/part/cube")["type"] == "stl"


def test_no_children_and_has_metadata():
    assert _get("deps") == []
    assert "desc" in _get("meta")


def test_unknown_key_is_none():
    assert _get("objects/sketch") is None
    assert _get("objects/part/missing") is None
