#
# PartCAD, 2025
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-23
#
# Licensed under Apache License, Version 2.0.
#

import hashlib
import inspect
import os
import shutil
import tarfile
import uuid

import requests

from . import project_factory as pf
from . import telemetry
from .project_local import ProjectLocal

# What bounds a remote -- or a proxy in front of one -- that accepts the
# connection and then stops answering. 'requests' has no timeout of its own, so
# without these an import of a tarball hangs for as long as the peer keeps the
# socket open, with nothing to say what it is waiting for.
#
# These bound *inactivity* rather than the transfer: requests applies them per
# socket operation, so a large archive on a slow link still arrives. The shape
# is the one '_apply_git_timeout' gives the git transport -- a short bound on
# reaching the remote at all, a longer one on it going quiet afterwards.
CONNECT_TIMEOUT = 60
READ_TIMEOUT = 180


def _lands_within(destination: str, name: str) -> bool:
    """Whether unpacking 'name' under 'destination' stays under it."""
    resolved = os.path.abspath(os.path.join(destination, name))
    return resolved == destination or resolved.startswith(destination + os.sep)


def _is_under(name: str, rel_path: str) -> bool:
    """Whether the member 'name' is 'rel_path' itself or something inside it.

    The boundary is what makes this more than a prefix test: 'pkg/sub' is a
    prefix of 'pkg/submarine', so asking for one subtree would quietly unpack
    its siblings alongside it. Archive member names are always '/'-separated,
    whatever the machine unpacking them uses.
    """
    prefix = rel_path.rstrip("/")
    if not prefix:
        return True
    return name == prefix or name.startswith(prefix + "/")


def _safe_members(tar_obj, destination):
    """What 'data_filter' refuses, for the interpreters that predate it.

    Below 3.10.12 and 3.11.4 there is no filter to ask for, so the check is
    made here: a member is unpacked only if it, and a link's target, land
    inside 'destination'. Iterating the archive as extraction proceeds is
    tarfile's own documented way of doing this, and the only one available over
    a stream.

    A function rather than a method of the factory because the class is
    '@telemetry.instrument()'ed, and that walks 'vars(cls)' wrapping everything
    callable -- which a 'staticmethod' object is, without having the '__code__'
    the wrapper reads.
    """
    destination = os.path.abspath(destination)
    for member in tar_obj:
        # What lands where is only half of it: a tarball can also ask for a
        # fifo or a device node, and 'os.mkfifo' needs no privilege at all.
        # A package is files and directories, so this is the same set
        # 'data_filter' allows.
        if not (member.isreg() or member.isdir() or member.issym() or member.islnk()):
            raise tarfile.TarError("'%s' is not a kind of file a package may contain" % member.name)

        targets = [member.name]
        if member.islnk() or member.issym():
            targets.append(os.path.join(os.path.dirname(member.name), member.linkname))
        for target in targets:
            if not _lands_within(destination, target):
                raise tarfile.TarError("'%s' would be unpacked outside the package" % member.name)
        yield member


class TarImportConfiguration:
    def __init__(self):
        self.import_config_url = self.config_obj.get("url")
        self.import_rel_path = self.config_obj.get("relPath")
        if "username" in self.config_obj and "password" in self.config_obj:
            self.auth_user = self.config_obj.get("username")
            self.auth_pass = self.config_obj.get("password")
        else:
            self.auth_user = None
            self.auth_pass = None


@telemetry.instrument()
class ProjectFactoryTar(pf.ProjectFactory, TarImportConfiguration):
    def __init__(self, ctx, parent, config):
        pf.ProjectFactory.__init__(self, ctx, parent, config)
        TarImportConfiguration.__init__(self)

        # TODO(clairbee): Clone self.import_config_url to self.path
        self.path = self._extract(self.import_config_url)

        # Complement the config object here if necessary
        self._create(config)

        # TODO(clairbee): actually fill in the self.project object here

        self._save()

    def _create_project(self, config):
        return ProjectLocal(
            self.ctx,
            self.name,
            self.path,
            include_paths=self.include_paths,
            inherited_config=self.inherited_config,
        )

    def _extract(self, tarball_url, cache_dir=None):
        """
        Extracts a tarball to a local directory.

        Args:
          tarball_url: URL of the '.tar.gz' file to download.
          cache_dir: Directory to store the extracted files to (defaults to ".cache").

        Returns:
          Local path to the extracted content.
        """

        if cache_dir is None:
            cache_dir = os.path.join(self.ctx.user_config.internal_state_dir, "tar")

        # Generate a unique identifier for the file based on its URL.
        url_hash = hashlib.sha256(tarball_url.encode()).hexdigest()[:16]
        cache_path = os.path.join(cache_dir, url_hash)

        # Check if the tarball is already cached.
        if not os.path.exists(cache_path):
            self._download(tarball_url, cache_path)

        if self.import_rel_path is not None:
            cache_path = os.path.join(cache_path, self.import_rel_path)

        return cache_path

    def _download(self, tarball_url, cache_path) -> None:
        """Fill 'cache_path' from 'tarball_url', or leave nothing behind.

        The archive is unpacked into a directory of this attempt's own and
        moved into place only once it is complete, because the directory being
        there is the whole of "this package is already downloaded": there is no
        lock over the cache and no marker inside it, so whatever is present is
        used as it stands. Creating it first and filling it afterwards
        therefore had two ways to serve an empty package for good -- a failure
        part way through, and a second import that looked while the first was
        still unpacking. Imports do run concurrently: 'Context' imports
        projects in a thread pool and locks by project name, while this cache
        is keyed by URL, so two differently named imports of one archive land
        here at the same time.
        """
        staging = "%s.%d.%s.partial" % (cache_path, os.getpid(), uuid.uuid4().hex[:8])

        try:
            os.makedirs(staging)

            auth = None
            if not (self.auth_user is None or self.auth_pass is None):
                auth = (self.auth_user, self.auth_pass)
            # 'requests' reads HTTPS_PROXY/HTTP_PROXY and NO_PROXY out of the
            # environment on its own, which is how this transport reaches a
            # remote on a machine whose only route out is a proxy. Nothing here
            # may pass 'proxies=' or turn 'trust_env' off without taking that
            # away.
            with requests.get(
                tarball_url,
                stream=True,
                auth=auth,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            ) as rx:
                # A proxy that refuses answers with a page, not with nothing,
                # and so does a 404. Left unchecked that page is what gets
                # handed to tarfile below, which reports "not a gzip file" -- a
                # corrupt archive, for what is really a 407 from the proxy or a
                # URL that has moved.
                rx.raise_for_status()

                with tarfile.open(fileobj=rx.raw, mode="r:gz") as tar_obj:
                    self._extract_all(tar_obj, staging)
        except Exception as e:
            shutil.rmtree(staging, ignore_errors=True)
            raise RuntimeError(f"Failed to download the tarball: {e}")

        try:
            os.rename(staging, cache_path)
        except OSError:
            # Another import of the same archive published first. That is not a
            # failure -- it is the same URL, so what is there is what this
            # would have written -- as long as something really is there.
            # A rename onto a non-empty directory is refused on POSIX and onto
            # any existing one on Windows, which is what makes this the losing
            # side of that race rather than a corrupted cache.
            shutil.rmtree(staging, ignore_errors=True)
            if not os.path.isdir(cache_path):
                raise

    def _extract_all(self, tar_obj, destination) -> None:
        """Unpack 'tar_obj' into 'destination', refusing what would escape it.

        A tarball is a list of paths to write, and nothing stops those paths
        from being absolute, from climbing out with '..', or from being links
        that point anywhere at all: an archive can name the files on this
        machine it would like to overwrite (CVE-2007-4559). Python answers that
        with extraction filters, and 'data' is the one meant for an archive
        from elsewhere.

        Passing a filter is what makes asking for it necessary. Python 3.14
        applies 'data' by default, so an unfiltered 'extractall' is checked
        there -- and a filter of our own *replaces* that default rather than
        adding to it. Selecting 'relPath' with a bare lambda would therefore
        have turned the checking off on exactly the newest interpreters.
        """
        args = inspect.getfullargspec(tar_obj.extractall)

        # 'filter' is keyword-only, so it is a kwonlyarg and never one of
        # 'args': looking for it among the positional ones found nothing on
        # every Python that has it, and the selection below never ran --
        # 'relPath' selected nothing and the whole archive was unpacked, which
        # reads as working because the path handed back points into the subtree
        # either way. It is still asked for rather than assumed, because 3.10
        # and 3.11 only gained it in a patch release (3.10.12, 3.11.4), which
        # is also where 'data_filter' arrived.
        if hasattr(tarfile, "data_filter") and ("filter" in args.args or "filter" in args.kwonlyargs):
            tar_obj.extractall(destination, filter=self._member_filter)
        else:
            tar_obj.extractall(destination, members=_safe_members(tar_obj, destination))

    def _member_filter(self, member, path):
        """Which members to unpack, and on what terms.

        'relPath' says which subtree the package is in, so nothing else is
        written at all; what is left goes through tarfile's own 'data' filter,
        which raises rather than returning for a member that would land outside
        'path'.
        """
        if self.import_rel_path is not None and not _is_under(member.name, self.import_rel_path):
            return None
        return tarfile.data_filter(member, path)
