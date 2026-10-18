#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The MCP Registry entry, `server.json`, against what it describes.

`deploy.yml` publishes it after the wheel, and a published version is final:
the registry refuses to take it again, changed or not. So everything it states
is checked here, where a mistake costs a red test rather than a listing that
installs the wrong thing until the next release:

* the release it names, which bump-my-version has to keep moving;
* the ownership proof, `mcp-name:` in README.md, which is the wheel's PyPI
  description and the only thing the registry reads to decide the wheel is ours;
* the command it tells a client to run, `uvx partcad mcp`, and the variable it
  offers for the package to serve.
"""

import json
import pathlib
import re
import tomllib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SERVER = json.loads((REPO_ROOT / "server.json").read_text(encoding="utf-8"))
PYPROJECT = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
BUMPVERSION = tomllib.loads((REPO_ROOT / "dev-tools" / "bumpversion.toml").read_text(encoding="utf-8"))


def _package():
    (package,) = SERVER["packages"]
    return package


def test_the_entry_names_this_release_twice():
    release = BUMPVERSION["tool"]["bumpversion"]["current_version"]
    assert SERVER["version"] == release
    assert _package()["version"] == release


def test_bumpversion_moves_the_entry():
    assert "server.json" in {entry["filename"] for entry in BUMPVERSION["tool"]["bumpversion"]["files"]}


def test_the_name_is_in_the_namespace_this_repository_can_publish():
    """GitHub OIDC from a repository owned by 'partcad' grants io.github.partcad/* and nothing else."""
    assert SERVER["name"].startswith("io.github.partcad/")
    assert re.fullmatch(r"[a-zA-Z0-9.-]+/[a-zA-Z0-9._-]+", SERVER["name"])
    assert 1 <= len(SERVER["description"]) <= 100


def test_the_wheels_description_carries_the_ownership_proof():
    assert PYPROJECT["project"]["readme"] == "README.md"
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    # The registry wants the name followed by a boundary -- whitespace, a tag or
    # the end of the comment -- so that a sentence's full stop does not join it.
    assert re.search(r"mcp-name: %s(?=\s|-->|<)" % re.escape(SERVER["name"]), readme), (
        "README.md has no 'mcp-name: %s'. It is the PyPI description of the wheel, and the MCP Registry "
        "refuses to publish server.json without it." % SERVER["name"]
    )


def test_the_package_is_this_wheel_from_pypi():
    package = _package()
    assert package["registryType"] == "pypi"
    assert package["registryBaseUrl"] == "https://pypi.org"
    assert package["identifier"] == PYPROJECT["project"]["name"]
    assert package["transport"] == {"type": "stdio"}


def test_the_command_it_names_is_the_one_this_wheel_has():
    """`uvx partcad mcp`: a console script named after the wheel, and a subcommand of it called `mcp`."""
    package = _package()
    assert package["runtimeHint"] == "uvx"
    assert PYPROJECT["project"]["scripts"][package["identifier"]] == "partcad_cli.click.command:cli"
    assert package["packageArguments"] == [{"type": "positional", "value": "mcp"}]

    from partcad_cli.click.command import cli

    assert cli.get_command(None, "mcp") is not None


def test_the_variable_it_offers_is_the_one_pc_reads(monkeypatch, tmp_path):
    """``PC_PATH`` is ``pc --path``: no ``envvar`` of its own, so click derives it from the root's prefix."""
    import click

    from partcad_cli.click.command import cli

    (variable,) = _package()["environmentVariables"]
    option = next(param for param in cli.params if param.name == "path")
    monkeypatch.setenv(variable["name"], str(tmp_path))
    context = click.Context(cli, **cli.context_settings)
    assert option.resolve_envvar_value(context) == str(tmp_path)
