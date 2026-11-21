#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc -p <path> init` creates the package where `-p` says, not in the current directory.

`init` used to read a parameter named "package" -- the name `pc add` gives its
own option -- from the top-level command, which has none, so `-p` was ignored
and everything went into the directory `pc` was run from: the `partcad.yaml`,
the launch configuration, the agents' skills and their MCP configuration.
"""

from click.testing import CliRunner

from partcad_cli.click.command import cli


def run(*args):
    result = CliRunner().invoke(cli, ["--no-ansi", *args])
    assert result.exit_code == 0, result.output
    return result


def test_a_directory_is_where_the_package_is_created(tmp_path, monkeypatch):
    here = tmp_path / "here"
    there = tmp_path / "there"
    here.mkdir()
    there.mkdir()
    monkeypatch.chdir(here)

    run("-p", str(there), "init", "--agents", "cursor")

    assert (there / "partcad.yaml").is_file()
    assert (there / ".cursor" / "skills" / "pc-init" / "SKILL.md").is_file()
    assert list(here.iterdir()) == []


def test_a_yaml_file_is_the_package_file_itself(tmp_path, monkeypatch):
    """`-p` names a `partcad.yaml` too; init refuses to replace one, so that is what is seen."""
    there = tmp_path / "there"
    there.mkdir()
    existing = there / "partcad.yaml"
    existing.write_text("name: //mine\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["--no-ansi", "-p", str(existing), "init", "--no-skills"])

    assert existing.read_text(encoding="utf-8") == "name: //mine\n"
    assert not (tmp_path / "partcad.yaml").exists()
    assert "already exists" in result.output or result.exit_code != 0


def test_skills_only_goes_where_p_says(tmp_path, monkeypatch):
    here = tmp_path / "here"
    there = tmp_path / "there"
    here.mkdir()
    there.mkdir()
    monkeypatch.chdir(here)

    run("-p", str(there), "init", "--skills-only", "--agents", "kiro", "--no-mcp")

    assert (there / ".kiro" / "skills" / "pc-init" / "SKILL.md").is_file()
    assert list(here.iterdir()) == []
