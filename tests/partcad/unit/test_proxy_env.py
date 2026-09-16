#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Every way PartCAD downloads something has to go through ``HTTPS_PROXY``.

On plenty of machines a proxy is not a preference but the only route out: a
corporate network, a CI runner behind an egress policy, a sandboxed agent
session. There a downloader that ignores the variable does not fall back to
anything -- it dials a host nothing can reach and stalls until it times out.

The three transports get there three different ways, which is why one of them
was wrong and the other two were not. libgit2 is asked for it explicitly
(``proxy=True``), ``requests`` does it on its own, and ``aiohttp`` reads the
variable only when it is built with ``trust_env=True``. Three mechanisms is
three things to break independently, so each is checked against a proxy that
records what it was asked to reach rather than against a mock of the client.

The hosts below are all under ``.invalid``, which RFC 2606 reserves and no
resolver answers for. That is deliberate: it makes "the proxy was ignored" a
prompt name-resolution failure rather than a connection to something real.
"""

import asyncio

import aiohttp
import pytest
from proxy_server import serve_proxy

from partcad.file_factory_url import FileFactoryUrl
from partcad.project_factory_git import GIT_ERRORS, CloneOptions, _clone
from partcad.project_factory_tar import ProjectFactoryTar

GIT_URL = "https://git.example.invalid/pkg.git"
GIT_HOST = "git.example.invalid"

TAR_URL = "https://tarballs.example.invalid/pkg.tar.gz"
TAR_HOST = "tarballs.example.invalid"

FILE_URL = "https://files.example.invalid/bolt.step"
FILE_HOST = "files.example.invalid"


class _TarStub(ProjectFactoryTar):
    """The factory with only what the download reads set up.

    Constructing it properly would need a context and a package to hang it off,
    and would do the download itself; the download is the subject here, so it
    is reached directly -- but through the real class, so that the methods it
    calls are the real ones.
    """

    auth_user = None
    auth_pass = None
    import_rel_path = None

    def __init__(self):
        pass


class _FileStub:
    """The same, for FileFactoryUrl._download."""

    def __init__(self, url):
        self.url = url


@pytest.fixture
def proxy_env(monkeypatch):
    """A recording proxy, named by HTTPS_PROXY and by nothing else.

    Only HTTPS_PROXY is set: it is the variable under test and every URL here
    is an https one. The rest are cleared because the machine running this may
    itself be behind a proxy, and either its NO_PROXY -- which would exempt the
    test's own destination from the proxy the test is checking -- or its
    ALL_PROXY would decide the outcome instead.
    """
    with serve_proxy() as proxy:
        for name in ("HTTP_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("HTTPS_PROXY", proxy.url)
        monkeypatch.setenv("NO_PROXY", "")
        monkeypatch.setenv("no_proxy", "")
        yield proxy


def _clone_through(url, path):
    with pytest.raises(GIT_ERRORS):
        _clone(url, str(path), {}, CloneOptions(revision=None, depth=1))


def _extract_through(url, cache_dir):
    with pytest.raises(RuntimeError):
        _TarStub()._extract(url, cache_dir=str(cache_dir))


def _download_through(url, path):
    with pytest.raises((aiohttp.ClientError, OSError)):
        asyncio.run(FileFactoryUrl._download(_FileStub(url), str(path)))


def test_a_git_import_goes_through_the_proxy(proxy_env, tmp_path):
    """libgit2 talks to the remote directly unless it is asked not to."""
    _clone_through(GIT_URL, tmp_path / "clone")

    assert proxy_env.reached(GIT_HOST), proxy_env.requests


def test_a_tarball_import_goes_through_the_proxy(proxy_env, tmp_path):
    _extract_through(TAR_URL, tmp_path / "tar")

    assert proxy_env.reached(TAR_HOST), proxy_env.requests


def test_a_file_download_goes_through_the_proxy(proxy_env, tmp_path):
    """'fileFrom: url' is aiohttp, which needs trust_env to read the variable."""
    _download_through(FILE_URL, tmp_path / "bolt.step")

    assert proxy_env.reached(FILE_HOST), proxy_env.requests


def test_no_proxy_still_exempts_a_host(proxy_env, tmp_path, monkeypatch):
    """Respecting the variable means respecting the exemption that comes with it.

    A proxy that a package's own git server is not reachable through is the
    usual reason NO_PROXY exists, so honouring HTTPS_PROXY and ignoring
    NO_PROXY would trade one unreachable remote for another.
    """
    monkeypatch.setenv("NO_PROXY", "%s,%s,%s" % (GIT_HOST, TAR_HOST, FILE_HOST))
    monkeypatch.setenv("no_proxy", "%s,%s,%s" % (GIT_HOST, TAR_HOST, FILE_HOST))

    # Each of these still fails: the hosts do not resolve. What is checked is
    # that the failure happened without the proxy being asked for anything.
    _clone_through(GIT_URL, tmp_path / "clone")
    _extract_through(TAR_URL, tmp_path / "tar")
    _download_through(FILE_URL, tmp_path / "bolt.step")

    assert proxy_env.requests == []


def test_a_failed_tarball_download_is_not_cached(proxy_env, tmp_path):
    """A proxy that refuses once must not break the import for good.

    The extracted copy is keyed by the URL and reused as-is if it is there, so
    a directory left behind by a download that never completed is served as the
    package from then on -- and nothing downloads it again.
    """
    cache_dir = tmp_path / "tar"

    _extract_through(TAR_URL, cache_dir)

    assert list(cache_dir.glob("*")) == []
