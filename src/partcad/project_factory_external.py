#
# PartCAD, 2025
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.
#

import os
import hashlib

from . import project_factory as pf
from .project import Project
from .project_external_repository import ProjectExternalRepository
from .cache import Cache
from . import logging as pc_logging
from . import telemetry


class ExternalImportConfiguration:
    def __init__(self):
        self.plugin = self.config_obj.get("plugin", ":plugin")
        # A child of a plugin-backed hierarchy carries the subfolder that scopes
        # its requests within the repository. Empty for a top-level package.
        self.subfolder = self.config_obj.get("subfolder", "")
        # An optional integer the plugin author bumps whenever the *shape* of the
        # data the plugin returns changes (e.g. a new field is added to every
        # part config). It is mixed into the on-disk cache location, so bumping it
        # invalidates every entry cached by an older version of the plugin - which
        # a key derived from the plugin reference and the request alone would keep
        # serving. See 'docs/source/configuration.rst' (external dependencies).
        self.cache_version = int(self.config_obj.get("cacheVersion", 0) or 0)


@telemetry.instrument()
class ProjectFactoryExternal(pf.ProjectFactory, ExternalImportConfiguration):
    def __init__(self, ctx, parent: Project, config):
        pf.ProjectFactory.__init__(self, ctx, parent, config)
        ExternalImportConfiguration.__init__(self)

        # 'plugin' is a resource reference ('<package>:<plugin>'), not a
        # filesystem path, so it has to be resolved against the parent's
        # package name. It used to be resolved against 'parent.path', which is
        # a directory on disk and never a valid package name.
        self.plugin = parent.normalize(self.plugin)

        # Find a place to store all temporary artifacts if any. The hash of the
        # resolved plugin reference identifies this repository instance, so two
        # vendored copies backed by different plugins get separate caches. The
        # optional 'cacheVersion' is folded in too, so bumping it moves every
        # child of this repository to a fresh cache namespace at once.
        repo_key = self.plugin if not self.cache_version else "%s@v%d" % (self.plugin, self.cache_version)
        repo_hash = hashlib.sha256(repo_key.encode()).hexdigest()[:16]
        self.path = os.path.join(ctx.user_config.internal_state_dir, "external", repo_hash)
        # The package is served by a plugin and has no source tree of its own,
        # but it still needs a real directory: it is the base into which
        # file-backed objects are materialized (see ProjectExternalRepository).
        os.makedirs(self.path, exist_ok=True)
        # A cache scoped to this repository instance, shared by every child of
        # the plugin-backed package via 'ProjectExternalRepository.request()'.
        self.cache = Cache("external/" + repo_hash, ctx.user_config)

        pc_logging.debug(f"External project path: {self.path}")

        # Complement the config object here if necessary
        self._create(config)

        self._save()

    def _create_project(self, config):
        return ProjectExternalRepository(
            self.ctx,
            self.name,
            self.path,
            plugin_ref=self.plugin,
            subfolder=self.subfolder,
            cache=self.cache,
            cache_version=self.cache_version,
            inherited_config=self.inherited_config,
        )
