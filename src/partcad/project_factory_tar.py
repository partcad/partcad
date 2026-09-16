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

import requests

from . import project_factory as pf
from . import telemetry
from .project_local import ProjectLocal


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
            # Download and extract. Creating the directory is kept apart from
            # filling it so that the cleanup below can only ever remove a
            # directory this attempt created -- never one another thread is
            # busy filling, which is what an unconditional cleanup here would
            # do to whichever of two concurrent imports lost the race.
            try:
                os.makedirs(cache_path)
            except OSError as e:
                raise RuntimeError(f"Failed to download the tarball: {e}")

            try:
                auth = None
                if not (self.auth_user is None or self.auth_pass is None):
                    auth = (self.auth_user, self.auth_pass)
                # 'requests' reads HTTPS_PROXY/HTTP_PROXY and NO_PROXY out of
                # the environment on its own, which is how this transport
                # reaches a remote on a machine whose only route out is a
                # proxy. Nothing here may pass 'proxies=' or turn 'trust_env'
                # off without taking that away.
                with requests.get(tarball_url, stream=True, auth=auth) as rx:
                    # A proxy that refuses answers with a page, not with
                    # nothing, and so does a 404. Left unchecked that page is
                    # what gets handed to tarfile below, which reports "not a
                    # gzip file" -- a corrupt archive, for what is really a 407
                    # from the proxy or a URL that has moved.
                    rx.raise_for_status()

                    with tarfile.open(fileobj=rx.raw, mode="r:gz") as tar_obj:
                        args = inspect.getfullargspec(tar_obj.extractall)

                        if "filter" in args.args:
                            if self.import_rel_path is not None:
                                filter = lambda member, _: (
                                    member if member.name.startswith(self.import_rel_path) else None
                                )
                            else:
                                filter = lambda member, _: member

                            tar_obj.extractall(cache_path, filter=filter)
                        else:
                            tar_obj.extractall(cache_path)
            except Exception as e:
                # Whatever this attempt managed to create is taken for a cached
                # copy by the next one, which then serves an empty directory as
                # the package and never downloads anything again. A proxy that
                # refuses once would poison the cache that way for good.
                shutil.rmtree(cache_path, ignore_errors=True)
                raise RuntimeError(f"Failed to download the tarball: {e}")

        if self.import_rel_path is not None:
            cache_path = os.path.join(cache_path, self.import_rel_path)

        return cache_path
