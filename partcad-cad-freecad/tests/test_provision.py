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
        ("Linux", "x86_64", ("linux-x86_64", "tar.gz")),
        ("Linux", "aarch64", ("linux-arm64", "tar.gz")),
        ("Darwin", "arm64", ("macos-arm64", "tar.gz")),
        ("Windows", "AMD64", ("windows-x86_64", "zip")),
    ],
)
def test_platform_names_match_install_sh(system, machine, expected):
    assert provision.platform_archive(system, machine) == expected


def test_an_unsupported_platform_has_no_bundle():
    assert provision.platform_archive("SunOS", "sparc") is None


def test_archive_and_artifact_names_are_the_ci_contract():
    assert provision.archive_name("0.7.158", "linux-x86_64", "tar.gz") == "partcad-0.7.158-linux-x86_64.tar.gz"
    assert provision.artifact_name("windows-x86_64") == "partcad-standalone-windows-x86_64"


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


def test_a_tar_bundle_unpacks_with_the_executable_bit_intact(tmp_path):
    archive = _bundle_tar(str(tmp_path / "bundle.tar.gz"), provision.EXE)
    dest = str(tmp_path / "out")

    provision.extract(archive, dest)

    exe = os.path.join(dest, "partcad", provision.EXE)
    assert os.path.isfile(exe)
    assert os.stat(exe).st_mode & stat.S_IXUSR


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
        "1": {"artifacts": [{"name": "partcad-standalone-macos-arm64", "archive_download_url": "wrong"}]},
        "2": {
            "artifacts": [
                {"name": "partcad-standalone-linux-x86_64", "archive_download_url": "right", "expired": False}
            ]
        },
    }

    def fake_get_json(url, token=None, timeout=60.0):  # pylint: disable=unused-argument
        assert token == "t"
        if "/runs?" in url or url.endswith("/runs"):
            return responses["runs"]
        return responses[url.rsplit("/runs/", 1)[1].split("/")[0]]

    monkeypatch.setattr(provision, "http_get_json", fake_get_json)

    artifact = provision.latest_devel_artifact("partcad/partcad", "linux-x86_64", "devel", "t")

    assert artifact["archive_download_url"] == "right"


def test_an_expired_artifact_is_skipped(monkeypatch):
    def fake_get_json(url, token=None, timeout=60.0):  # pylint: disable=unused-argument
        if "/runs?" in url:
            return {"workflow_runs": [{"id": 1}]}
        return {"artifacts": [{"name": "partcad-standalone-linux-x86_64", "expired": True}]}

    monkeypatch.setattr(provision, "http_get_json", fake_get_json)

    assert provision.latest_devel_artifact("partcad/partcad", "linux-x86_64", "devel", "t") is None


def test_downloading_a_devel_build_without_a_token_says_so(tmp_path):
    with pytest.raises(RuntimeError, match="GitHub token"):
        provision.download_devel("partcad/partcad", "linux-x86_64", "devel", str(tmp_path), lambda _m: None)


def test_a_release_with_a_bundle_for_this_platform_is_used(tmp_path, monkeypatch):
    calls = {}
    monkeypatch.setattr(provision, "resolve_service_path", lambda _cache: None)
    monkeypatch.setattr(provision, "platform_archive", lambda: ("linux-x86_64", "tar.gz"))
    monkeypatch.setattr(provision, "latest_release_tag", lambda repo: "0.7.158")
    monkeypatch.setattr(provision, "url_exists", lambda url: calls.setdefault("asset", url) is None or True)
    monkeypatch.setattr(provision, "download_release", lambda *args: "/bundle/" + provision.EXE)
    monkeypatch.setattr(provision, "download_devel", lambda *args: pytest.fail("should not fall back"))

    assert provision.ensure_service(str(tmp_path)) == "/bundle/" + provision.EXE
    assert calls["asset"].endswith("/0.7.158/partcad-0.7.158-linux-x86_64.tar.gz")


def test_a_release_without_a_bundle_falls_back_to_the_devel_build(tmp_path, monkeypatch):
    monkeypatch.setattr(provision, "resolve_service_path", lambda _cache: None)
    monkeypatch.setattr(provision, "platform_archive", lambda: ("linux-x86_64", "tar.gz"))
    # The latest release ships only the wheels, which is the state of the
    # repository's own releases today.
    monkeypatch.setattr(provision, "latest_release_tag", lambda repo: "0.7.135")
    monkeypatch.setattr(provision, "url_exists", lambda url: False)
    monkeypatch.setattr(provision, "download_release", lambda *args: pytest.fail("no bundle to download"))
    monkeypatch.setattr(provision, "download_devel", lambda *args: "/devel/" + provision.EXE)

    assert provision.ensure_service(str(tmp_path)) == "/devel/" + provision.EXE


def test_no_release_at_all_falls_back_to_the_devel_build(tmp_path, monkeypatch):
    monkeypatch.setattr(provision, "resolve_service_path", lambda _cache: None)
    monkeypatch.setattr(provision, "platform_archive", lambda: ("linux-x86_64", "tar.gz"))
    monkeypatch.setattr(provision, "latest_release_tag", lambda repo: None)
    monkeypatch.setattr(provision, "download_devel", lambda *args: "/devel/" + provision.EXE)

    assert provision.ensure_service(str(tmp_path)) == "/devel/" + provision.EXE


def test_pc_cad_devel_skips_the_release_lookup_entirely(tmp_path, monkeypatch):
    monkeypatch.setenv("PC_CAD_DEVEL", "1")
    monkeypatch.setattr(provision, "resolve_service_path", lambda _cache: None)
    monkeypatch.setattr(provision, "platform_archive", lambda: ("linux-x86_64", "tar.gz"))
    monkeypatch.setattr(provision, "latest_release_tag", lambda repo: pytest.fail("no release lookup"))
    monkeypatch.setattr(provision, "download_devel", lambda *args: "/devel/" + provision.EXE)

    assert provision.ensure_service(str(tmp_path)) == "/devel/" + provision.EXE


def test_an_existing_installation_is_never_downloaded_over(tmp_path, monkeypatch):
    monkeypatch.setattr(provision, "resolve_service_path", lambda _cache: "/usr/bin/" + provision.EXE)
    monkeypatch.setattr(provision, "latest_release_tag", lambda repo: pytest.fail("no network access"))

    assert provision.ensure_service(str(tmp_path)) == "/usr/bin/" + provision.EXE


def test_an_unsupported_platform_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(provision, "resolve_service_path", lambda _cache: None)
    monkeypatch.setattr(provision, "platform_archive", lambda: None)

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
