#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for updating the PartCAD installation itself.

The parts that must hold whatever shape PartCAD was installed in:

* nothing is written, and the caller's `before_install` hook does not run, until
  a newer version has actually been found,
* the new bundle is installed beside the running one, never over it,
* a corrupted or hostile archive is refused before it is unpacked,
* and none of it knows what a daemon is -- that belongs to the client.

The download is stubbed throughout; the archive it produces is a real tarball
with the real layout, so the unpacking, moving, relinking and pruning are
exercised for real.
"""

import os
import pathlib
import tarfile
import textwrap

import pytest
from partcad_client_utils import selfupdate

# ---------------------------------------------------------------------------
# What is installed
# ---------------------------------------------------------------------------


def test_installation_kind_is_standalone_when_frozen(monkeypatch):
    monkeypatch.setattr(selfupdate.sys, "frozen", True, raising=False)
    assert selfupdate.installation_kind() == selfupdate.KIND_STANDALONE


def test_installation_kind_is_wheel_when_under_site_packages(monkeypatch):
    monkeypatch.delattr(selfupdate.sys, "frozen", raising=False)
    monkeypatch.setattr(
        selfupdate,
        "__file__",
        os.path.join("/venv", "lib", "python3.12", "site-packages", "partcad_client_utils", "selfupdate.py"),
    )
    assert selfupdate.installation_kind() == selfupdate.KIND_WHEEL


def test_installation_kind_is_source_for_a_checkout(monkeypatch):
    monkeypatch.delattr(selfupdate.sys, "frozen", raising=False)
    monkeypatch.setattr(
        selfupdate, "__file__", "/home/dev/partcad/partcad-client-utils/src/partcad_client_utils/selfupdate.py"
    )
    assert selfupdate.installation_kind() == selfupdate.KIND_SOURCE


def test_bundle_dir_resolves_the_launcher_symlink(monkeypatch, tmp_path):
    bundle = tmp_path / "0.7.159"
    bundle.mkdir()
    (bundle / "pc").write_text("")
    link = tmp_path / "bin"
    link.mkdir()
    os.symlink(bundle / "pc", link / "pc")
    monkeypatch.setattr(selfupdate.sys, "executable", str(link / "pc"))
    assert selfupdate.bundle_dir() == str(bundle)
    assert selfupdate.install_dir() == str(tmp_path)


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "candidate,installed,expected",
    [
        ("0.7.159", "0.7.158", True),
        ("0.8.0", "0.7.158", True),
        ("0.7.158", "0.7.158", False),
        ("0.7.157", "0.7.158", False),
        ("0.7.160", "0.7.9", True),  # numeric, not lexicographic
        ("nightly", "0.7.158", True),  # unparseable: different means newer
        ("nightly", "nightly", False),
    ],
)
def test_is_newer(candidate, installed, expected):
    assert selfupdate.is_newer(candidate, installed) is expected


def test_check_refuses_a_source_checkout(monkeypatch):
    monkeypatch.setattr(selfupdate, "installation_kind", lambda: selfupdate.KIND_SOURCE)
    status = selfupdate.check()
    assert status["update_available"] is False
    assert "source checkout" in status["reason"]


def test_check_reports_an_available_update(monkeypatch):
    monkeypatch.setattr(selfupdate, "installation_kind", lambda: selfupdate.KIND_STANDALONE)
    monkeypatch.setattr(selfupdate, "current_version", lambda: "0.7.158")
    monkeypatch.setattr(selfupdate, "latest_version", lambda kind=None, repo=None: "0.7.159")
    status = selfupdate.check()
    assert (status["update_available"], status["latest"]) == (True, "0.7.159")


def test_an_explicitly_pinned_older_version_is_a_downgrade_not_a_no_op(monkeypatch):
    """`--to-version` is an instruction, so "older" still counts as available."""
    monkeypatch.setattr(selfupdate, "installation_kind", lambda: selfupdate.KIND_STANDALONE)
    monkeypatch.setattr(selfupdate, "current_version", lambda: "0.7.158")
    status = selfupdate.check(to_version="0.7.100")
    assert status["update_available"] is True
    assert status["pinned"] == "0.7.100"


def test_a_pin_to_the_installed_version_is_a_no_op(monkeypatch):
    monkeypatch.setattr(selfupdate, "installation_kind", lambda: selfupdate.KIND_STANDALONE)
    monkeypatch.setattr(selfupdate, "current_version", lambda: "0.7.158")
    assert selfupdate.check(to_version="0.7.158")["update_available"] is False


def test_latest_release_tag_reads_the_github_release(monkeypatch):
    monkeypatch.setattr(selfupdate, "_http_get", lambda url, headers=None: b'{"tag_name": "0.7.159"}')
    assert selfupdate._latest_release_tag("partcad/partcad") == "0.7.159"


def test_latest_release_tag_without_a_tag_is_an_error(monkeypatch):
    monkeypatch.setattr(selfupdate, "_http_get", lambda url, headers=None: b"{}")
    with pytest.raises(selfupdate.SelfUpdateError):
        selfupdate._latest_release_tag("partcad/partcad")


def test_repository_honors_the_environment(monkeypatch):
    assert selfupdate.repository() == selfupdate.DEFAULT_REPOSITORY
    monkeypatch.setenv("PARTCAD_REPOSITORY", "someone/fork")
    assert selfupdate.repository() == "someone/fork"


# ---------------------------------------------------------------------------
# Platform naming
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "platform_name,machine,expected",
    [
        ("linux", "x86_64", ("linux-x86_64", "tar.gz")),
        ("linux", "aarch64", ("linux-arm64", "tar.gz")),
        ("darwin", "arm64", ("macos-arm64", "tar.gz")),
        ("win32", "AMD64", ("windows-x86_64", "zip")),
    ],
)
def test_platform_archive(monkeypatch, platform_name, machine, expected):
    monkeypatch.setattr(selfupdate.sys, "platform", platform_name)
    monkeypatch.setattr(selfupdate.platform, "machine", lambda: machine)
    assert selfupdate.platform_archive() == expected


def test_platform_archive_rejects_an_unsupported_machine(monkeypatch):
    monkeypatch.setattr(selfupdate.sys, "platform", "linux")
    monkeypatch.setattr(selfupdate.platform, "machine", lambda: "riscv64")
    with pytest.raises(selfupdate.SelfUpdateError, match="no standalone PartCAD bundle"):
        selfupdate.platform_archive()


# ---------------------------------------------------------------------------
# Archive handling
# ---------------------------------------------------------------------------


def _make_bundle_archive(path, version="0.7.159"):
    """A tarball shaped like a real release: one top-level `partcad/` directory."""
    staging = path / "build" / "partcad"
    staging.mkdir(parents=True)
    for name in selfupdate.BUNDLE_EXECUTABLES:
        (staging / name).write_text("#!/bin/sh\necho %s\n" % version)
    (staging / "_internal").mkdir()
    archive = path / ("partcad-%s-linux-x86_64.tar.gz" % version)
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(staging, arcname="partcad")
    return archive


def test_reject_traversal_refuses_members_outside_the_destination(tmp_path):
    with pytest.raises(selfupdate.SelfUpdateError, match="unsafe path"):
        selfupdate._reject_traversal(["partcad/pc", "../../etc/passwd"], str(tmp_path))


def test_reject_traversal_accepts_a_normal_bundle(tmp_path):
    selfupdate._reject_traversal(["partcad", "partcad/pc"], str(tmp_path))


def test_extract_unpacks_the_bundle(tmp_path):
    archive = _make_bundle_archive(tmp_path)
    dest = tmp_path / "dest"
    dest.mkdir()
    selfupdate._extract(str(archive), str(dest), "tar.gz")
    assert (dest / "partcad" / "pc").is_file()


def test_checksum_mismatch_is_fatal(monkeypatch, tmp_path):
    archive = tmp_path / "a.tar.gz"
    archive.write_bytes(b"payload")
    monkeypatch.setattr(selfupdate, "_http_get", lambda url, headers=None: b"0" * 64 + b"  a.tar.gz")
    with pytest.raises(selfupdate.SelfUpdateError, match="checksum mismatch"):
        selfupdate._verify_checksum("https://example.invalid/a.tar.gz", str(archive), lambda _m: None)


def test_a_missing_checksum_is_only_a_warning(monkeypatch, tmp_path):
    archive = tmp_path / "a.tar.gz"
    archive.write_bytes(b"payload")

    def unavailable(url, headers=None):
        raise selfupdate.SelfUpdateError("404")

    monkeypatch.setattr(selfupdate, "_http_get", unavailable)
    warnings = []
    selfupdate._verify_checksum("https://example.invalid/a.tar.gz", str(archive), warnings.append)
    assert any("skipping verification" in w for w in warnings)


# ---------------------------------------------------------------------------
# Installing a standalone bundle
# ---------------------------------------------------------------------------


@pytest.fixture
def no_reaper(monkeypatch):
    """Record what the running bundle is handed to, instead of spawning a helper.

    The reaper outlives the test process by design, so letting it run would leave
    a shell looping on the pytest pid. Its own behaviour is tested for real
    further down, against a throwaway process.
    """
    handed = []
    monkeypatch.setattr(selfupdate, "_reap_after_exit", lambda path, log: handed.append(path))
    return handed


@pytest.fixture
def standalone(monkeypatch, tmp_path):
    """A fake standalone installation: <root>/0.7.158/pc, linked from <root>/bin.

    Yields the installation root with the download stubbed out to serve a real
    archive of ``0.7.159``.
    """
    root = tmp_path / "share" / "partcad"
    running = root / "0.7.158"
    running.mkdir(parents=True)
    for name in selfupdate.BUNDLE_EXECUTABLES:
        (running / name).write_text("old")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("pc", "partcad"):
        os.symlink(running / name, bin_dir / name)

    monkeypatch.setattr(selfupdate.sys, "frozen", True, raising=False)
    monkeypatch.setattr(selfupdate.sys, "executable", str(running / "partcad-json-rpc"))
    monkeypatch.setenv("PARTCAD_BIN_DIR", str(bin_dir))
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setattr(selfupdate.sys, "platform", "linux")
    monkeypatch.setattr(selfupdate.platform, "machine", lambda: "x86_64")

    archive = _make_bundle_archive(tmp_path / "release")

    def fake_download(url, dest):
        import shutil

        shutil.copyfile(archive, dest)

    monkeypatch.setattr(selfupdate, "_download", fake_download)
    monkeypatch.setattr(selfupdate, "_verify_checksum", lambda url, path, log: None)
    yield root, bin_dir, running


def test_install_standalone_installs_beside_the_running_bundle(standalone, no_reaper):
    root, _bin_dir, running = standalone
    target = selfupdate._install_standalone("0.7.159", "partcad/partcad", lambda _m: None)
    assert target == str(root / "0.7.159")
    assert os.path.isfile(os.path.join(target, "pc"))
    # Beside, never over: the running bundle is intact when the install returns,
    # which is what makes this safe on Windows and safe for a daemon that
    # outlived the stop. It is handed to the reaper, not deleted here.
    assert running.is_dir()
    assert no_reaper == [str(running)]


def test_install_standalone_repoints_the_launchers(standalone, no_reaper):
    root, bin_dir, _running = standalone
    selfupdate._install_standalone("0.7.159", "partcad/partcad", lambda _m: None)
    assert os.path.realpath(bin_dir / "pc") == str(root / "0.7.159" / "pc")
    assert os.path.realpath(bin_dir / "partcad") == str(root / "0.7.159" / "partcad")


def test_install_standalone_leaves_foreign_launchers_alone(standalone, no_reaper, tmp_path):
    """A `pc` from a wheel on PATH belongs to somebody else."""
    root, bin_dir, _running = standalone
    foreign_dir = tmp_path / "venv-bin"
    foreign_dir.mkdir()
    foreign = foreign_dir / "pc"
    foreign.write_text("#!/usr/bin/env python\n")
    link = tmp_path / "elsewhere"
    link.mkdir()
    os.symlink(foreign, link / "pc")
    os.environ["PATH"] = os.pathsep.join([str(bin_dir), str(link)])

    selfupdate._install_standalone("0.7.159", "partcad/partcad", lambda _m: None)
    assert os.path.realpath(link / "pc") == str(foreign)


def test_install_standalone_prunes_superseded_bundles(standalone, no_reaper):
    root, _bin_dir, _running = standalone
    stale = root / "0.7.100"
    stale.mkdir()
    (stale / "pc").write_text("ancient")
    selfupdate._install_standalone("0.7.159", "partcad/partcad", lambda _m: None)
    assert not stale.exists()


def test_no_old_bundle_is_left_behind(standalone, no_reaper):
    """Every superseded bundle goes: the idle ones now, the running one on exit."""
    root, _bin_dir, running = standalone
    for version in ("0.7.100", "0.7.157"):
        stale = root / version
        stale.mkdir()
        (stale / "pc").write_text("ancient")

    target = selfupdate._install_standalone("0.7.159", "partcad/partcad", lambda _m: None)

    on_disk = {p.name for p in root.iterdir() if p.is_dir()}
    assert on_disk == {os.path.basename(target), running.name}
    # ...and the one still on disk is the one the reaper was handed.
    assert no_reaper == [str(running)]


def test_install_standalone_leaves_unrelated_neighbours_alone(standalone, no_reaper):
    root, _bin_dir, _running = standalone
    neighbour = root / "notes"
    neighbour.mkdir()
    (neighbour / "README").write_text("not a bundle")
    selfupdate._install_standalone("0.7.159", "partcad/partcad", lambda _m: None)
    assert (neighbour / "README").exists()


def test_install_standalone_replaces_an_existing_copy_of_the_same_version(standalone, no_reaper):
    root, _bin_dir, _running = standalone
    existing = root / "0.7.159"
    existing.mkdir()
    (existing / "stale-leftover").write_text("from a previous attempt")
    selfupdate._install_standalone("0.7.159", "partcad/partcad", lambda _m: None)
    assert not (existing / "stale-leftover").exists()
    assert (existing / "pc").is_file()


def test_install_standalone_uses_the_base_url_override(monkeypatch, standalone):
    urls = []
    monkeypatch.setenv("PARTCAD_BASE_URL", "https://example.invalid/builds")
    monkeypatch.setattr(selfupdate, "_download", lambda url, dest: urls.append(url) or _fail_download(url, dest))

    with pytest.raises(selfupdate.SelfUpdateError):
        selfupdate._install_standalone("0.7.159", "partcad/partcad", lambda _m: None)
    assert urls == ["https://example.invalid/builds/partcad-0.7.159-linux-x86_64.tar.gz"]


def _fail_download(url, dest):
    raise selfupdate.SelfUpdateError("download failed: %s" % url)


# ---------------------------------------------------------------------------
# `before_install`: the caller's chance to quiesce, and when it gets it.
#
# This module knows nothing about daemons -- a caller that has one injects the
# stopping here. What it is owed is the timing: after a newer version has been
# confirmed, before the first byte is written, and never otherwise.
# ---------------------------------------------------------------------------


class _Recorder:
    """Records the order of the steps an update takes."""

    def __init__(self, monkeypatch):
        self.events = []
        monkeypatch.setattr(selfupdate, "_install_standalone", self._install)
        monkeypatch.setattr(selfupdate, "_install_wheels", lambda pin, log: self.events.append("install") or "/wheels")
        monkeypatch.setattr(selfupdate, "installation_kind", lambda: selfupdate.KIND_STANDALONE)
        monkeypatch.setattr(selfupdate, "current_version", lambda: "0.7.158")

    def prepare(self):
        self.events.append("before_install")

    def _install(self, version, repo, log):
        self.events.append("install")
        return "/installed/%s" % version


def test_before_install_runs_before_anything_is_written(monkeypatch):
    monkeypatch.setattr(selfupdate, "latest_version", lambda kind=None, repo=None: "0.7.159")
    recorder = _Recorder(monkeypatch)
    result = selfupdate.update(before_install=recorder.prepare)
    assert recorder.events == ["before_install", "install"]
    assert result["updated"] is True


def test_before_install_does_not_run_when_nothing_is_newer(monkeypatch):
    """The common case: a no-op update must not cost anyone their warm context."""
    monkeypatch.setattr(selfupdate, "latest_version", lambda kind=None, repo=None: "0.7.158")
    recorder = _Recorder(monkeypatch)
    result = selfupdate.update(before_install=recorder.prepare)
    assert recorder.events == []
    assert result["updated"] is False


def test_update_without_a_before_install_hook_just_installs(monkeypatch):
    monkeypatch.setattr(selfupdate, "latest_version", lambda kind=None, repo=None: "0.7.159")
    recorder = _Recorder(monkeypatch)
    assert selfupdate.update()["updated"] is True
    assert recorder.events == ["install"]


def test_the_module_never_reaches_for_a_daemon():
    """Updating is a client-side act; a daemon can be remote, or somebody else's.

    Even inside `partcad-client-utils`, the updater does not reach for the
    daemon module next to it: a caller that has daemons passes `before_install`,
    which is what lets `pc upgrade` stop all the local ones and lets the VS Code
    extension's Python backend -- which has none -- stop nothing.
    """
    source = pathlib.Path(selfupdate.__file__).read_text(encoding="utf-8")
    body = source.split('"""', 2)[2]  # everything after the module docstring
    assert "partcad_service_json_rpc" not in body
    assert "from .daemon" not in body
    assert "stop_daemon" not in body
    assert "stop_all_daemons" not in body


def test_update_refuses_a_source_checkout(monkeypatch):
    monkeypatch.setattr(selfupdate, "installation_kind", lambda: selfupdate.KIND_SOURCE)
    with pytest.raises(selfupdate.SelfUpdateError, match="source checkout"):
        selfupdate.update()


# ---------------------------------------------------------------------------
# Installing wheels
# ---------------------------------------------------------------------------


def test_install_wheels_upgrades_only_the_installed_distributions(monkeypatch):
    monkeypatch.setattr(selfupdate, "_installed_distributions", lambda: ["partcad-service-json-rpc"])
    monkeypatch.setattr(selfupdate, "_pip_target_flags", list)
    calls = []

    class Result:
        returncode = 0
        stdout = "Successfully installed"
        stderr = ""

    monkeypatch.setattr(selfupdate.subprocess, "run", lambda argv, **kw: calls.append(argv) or Result())
    selfupdate._install_wheels(None, lambda _m: None)
    assert calls[0][-1] == "partcad-service-json-rpc"
    assert "--upgrade" in calls[0]
    # Unpinned: every component shares a version number but not every one of
    # them is published for every release.
    assert not any("==" in arg for arg in calls[0])


def test_install_wheels_pins_only_when_a_version_was_asked_for(monkeypatch):
    monkeypatch.setattr(selfupdate, "_installed_distributions", lambda: ["partcad-cli"])
    monkeypatch.setattr(selfupdate, "_pip_target_flags", list)
    calls = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(selfupdate.subprocess, "run", lambda argv, **kw: calls.append(argv) or Result())
    selfupdate._install_wheels("0.7.100", lambda _m: None)
    assert calls[0][-1] == "partcad-cli==0.7.100"


def test_install_wheels_reports_a_pip_failure(monkeypatch):
    monkeypatch.setattr(selfupdate, "_installed_distributions", lambda: ["partcad-cli"])
    monkeypatch.setattr(selfupdate, "_pip_target_flags", list)

    class Result:
        returncode = 1
        stdout = ""
        stderr = "No matching distribution found"

    monkeypatch.setattr(selfupdate.subprocess, "run", lambda argv, **kw: Result())
    with pytest.raises(selfupdate.SelfUpdateError, match="No matching distribution"):
        selfupdate._install_wheels(None, lambda _m: None)


def test_install_wheels_without_a_partcad_distribution_is_an_error(monkeypatch):
    monkeypatch.setattr(selfupdate, "_installed_distributions", list)
    with pytest.raises(selfupdate.SelfUpdateError, match="no PartCAD distribution"):
        selfupdate._install_wheels(None, lambda _m: None)


def test_pip_target_flags_never_pass_user_inside_a_virtualenv(monkeypatch):
    monkeypatch.setattr(selfupdate.sys, "prefix", "/venv")
    monkeypatch.setattr(selfupdate.sys, "base_prefix", "/usr")
    monkeypatch.setattr(selfupdate, "_pip_supports_break_system_packages", lambda: False)
    assert "--user" not in selfupdate._pip_target_flags()


def test_pip_target_flags_ask_for_user_when_the_environment_is_read_only(monkeypatch):
    monkeypatch.setattr(selfupdate.sys, "prefix", "/usr")
    monkeypatch.setattr(selfupdate.sys, "base_prefix", "/usr")
    monkeypatch.setattr(selfupdate, "_pip_supports_break_system_packages", lambda: True)
    monkeypatch.setattr(selfupdate.os, "access", lambda path, mode: False)
    flags = selfupdate._pip_target_flags()
    assert flags == ["--break-system-packages", "--user"]


def test_module_docstring_documents_the_rules():
    """The invariants above are only safe because they are written down."""
    doc = textwrap.dedent(selfupdate.__doc__).lower()
    assert "updating an installation is a\nclient-side operation" in doc
    assert "never write over the running installation" in doc


def test_install_standalone_refuses_to_unpack_into_the_running_bundle(monkeypatch, standalone):
    """A hand-assembled install whose directory name is not the version it runs."""
    root, _bin_dir, running = standalone
    monkeypatch.setattr(selfupdate, "current_version", lambda: "0.7.158")
    with pytest.raises(selfupdate.SelfUpdateError, match="reinstall it with install.sh"):
        # The running bundle lives in `<root>/0.7.158`, so asking for 0.7.158
        # would target the directory currently being executed.
        selfupdate._install_standalone("0.7.158", "partcad/partcad", lambda _m: None)
    assert (running / "pc").read_text() == "old"


# ---------------------------------------------------------------------------
# The reaper: removing the bundle this process is running out of.
# ---------------------------------------------------------------------------


def test_reap_after_exit_removes_the_directory_once_the_process_is_gone(tmp_path, monkeypatch):
    """For real: a throwaway process stands in for the one being updated."""
    import subprocess
    import time

    doomed = tmp_path / "0.7.158"
    doomed.mkdir()
    (doomed / "pc").write_text("old")
    (doomed / "_internal").mkdir()
    (doomed / "_internal" / "lib.so").write_text("payload")

    victim = subprocess.Popen(["/bin/sh", "-c", "sleep 30"])
    monkeypatch.setattr(selfupdate.os, "getpid", lambda: victim.pid)
    try:
        selfupdate._reap_after_exit(str(doomed), lambda _m: None)
        # Still there while the process lives: the whole point is not deleting
        # files out from under a running bundle.
        time.sleep(0.5)
        assert doomed.is_dir()

        victim.terminate()
        victim.wait(timeout=10)
        deadline = time.monotonic() + 15
        while doomed.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not doomed.exists()
    finally:
        if victim.poll() is None:
            victim.kill()


def test_reap_after_exit_reports_rather_than_raises_when_it_cannot_start(tmp_path, monkeypatch):
    """A machine without /bin/sh keeps its stale bundle; it does not fail the update."""
    doomed = tmp_path / "0.7.158"
    doomed.mkdir()

    def no_processes(*args, **kwargs):
        raise OSError("no such file or directory")

    monkeypatch.setattr(selfupdate.subprocess, "Popen", no_processes)
    messages = []
    selfupdate._reap_after_exit(str(doomed), messages.append)
    assert any("next update will remove it" in m for m in messages)
    assert doomed.is_dir()
