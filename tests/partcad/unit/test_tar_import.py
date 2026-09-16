#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What the tarball transport does with what it downloaded.

The archive is served over HTTP from a private loopback port rather than
fetched from a real remote. It is the same code path, it runs in milliseconds,
and it can express the cases a fixed URL on a hosting service cannot: a
response that is not an archive at all, a ``relPath`` that selects one subtree,
and a cache directory that cannot be created.

What every case here shares is the cache. The extracted copy is keyed by the
URL and reused as-is if it is there, so *anything* an attempt leaves behind is
served as the package from then on and nothing downloads it again. A failure
that leaves a directory is therefore not one failure but every future one.
"""

import inspect
import io
import os
import tarfile

import pytest
import requests
from http_server import serve as _serve

from partcad import project_factory_tar
from partcad.project_factory_tar import ProjectFactoryTar

ARCHIVE = "pkg.tar.gz"

# What the served archive holds. The nesting matters: 'relPath' selects a
# subtree, so there has to be something outside the one it selects.
TREE = {
    "pkg/partcad.yaml": "parts:\n  bolt:\n    type: step\n",
    "pkg/sub/part.step": "ISO-10303-21;\n",
}

# A member name that leaves the directory it is unpacked into. The oldest
# tarball attack there is (CVE-2007-4559), and what tarfile's 'data' filter
# exists to refuse.
ESCAPING_MEMBER = "../escaped.txt"

_REAL_ARGSPEC = inspect.getfullargspec


class _Tar(ProjectFactoryTar):
    """The factory with only what the download reads set up.

    ProjectFactoryTar.__init__ would need a context and a package to hang the
    factory off, and would go on to do the download itself. The download is the
    subject here, so it is reached directly -- but through the real class, so
    that the methods it calls are the real ones.
    """

    def __init__(self, rel_path=None):
        self.auth_user = None
        self.auth_pass = None
        self.import_rel_path = rel_path


def _extract(factory, url, cache_dir):
    return factory._extract(url, cache_dir=str(cache_dir))


@pytest.fixture
def served(tmp_path):
    """A directory holding 'pkg.tar.gz', built out of TREE."""
    root = tmp_path / "served"
    root.mkdir()

    content = tmp_path / "content"
    for name, text in TREE.items():
        path = content / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    with tarfile.open(root / ARCHIVE, "w:gz") as tar:
        # Named one by one rather than by adding the directory, so that the
        # member names in the archive are exactly the paths in TREE.
        for name in TREE:
            tar.add(content / name, arcname=name)

    return root


@pytest.fixture
def cache(tmp_path):
    return tmp_path / "cache"


@pytest.fixture
def malicious(tmp_path):
    """A served archive whose one member climbs out of where it is unpacked."""
    root = tmp_path / "served-evil"
    root.mkdir()

    payload = b"owned\n"
    with tarfile.open(root / ARCHIVE, "w:gz") as tar:
        info = tarfile.TarInfo(ESCAPING_MEMBER)
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))

    return root


def _without_filter(func):
    """getfullargspec, with 'filter' taken back out of extractall's signature."""
    spec = _REAL_ARGSPEC(func)
    return spec._replace(kwonlyargs=[name for name in spec.kwonlyargs if name != "filter"])


def test_a_tarball_is_downloaded_and_extracted(served, cache):
    with _serve(served) as url:
        path = _extract(_Tar(), "%s/%s" % (url, ARCHIVE), cache)

    for name, text in TREE.items():
        assert open(os.path.join(path, *name.split("/"))).read() == text


def test_rel_path_selects_one_subtree(served, cache):
    """'relPath' is where the package is, and the rest is not unpacked at all."""
    with _serve(served) as url:
        path = _extract(_Tar("pkg/sub"), "%s/%s" % (url, ARCHIVE), cache)

    assert os.path.normpath(path).endswith(os.path.join("pkg", "sub"))
    assert open(os.path.join(path, "part.step")).read() == TREE["pkg/sub/part.step"]

    # The file outside the selected subtree was filtered out rather than merely
    # left unreferenced. This is what tells a working filter apart from one
    # that is never applied: the returned path points into the subtree either
    # way, so only what is *beside* it says whether 'relPath' did anything.
    outside = os.path.join(os.path.dirname(path), "partcad.yaml")
    assert not os.path.exists(outside)


def test_a_python_that_cannot_filter_still_extracts(served, cache, monkeypatch):
    """extractall grew its 'filter' argument in a patch release.

    3.10.12 and 3.11.4, so an interpreter within PartCAD's supported range can
    predate it -- and one that does takes no such argument at all. There the
    archive is unpacked whole and 'relPath' is honoured only by the path that
    comes back. The signature is faked because every Python this suite can run
    on is already new enough to take one.
    """
    monkeypatch.setattr(inspect, "getfullargspec", _without_filter)

    with _serve(served) as url:
        path = _extract(_Tar("pkg/sub"), "%s/%s" % (url, ARCHIVE), cache)

    assert open(os.path.join(path, "part.step")).read() == TREE["pkg/sub/part.step"]
    # Unfiltered, so what 'relPath' excluded is on disk as well.
    assert os.path.exists(os.path.join(os.path.dirname(path), "partcad.yaml"))


def test_an_extracted_tarball_is_not_downloaded_again(served, cache):
    """The second call answers from the cache -- with the server gone."""
    url_path = None
    with _serve(served) as url:
        url_path = "%s/%s" % (url, ARCHIVE)
        first = _extract(_Tar(), url_path, cache)

    second = _extract(_Tar(), url_path, cache)

    assert second == first
    assert os.path.exists(os.path.join(second, "pkg", "partcad.yaml"))


def test_a_response_that_is_not_an_archive_is_reported(served, cache):
    """A 404 answers with a page, and a page is not an empty package.

    Unchecked, that page reaches tarfile and comes back as "not a gzip file" --
    a corrupt archive, for a URL that has moved. A proxy refusing with a 407
    looks exactly the same from here.
    """
    with _serve(served) as url:
        with pytest.raises(RuntimeError):
            _extract(_Tar(), "%s/nosuch.tar.gz" % url, cache)

    # And nothing was left behind for the next import to serve as the package.
    assert not os.path.exists(cache) or list(cache.iterdir()) == []


def test_a_cache_directory_that_cannot_be_created_is_reported(tmp_path):
    """Reported as a failed download rather than raised as a bare OSError."""
    blocked = tmp_path / "blocked"
    blocked.write_text("a file where the cache directory would go")

    # Nothing is fetched: this fails before the URL is ever reached.
    with pytest.raises(RuntimeError):
        _extract(_Tar(), "https://tarballs.example.invalid/pkg.tar.gz", blocked)


@pytest.mark.parametrize("can_filter", [True, False], ids=["data_filter", "no_filter_argument"])
def test_a_member_that_climbs_out_of_the_package_is_refused(malicious, cache, monkeypatch, can_filter):
    """An archive does not get to choose which files on this machine to write.

    Both ways of extracting have to refuse it, and they refuse it differently:
    the modern one hands tarfile's own 'data' filter the member, the one for
    interpreters without a 'filter' argument checks the destination itself. The
    modern path is the one this PR could have broken -- passing a filter
    replaces Python 3.14's 'data' default rather than adding to it.
    """
    if not can_filter:
        monkeypatch.setattr(inspect, "getfullargspec", _without_filter)

    with _serve(malicious) as url:
        with pytest.raises(RuntimeError):
            _extract(_Tar(), "%s/%s" % (url, ARCHIVE), cache)

    assert not os.path.exists(os.path.join(cache, os.path.basename(ESCAPING_MEMBER)))
    assert not os.path.exists(cache) or list(cache.iterdir()) == []


def test_the_download_is_bounded_by_a_timeout(served, cache, monkeypatch):
    """'requests' waits forever by default.

    A remote -- or a proxy in front of one -- that accepts the connection and
    then says nothing would hold the import open for as long as it cared to,
    with nothing to say what was being waited for.
    """
    passed = {}
    real_get = requests.get

    def recording_get(url, **kwargs):
        passed.update(kwargs)
        return real_get(url, **kwargs)

    monkeypatch.setattr(project_factory_tar.requests, "get", recording_get)

    with _serve(served) as url:
        _extract(_Tar(), "%s/%s" % (url, ARCHIVE), cache)

    connect, read = passed["timeout"]
    assert connect > 0
    assert read > 0


def test_nothing_is_published_until_it_is_complete(served, cache):
    """The cache has no lock and no marker, so a directory that is there is used.

    A download that created the directory and filled it afterwards could be
    read mid-extraction by a second import of the same URL -- they are keyed by
    URL while the import lock is by project name, so two differently named
    imports of one archive race here. Nothing appears under the cache but the
    finished entry and, while it runs, this attempt's own staging directory.
    """
    with _serve(served) as url:
        _extract(_Tar(), "%s/%s" % (url, ARCHIVE), cache)

    entries = sorted(entry.name for entry in cache.iterdir())

    assert len(entries) == 1
    assert not entries[0].endswith(".partial")


def test_an_import_that_lost_the_race_keeps_what_the_winner_published(served, cache):
    """Two imports of one archive can be unpacking it at the same time.

    The one that finishes second finds the entry already there. That is not a
    failure -- same URL, same bytes, and what is there is complete -- so it
    discards its own copy and uses the published one rather than disturbing it.
    """
    cache.mkdir(parents=True)
    published = cache / "entry"
    published.mkdir()
    (published / "partcad.yaml").write_text("published by the winner\n")

    with _serve(served) as url:
        _Tar()._download("%s/%s" % (url, ARCHIVE), str(published))

    assert (published / "partcad.yaml").read_text() == "published by the winner\n"
    # And the staging directory this attempt used is gone.
    assert sorted(entry.name for entry in cache.iterdir()) == ["entry"]


def test_a_rename_that_failed_for_any_other_reason_is_not_swallowed(served, cache):
    """Losing the race is forgiven because something complete is there instead.

    Nothing else is: if the entry cannot be published and there is no entry, the
    import has not happened and must say so.
    """
    cache.mkdir(parents=True)
    blocked = cache / "entry"
    blocked.write_text("a file where the cache entry belongs")

    with _serve(served) as url:
        with pytest.raises(OSError):
            _Tar()._download("%s/%s" % (url, ARCHIVE), str(blocked))
