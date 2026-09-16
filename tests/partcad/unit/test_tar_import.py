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
import os
import tarfile

import pytest
from http_server import serve as _serve

from partcad.project_factory_tar import ProjectFactoryTar

ARCHIVE = "pkg.tar.gz"

# What the served archive holds. The nesting matters: 'relPath' selects a
# subtree, so there has to be something outside the one it selects.
TREE = {
    "pkg/partcad.yaml": "parts:\n  bolt:\n    type: step\n",
    "pkg/sub/part.step": "ISO-10303-21;\n",
}


class _Tar:
    """What ProjectFactoryTar._extract reads off 'self', and nothing else.

    Constructing the factory would need a context and a package to hang it off;
    the download is the subject here, so it is called directly.
    """

    def __init__(self, rel_path=None):
        self.auth_user = None
        self.auth_pass = None
        self.import_rel_path = rel_path


def _extract(factory, url, cache_dir):
    return ProjectFactoryTar._extract(factory, url, cache_dir=str(cache_dir))


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
    real = inspect.getfullargspec

    def without_filter(func):
        spec = real(func)
        return spec._replace(kwonlyargs=[name for name in spec.kwonlyargs if name != "filter"])

    monkeypatch.setattr(inspect, "getfullargspec", without_filter)

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
