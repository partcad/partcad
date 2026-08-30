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
from partcad_client import selfupdate

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
        os.path.join("/venv", "lib", "python3.12", "site-packages", "partcad_client", "selfupdate.py"),
    )
    assert selfupdate.installation_kind() == selfupdate.KIND_WHEEL


def test_installation_kind_is_source_for_a_checkout(monkeypatch):
    monkeypatch.delattr(selfupdate.sys, "frozen", raising=False)
    monkeypatch.setattr(selfupdate, "__file__", "/home/dev/src/partcad_client/selfupdate.py")
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
        ("linux", "x86_64", ("linux", "x86_64")),
        ("linux", "aarch64", ("linux", "arm64")),
        ("darwin", "arm64", ("macos", "arm64")),
        ("win32", "AMD64", ("windows", "x86_64")),
    ],
)
def test_host_platform(monkeypatch, platform_name, machine, expected):
    monkeypatch.setattr(selfupdate.sys, "platform", platform_name)
    monkeypatch.setattr(selfupdate.platform, "machine", lambda: machine)
    assert selfupdate.host_platform() == expected


def test_host_platform_rejects_an_unsupported_machine(monkeypatch):
    monkeypatch.setattr(selfupdate.sys, "platform", "linux")
    monkeypatch.setattr(selfupdate.platform, "machine", lambda: "riscv64")
    with pytest.raises(selfupdate.SelfUpdateError, match="no standalone PartCAD bundle"):
        selfupdate.host_platform()


def test_archive_extension_is_zip_on_windows_only():
    assert selfupdate.archive_extension("windows") == "zip"
    assert selfupdate.archive_extension("linux") == "tar.xz"
    assert selfupdate.archive_extension("macos") == "tar.xz"


def test_host_release_reads_the_ubuntu_version(monkeypatch, tmp_path):
    os_release = tmp_path / "os-release"
    os_release.write_text('NAME="Ubuntu"\nID=ubuntu\nVERSION_ID="22.04"\n')
    monkeypatch.setattr(selfupdate.sys, "platform", "linux")
    monkeypatch.setattr(selfupdate, "open", lambda *a, **k: open(os_release, "r", encoding="utf-8"), raising=False)
    assert selfupdate.host_release() == "ubuntu-22.04"


def test_host_release_is_unknown_on_a_distribution_that_is_not_ubuntu(monkeypatch, tmp_path):
    os_release = tmp_path / "os-release"
    os_release.write_text('NAME="Fedora Linux"\nID=fedora\nVERSION_ID=41\n')
    monkeypatch.setattr(selfupdate.sys, "platform", "linux")
    monkeypatch.setattr(selfupdate, "open", lambda *a, **k: open(os_release, "r", encoding="utf-8"), raising=False)
    assert selfupdate.host_release() is None


def test_host_release_takes_the_macos_major_version(monkeypatch):
    monkeypatch.setattr(selfupdate.sys, "platform", "darwin")
    monkeypatch.setattr(selfupdate.platform, "mac_ver", lambda: ("15.3.1", ("", "", ""), "arm64"))
    assert selfupdate.host_release() == "macos-15"


def test_host_release_is_unknown_on_windows(monkeypatch):
    # The Windows builds are named after the runner image ("windows-2025"),
    # which is not a version this machine has, so there is nothing to compare.
    monkeypatch.setattr(selfupdate.sys, "platform", "win32")
    assert selfupdate.host_release() is None


# ---------------------------------------------------------------------------
# Choosing a build out of the release manifest
# ---------------------------------------------------------------------------

MANIFEST = {
    "version": "0.7.177",
    "bundle": {
        "linux": {
            "x86_64": ["ubuntu-24.04-x86_64", "ubuntu-22.04-x86_64"],
            "arm64": ["ubuntu-24.04-arm64", "ubuntu-22.04-arm64"],
        },
        "macos": {"arm64": ["macos-26-arm64", "macos-15-arm64"]},
        # One Windows build, not one per image: nothing here can be compared
        # against a Windows host, and there is no floor for two builds to differ
        # in. See the note beside the matrix in "build-standalone.yml".
        "windows": {"x86_64": ["windows-2022-x86_64"]},
    },
    "ide": {
        "linux": {"x86_64": ["linux-x86_64"]},
        "macos": {"arm64": ["macos-arm64"]},
        "windows": {"x86_64": ["windows-x86_64"]},
    },
}


def _select(os_name, arch, release, kind="bundle", manifest=MANIFEST):
    return selfupdate.select_platforms(manifest, kind, os_name, arch, release)


def test_a_matching_host_gets_its_own_build_first():
    assert _select("linux", "x86_64", "ubuntu-24.04") == ["ubuntu-24.04-x86_64", "ubuntu-22.04-x86_64"]


def test_a_build_newer_than_the_host_is_never_offered():
    # 22.04 cannot run a bundle frozen on 24.04: the glibc it needs is not there.
    assert _select("linux", "x86_64", "ubuntu-22.04") == ["ubuntu-22.04-x86_64"]


def test_a_host_newer_than_every_build_gets_all_of_them_newest_first():
    assert _select("linux", "x86_64", "ubuntu-26.04") == ["ubuntu-24.04-x86_64", "ubuntu-22.04-x86_64"]
    assert _select("macos", "arm64", "macos-27") == ["macos-26-arm64", "macos-15-arm64"]


def test_a_host_older_than_every_build_still_gets_the_oldest_one():
    # Nothing published can be promised to run here, but the oldest build is the
    # only candidate with a chance, so it is offered rather than nothing at all.
    assert _select("linux", "x86_64", "ubuntu-20.04") == ["ubuntu-22.04-x86_64"]
    assert _select("macos", "arm64", "macos-14") == ["macos-15-arm64"]


def test_an_unidentified_host_is_offered_the_oldest_build_first():
    # A non-Ubuntu Linux: the release cannot be compared, so the widest build
    # (the lowest C library floor) goes first.
    assert _select("linux", "x86_64", None) == ["ubuntu-22.04-x86_64", "ubuntu-24.04-x86_64"]


def test_windows_has_one_build_and_needs_no_ordering():
    # A Windows host is always "unidentified" -- the builds are named after
    # runner images, which is not a version this machine has -- and that is
    # exactly why only one is published: a list of one needs no policy.
    assert _select("windows", "x86_64", None) == ["windows-2022-x86_64"]


def test_a_release_name_the_manifest_does_not_carry_counts_as_unidentified():
    assert _select("linux", "x86_64", "debian-12") == ["ubuntu-22.04-x86_64", "ubuntu-24.04-x86_64"]


def test_an_unknown_operating_system_has_no_candidates():
    assert _select("freebsd", "x86_64", None) == []


def test_an_architecture_the_release_does_not_carry_has_no_candidates():
    # macOS x86_64 has no bundle: nothing is offered, rather than an arm64 one.
    assert _select("macos", "x86_64", "macos-15") == []


def test_the_ide_archives_carry_no_os_version_and_are_offered_as_they_are():
    assert _select("linux", "x86_64", "ubuntu-22.04", kind="ide") == ["linux-x86_64"]
    assert _select("macos", "arm64", "macos-15", kind="ide") == ["macos-arm64"]


def test_a_manifest_without_this_kind_has_no_candidates():
    assert _select("linux", "x86_64", "ubuntu-24.04", manifest={"version": "0.7.177"}) == []


def test_a_manifest_that_omits_a_level_has_no_candidates():
    # Absent is an answer, not a fault: a release that published nothing for this
    # host says so by leaving the level out, and that is reported against the
    # release rather than against the manifest.
    assert _select("linux", "x86_64", "ubuntu-24.04", manifest={"bundle": {}}) == []
    assert _select("linux", "x86_64", "ubuntu-24.04", manifest={"bundle": {"linux": {}}}) == []


def test_a_platform_list_that_is_a_string_is_rejected():
    # Not filtered down to nothing and not iterated: every character of
    # "ubuntu-24.04-x86_64" is a non-empty string, so a lenient reader would go
    # looking for an archive named "u".
    manifest = {"bundle": {"linux": {"x86_64": "ubuntu-24.04-x86_64"}}}
    with pytest.raises(selfupdate.SelfUpdateError, match="bundle.linux.x86_64 is str, not a list"):
        _select("linux", "x86_64", "ubuntu-24.04", manifest=manifest)


def test_a_platform_list_holding_something_that_is_not_an_id_is_rejected():
    manifest = {"bundle": {"linux": {"x86_64": ["ubuntu-24.04-x86_64", 42]}}}
    with pytest.raises(selfupdate.SelfUpdateError, match="bundle.linux.x86_64 lists 42"):
        _select("linux", "x86_64", "ubuntu-24.04", manifest=manifest)


def test_a_manifest_level_that_is_not_an_object_is_rejected():
    # A list here used to reach `.get` on a list and raise AttributeError, which
    # says nothing about which file was wrong.
    with pytest.raises(selfupdate.SelfUpdateError, match="bundle is list, not an object"):
        _select("linux", "x86_64", "ubuntu-24.04", manifest={"bundle": ["ubuntu-24.04-x86_64"]})
    with pytest.raises(selfupdate.SelfUpdateError, match="bundle.linux is str, not an object"):
        _select("linux", "x86_64", "ubuntu-24.04", manifest={"bundle": {"linux": "x86_64"}})


def test_fetch_manifest_explains_a_release_that_does_not_publish_one(monkeypatch):
    def missing(url, headers=None):
        raise selfupdate.SelfUpdateError("could not reach %s" % url)

    monkeypatch.setattr(selfupdate, "_http_get", missing)
    with pytest.raises(selfupdate.SelfUpdateError, match="platforms.json is not published"):
        selfupdate.fetch_manifest("https://example.invalid/builds")


def test_fetch_manifest_rejects_a_body_that_is_not_a_manifest(monkeypatch):
    monkeypatch.setattr(selfupdate, "_http_get", lambda url, headers=None: b"<html>404</html>")
    with pytest.raises(selfupdate.SelfUpdateError, match="not valid JSON"):
        selfupdate.fetch_manifest("https://example.invalid/builds")


def test_release_platforms_reports_a_machine_the_release_has_no_build_for(monkeypatch):
    monkeypatch.setattr(selfupdate.sys, "platform", "darwin")
    monkeypatch.setattr(selfupdate.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(selfupdate, "fetch_manifest", lambda base_url: MANIFEST)
    monkeypatch.setattr(selfupdate, "host_release", lambda: "macos-15")
    with pytest.raises(selfupdate.SelfUpdateError, match="no standalone bundle for macos/x86_64"):
        selfupdate.release_platforms("https://example.invalid/builds")


# ---------------------------------------------------------------------------
# Archive handling
# ---------------------------------------------------------------------------


# Whether a bundle's aliases are symlinks here, which is what
# `dev-tools/pyinstaller/build.sh` decides: it points `partcad` and
# `partcad-json-rpc` at `pc` everywhere but Windows, where the archive is a zip
# (which stores a symlink as a copy of its target) and creating one needs a
# privilege a runner may not have. The fixture below ships what the platform
# ships, so these tests exercise the real layout on both.
BUNDLE_USES_SYMLINKS = os.name != "nt"

# The suffix a bundle's executables carry on this machine: the Windows bundle
# `dev-tools/pyinstaller/build.sh` publishes holds `pc.exe`. `_prune_old_versions`
# looks for exactly that name when it decides whether a directory holds a bundle
# at all, and it decides off `os.name` -- the host -- not off the `sys.platform`
# these tests fake to choose an archive. So a bundle laid out below has to carry
# the host's suffix, or the code under test does not recognise it as one.
BUNDLE_EXE_SUFFIX = ".exe" if os.name == "nt" else ""


def _make_bundle_archive(path, version="0.7.159"):
    """A tarball shaped like a real release: one top-level `partcad/` directory.

    Including how the executables are laid out: `pc` is the payload and the
    other names point at it -- as relative symlinks where the real bundle uses
    them, as copies where it does not. See BUNDLE_USES_SYMLINKS.
    """
    staging = path / "build" / "partcad"
    staging.mkdir(parents=True)
    payload = "#!/bin/sh\necho %s\n" % version
    (staging / ("pc" + BUNDLE_EXE_SUFFIX)).write_text(payload)
    for name in selfupdate.BUNDLE_EXECUTABLES:
        if name == "pc":
            continue
        if BUNDLE_USES_SYMLINKS:
            os.symlink("pc", staging / name)
        else:
            (staging / (name + BUNDLE_EXE_SUFFIX)).write_text(payload)
    (staging / "_internal").mkdir()
    archive = path / ("partcad-%s-linux-x86_64.tar.xz" % version)
    with tarfile.open(archive, "w:xz") as tf:
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
    selfupdate._extract(str(archive), str(dest), "tar.xz")
    assert (dest / "partcad" / ("pc" + BUNDLE_EXE_SUFFIX)).is_file()


@pytest.mark.skipif(os.name == "nt", reason="the bundle ships copies, not symlinks, on Windows")
def test_extract_keeps_the_aliases_that_point_at_pc(tmp_path):
    """The bundle ships one payload under three names.

    `partcad` and `partcad-json-rpc` are symlinks to `pc`; an extractor that
    dropped them -- or followed them into a copy -- would give back either a
    broken installation or the megabytes the links exist to save.
    """
    archive = _make_bundle_archive(tmp_path)
    dest = tmp_path / "dest"
    dest.mkdir()
    selfupdate._extract(str(archive), str(dest), "tar.xz")
    for name in selfupdate.BUNDLE_EXECUTABLES:
        if name == "pc":
            continue
        alias = dest / "partcad" / name
        assert alias.is_symlink()
        assert os.readlink(alias) == "pc"
        assert alias.is_file()


def _link_member(name, linkname):
    member = tarfile.TarInfo(name)
    member.type = tarfile.SYMTYPE
    member.linkname = linkname
    return member


def _link_archive(path, name, linkname):
    archive = path / "links.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        tf.addfile(_link_member(name, linkname))
    return archive


def test_extract_refuses_a_link_out_of_the_bundle(tmp_path):
    archive = _link_archive(tmp_path, "partcad/pc", "../../../../etc/passwd")
    dest = tmp_path / "dest"
    dest.mkdir()
    with pytest.raises(selfupdate.SelfUpdateError, match="unsafe link"):
        selfupdate._extract(str(archive), str(dest), "tar.xz")


def test_extract_refuses_an_absolute_link(tmp_path):
    archive = _link_archive(tmp_path, "partcad/pc", "/etc/passwd")
    dest = tmp_path / "dest"
    dest.mkdir()
    with pytest.raises(selfupdate.SelfUpdateError, match="absolute link"):
        selfupdate._extract(str(archive), str(dest), "tar.xz")


# Every spelling of a link target that names a place of its own rather than one
# inside the archive. Both hosts run all of them, because the answer is a
# property of the archive and not of the machine that unpacks it -- and because
# a table only one host could tell apart is what let this one through.
#
# `/etc/passwd` is the case that broke: a tar carries a link target as a POSIX
# path, but the guard asked `os.path.isabs`, which is `ntpath.isabs` on Windows,
# and Python 3.13 stopped calling a rootless path absolute there (Windows
# resolves it against the current drive). So on a Windows 3.13+ the archive was
# still refused -- by the traversal check a line later -- but as a malformed one
# rather than a hostile one, and only that host and that interpreter could see
# it. The four Windows spellings are the mirror image: `posixpath` calls every
# one of them an ordinary relative filename, and so did the old guard on a POSIX
# host, which asked for a drive only when `os.name == "nt"`.
ANCHORED_LINKS = [
    "/etc/passwd",  # absolute, and drive-relative on Windows since 3.13
    "//server/share/secrets",  # a UNC root, absolute either way
    "C:/Windows/System32/config/SAM",  # a drive, in the spelling a tar carries
    "C:\\Windows\\System32\\config\\SAM",  # a drive, in Windows spelling
    "C:secrets",  # anchored to a drive without a root
    "\\etc\\passwd",  # the root of the current drive on Windows
]


@pytest.mark.parametrize("link", ANCHORED_LINKS)
def test_an_anchored_link_is_refused_as_absolute(link, tmp_path):
    with pytest.raises(selfupdate.SelfUpdateError, match="absolute link"):
        selfupdate._reject_unsafe_links([_link_member("partcad/pc", link)], str(tmp_path))


@pytest.mark.parametrize("link", ["../../../../etc/passwd", "../../outside", "aliases/../../../outside"])
def test_a_climbing_link_is_refused_as_unsafe(link, tmp_path):
    """The other half of the pair: relative, but it walks out of the bundle."""
    with pytest.raises(selfupdate.SelfUpdateError, match="unsafe link"):
        selfupdate._reject_unsafe_links([_link_member("partcad/pc", link)], str(tmp_path))


def test_the_links_a_bundle_carries_are_accepted(tmp_path):
    """Nothing above may cost the bundle its aliases: `pc` is a bare name."""
    members = [_link_member("partcad/" + name, "pc") for name in selfupdate.BUNDLE_EXECUTABLES if name != "pc"]
    assert members
    selfupdate._reject_unsafe_links(members, str(tmp_path))


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
        (running / (name + BUNDLE_EXE_SUFFIX)).write_text("old")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("pc", "partcad"):
        os.symlink(running / (name + BUNDLE_EXE_SUFFIX), bin_dir / name)

    monkeypatch.setattr(selfupdate.sys, "frozen", True, raising=False)
    monkeypatch.setattr(selfupdate.sys, "executable", str(running / ("partcad-json-rpc" + BUNDLE_EXE_SUFFIX)))
    monkeypatch.setenv("PARTCAD_BIN_DIR", str(bin_dir))
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setattr(selfupdate.sys, "platform", "linux")
    monkeypatch.setattr(selfupdate.platform, "machine", lambda: "x86_64")
    # What the release says it carries, and what this machine is: together they
    # name the archive, which no client can work out from the host alone.
    monkeypatch.setattr(selfupdate, "fetch_manifest", lambda base_url: MANIFEST)
    monkeypatch.setattr(selfupdate, "host_release", lambda: "ubuntu-24.04")

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
    assert os.path.isfile(os.path.join(target, "pc" + BUNDLE_EXE_SUFFIX))
    # Beside, never over: the running bundle is intact when the install returns,
    # which is what makes this safe on Windows and safe for a daemon that
    # outlived the stop. It is handed to the reaper, not deleted here.
    assert running.is_dir()
    assert no_reaper == [str(running)]


@pytest.mark.skipif(os.name == "nt", reason="install.sh does not run on Windows, so there are no launchers to repoint")
def test_install_standalone_repoints_the_launchers(standalone, no_reaper):
    root, bin_dir, _running = standalone
    selfupdate._install_standalone("0.7.159", "partcad/partcad", lambda _m: None)
    # `readlink`, not `realpath`: where the bundle's own aliases are symlinks to
    # `pc`, resolving all the way through says nothing about which version the
    # launcher was pointed at -- which is what this is.
    for name in ("pc", "partcad"):
        assert os.readlink(bin_dir / name) == str(root / "0.7.159" / name)
        resolved = "pc" if BUNDLE_USES_SYMLINKS else name
        assert os.path.realpath(bin_dir / name) == str(root / "0.7.159" / resolved)


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
    (stale / ("pc" + BUNDLE_EXE_SUFFIX)).write_text("ancient")
    selfupdate._install_standalone("0.7.159", "partcad/partcad", lambda _m: None)
    assert not stale.exists()


def test_no_old_bundle_is_left_behind(standalone, no_reaper):
    """Every superseded bundle goes: the idle ones now, the running one on exit."""
    root, _bin_dir, running = standalone
    for version in ("0.7.100", "0.7.157"):
        stale = root / version
        stale.mkdir()
        (stale / ("pc" + BUNDLE_EXE_SUFFIX)).write_text("ancient")

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
    assert (existing / ("pc" + BUNDLE_EXE_SUFFIX)).is_file()


def test_install_standalone_uses_the_base_url_override(monkeypatch, standalone):
    urls = []
    monkeypatch.setenv("PARTCAD_BASE_URL", "https://example.invalid/builds")
    monkeypatch.setattr(selfupdate, "_download", lambda url, dest: urls.append(url) or _fail_download(url, dest))

    with pytest.raises(selfupdate.SelfUpdateError):
        selfupdate._install_standalone("0.7.159", "partcad/partcad", lambda _m: None)
    assert urls == ["https://example.invalid/builds/partcad-0.7.159-ubuntu-24.04-x86_64.tar.xz"]


def test_install_standalone_falls_through_to_the_next_published_build(monkeypatch, standalone, no_reaper):
    """A build the manifest lists but the release does not have moves on.

    A builder can fail after the manifest is written, and a mirror behind
    PARTCAD_BASE_URL can carry part of a release. Every later candidate is still
    a bundle this machine can run.
    """
    root, _bin_dir, _running = standalone
    real_download = selfupdate._download
    urls = []

    def download(url, dest):
        urls.append(url)
        if "ubuntu-24.04" in url:
            raise selfupdate._NotPublished("no build was published at %s" % url)
        real_download(url, dest)

    monkeypatch.setattr(selfupdate, "_download", download)
    target = selfupdate._install_standalone("0.7.159", "partcad/partcad", lambda _m: None)
    assert target == str(root / "0.7.159")
    assert [url.rsplit("/", 1)[-1] for url in urls] == [
        "partcad-0.7.159-ubuntu-24.04-x86_64.tar.xz",
        "partcad-0.7.159-ubuntu-22.04-x86_64.tar.xz",
    ]


def test_install_standalone_reports_every_build_it_tried(monkeypatch, standalone):
    monkeypatch.setattr(selfupdate, "_download", lambda url, dest: _fail_missing(url))
    with pytest.raises(selfupdate.SelfUpdateError, match="ubuntu-24.04-x86_64, ubuntu-22.04-x86_64"):
        selfupdate._install_standalone("0.7.159", "partcad/partcad", lambda _m: None)


def _fail_download(url, dest):
    raise selfupdate.SelfUpdateError("download failed: %s" % url)


def _fail_missing(url):
    raise selfupdate._NotPublished("no build was published at %s" % url)


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

    Even inside `partcad_client`, the updater does not reach for the
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
    """A `pip install partcad` with no shim gets `partcad` upgraded and nothing else."""
    monkeypatch.setattr(selfupdate, "_installed_distributions", lambda: ["partcad"])
    monkeypatch.setattr(selfupdate, "_pip_target_flags", list)
    calls = []

    class Result:
        returncode = 0
        stdout = "Successfully installed"
        stderr = ""

    monkeypatch.setattr(selfupdate.subprocess, "run", lambda argv, **kw: calls.append(argv) or Result())
    selfupdate._install_wheels(None, lambda _m: None)
    assert calls[0][-1] == "partcad"
    assert "partcad-cli" not in calls[0]
    assert "--upgrade" in calls[0]
    # Unpinned unless the caller asked for a version: pip resolves the newest.
    assert not any("==" in arg for arg in calls[0])


def test_install_wheels_upgrades_the_shim_alongside_the_wheel(monkeypatch):
    """`partcad-cli` pins `partcad` at its own version, so it cannot be left behind.

    An installation that arrived through the old name has both distributions.
    Upgrading only `partcad` would leave the shim pinning the version just
    replaced, and pip would resolve the conflict by putting it back.
    """
    monkeypatch.setattr(selfupdate, "_installed_distributions", lambda: ["partcad", "partcad-cli"])
    monkeypatch.setattr(selfupdate, "_pip_target_flags", list)
    calls = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(selfupdate.subprocess, "run", lambda argv, **kw: calls.append(argv) or Result())
    selfupdate._install_wheels(None, lambda _m: None)
    assert calls[0][-2:] == ["partcad", "partcad-cli"]


def test_only_the_two_published_distributions_are_looked_for():
    """The five-distribution era is over: one wheel, and the shim beside it.

    `_installed_distributions` decides both what a version lookup asks PyPI
    about and what an upgrade installs, so a name that is no longer published
    here would make `pc upgrade` query a project this repository does not own.
    """
    assert selfupdate.DISTRIBUTIONS == ("partcad", "partcad-cli")


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
    assert (running / ("pc" + BUNDLE_EXE_SUFFIX)).read_text() == "old"


# ---------------------------------------------------------------------------
# The reaper: removing the bundle this process is running out of.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(os.name == "nt", reason="the helper here is the POSIX one; Windows gets the `cmd` loop instead")
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
