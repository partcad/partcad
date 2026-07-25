#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#
"""Tests the repository plugin script against the endpoint, without PartCAD.

'remote.handle' is driven with a 'fetch' backed by the Flask test client, so the
plugin's request/response mapping is exercised against the real server logic
without binding a port or starting the sandbox runtime.
"""

import importlib.util
import os

import pytest

pytest.importorskip("flask")

_here = os.path.dirname(__file__)
# Load 'remote.py' under a unique module name; other examples ship one too.
_spec = importlib.util.spec_from_file_location("full_remote", os.path.join(_here, "remote.py"))
remote = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(remote)

_sspec = importlib.util.spec_from_file_location("full_server", os.path.join(_here, "server.py"))
server = importlib.util.module_from_spec(_sspec)
_sspec.loader.exec_module(server)


@pytest.fixture
def fetch():
    client = server.create_app().test_client()

    def _fetch(endpoint, key):
        resp = client.get("/data", query_string={"key": key})
        return resp.get_json()["result"] if resp.status_code == 200 else None

    return _fetch


def test_handle_lists_parts(fetch):
    out = remote.handle({"key": "objects/part", "parameters": {}}, fetch=fetch)
    assert set(out["result"].keys()) == {"cube", "cylinder"}


def test_handle_gets_single_part(fetch):
    out = remote.handle({"key": "objects/part/cube", "parameters": {}}, fetch=fetch)
    assert out["result"]["type"] == "cadquery"


def test_handle_unknown_key_is_empty(fetch):
    out = remote.handle({"key": "objects/part/missing", "parameters": {}}, fetch=fetch)
    assert out["result"] is None
