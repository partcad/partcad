#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Which of `pc`'s settings `pc daemon start` hands to the daemon it starts."""

import types

import pytest

from partcad_cli.click.commands.daemon import start


@pytest.fixture
def config(monkeypatch):
    import partcad_utils.user_config as module

    fake = types.SimpleNamespace(
        offline=False, force_update=False, python_sandbox="conda", python_sandbox_declared=False
    )
    monkeypatch.setattr(module, "user_config", fake)
    return fake


def test_a_sandbox_nobody_chose_is_not_forwarded(config):
    """The fallback is not a choice: forwarded, the daemon obeyed it and never preferred Docker."""
    assert "--python-sandbox" not in start.daemon_args()


def test_a_sandbox_somebody_chose_is(config):
    config.python_sandbox = "docker"
    config.python_sandbox_declared = True
    args = start.daemon_args()
    assert args[args.index("--python-sandbox") + 1] == "docker"
