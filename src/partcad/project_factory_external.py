#
# PartCAD, 2025
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.
#

import ast
import hashlib
import os
import threading
import weakref

from . import logging as pc_logging
from . import project_factory as pf
from . import telemetry
from .cache import Cache
from .project import Project
from .project_external_repository import ProjectExternalRepository
from .utils import resolve_resource_path

# The module-level name a repository plugin states its cache version with.
CACHE_VERSION_NAME = "CACHE_VERSION"

# One answer per plugin reference, per context. The root of a plugin-backed
# hierarchy is created before its children and resolves the number first, so
# every child of it reads the same answer here even if the package that hosts
# the plugin is no longer reachable by the time the child is built. Without that
# the children would compute a different namespace from the root's and stop
# sharing its cache.
#
# Per context and not per process: a daemon keeps a context warm for as long as
# it runs, and a memo that outlived the context would go on reporting a version
# the script no longer states. A context is dropped when its files change, and
# this goes with it.
_declared_versions: "weakref.WeakKeyDictionary[object, dict[str, int]]" = weakref.WeakKeyDictionary()
_declared_versions_lock = threading.Lock()


def _read_declared_cache_version(ctx, parent: Project, plugin_ref: str) -> int:
    """The cache version the plugin states in its own code, or 0 if it states none.

    The number says when the plugin's answers stopped meaning what they used to
    mean. It belongs to the plugin and to nobody else: a package that imports a
    plugin-backed library has no way of knowing that the library now serves its
    parts the other way up, and should not have to be told. So this is read out
    of the plugin, not out of the configuration of whoever imports it.

    It is *read* rather than asked for, because the answer is needed before the
    first question can be asked: it names both the cache the answers are kept in
    and the directory the plugin's own files are materialized into. The script is
    parsed, never executed - a module-level 'CACHE_VERSION = <int>' and nothing
    else. A repository with no script of its own (an 'enrich' one, which rewrites
    another repository's answers) has no code to version and gets 0.
    """
    package_name, repository_name = resolve_resource_path(parent.name, plugin_ref)
    # The plugin almost always lives in the package that declares the dependency
    # ('plugin: :name'), and that package is 'parent' - which is loaded, because
    # it is what is being imported from. Reach for any other one only if asked.
    source = parent if package_name == parent.name else ctx.get_project(package_name)
    if source is None:
        pc_logging.debug("Cannot version the plugin cache: package not loaded: %s" % package_name)
        return 0

    config = (source.config_obj.get("repositories") or {}).get(repository_name)
    if not isinstance(config, dict) or not config.get("path"):
        return 0
    path = os.path.join(source.config_dir, config["path"])

    try:
        with open(path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=path)
    except (OSError, SyntaxError, ValueError) as e:
        pc_logging.debug("Cannot version the plugin cache: %s: %s" % (path, e))
        return 0

    for node in tree.body:
        if isinstance(node, ast.AnnAssign):
            targets = [node.target]
        elif isinstance(node, ast.Assign):
            targets = node.targets
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == CACHE_VERSION_NAME for t in targets):
            continue
        value = node.value
        # 'bool' is an 'int' and 'CACHE_VERSION = True' is a typo, not a version.
        if isinstance(value, ast.Constant) and isinstance(value.value, int) and not isinstance(value.value, bool):
            return value.value
        pc_logging.error("%s: %s must be an integer literal" % (path, CACHE_VERSION_NAME))
        return 0
    return 0


def declared_cache_version(ctx, parent: Project, plugin_ref: str) -> int:
    """'_read_declared_cache_version', once per plugin reference per context."""
    with _declared_versions_lock:
        known = _declared_versions.setdefault(ctx, {})
        if plugin_ref in known:
            return known[plugin_ref]
    version = _read_declared_cache_version(ctx, parent, plugin_ref)
    with _declared_versions_lock:
        return known.setdefault(plugin_ref, version)


class ExternalImportConfiguration:
    def __init__(self):
        self.plugin = self.config_obj.get("plugin", ":plugin")
        # A child of a plugin-backed hierarchy carries the subfolder that scopes
        # its requests within the repository. Empty for a top-level package.
        self.subfolder = self.config_obj.get("subfolder", "")
        # 'cacheVersion' used to be declared here, by whoever imported the
        # plugin. Said by name, because an unknown key is otherwise refused
        # without saying which one it was or what replaced it.
        #
        # A warning and not an error: the package that still carries one is
        # somebody else's, published before this changed, and whoever runs into
        # it is usually in no position to fix it. Failing their command over it
        # would make one unmigrated dependency anywhere in the tree the end of
        # every command that reaches it.
        if "cacheVersion" in self.config_obj:
            pc_logging.warning(
                "'cacheVersion' is no longer a property of a dependency and is ignored here: "
                "a plugin states it itself, as a module-level '%s = <int>' in its own script." % CACHE_VERSION_NAME
            )


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
        # version the plugin states in its own code is folded in too, so raising
        # it moves this repository and every child of it to a fresh cache
        # namespace at once.
        self.cache_version = declared_cache_version(ctx, parent, self.plugin)
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
            inherited_config=self.inherited_config,
        )
