#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`pc upgrade` refuses inside a bundle the editor extension owns.

The extension downloads a standalone bundle into its own `globalStorageUri` and
replaces it by being updated itself. Upgrading from inside that bundle would
install a second copy the extension does not know about, and the extension would
go on running the old one -- so this is a refusal with a reason, not a no-op.

Two signals are checked, because they cover different ways of getting here: the
environment variable the extension sets on the terminals it opens (exact, and
editor-agnostic), and the install path (for a bundle reached from anywhere else).
"""

import os
import sys

import pytest

from partcad_client import selfupdate


@pytest.fixture
def frozen_at(monkeypatch):
    """Make the module believe it is a frozen bundle at a given path."""

    def _frozen(path):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", path)

    monkeypatch.delenv(selfupdate.MANAGED_BY_ENV, raising=False)
    return _frozen


def _extension_bundle(*, version="0.8.0"):
    """The path shape the extension's `cachedBundleRoot` produces."""
    return os.sep.join(
        [
            "",
            "home",
            "someone",
            ".config",
            "Code",
            "User",
            "globalStorage",
            "partcad.partcad",
            "partcad-bundle",
            version,
            "pc",
        ]
    )


def test_the_environment_variable_is_enough(monkeypatch):
    """A terminal the extension opened says so, whatever the tools are."""
    monkeypatch.setenv(selfupdate.MANAGED_BY_ENV, selfupdate.MANAGED_BY_EXTENSION)
    assert selfupdate.installation_kind() == selfupdate.KIND_IDE_MANAGED


def test_an_unrelated_value_is_not_enough(monkeypatch, frozen_at):
    """Only the extension's own marker counts."""
    monkeypatch.setenv(selfupdate.MANAGED_BY_ENV, "something-else")
    frozen_at(os.sep.join(["", "opt", "partcad", "0.8.0", "pc"]))
    assert selfupdate.installation_kind() == selfupdate.KIND_STANDALONE


def test_a_bundle_under_globalStorage_is_recognised_without_the_variable(frozen_at):
    """A plain OS terminal has no marker, so the path is what is left to read."""
    frozen_at(_extension_bundle())
    assert selfupdate.installation_kind() == selfupdate.KIND_IDE_MANAGED


def test_install_sh_bundles_are_still_ordinary_standalone(frozen_at):
    """`install.sh` writes to XDG_DATA_HOME, which `pc upgrade` may replace."""
    frozen_at(os.sep.join(["", "home", "someone", ".local", "share", "partcad", "0.8.0", "pc"]))
    assert selfupdate.installation_kind() == selfupdate.KIND_STANDALONE


def test_both_path_segments_are_required(frozen_at):
    """An unrelated `globalStorage` is not a PartCAD bundle."""
    frozen_at(os.sep.join(["", "home", "someone", ".config", "Code", "User", "globalStorage", "other", "pc"]))
    assert selfupdate.installation_kind() == selfupdate.KIND_STANDALONE


def test_a_wheel_install_is_unaffected_by_the_variable(monkeypatch):
    """The variable marks the tools, and a wheel is not the tools it marks.

    A user can perfectly well `pip install partcad` into a venv and run it from a
    terminal the extension seeded. That installation is theirs to upgrade, so the
    marker must not capture it -- which is why the path half of the check is
    guarded on `sys.frozen`, and why this asserts the whole classification rather
    than just the path helper.
    """
    monkeypatch.delenv(selfupdate.MANAGED_BY_ENV, raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert selfupdate.installation_kind() in (selfupdate.KIND_WHEEL, selfupdate.KIND_SOURCE)


def test_check_refuses_and_names_the_remedy(monkeypatch):
    """The refusal has to say what to do instead, or it is just a failure."""
    monkeypatch.setenv(selfupdate.MANAGED_BY_ENV, selfupdate.MANAGED_BY_EXTENSION)

    def fail(*_args, **_kwargs):
        raise AssertionError("check() must not reach the network for a refusal")

    monkeypatch.setattr(selfupdate, "latest_version", fail)

    status = selfupdate.check()

    assert status["kind"] == selfupdate.KIND_IDE_MANAGED
    assert status["update_available"] is False
    assert "extension" in status["reason"]
    assert "Update the extension" in status["reason"]


def test_update_raises_rather_than_installing(monkeypatch):
    """`check()` reporting a reason is what `update()` turns into an error."""
    monkeypatch.setenv(selfupdate.MANAGED_BY_ENV, selfupdate.MANAGED_BY_EXTENSION)

    def fail(*_args, **_kwargs):
        raise AssertionError("nothing may be installed for an extension-managed bundle")

    monkeypatch.setattr(selfupdate, "_install_standalone", fail)
    monkeypatch.setattr(selfupdate, "_install_wheels", fail)

    with pytest.raises(selfupdate.SelfUpdateError) as excinfo:
        selfupdate.update()

    assert "Update the extension" in str(excinfo.value)


def test_before_install_is_never_called(monkeypatch):
    """`pc upgrade` passes a callback that stops every local daemon.

    Refusing has to happen before that runs: taking the daemons down and then
    failing would leave the user worse off than not having tried.
    """
    monkeypatch.setenv(selfupdate.MANAGED_BY_ENV, selfupdate.MANAGED_BY_EXTENSION)
    called = []

    with pytest.raises(selfupdate.SelfUpdateError):
        selfupdate.update(before_install=lambda: called.append(True))

    assert called == []
