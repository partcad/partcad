#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#
"""Tests the hierarchy-serving plugin script directly, without PartCAD.

Exercises the key space the way ProjectExternalRepository forwards it: the top
package's 'deps' and provider, and each subfolder's own objects and children.
"""

import importlib.util
import os

# Load this example's 'remote.py' under a unique module name; other examples
# ship a 'remote.py' too, and a plain 'import remote' would collide.
_spec = importlib.util.spec_from_file_location(
    "tree_remote", os.path.join(os.path.dirname(__file__), "remote.py")
)
remote = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(remote)


def _get(key):
    return remote.handle({"key": key})["result"]


def test_top_package_lists_children():
    assert _get("deps") == ["brackets", "motors"]


def test_subfolders_serve_their_own_parts():
    assert list(_get("brackets/objects/part")) == ["l_bracket"]
    assert list(_get("motors/objects/part")) == ["shaft"]


def test_subfolders_serve_their_part_files():
    import base64

    content = base64.b64decode(_get("brackets/files/l_bracket.py")).decode()
    assert "cadquery" in content


def test_leaf_subfolders_have_no_children():
    assert _get("brackets/deps") == []
    assert _get("motors/deps") == []


def test_unknown_key_is_none():
    assert _get("objects/part") is None  # the top package has no parts of its own
    assert _get("nonexistent/objects/part") is None
