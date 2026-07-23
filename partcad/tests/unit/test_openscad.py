#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import os
import stat

import pytest

import partcad.openscad as pc_openscad


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
    """macOS bundles, and hand-made ones, are built without OpenSCAD."""
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
