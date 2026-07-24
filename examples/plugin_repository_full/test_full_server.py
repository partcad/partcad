#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#
"""Standalone pytest coverage for the example's repository endpoint.

This exercises the "remote" server directly, without PartCAD, proving that the
mocked endpoint is ordinary, testable Python. It uses Flask's test client, so no
port is bound.
"""

import os
import sys

import pytest

pytest.importorskip("flask")

sys.path.insert(0, os.path.dirname(__file__))

import server  # noqa: E402


@pytest.fixture
def client():
    app = server.create_app()
    app.testing = True
    return app.test_client()


def test_list_parts(client):
    """objects/part enumerates the whole catalog."""
    resp = client.get("/data", query_string={"key": "objects/part"})
    assert resp.status_code == 200
    result = resp.get_json()["result"]
    assert set(result.keys()) == {"cube", "cylinder"}
    assert result["cube"]["type"] == "cadquery"


def test_get_single_part(client):
    """objects/part/<name> fetches one part without listing everything."""
    resp = client.get("/data", query_string={"key": "objects/part/cylinder"})
    assert resp.status_code == 200
    assert resp.get_json()["result"]["path"] == "cylinder.py"


def test_empty_kinds_are_present(client):
    """Kinds the package does not use still resolve, to an empty listing."""
    for kind in ("sketch", "assembly"):
        resp = client.get("/data", query_string={"key": "objects/" + kind})
        assert resp.status_code == 200
        assert resp.get_json()["result"] == {}


def test_unknown_key_is_404(client):
    resp = client.get("/data", query_string={"key": "objects/part/nonexistent"})
    assert resp.status_code == 404
    assert resp.get_json()["key"] == "objects/part/nonexistent"
