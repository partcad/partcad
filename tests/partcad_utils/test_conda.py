#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Which conda PartCAD runs, and in what environment it runs it.

The standalone bundle carries a conda so that a machine with no conda can still
build a CAD sandbox -- and it must not displace a conda the machine already has,
whose package cache holds the gigabytes the sandbox is made of. Neither half of
that is observable from a build: a bundle built on a machine with no conda passes
its smoke test whichever way round the two are tried. So it is pinned down here,
where a bundled copy and a host copy can be made to exist at the same time.
"""

import os
import stat

import pytest

from partcad_utils import conda as pc_conda


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    """Make PartCAD look like a frozen bundle whose payload is under tmp_path."""
    monkeypatch.setattr(pc_conda.sys, "frozen", True, raising=False)
    monkeypatch.setattr(pc_conda.sys, "_MEIPASS", str(tmp_path), raising=False)
    return tmp_path


@pytest.fixture
def no_host_conda(monkeypatch):
    """A machine with neither mamba nor conda on PATH."""
    monkeypatch.setattr(pc_conda.shutil, "which", lambda _name: None)


def _make_payload(bundle_dir):
    """Create an executable at the path the bundle is expected to carry."""
    executable = bundle_dir.joinpath(*pc_conda.BUNDLED_SUBPATH)
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text("")
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return str(executable)


def test_bundled_executable_is_found_in_a_bundle(bundle):
    expected = _make_payload(bundle)
    assert pc_conda.find_bundled_executable() == expected


def test_bundled_executable_is_none_outside_a_bundle(tmp_path, monkeypatch):
    """A wheel or a source checkout has no payload, however sys is configured."""
    monkeypatch.delattr(pc_conda.sys, "frozen", raising=False)
    monkeypatch.setattr(pc_conda.sys, "_MEIPASS", str(tmp_path), raising=False)
    _make_payload(tmp_path)
    assert pc_conda.find_bundled_executable() is None


def test_bundled_executable_is_none_when_the_bundle_carries_no_payload(bundle):
    """A `pyinstaller partcad.spec` run by hand: `build.sh` is what stages it."""
    assert pc_conda.find_bundled_executable() is None


@pytest.mark.skipif(os.name == "nt", reason="the executable bit is a POSIX notion")
def test_a_payload_that_lost_its_executable_bit_is_not_offered(bundle):
    """Better to report no conda than to hand back a path that cannot be run."""
    executable = bundle.joinpath(*pc_conda.BUNDLED_SUBPATH)
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text("")
    executable.chmod(0o644)
    assert pc_conda.find_bundled_executable() is None


def test_the_bundled_conda_is_used_when_the_host_has_none(bundle, no_host_conda):
    """The whole point: a machine with no conda gets one anyway."""
    expected = _make_payload(bundle)
    assert pc_conda.find_executable() == expected


def test_the_host_conda_wins_over_the_bundled_one(bundle, monkeypatch):
    """Deliberately the opposite of the bundled OpenSCAD.

    conda is not a program but an installation -- a channel configuration the
    user chose and a package cache they have already paid gigabytes for. Taking
    ours instead would strand that cache and re-download the whole CAD stack
    beside it, on a machine that was working perfectly well.
    """
    _make_payload(bundle)
    monkeypatch.setattr(pc_conda.shutil, "which", lambda name: "/usr/bin/" + name)
    assert pc_conda.find_executable() == "/usr/bin/mamba"


def test_mamba_is_preferred_over_conda(monkeypatch):
    """The older of the two preferences: mamba solves the CAD stack far faster."""
    monkeypatch.delattr(pc_conda.sys, "frozen", raising=False)
    monkeypatch.setattr(pc_conda.shutil, "which", lambda name: "/usr/bin/" + name)
    assert pc_conda.find_executable() == "/usr/bin/mamba"


def test_the_host_conda_is_used_when_there_is_no_mamba(monkeypatch):
    monkeypatch.delattr(pc_conda.sys, "frozen", raising=False)
    monkeypatch.setattr(pc_conda.shutil, "which", lambda name: None if name == "mamba" else "/usr/bin/conda")
    assert pc_conda.find_executable() == "/usr/bin/conda"


def test_none_when_there_is_no_conda_anywhere(monkeypatch, no_host_conda):
    """A wheel on a machine with nothing installed: `pythonSandbox` is "none"."""
    monkeypatch.delattr(pc_conda.sys, "frozen", raising=False)
    assert pc_conda.find_executable() is None


def test_is_bundled_tells_the_two_apart(bundle, no_host_conda):
    bundled = _make_payload(bundle)
    assert pc_conda.is_bundled(bundled)
    assert not pc_conda.is_bundled("/usr/bin/mamba")
    assert not pc_conda.is_bundled(None)


def test_the_bundled_conda_keeps_its_state_under_the_internal_state_dir(monkeypatch):
    """Not in the user's home directory, which is micromamba's own default.

    PartCAD would be creating `~/.local/share/mamba` without ever having said so,
    outside everything that reports and clears its state -- `pc system status`,
    `pc system reset`, and the `PC_INTERNAL_STATE_DIR` redirect that lets
    `snap remove --purge` take the whole of it away.
    """
    monkeypatch.delenv("MAMBA_ROOT_PREFIX", raising=False)
    env = pc_conda.bundled_command_env(os.path.join("/state", "partcad"))
    assert env["MAMBA_ROOT_PREFIX"] == os.path.join("/state", "partcad", pc_conda.ROOT_PREFIX_SUBDIR)


def test_an_existing_root_prefix_is_left_alone(monkeypatch):
    """Someone running their own micromamba has a cache worth sharing."""
    monkeypatch.setenv("MAMBA_ROOT_PREFIX", "/home/user/micromamba")
    assert pc_conda.bundled_command_env("/state/partcad")["MAMBA_ROOT_PREFIX"] == "/home/user/micromamba"


def test_the_rest_of_the_environment_is_carried_over(monkeypatch):
    """It is this process's environment plus one variable, not a replacement."""
    monkeypatch.setenv("PARTCAD_TEST_MARKER", "kept")
    assert pc_conda.bundled_command_env("/state/partcad")["PARTCAD_TEST_MARKER"] == "kept"
