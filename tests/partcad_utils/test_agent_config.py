#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What `pc mcp --root <path>` serves, wherever the agent started it.

The path is relative to the folder of the `.mcp.json` holding the entry, which
is not always the directory the server is started in: Claude Code reads the
`.mcp.json` of every folder above the one it was started in, and starts the
server in that one. `partcad.ai_agents` writes the entry; this is how the
server reads it back.
"""

import json
import os

from partcad_utils import agent_config


def write_config(folder, *roots, name="partcad"):
    servers = {
        "%s-%d" % (name, index): {"command": "pc", "args": ["mcp", "--root", root]} for index, root in enumerate(roots)
    }
    (folder / ".mcp.json").write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")


def test_from_the_folder_holding_the_file(tmp_path):
    """Visual Studio Code, and Claude Code started there: the plain case."""
    write_config(tmp_path, "hw")
    assert agent_config.resolve_root(str(tmp_path), "hw") == str(tmp_path / "hw")


def test_from_a_folder_below_it(tmp_path):
    """Claude Code started in a subfolder still means the folder its entry came from."""
    write_config(tmp_path, "hw")
    started = tmp_path / "hw" / "motor" / "docs"
    started.mkdir(parents=True)

    assert agent_config.config_folder(str(started), "hw") == str(tmp_path)
    assert agent_config.resolve_root(str(started), "hw") == str(tmp_path / "hw")
    assert agent_config.resolve_root(str(started), ".") is None  # no entry says "."


def test_a_file_on_the_way_up_that_does_not_name_the_root_is_passed_over(tmp_path):
    """Claude Code merges them all; the one that started this server is the one naming its root."""
    write_config(tmp_path, "hw")
    inner = tmp_path / "hw"
    inner.mkdir()
    write_config(inner, ".", name="other")
    (inner / "sub").mkdir()

    assert agent_config.resolve_root(str(inner / "sub"), "hw") == str(tmp_path / "hw")
    assert agent_config.resolve_root(str(inner / "sub"), ".") == str(inner)


def test_the_nearest_file_naming_the_root_wins(tmp_path):
    write_config(tmp_path, ".")
    inner = tmp_path / "inner"
    inner.mkdir()
    write_config(inner, ".")

    assert agent_config.resolve_root(str(inner), ".") == str(inner)


def test_with_no_file_naming_it_there_is_no_answer(tmp_path):
    """Started somewhere that file is not: the image given the wrong folder to mount, or a person typing it.

    A directory chosen anyway would be a guess, and `--root .` would always find
    one -- the wrong one.
    """
    (tmp_path / "hw").mkdir()
    assert agent_config.config_folder(str(tmp_path), "hw") is None
    assert agent_config.resolve_root(str(tmp_path), "hw") is None
    assert agent_config.resolve_root(str(tmp_path), ".") is None


def test_files_that_are_not_configurations_are_passed_over(tmp_path):
    (tmp_path / ".mcp.json").write_text("{ not json", encoding="utf-8")
    inner = tmp_path / "a"
    inner.mkdir()
    (inner / ".mcp.json").write_text('{"mcpServers": ["not", "an", "object"]}', encoding="utf-8")

    assert agent_config.config_folder(str(inner), "hw") is None


def test_an_absolute_root_is_taken_as_it_is(tmp_path):
    assert agent_config.resolve_root(str(tmp_path), str(tmp_path / "x" / "..")) == str(tmp_path)


def test_the_root_argument_is_read_out_of_an_entry():
    assert agent_config.root_argument(["mcp", "--root", "hw"]) == "hw"
    assert agent_config.root_argument(["-p", "hw", "mcp"]) is None
    assert agent_config.root_argument(["mcp", "--root"]) is None
    assert agent_config.root_argument("mcp --root hw") is None


def test_a_climbing_root_resolves_above_the_folder(tmp_path):
    """An editor opened on a folder inside the root: `pc init --editor-folder` writes `--root ..`."""
    docs = tmp_path / "docs"
    docs.mkdir()
    write_config(docs, "..")
    assert agent_config.resolve_root(str(docs), "..") == os.path.normpath(str(tmp_path))


# --- Every agent's file, not only `.mcp.json` ---


def test_a_codex_table_is_found(tmp_path):
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "config.toml").write_text(
        '[mcp_servers.partcad]\ncommand = "pc"\nargs = ["mcp", "--root", "hw"]\n', encoding="utf-8"
    )
    (tmp_path / "hw" / "sub").mkdir(parents=True)
    assert agent_config.resolve_root(str(tmp_path / "hw" / "sub"), "hw") == str(tmp_path / "hw")


def test_a_codex_table_is_found_without_a_toml_parser(tmp_path, monkeypatch):
    """Python 3.10 with no `tomli`: the lines `pc init` writes are read as JSON."""
    import builtins

    real_import = builtins.__import__

    def no_toml(name, *args, **kwargs):
        if name in ("tomllib", "tomli"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_toml)
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "config.toml").write_text(
        '[mcp_servers.partcad]\ncommand = "pc"\nargs = ["mcp", "--root", "hw"]\n', encoding="utf-8"
    )
    assert agent_config.config_folder(str(tmp_path), "hw") == str(tmp_path)


def test_an_opencode_command_array_under_its_own_key_is_found(tmp_path):
    config = {"mcp": {"servers": {"partcad-hw": {"type": "local", "command": ["pc", "mcp", "--root", "hw"]}}}}
    (tmp_path / "opencode.json").write_text(json.dumps(config), encoding="utf-8")
    assert agent_config.config_folder(str(tmp_path), "hw") == str(tmp_path)


def test_a_zed_server_is_found(tmp_path):
    (tmp_path / ".zed").mkdir()
    config = {"theme": "x", "context_servers": {"partcad": {"command": "pc", "args": ["mcp", "--root", "."]}}}
    (tmp_path / ".zed" / "settings.json").write_text(json.dumps(config), encoding="utf-8")
    assert agent_config.config_folder(str(tmp_path), ".") == str(tmp_path)


def test_the_editor_and_the_ide_name_the_variable_pc_init_reads():
    """Three languages, one name, and nothing to import across them: a test is what holds them together."""
    import pathlib
    import re

    repository = pathlib.Path(__file__).resolve().parents[2]
    extension = (repository / "ide" / "vscode" / "src" / "common" / "workspaceFolderEnv.ts").read_text(encoding="utf-8")
    assert "export const WORKSPACE_FOLDER_ENV = '%s';" % agent_config.WORKSPACE_FOLDER_ENV in extension
    bootstrap = (repository / "ide" / "standalone" / "bootstrap" / "extension.js").read_text(encoding="utf-8")
    assert re.search(r"\b%s: directory\b" % agent_config.WORKSPACE_FOLDER_ENV, bootstrap)
