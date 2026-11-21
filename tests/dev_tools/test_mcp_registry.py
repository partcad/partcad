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
  offers for the package to serve;
* the image it offers beside the wheel, `ghcr.io/partcad/partcad`, which the
  registry decides is ours by a label the Dockerfile has to carry, and the
  `docker run` arguments a client is told to start it with.
"""

import json
import pathlib
import re

# `tomllib` is only in the standard library from Python 3.11, and the CI matrix
# still runs 3.10 -- see the same fallback in tests/partcad_cli/unit/test_versions.py.
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SERVER = json.loads((REPO_ROOT / "server.json").read_text(encoding="utf-8"))
PYPROJECT = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
BUMPVERSION = tomllib.loads((REPO_ROOT / "dev-tools" / "bumpversion.toml").read_text(encoding="utf-8"))


DOCKERFILE = (REPO_ROOT / "tools" / "containers" / "partcad" / "Dockerfile").read_text(encoding="utf-8")


def _package(registry_type="pypi"):
    (package,) = [package for package in SERVER["packages"] if package["registryType"] == registry_type]
    return package


def test_the_entry_offers_the_wheel_and_the_image_and_nothing_else():
    assert sorted(package["registryType"] for package in SERVER["packages"]) == ["oci", "pypi"]


def test_the_entry_names_this_release_three_times():
    release = BUMPVERSION["tool"]["bumpversion"]["current_version"]
    assert SERVER["version"] == release
    assert _package()["version"] == release
    # An image names its release in its tag, and has no "version" of its own.
    assert _package("oci")["identifier"] == "ghcr.io/partcad/partcad:%s" % release
    assert "version" not in _package("oci")


def test_bumpversion_moves_the_entry():
    files = BUMPVERSION["tool"]["bumpversion"]["files"]
    searches = {entry["search"] for entry in files if entry["filename"] == "server.json"}
    assert searches == {'"version": "{current_version}"', "ghcr.io/partcad/partcad:{current_version}"}


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


# --------------------------------------------------------------------------- #
# The image                                                                    #
# --------------------------------------------------------------------------- #


def test_the_image_carries_the_ownership_proof():
    """The registry reads `io.modelcontextprotocol.server.name` off the image, and refuses it without."""
    assert 'io.modelcontextprotocol.server.name="%s"' % SERVER["name"] in DOCKERFILE


def test_the_image_is_started_by_docker_and_speaks_on_stdio():
    package = _package("oci")
    assert package["runtimeHint"] == "docker"
    assert package["transport"] == {"type": "stdio"}
    assert package["packageArguments"] == [{"type": "positional", "value": "mcp"}]


def test_the_image_hands_its_argument_to_pc():
    """`docker run <image> mcp` is `pc mcp`: the entrypoint passes a command of `pc`'s to `pc`."""
    from partcad_cli.click.command import cli

    assert cli.get_command(None, _package("oci")["packageArguments"][0]["value"]) is not None
    entrypoint = (REPO_ROOT / "tools" / "containers" / "partcad" / "entrypoint.sh").read_text(encoding="utf-8")
    assert "set -- pc" in entrypoint


def _runtime_values(name):
    return [argument["value"] for argument in _package("oci")["runtimeArguments"] if argument["name"] == name]


def test_the_workspace_is_mounted_and_worked_in():
    """One variable, the workspace, mounted where the server then runs: the entrypoint becomes its owner."""
    (workdir,) = _runtime_values("-w")
    mounts = _runtime_values("--mount")
    assert "type=bind,src={workspace},dst=%s" % workdir in mounts
    (bind,) = [a for a in _package("oci")["runtimeArguments"] if a["value"].startswith("type=bind")]
    assert bind["variables"]["workspace"]["format"] == "filepath"
    assert bind["isRequired"] and bind["variables"]["workspace"]["isRequired"]


def test_the_state_is_kept_in_the_volume_the_image_expects():
    """Without it every run builds a CAD sandbox from nothing -- minutes, more than a client waits."""
    from partcad_utils import app_image

    assert "type=volume,src=%s,dst=%s" % (app_image.STATE_VOLUME, app_image.STATE_DIR) in _runtime_values("--mount")
    assert "PC_INTERNAL_STATE_DIR=%s" % app_image.STATE_DIR in DOCKERFILE


def test_the_hosts_docker_is_not_handed_over_by_the_registry():
    """The socket gives the container the host's Docker. A client must not add it on a listing's say-so."""
    assert not any("docker.sock" in json.dumps(argument) for argument in _package("oci")["runtimeArguments"])
