#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Finding, naming, downloading and unpacking the standalone service bundle."""

import io
import os
import stat
import tarfile
import zipfile

import pytest
from partcad_freecad import provision


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    """The provisioning reads several PC_CAD_* / GITHUB_* variables."""
    for name in (
        "PC_CAD_SERVICE_PATH",
        "PC_CAD_DEVEL",
        "PC_CAD_REPOSITORY",
        "PC_CAD_BRANCH",
        "PC_CAD_GITHUB_TOKEN",
        "GITHUB_TOKEN",
        "GH_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)


# ---- naming ------------------------------------------------------------------


@pytest.mark.parametrize(
    "system, machine, expected",
    [
        ("Linux", "x86_64", ("linux", "x86_64")),
        ("Linux", "aarch64", ("linux", "arm64")),
        ("Darwin", "arm64", ("macos", "arm64")),
        ("Windows", "AMD64", ("windows", "x86_64")),
    ],
)
def test_platform_names_match_install_sh(system, machine, expected):
    assert provision.host_platform(system, machine) == expected


def test_an_unsupported_platform_has_no_bundle():
    assert provision.host_platform("SunOS", "sparc") is None


def test_the_archive_format_is_zip_on_windows_only():
    assert provision.archive_extension("windows") == "zip"
    assert provision.archive_extension("linux") == "tar.gz"


def test_archive_and_artifact_names_are_the_ci_contract():
    assert (
        provision.archive_name("0.7.158", "ubuntu-24.04-x86_64", "tar.gz")
        == "partcad-0.7.158-ubuntu-24.04-x86_64.tar.gz"
    )
    assert provision.artifact_name("windows-2025-x86_64") == "partcad-standalone-windows-2025-x86_64"


def test_the_host_release_is_the_macos_major_version(monkeypatch):
    monkeypatch.setattr(provision._platform, "mac_ver", lambda: ("26.1", ("", "", ""), "arm64"))
    assert provision.host_release("Darwin") == "macos-26"


def test_the_host_release_is_unknown_on_windows():
    # The Windows builds are named after the runner image ("windows-2025"),
    # which is not a version this machine has, so there is nothing to compare.
    assert provision.host_release("Windows") is None


# ---- choosing a build --------------------------------------------------------

MANIFEST = {
    "version": "0.7.177",
    "bundle": {
        "linux": {
            "x86_64": ["ubuntu-24.04-x86_64", "ubuntu-22.04-x86_64"],
            "arm64": ["ubuntu-24.04-arm64", "ubuntu-22.04-arm64"],
        },
        "macos": {"arm64": ["macos-26-arm64", "macos-15-arm64"]},
        "windows": {"x86_64": ["windows-2025-x86_64", "windows-2022-x86_64"]},
    },
    "ide": {"linux": {"x86_64": ["linux-x86_64"]}},
}


def _select(os_name, arch, release, kind="bundle", manifest=MANIFEST):
    return provision.select_platforms(manifest, kind, os_name, arch, release)


def test_the_host_gets_its_own_build_first():
    assert _select("linux", "x86_64", "ubuntu-24.04") == ["ubuntu-24.04-x86_64", "ubuntu-22.04-x86_64"]


def test_a_build_newer_than_the_host_is_never_offered():
    assert _select("linux", "x86_64", "ubuntu-22.04") == ["ubuntu-22.04-x86_64"]


def test_a_host_newer_than_every_build_gets_all_of_them():
    assert _select("macos", "arm64", "macos-27") == ["macos-26-arm64", "macos-15-arm64"]


def test_a_host_older_than_every_build_still_gets_the_oldest():
    assert _select("macos", "arm64", "macos-14") == ["macos-15-arm64"]


def test_an_unidentified_host_is_offered_the_most_portable_build_first():
    assert _select("windows", "x86_64", None) == ["windows-2022-x86_64", "windows-2025-x86_64"]
    assert _select("linux", "x86_64", None) == ["ubuntu-22.04-x86_64", "ubuntu-24.04-x86_64"]


def test_an_unknown_operating_system_has_no_candidates():
    assert _select("sunos", "sparc", None) == []


def test_an_architecture_the_release_does_not_carry_has_no_candidates():
    assert _select("macos", "x86_64", "macos-15") == []


def test_a_missing_manifest_leaves_nothing_to_try():
    assert _select("linux", "x86_64", "ubuntu-24.04", manifest={}) == []


def test_ci_artifact_names_are_grouped_like_a_manifest():
    grouped = provision.group_platforms(
        [
            "ubuntu-22.04-x86_64",
            "macos-15-arm64",
            "ubuntu-24.04-x86_64",
            "windows-2022-x86_64",
            "not-a-platform-id-at-all",
        ]
    )
    assert grouped["linux"]["x86_64"] == ["ubuntu-24.04-x86_64", "ubuntu-22.04-x86_64"]
    assert grouped["macos"]["arm64"] == ["macos-15-arm64"]
    assert grouped["windows"]["x86_64"] == ["windows-2022-x86_64"]


def test_a_release_without_a_manifest_reads_as_no_manifest(monkeypatch):
    def missing(url, headers=None, timeout=60.0):
        raise OSError("404")

    monkeypatch.setattr(provision, "http_get", missing)
    assert provision.release_manifest("partcad/partcad", "0.7.135") is None


# ---- locating an existing installation ---------------------------------------


def _make_executable(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as stream:
        stream.write("#!/bin/sh\n")
    os.chmod(path, 0o755)
    return path


def test_an_explicit_path_wins(tmp_path, monkeypatch):
    explicit = _make_executable(str(tmp_path / "elsewhere" / provision.EXE))
    monkeypatch.setenv("PC_CAD_SERVICE_PATH", explicit)

    assert provision.resolve_service_path(str(tmp_path / "cache")) == explicit


def test_a_bundle_this_addon_downloaded_is_reused(tmp_path):
    cache = str(tmp_path / "cache")
    exe = _make_executable(os.path.join(provision.bundle_root(cache), "partcad", provision.EXE))

    assert provision.resolve_service_path(cache) == exe


def test_an_install_sh_installation_is_reused(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setattr(os.path, "expanduser", lambda path: path.replace("~", str(tmp_path / "home")))
    exe = _make_executable(str(tmp_path / "share" / "partcad" / "0.7.158" / provision.EXE))
    monkeypatch.setattr(provision, "_which", lambda _exe: None)

    assert provision.resolve_service_path(str(tmp_path / "cache")) == exe


def test_the_most_recently_installed_version_is_preferred(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setattr(os.path, "expanduser", lambda path: path.replace("~", str(tmp_path / "home")))
    # Named so that ordering by version string would pick the wrong one: as
    # text, "0.7.98" sorts after "0.7.158".
    newest = _make_executable(str(tmp_path / "share" / "partcad" / "0.7.158" / provision.EXE))
    older = _make_executable(str(tmp_path / "share" / "partcad" / "0.7.98" / provision.EXE))
    os.utime(os.path.dirname(older), (1, 1))
    monkeypatch.setattr(provision, "_which", lambda _exe: None)

    assert provision.resolve_service_path(str(tmp_path / "cache")) == newest


def test_falling_back_to_the_path(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setattr(os.path, "expanduser", lambda path: path.replace("~", str(tmp_path / "home")))
    monkeypatch.setattr(provision, "_which", lambda _exe: "/usr/local/bin/" + provision.EXE)

    assert provision.resolve_service_path(str(tmp_path / "cache")) == "/usr/local/bin/" + provision.EXE


def test_nothing_installed_yields_none(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setattr(os.path, "expanduser", lambda path: path.replace("~", str(tmp_path / "home")))
    monkeypatch.setattr(provision, "_which", lambda _exe: None)

    assert provision.resolve_service_path(str(tmp_path / "cache")) is None


# ---- the devel switch --------------------------------------------------------


@pytest.mark.parametrize("value, expected", [("1", True), ("true", True), ("", False), ("0", False), ("no", False)])
def test_pc_cad_devel_selects_the_development_build(monkeypatch, value, expected):
    monkeypatch.setenv("PC_CAD_DEVEL", value)

    assert provision.want_devel() is expected


def test_without_pc_cad_devel_a_release_is_preferred():
    assert provision.want_devel() is False


def test_the_github_token_is_read_from_any_of_the_usual_variables(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "from-gh")
    assert provision.github_token() == "from-gh"
    monkeypatch.setenv("PC_CAD_GITHUB_TOKEN", "ours")
    assert provision.github_token() == "ours"


# ---- unpacking ---------------------------------------------------------------


def _bundle_tar(path, executable_name):
    inner = os.path.join(os.path.dirname(path), "payload")
    os.makedirs(os.path.join(inner, "partcad"), exist_ok=True)
    exe = _make_executable(os.path.join(inner, "partcad", executable_name))
    with tarfile.open(path, "w:gz") as tf:
        tf.add(exe, arcname="partcad/" + executable_name)
    return path


@pytest.mark.skipif(os.name == "nt", reason="Windows has no executable bit; chmod only toggles read-only")
def test_a_tar_bundle_unpacks_with_the_executable_bit_intact(tmp_path):
    archive = _bundle_tar(str(tmp_path / "bundle.tar.gz"), provision.EXE)
    dest = str(tmp_path / "out")

    provision.extract(archive, dest)

    exe = os.path.join(dest, "partcad", provision.EXE)
    assert os.path.isfile(exe)
    assert os.stat(exe).st_mode & stat.S_IXUSR


@pytest.mark.skipif(os.name == "nt", reason="Windows has no executable bit; chmod only toggles read-only")
def test_a_zip_bundle_unpacks_with_the_executable_bit_intact(tmp_path):
    archive = str(tmp_path / "bundle.zip")
    with zipfile.ZipFile(archive, "w") as zf:
        info = zipfile.ZipInfo("partcad/partcad-json-rpc")
        info.external_attr = 0o755 << 16
        zf.writestr(info, "#!/bin/sh\n")
    dest = str(tmp_path / "out")

    provision.extract(archive, dest)

    exe = os.path.join(dest, "partcad", "partcad-json-rpc")
    assert os.stat(exe).st_mode & stat.S_IXUSR


def test_a_zip_bundle_unpacks_its_contents(tmp_path):
    """The part of the zip round trip that is meaningful on every platform."""
    archive = str(tmp_path / "bundle.zip")
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("partcad/partcad-json-rpc", "#!/bin/sh\n")
    dest = str(tmp_path / "out")

    provision.extract(archive, dest)

    assert os.path.isfile(os.path.join(dest, "partcad", "partcad-json-rpc"))


def test_the_tar_member_policy_drops_what_must_not_be_written(tmp_path):
    # The stand-in for filter="data" on interpreters that lack it. Anything that
    # escapes the destination, and every link or special file, has to go.
    archive = str(tmp_path / "hostile.tar.gz")
    payload = tmp_path / "payload"
    payload.write_text("x")
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(str(payload), arcname="partcad/ok")
        for name in ("../escape", "partcad/../../escape"):
            tf.add(str(payload), arcname=name)
        # Written through TarInfo rather than add(): add() strips the leading
        # separator itself, so only a hand-crafted archive carries a genuinely
        # absolute member -- which is the one worth rejecting.
        absolute = tarfile.TarInfo("/etc/partcad-escape")
        absolute.size = 0
        tf.addfile(absolute)
        link = tarfile.TarInfo("partcad/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        tf.addfile(link)
        fifo = tarfile.TarInfo("partcad/fifo")
        fifo.type = tarfile.FIFOTYPE
        tf.addfile(fifo)

    dest = str(tmp_path / "out")
    with tarfile.open(archive) as tf:
        kept = [member.name for member in provision._safe_members(tf, dest)]

    assert kept == ["partcad/ok"]


def test_the_tar_member_policy_keeps_a_normal_bundle(tmp_path):
    archive = _bundle_tar(str(tmp_path / "bundle.tar.gz"), provision.EXE)
    dest = str(tmp_path / "out")

    with tarfile.open(archive) as tf:
        kept = [member.name for member in provision._safe_members(tf, dest)]

    assert kept == ["partcad/" + provision.EXE]


def test_a_checksum_line_is_parsed_the_way_sha256sum_writes_it():
    assert provision._checksum_from("abc123  partcad-0.1-linux-x86_64.tar.gz\n") == "abc123"
    assert provision._checksum_from("") is None


def test_a_mismatched_checksum_removes_the_archive(tmp_path):
    archive = tmp_path / "bundle.tar.gz"
    archive.write_bytes(b"corrupted")

    with pytest.raises(RuntimeError, match="corrupted"):
        provision._verify(str(archive), "0" * 64)

    assert not archive.exists()


def test_a_matching_checksum_keeps_the_archive(tmp_path):
    archive = tmp_path / "bundle.tar.gz"
    archive.write_bytes(b"payload")

    provision._verify(str(archive), provision.sha256(str(archive)))

    assert archive.exists()


def test_a_missing_checksum_is_not_fatal(tmp_path):
    archive = tmp_path / "bundle.tar.gz"
    archive.write_bytes(b"payload")

    provision._verify(str(archive), None)

    assert archive.exists()


# ---- discovery ---------------------------------------------------------------


def test_the_newest_run_carrying_this_platforms_artifact_is_used(monkeypatch):
    responses = {
        "runs": {"workflow_runs": [{"id": 1}, {"id": 2}]},
        "1": {"artifacts": [{"name": "partcad-standalone-macos-15-arm64", "archive_download_url": "wrong"}]},
        "2": {
            "artifacts": [
                {"name": "partcad-standalone-ubuntu-24.04-x86_64", "archive_download_url": "right", "expired": False}
            ]
        },
    }

    def fake_get_json(url, token=None, timeout=60.0):  # pylint: disable=unused-argument
        assert token == "t"
        if "/runs?" in url or url.endswith("/runs"):
            return responses["runs"]
        return responses[url.rsplit("/runs/", 1)[1].split("/")[0]]

    monkeypatch.setattr(provision, "http_get_json", fake_get_json)

    artifact, platform_name = provision.latest_devel_artifact(
        "partcad/partcad", "linux", "x86_64", "ubuntu-24.04", "devel", "t"
    )

    assert artifact["archive_download_url"] == "right"
    assert platform_name == "ubuntu-24.04-x86_64"


def test_a_run_builds_what_it_builds_and_the_host_picks_from_that(monkeypatch):
    """The run's artifact names are its inventory, and the host filters them.

    Which platforms exist is a property of the run -- a shallow run builds fewer
    than a deep one -- the way it is a property of a release. So the names the
    run produced are read first and the host applied to them, rather than a name
    being guessed in advance and asked for.
    """

    def fake_get_json(url, token=None, timeout=60.0):  # pylint: disable=unused-argument
        if "/runs?" in url:
            return {"workflow_runs": [{"id": 1}]}
        return {
            "artifacts": [
                {"name": "partcad-standalone-ubuntu-24.04-x86_64", "archive_download_url": "too-new"},
                {"name": "partcad-standalone-ubuntu-22.04-x86_64", "archive_download_url": "right"},
                {"name": "partcad-standalone-macos-15-arm64", "archive_download_url": "wrong-os"},
            ]
        }

    monkeypatch.setattr(provision, "http_get_json", fake_get_json)

    artifact, platform_name = provision.latest_devel_artifact(
        "partcad/partcad", "linux", "x86_64", "ubuntu-22.04", "devel", "t"
    )
    assert (artifact["archive_download_url"], platform_name) == ("right", "ubuntu-22.04-x86_64")


def test_the_only_build_a_run_has_is_offered_even_to_an_older_host(monkeypatch):
    """Nothing can be promised, but the oldest build is the only chance there is."""

    def fake_get_json(url, token=None, timeout=60.0):  # pylint: disable=unused-argument
        if "/runs?" in url:
            return {"workflow_runs": [{"id": 1}]}
        return {"artifacts": [{"name": "partcad-standalone-ubuntu-24.04-x86_64", "archive_download_url": "only"}]}

    monkeypatch.setattr(provision, "http_get_json", fake_get_json)

    artifact, platform_name = provision.latest_devel_artifact(
        "partcad/partcad", "linux", "x86_64", "ubuntu-22.04", "devel", "t"
    )
    assert (artifact["archive_download_url"], platform_name) == ("only", "ubuntu-24.04-x86_64")


def test_an_expired_artifact_is_skipped(monkeypatch):
    def fake_get_json(url, token=None, timeout=60.0):  # pylint: disable=unused-argument
        if "/runs?" in url:
            return {"workflow_runs": [{"id": 1}]}
        return {"artifacts": [{"name": "partcad-standalone-ubuntu-24.04-x86_64", "expired": True}]}

    monkeypatch.setattr(provision, "http_get_json", fake_get_json)

    assert provision.latest_devel_artifact("partcad/partcad", "linux", "x86_64", None, "devel", "t") is None


def test_downloading_a_devel_build_without_a_token_says_so(tmp_path):
    with pytest.raises(RuntimeError, match="GitHub token"):
        provision.download_devel("partcad/partcad", "linux", "x86_64", None, "devel", str(tmp_path), lambda _m: None)


@pytest.fixture
def ubuntu_2404_host(monkeypatch):
    """A host the manifest can be resolved against, with nothing installed yet."""
    monkeypatch.setattr(provision, "resolve_service_path", lambda _cache: None)
    monkeypatch.setattr(provision, "host_platform", lambda: ("linux", "x86_64"))
    monkeypatch.setattr(provision, "host_release", lambda: "ubuntu-24.04")


def test_a_release_with_a_bundle_for_this_platform_is_used(tmp_path, monkeypatch, ubuntu_2404_host):
    calls = {}
    monkeypatch.setattr(provision, "latest_release_tag", lambda repo: "0.7.177")
    monkeypatch.setattr(provision, "release_manifest", lambda repo, version: MANIFEST)
    monkeypatch.setattr(provision, "url_exists", lambda url: calls.setdefault("asset", url) is None or True)
    monkeypatch.setattr(provision, "download_release", lambda *args: "/bundle/" + provision.EXE)
    monkeypatch.setattr(provision, "download_devel", lambda *args: pytest.fail("should not fall back"))

    assert provision.ensure_service(str(tmp_path)) == "/bundle/" + provision.EXE
    assert calls["asset"].endswith("/0.7.177/partcad-0.7.177-ubuntu-24.04-x86_64.tar.gz")


def test_an_archive_the_manifest_lists_but_the_release_lacks_moves_on(tmp_path, monkeypatch, ubuntu_2404_host):
    """The manifest is written before the upload, so a listed archive can be absent."""
    tried = []
    monkeypatch.setattr(provision, "latest_release_tag", lambda repo: "0.7.177")
    monkeypatch.setattr(provision, "release_manifest", lambda repo, version: MANIFEST)
    monkeypatch.setattr(provision, "url_exists", lambda url: tried.append(url) is None and "ubuntu-22.04" in url)
    monkeypatch.setattr(provision, "download_release", lambda repo, version, platform_name, *rest: platform_name)
    monkeypatch.setattr(provision, "download_devel", lambda *args: pytest.fail("should not fall back"))

    assert provision.ensure_service(str(tmp_path)) == "ubuntu-22.04-x86_64"
    assert len(tried) == 2


def test_a_release_without_a_manifest_falls_back_to_the_devel_build(tmp_path, monkeypatch, ubuntu_2404_host):
    # A release that publishes the wheels but no standalone bundle for this
    # platform, or one made before the manifest existed: either way there is
    # nothing here to resolve, and the development build is the fallback.
    monkeypatch.setattr(provision, "latest_release_tag", lambda repo: "0.7.135")
    monkeypatch.setattr(provision, "release_manifest", lambda repo, version: None)
    monkeypatch.setattr(provision, "url_exists", lambda url: pytest.fail("nothing to ask about"))
    monkeypatch.setattr(provision, "download_release", lambda *args: pytest.fail("no bundle to download"))
    monkeypatch.setattr(provision, "download_devel", lambda *args: "/devel/" + provision.EXE)

    assert provision.ensure_service(str(tmp_path)) == "/devel/" + provision.EXE


def test_a_release_with_no_bundle_for_this_host_falls_back_to_the_devel_build(tmp_path, monkeypatch, ubuntu_2404_host):
    monkeypatch.setattr(provision, "latest_release_tag", lambda repo: "0.7.177")
    monkeypatch.setattr(provision, "release_manifest", lambda repo, version: MANIFEST)
    monkeypatch.setattr(provision, "url_exists", lambda url: False)
    monkeypatch.setattr(provision, "download_release", lambda *args: pytest.fail("no bundle to download"))
    monkeypatch.setattr(provision, "download_devel", lambda *args: "/devel/" + provision.EXE)

    assert provision.ensure_service(str(tmp_path)) == "/devel/" + provision.EXE


def test_no_release_at_all_falls_back_to_the_devel_build(tmp_path, monkeypatch, ubuntu_2404_host):
    monkeypatch.setattr(provision, "latest_release_tag", lambda repo: None)
    monkeypatch.setattr(provision, "download_devel", lambda *args: "/devel/" + provision.EXE)

    assert provision.ensure_service(str(tmp_path)) == "/devel/" + provision.EXE


def test_pc_cad_devel_skips_the_release_lookup_entirely(tmp_path, monkeypatch, ubuntu_2404_host):
    monkeypatch.setenv("PC_CAD_DEVEL", "1")
    monkeypatch.setattr(provision, "latest_release_tag", lambda repo: pytest.fail("no release lookup"))
    monkeypatch.setattr(provision, "download_devel", lambda *args: "/devel/" + provision.EXE)

    assert provision.ensure_service(str(tmp_path)) == "/devel/" + provision.EXE


def test_an_existing_installation_is_never_downloaded_over(tmp_path, monkeypatch):
    monkeypatch.setattr(provision, "resolve_service_path", lambda _cache: "/usr/bin/" + provision.EXE)
    monkeypatch.setattr(provision, "latest_release_tag", lambda repo: pytest.fail("no network access"))

    assert provision.ensure_service(str(tmp_path)) == "/usr/bin/" + provision.EXE


def test_an_unsupported_platform_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(provision, "resolve_service_path", lambda _cache: None)
    monkeypatch.setattr(provision, "host_platform", lambda: None)

    with pytest.raises(RuntimeError, match="unsupported platform"):
        provision.ensure_service(str(tmp_path))


def test_the_progress_callback_reports_the_download(monkeypatch, tmp_path):
    payload = b"x" * 1000

    class FakeResponse(io.BytesIO):
        headers = {"Content-Length": str(len(payload))}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(provision, "urlopen", lambda *args, **kwargs: FakeResponse(payload))
    messages = []
    dest = str(tmp_path / "archive")

    provision.download_file("https://example.invalid/a.tar.gz", dest, progress=messages.append)

    assert open(dest, "rb").read() == payload
    assert messages and messages[-1] == "downloading... 100%"
