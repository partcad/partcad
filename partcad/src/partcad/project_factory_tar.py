#
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
import requests
import tarfile

from . import project_factory as pf
from .user_config import user_config


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
            cache_dir = os.path.join(user_config.internal_state_dir, "tar")

        # Generate a unique identifier for the file based on its URL.
        url_hash = hashlib.sha256(tarball_url.encode()).hexdigest()
        cache_path = os.path.join(cache_dir, url_hash)

        # Check if the tarball is already cached.
        if not os.path.exists(cache_path):
            # Download and extract
            try:
                os.makedirs(cache_path)

                auth = None
                if not (self.auth_user is None or self.auth_pass is None):
                    auth = (self.auth_user, self.auth_pass)
                with (
                    requests.get(tarball_url, stream=True, auth=auth) as rx,
                    tarfile.open(fileobj=rx.raw, mode="r:gz") as tarobj,
                ):
                    args = inspect.getfullargspec(tarobj.extractall)

                    if "filter" in args.args:
                        if not self.import_rel_path is None:
                            filter = lambda member, _: (
                                member if member.name.startswith(self.import_rel_path) else None
                            )
                        else:
                            filter = lambda member, _: member

                        tarobj.extractall(cache_path, filter=filter)
                    else:
                        tarobj.extractall(cache_path)
            except Exception as e:
                raise RuntimeError(f"Failed to download the tarball: {e}")

        if not self.import_rel_path is None:
            cache_path = os.path.join(cache_path, self.import_rel_path)

        return cache_path
