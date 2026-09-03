#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc system reset` and the package cache the bundled conda fills.

A standalone bundle carries its own conda, which keeps its packages under
PartCAD's internal state directory (`partcad_utils.conda.ROOT_PREFIX_SUBDIR`).
That is the largest thing PartCAD writes there -- gigabytes, against megabytes
for the environments built out of it -- so a reset that left it behind would not
have reset much.

The case pinned here is the one that is easy to get wrong by indentation alone:
the cache has to go even when there is no `sandbox` directory beside it. That
happens whenever the environments were removed and the cache was not, which is
precisely the state a previous half-reset leaves behind.
"""

import logging
from collections.abc import Iterator

import pytest
from click.testing import CliRunner

from partcad.user_config import user_config
from partcad_cli.click.command import cli
from partcad_utils import conda as pc_conda


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    """Point PartCAD's internal state directory at a throwaway one."""
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(user_config, "internal_state_dir", str(state))
    return state


def _make_conda_cache(state):
    cache = state / pc_conda.ROOT_PREFIX_SUBDIR / "pkgs"
    cache.mkdir(parents=True)
    (cache / "somepackage.conda").write_text("")
    return state / pc_conda.ROOT_PREFIX_SUBDIR


def test_reset_removes_the_conda_package_cache(click_runner: Iterator[CliRunner], state_dir) -> None:
    conda_dir = _make_conda_cache(state_dir)
    (state_dir / "sandbox" / "pc-py-conda-3.13").mkdir(parents=True)

    result = click_runner.invoke(cli, ["--no-ansi", "system", "reset"])
    logging.debug("result.output: %s", result.output)

    assert result.exit_code == 0
    assert not conda_dir.exists()


def test_reset_removes_the_conda_cache_with_no_sandbox_beside_it(click_runner: Iterator[CliRunner], state_dir) -> None:
    """The cache is not nested under "there are environments to remove".

    Gating it on the `sandbox` directory existing would leave the whole cache in
    place here, and nothing in the output would say so.
    """
    conda_dir = _make_conda_cache(state_dir)
    assert not (state_dir / "sandbox").exists()

    result = click_runner.invoke(cli, ["--no-ansi", "system", "reset"])
    logging.debug("result.output: %s", result.output)

    assert result.exit_code == 0
    assert not conda_dir.exists()


def test_reset_leaves_the_conda_cache_alone_for_the_other_options(click_runner: Iterator[CliRunner], state_dir) -> None:
    """It belongs to the sandboxes, so the repo and cache resets do not take it."""
    conda_dir = _make_conda_cache(state_dir)

    for option in ("--repo-only", "--cache-only"):
        result = click_runner.invoke(cli, ["--no-ansi", "system", "reset", option])
        assert result.exit_code == 0, option
        assert conda_dir.exists(), option
