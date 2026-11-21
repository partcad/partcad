#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The Gemini CLI extension `materialize.sh` writes at the root of the `plugin-dist` tree.

Gemini CLI reads `gemini-extension.json` only at the root of what it installs,
and drops a skill whose name it does not accept without a word -- so what is
checked is that the tree it would install has both, and that it carries what the
Claude plugin carries, under the names every other agent knows the skills by.
"""

import json
import os
import subprocess
import sys

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(ROOT, "ai-agents", "scripts", "gemini_extension.py")
LIBRARY = os.path.join(ROOT, "ai-agents", "common", "skills")


@pytest.fixture(scope="module")
def extension(tmp_path_factory):
    out = tmp_path_factory.mktemp("extension")
    # `-I`: the script must work with nothing installed, as on a bare runner.
    subprocess.run([sys.executable, "-I", SCRIPT, str(out)], check=True, capture_output=True)
    return out


def test_the_manifest_is_at_the_root_and_states_the_release(extension):
    manifest = json.loads((extension / "gemini-extension.json").read_text(encoding="utf-8"))
    with open(os.path.join(ROOT, "ai-agents", "claude", ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
        assert manifest["version"] == json.load(f)["version"]
    assert manifest["name"] == "partcad"
    assert manifest["contextFileName"] == "GEMINI.md"
    assert (extension / "GEMINI.md").is_file()


def test_the_server_is_pc_mcp_for_the_workspace(extension):
    manifest = json.loads((extension / "gemini-extension.json").read_text(encoding="utf-8"))
    assert manifest["mcpServers"]["partcad"] == {"command": "pc", "args": ["-p", "${workspacePath}", "mcp"]}


def test_every_skill_in_the_library_is_carried_renamed(extension):
    shipped = sorted(name for name in os.listdir(LIBRARY) if os.path.isfile(os.path.join(LIBRARY, name, "SKILL.md")))
    carried = sorted(os.listdir(extension / "skills"))
    assert carried == ["pc-" + name for name in shipped]
    for name in carried:
        text = (extension / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        front_matter = yaml.safe_load(text[4 : text.index("\n---", 3)])
        assert front_matter["name"] == name
        assert "/pc:" not in text, name


def test_a_skills_helper_script_travels_with_it(extension):
    assert (extension / "skills" / "pc-gen-sketch" / "measure.py").is_file()
    assert (extension / "skills" / "pc-sim-assembly-fea" / "part_loads.py").is_file()


def test_the_context_names_every_skill(extension):
    context = (extension / "GEMINI.md").read_text(encoding="utf-8")
    for name in os.listdir(extension / "skills"):
        assert "`%s`" % name in context
