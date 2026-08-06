#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Tests for the workspace URL <-> path pair the context protocol rides on.

The CLI turns the workspace directory into a URL (``Path(path).resolve().as_uri()``
in ``partcad_cli.click.service.run``) and the daemon turns that URL back into a
directory (``operations._url_to_path``). Both halves are pure functions, yet the
pair only ever broke on Windows: the CLI used to build ``"file://" +
os.path.abspath(path)``, which makes ``urlparse`` read ``D:`` as the URL
*authority*, so the daemon opened something that was not the workspace at all and
every ``pc -p <dir> render/export`` died with "PartCAD configuration file is not
found". Finding that cost a full Windows CI cycle.

The only platform-dependent piece of the decoder is ``urllib.request.url2pathname``,
which resolves to ``nturl2path``'s implementation on Windows and to plain
``unquote`` on POSIX. These tests substitute that one function, so both
platforms' behavior is asserted on whichever platform runs the suite.
"""

import ntpath
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import unquote

import pytest
from partcad_service_json_rpc.core import operations
from partcad_service_json_rpc.rpc.dispatcher import JsonRpcError


@pytest.fixture
def posix_decoder(monkeypatch):
    """Decode as the daemon does on POSIX, where ``url2pathname`` is ``unquote``."""
    monkeypatch.setattr(operations, "url2pathname", unquote)


@pytest.fixture
def windows_decoder(monkeypatch):
    """Decode as the daemon does on Windows.

    ``nturl2path`` is the stdlib module ``urllib.request`` imports ``url2pathname``
    from when ``os.name == "nt"``, so binding it here reproduces the Windows
    decoder exactly -- on any host.
    """
    nturl2path = pytest.importorskip("nturl2path")
    monkeypatch.setattr(operations, "url2pathname", nturl2path.url2pathname)


# ---- round trip: the path the CLI has -> URL -> the path the daemon opens ----
# The URL column is what ``Path(path).as_uri()`` produces for that path, so each
# case pins the encoder and the decoder against each other without needing a host
# of that platform.


@pytest.mark.parametrize(
    "path, url",
    [
        ("/home/user/pkg", "file:///home/user/pkg"),
        ("/home/user/my parts", "file:///home/user/my%20parts"),
        ("/home/user/pkg-\u00fcber", "file:///home/user/pkg-%C3%BCber"),
        ("/home/user/\u96f6\u4ef6/pkg", "file:///home/user/%E9%9B%B6%E4%BB%B6/pkg"),
        # '#' would otherwise start a URL fragment and truncate the path.
        ("/home/user/c#1", "file:///home/user/c%231"),
        ("/home/user/a+b&c", "file:///home/user/a%2Bb%26c"),
        # A literal '%' has to survive the decoder's unquoting.
        ("/home/user/100%done", "file:///home/user/100%25done"),
    ],
)
def test_posix_workspace_path_round_trips_through_the_url(posix_decoder, path, url):
    assert PurePosixPath(path).as_uri() == url
    assert operations._url_to_path(url) == path


@pytest.mark.parametrize(
    "path, url",
    [
        ("C:\\dir\\pkg", "file:///C:/dir/pkg"),
        ("D:\\Users\\me\\my parts", "file:///D:/Users/me/my%20parts"),
        ("C:\\dir\\pkg-\u00fcber", "file:///C:/dir/pkg-%C3%BCber"),
        ("C:\\dir\\c#1", "file:///C:/dir/c%231"),
        ("Z:\\a+b&c\\pkg", "file:///Z:/a%2Bb%26c/pkg"),
    ],
)
def test_windows_workspace_path_round_trips_through_the_url(windows_decoder, path, url):
    assert PureWindowsPath(path).as_uri() == url
    assert operations._url_to_path(url) == path


def test_windows_unc_workspace_path_round_trips_through_the_url(windows_decoder):
    """A UNC share puts the host in the URL authority, which must not be dropped."""
    path = "\\\\host\\share\\pkg"
    url = PureWindowsPath(path).as_uri()
    assert url == "file://host/share/pkg"
    decoded = operations._url_to_path(url)
    # The decoder rebuilds the authority with forward slashes ("//host\share\pkg").
    # Windows accepts either separator and ``context_create`` normalizes the result
    # through ``os.path.abspath``, so compare the normalized forms.
    assert ntpath.normpath(decoded) == path


def test_localhost_authority_is_not_mistaken_for_a_unc_host(posix_decoder):
    """``file://localhost/...`` is the same file as ``file:///...``, not a share."""
    assert operations._url_to_path("file://localhost/home/user/pkg") == "/home/user/pkg"
    assert operations._url_to_path("file://LOCALHOST/home/user/pkg") == "/home/user/pkg"


@pytest.mark.parametrize("name", ["pkg", "my parts", "pkg-\u00fcber"])
def test_a_real_workspace_directory_round_trips_on_this_platform(tmp_path, name):
    """The unpatched pair, driven exactly as the CLI drives it, against real dirs."""
    workspace = tmp_path / name
    workspace.mkdir()

    url = Path(workspace).resolve().as_uri()  # what partcad_cli.click.service.run builds
    decoded = operations._url_to_path(url)

    assert os.path.isdir(decoded), "the daemon must be able to open what the CLI sent"
    assert os.path.samefile(decoded, str(workspace))
    # context_create hashes os.path.abspath(decoded) into the context id, so the
    # decoded form has to normalize to the very directory the user pointed at.
    assert os.path.abspath(decoded) == str(workspace.resolve())


def test_concatenating_file_scheme_onto_a_windows_path_loses_the_drive(windows_decoder):
    """The regression this file exists for: ``"file://" + os.path.abspath(path)``.

    On Windows the drive letter lands in the URL authority instead of the path, so
    the daemon resolved a directory that was not the workspace and reported a
    missing configuration file. Pinned from the decoder side so no caller can go
    back to building workspace URLs by concatenation.
    """
    path = "D:\\dir\\pkg"
    assert operations._url_to_path("file://" + path) != path
    assert operations._url_to_path(PureWindowsPath(path).as_uri()) == path


# ---- non-file inputs --------------------------------------------------------


@pytest.mark.parametrize("path", ["/home/user/pkg", "/home/user/my parts", "relative/pkg", "."])
def test_a_bare_path_is_passed_through_unchanged(path):
    """No scheme means it is already a path; it must not be unquoted or rewritten."""
    assert operations._url_to_path(path) == path


@pytest.mark.parametrize("path", [r"C:\dir\pkg", r"d:\proj\parts", r"Z:\pkg"])
def test_a_bare_windows_path_is_a_path_not_an_unsupported_scheme(path):
    """A drive letter parses as a one-character scheme; it is still a bare path.

    No real URL scheme is a single character, so rejecting these as
    "Unsupported context URL scheme: c" made the documented bare-path
    passthrough unusable on Windows.
    """
    assert operations._url_to_path(path) == path


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/pkg",
        "http://127.0.0.1:8017/pkg",
        "git+ssh://git@github.com/openvmp/partcad.git",
        "ftp://example.com/pkg",
    ],
)
def test_an_unsupported_scheme_is_reported_as_an_invalid_configuration(url):
    """Remote workspaces are a TODO; until then the client gets a real error."""
    with pytest.raises(JsonRpcError) as excinfo:
        operations._url_to_path(url)
    assert excinfo.value.code == operations.INVALID_CONFIG
    assert "scheme" in excinfo.value.message
