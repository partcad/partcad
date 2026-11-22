#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc mcp --root`: the PartCAD root, relative to the `.mcp.json` that names it.

What `pc init` writes into `.mcp.json` (see `partcad.ai_agents.mcp`). The
resolution itself is tested in `tests/partcad_utils/test_agent_config.py`; this
is the command around it -- what it hands the server, and what it refuses.
"""

import json
import re

import pytest
from click.testing import CliRunner

from partcad_cli.click.command import cli


@pytest.fixture
def served(monkeypatch):
    """The workspace `pc mcp` would serve, instead of serving it."""
    import partcad_client.mcp_server as mcp_server

    calls = []
    monkeypatch.setattr(mcp_server, "serve", lambda workspace, **kwargs: calls.append(workspace))
    return calls


@pytest.fixture
def repository(tmp_path):
    (tmp_path / "hw" / "motor").mkdir(parents=True)
    (tmp_path / "hw" / "partcad.yaml").write_text("desc: hw\n", encoding="utf-8")
    entry = {"type": "stdio", "command": "pc", "args": ["mcp", "--root", "hw"]}
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {"partcad": entry}}), encoding="utf-8")
    return tmp_path


def invoke(*args):
    return CliRunner().invoke(cli, ["--no-ansi", *args])


def message(result) -> str:
    """The output as words: rich-click draws an error in a box, wrapping it across lines."""
    return " ".join(re.sub(r"\x1b\[[0-9;]*m|[│╭╮╰╯─]", " ", result.output).split())


def test_started_where_the_file_is(repository, served, monkeypatch):
    monkeypatch.chdir(repository)
    result = invoke("mcp", "--root", "hw")
    assert result.exit_code == 0, result.output
    assert served == [str(repository / "hw")]


def test_started_below_where_the_file_is(repository, served, monkeypatch):
    """Claude Code started in a subfolder reads the file above it and starts the server in the subfolder."""
    monkeypatch.chdir(repository / "hw" / "motor")
    result = invoke("mcp", "--root", "hw")
    assert result.exit_code == 0, result.output
    assert served == [str(repository / "hw")]


def test_started_where_no_configuration_names_it_says_where_to_start_the_agent(tmp_path, served, monkeypatch):
    """In the PartCAD image with the wrong folder mounted, `--root .` would otherwise serve that folder."""
    (tmp_path / "hw").mkdir()
    monkeypatch.chdir(tmp_path)
    for root in ("hw", "."):
        result = invoke("mcp", "--root", root)
        assert result.exit_code != 0
        assert "start the agent in the folder" in message(result)
    assert served == []


def test_a_root_that_is_gone_is_refused(repository, served, monkeypatch):
    (repository / "hw" / "partcad.yaml").unlink()
    (repository / "hw" / "motor").rmdir()
    (repository / "hw").rmdir()
    monkeypatch.chdir(repository)
    result = invoke("mcp", "--root", "hw")
    assert result.exit_code != 0
    assert "does not exist" in message(result)
    assert served == []


def test_root_and_path_are_one_too_many(repository, served, monkeypatch):
    monkeypatch.chdir(repository)
    result = invoke("-p", str(repository / "hw"), "mcp", "--root", "hw")
    assert result.exit_code != 0
    assert "give one of them" in message(result)
    assert served == []


def test_without_root_nothing_changes(repository, served, monkeypatch):
    monkeypatch.chdir(repository / "hw")
    assert invoke("mcp").exit_code == 0
    assert invoke("-p", str(repository / "hw"), "mcp").exit_code == 0
    assert served == [str(repository / "hw"), str(repository / "hw")]
