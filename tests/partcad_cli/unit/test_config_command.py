#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What `pc config` says the configuration resolved to.

The command exists to answer one question -- what is this machine actually
going to do -- so an option missing from its output is worse than a wrong
value: nothing looks wrong. That is what happened when `pythonSandbox` became a
property, because the obvious way to enumerate a configuration ('vars()') sees
instance attributes and a property is not one.
"""

from partcad_utils.config_report import resolved_options
from partcad_utils.user_config import UserConfig

# What the command prints, through the function it prints with. That function
# lives in `partcad_utils` rather than in the command, because `pc system status
# config` and the daemon's own `daemon.status.config` print the same report and
# a redaction rule with three copies has two that can stop redacting.


def _printed():
    """What the command prints, keyed by option name."""
    return dict(resolved_options(UserConfig()))


def test_an_option_kept_as_a_property_is_reported(monkeypatch, tmp_path):
    """'pythonSandbox' is one, so that assigning it counts as a decision."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("PC_PYTHON_SANDBOX", raising=False)

    printed = _printed()

    assert "python_sandbox" in printed
    assert printed["python_sandbox"] in ("conda", "venv", "none", "pypy", "docker", "remote")
    # And the flag beside it, which is what decides whether a container runtime
    # gets to override that value.
    assert printed["python_sandbox_declared"] is False


def test_an_ordinary_attribute_is_still_reported(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert "use_docker" in _printed()


def test_nothing_private_is_reported(monkeypatch, tmp_path):
    """A property's backing attribute would otherwise be printed twice, once
    under a name nobody configured."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert not [key for key in _printed() if key.startswith("_")]


def test_each_option_is_reported_once(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    names = [key for key, _value in resolved_options(UserConfig())]
    assert len(names) == len(set(names))


def test_a_secret_is_reported_as_set_and_never_printed(monkeypatch, tmp_path):
    """This output is what people paste into bug reports.

    A shared secret that runs commands on another machine is not a thing to put
    in one, and "is it configured?" is the whole of what a reader of `pc config`
    needs from it.
    """
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PC_REMOTE_SANDBOX_TOKEN", "s3cret")

    printed = _printed()

    assert printed["remote_sandbox_token"] == "<set>"
    assert "s3cret" not in str(printed)


def test_an_unset_secret_says_so(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("PC_REMOTE_SANDBOX_TOKEN", raising=False)

    assert _printed()["remote_sandbox_token"] == "<not set>"
