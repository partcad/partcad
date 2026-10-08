#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What `pc lint --file` takes beyond the file: the include paths and parameter values the editor's
'partcad.lint' settings pass, in the spelling every `pc` command uses for them."""

import json

from partcad_cli.click.command import cli
from partcad_utils.user_config import user_config


def test_extra_params_and_include_paths_reach_the_check(click_runner, tmp_path):
    root = tmp_path / "pkg"
    root.mkdir()
    (root / "partcad.yaml").write_text("assemblies:\n  thing:\n    type: assy\n    parameters:\n      count: 1\n")
    (root / "thing.assy").write_text("links:\n{% for n in range(param_count) %}{% include 'leg.yaml' %}{% endfor %}\n")
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "leg.yaml").write_text("\n  - part: leg\n    locaton: 1\n")

    try:
        result = click_runner.invoke(
            cli,
            [
                "--no-ansi",
                "--extra-param",
                "thing.count=2",
                "lint",
                "--file",
                str(root / "thing.assy"),
                "--include-path",
                str(shared),
                "--json",
            ],
        )
    finally:
        # The global option writes into the process's configuration.
        del user_config.parameter_config["thing"]

    report = json.loads(result.stdout.strip().splitlines()[-1])
    [diagnostic] = report["files"][0]["diagnostics"]
    # Two legs rendered, one finding: the include, with the value from the command line.
    assert diagnostic["message"] == "unexpected property 'locaton'"


def test_an_include_path_is_only_for_a_file(click_runner):
    result = click_runner.invoke(cli, ["--no-ansi", "lint", "--include-path", "."])
    assert result.exit_code != 0
    assert "--include-path" in result.output
