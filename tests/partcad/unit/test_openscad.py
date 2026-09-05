#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import os
import stat
import sys

import pytest

import partcad.healthcheck.openscad as pc_openscad


# The standalone bundle ships its own OpenSCAD and must run that one rather than
# whatever the host happens to have installed. Nothing about that ordering is
# observable from a build -- a bundle built on a machine with no OpenSCAD passes
# its smoke test either way -- so it is pinned down here, where both a bundled
# copy and a host copy can be made to exist at the same time.


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    """Make PartCAD look like a frozen bundle whose payload is under tmp_path."""
    monkeypatch.setattr(pc_openscad.sys, "frozen", True, raising=False)
    monkeypatch.setattr(pc_openscad.sys, "_MEIPASS", str(tmp_path), raising=False)
    return tmp_path


def _make_payload(bundle_dir):
    """Create an executable at the path the bundle is expected to carry."""
    executable = bundle_dir.joinpath(*pc_openscad.BUNDLED_SUBPATH)
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text("")
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return str(executable)


def test_bundled_executable_is_found_in_a_bundle(bundle):
    expected = _make_payload(bundle)
    assert pc_openscad.find_bundled_executable() == expected


def test_bundled_executable_is_none_outside_a_bundle(tmp_path, monkeypatch):
    """A wheel or a source checkout has no payload, however sys is configured."""
    monkeypatch.delattr(pc_openscad.sys, "frozen", raising=False)
    monkeypatch.setattr(pc_openscad.sys, "_MEIPASS", str(tmp_path), raising=False)
    _make_payload(tmp_path)
    assert pc_openscad.find_bundled_executable() is None


def test_bundled_executable_is_none_when_the_bundle_carries_no_payload(bundle):
    """Linux arm64 bundles, and hand-made ones, are built without OpenSCAD."""
    assert pc_openscad.find_bundled_executable() is None


@pytest.mark.skipif(os.name == "nt", reason="the executable bit is a POSIX notion")
def test_a_payload_that_lost_its_executable_bit_is_not_offered(bundle):
    """Better to fall back than to hand back a path that cannot be run."""
    executable = bundle.joinpath(*pc_openscad.BUNDLED_SUBPATH)
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text("")
    executable.chmod(0o644)
    assert pc_openscad.find_bundled_executable() is None


def test_the_bundled_executable_wins_over_the_host(bundle, monkeypatch):
    """The whole point: a host OpenSCAD does not displace the bundled one."""
    expected = _make_payload(bundle)
    monkeypatch.setattr(pc_openscad.shutil, "which", lambda _name: "/usr/bin/openscad")
    assert pc_openscad.find_executable() == expected


def test_the_host_executable_is_used_when_nothing_is_bundled(monkeypatch):
    monkeypatch.delattr(pc_openscad.sys, "frozen", raising=False)
    monkeypatch.setattr(pc_openscad.shutil, "which", lambda _name: "/usr/bin/openscad")
    assert pc_openscad.find_executable() == "/usr/bin/openscad"


def test_none_when_there_is_no_openscad_anywhere(monkeypatch):
    monkeypatch.delattr(pc_openscad.sys, "frozen", raising=False)
    monkeypatch.setattr(pc_openscad.shutil, "which", lambda _name: None)
    assert pc_openscad.find_executable() is None


def test_ignore_bundled_uses_the_host_even_inside_a_bundle(bundle, monkeypatch):
    """The opt-out: with ignore_bundled the host's OpenSCAD wins over the payload."""
    _make_payload(bundle)  # a bundled copy exists...
    monkeypatch.setattr(pc_openscad.shutil, "which", lambda _name: "/usr/bin/openscad")
    assert pc_openscad.find_executable(ignore_bundled=True) == "/usr/bin/openscad"


def test_ignore_bundled_returns_none_when_the_host_has_none(bundle, monkeypatch):
    """Opting out of the bundled copy leaves nothing when the host has none."""
    _make_payload(bundle)
    monkeypatch.setattr(pc_openscad.shutil, "which", lambda _name: None)
    assert pc_openscad.find_executable(ignore_bundled=True) is None


# The macOS installer. Homebrew disabled the "openscad" cask on 2026-09-01 for
# failing the Gatekeeper check, and until then this ran `brew install openscad`
# -- so the auto-fix could not install OpenSCAD on any Mac, and CI, which ran
# the same command, could not either. None of that is visible from a Linux test
# run, and the command is a list of strings nothing here executes, so the cask
# it names is pinned rather than left to be rediscovered the next time the one
# it names goes away.


@pytest.fixture
def homebrew(tmp_path, monkeypatch):
    """Capture the command ``MacOpenSCADCheck.fix`` runs, and run nothing.

    ``Path.home`` is redirected too, and not for isolation alone: before
    installing, ``fix`` deletes cached ``*openscad*.dmg`` files out of the real
    Homebrew download directory, which is not something a unit test may do to
    the machine running it.
    """
    calls = []

    class _Completed:
        returncode = 0
        stderr = b""

    def _run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return _Completed()

    monkeypatch.setattr(pc_openscad.subprocess, "run", _run)
    monkeypatch.setattr(pc_openscad.Path, "home", staticmethod(lambda: tmp_path))
    return calls


def test_macos_installs_the_cask_homebrew_still_has(homebrew):
    """`openscad` is disabled for good; `openscad@snapshot` is the maintained one."""
    assert pc_openscad.MacOpenSCADCheck().fix() is True
    assert [command for command, _ in homebrew] == [["brew", "install", "--cask", "openscad@snapshot"]]


def test_macos_install_does_not_let_homebrew_update_itself(homebrew):
    """One install stays one install rather than becoming a full `brew update`."""
    pc_openscad.MacOpenSCADCheck().fix()
    _, kwargs = homebrew[0]
    assert kwargs["env"]["HOMEBREW_NO_AUTO_UPDATE"] == "1"


# Where each platform's payload sits inside the bundle. Every test above builds
# its payload from BUNDLED_SUBPATH, so they would all agree with a wrong value;
# what the layout *is* comes from an artifact none of them has, and on a platform
# the test run is not on. So all three are pinned here, and `build.sh` stages and
# asserts the same paths -- a change to one and not the other is a bundle whose
# OpenSCAD PartCAD cannot find.


@pytest.mark.parametrize(
    "os_name, platform_name, expected",
    [
        ("nt", "win32", ("openscad", "openscad.exe")),
        ("posix", "darwin", ("openscad", "OpenSCAD.app", "Contents", "MacOS", "OpenSCAD")),
        ("posix", "linux", ("openscad", "AppRun")),
    ],
)
def test_the_payload_layout_is_the_one_build_sh_stages(os_name, platform_name, expected):
    """macOS keeps the whole '.app': the binary inside needs the bundle around it."""
    assert pc_openscad.bundled_subpath(os_name, platform_name) == expected


def test_the_layout_in_use_is_the_one_for_this_platform():
    """The module-level constant is that function applied to this process."""
    assert pc_openscad.BUNDLED_SUBPATH == pc_openscad.bundled_subpath(os.name, sys.platform)
