#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'-x'/'--exclude' on the commands that walk a subtree of packages.

What is pinned here is what reaches the daemon: one spelling, one parameter
name, on every command that offers it. What the daemon does with it is tested
beside 'Context.get_all_packages' and the operations.
"""

import importlib

import pytest
from click.testing import CliRunner

from partcad_cli.click.command import cli


class _Recorder:
    def __init__(self):
        self.calls = []

    def run(self, cli_ctx, method, params, needs_context=False):
        self.calls.append((method, params))
        return None


def _record(monkeypatch, *modules):
    recorder = _Recorder()
    for module in modules:
        monkeypatch.setattr(importlib.import_module("partcad_cli.click.commands." + module), "run", recorder.run)
    return recorder


def _invoke(*args):
    return CliRunner().invoke(cli, ["--no-ansi", *args])


@pytest.mark.parametrize(
    "module, method, args",
    [
        ("test", "test.run", ["test", "-P", "//pub..."]),
        ("render", "render.objects", ["render", "-P", "//pub..."]),
        ("lint", "lint.run", ["lint", "-P", "//pub..."]),
        ("info", "info.object", ["info", "//pub...:bolt"]),
        ("sim", "simulate.run", ["sim", "-P", "//pub..."]),
        ("list.parts", "list.objects", ["list", "parts", "//pub..."]),
        ("list.packages", "list.packages", ["list", "packages", "//pub..."]),
    ],
)
def test_every_exclusion_reaches_the_daemon(monkeypatch, module, method, args):
    recorder = _record(monkeypatch, module)

    result = _invoke(*args, "-x", "//pub/universe/lego/ldraw", "--exclude", "//pub/electronics/sbcs/intel")

    # Not 'exit_code == 0': what a command does with the answer is its own
    # business ('pc sim' fails a run that simulated nothing, which this fake
    # answer is). A usage error, though, would be the option not parsing.
    assert result.exit_code != 2, result.output
    ((called, params),) = recorder.calls
    assert called == method
    assert params["exclude"] == ["//pub/universe/lego/ldraw", "//pub/electronics/sbcs/intel"]


def test_no_exclusion_is_an_empty_list(monkeypatch):
    recorder = _record(monkeypatch, "test")

    result = _invoke("test", "-P", "//pub...")

    assert result.exit_code == 0, result.output
    ((_, params),) = recorder.calls
    assert params["exclude"] == []


_LISTINGS = (
    "assemblies",
    "interfaces",
    "materials",
    "mates",
    "packages",
    "parts",
    "providers",
    "scenes",
    "sketches",
    "software",
)


def test_list_all_passes_its_exclusions_to_every_listing_it_runs(monkeypatch):
    recorder = _record(monkeypatch, *("list." + name for name in _LISTINGS))

    result = _invoke("list", "all", "-r", "-x", "//pub/universe/lego/ldraw", "//pub")

    assert result.exit_code == 0, result.output
    walks = [params for _, params in recorder.calls if params.get("recursive")]
    assert {params.get("kind") for params in walks} >= {"parts", "assemblies", "sketches", "scenes"}
    assert all(params["exclude"] == ["//pub/universe/lego/ldraw"] for params in walks)


def test_lint_of_named_files_takes_no_exclusion(monkeypatch, tmp_path):
    """'--file' checks the files it names, so there is no walk to leave anything out of."""
    recorder = _record(monkeypatch, "lint")
    (tmp_path / "partcad.yaml").write_text("name: //test\n")

    result = _invoke("lint", "--file", str(tmp_path / "partcad.yaml"), "-x", "//pub")

    assert result.exit_code != 0
    assert "-x" in result.output
    assert recorder.calls == []
