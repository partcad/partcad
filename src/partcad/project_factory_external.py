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
from .cache_hash import file_stat
from .project import Project
from .project_external_repository import ProjectExternalRepository
from .utils import resolve_resource_path

# The module-level name a repository plugin states its cache version with.
CACHE_VERSION_NAME = "CACHE_VERSION"

# One answer per plugin reference, per context: '(script path, its stat,
# version)'. The root of a plugin-backed hierarchy is created before its
# children and resolves the number first, so every child of it reads the same
# answer here without resolving anything - it need only stat the path the root
# found, and re-read *that* path if it has moved on. Without this the children
# would compute a different namespace from the root's and stop sharing its
# cache. Only a script that was found is remembered; see 'declared_cache_version'.
#
# Guarded by a stat rather than held outright, because a daemon keeps a context
# warm for as long as it runs and edits the packages under it in place: a memo
# that only remembered the number would go on reporting a version the script had
# stopped stating. 'Context.reload_changed_packages()' drops the *packages*
# whose configuration changed and keeps the context, so waiting for the context
# to go would be waiting for something that does not happen.
#
# A plugin-backed package is deliberately not one of the packages that reload
# looks at - it has no file to stat, and asking its repository is a round trip.
# The plugin's own script does have a file, and this is where it is watched.
_declared_versions: "weakref.WeakKeyDictionary[object, dict[str, tuple]]" = weakref.WeakKeyDictionary()
_declared_versions_lock = threading.Lock()


def _locate_plugin_script(ctx, parent: Project, plugin_ref: str):
    """The file the repository plugin is written in, or None.

    None when the repository names no script - an 'enrich' one, which rewrites
    another repository's answers, has no code of its own - or when the package
    that hosts it is not loaded.
    """
    package_name, repository_name = resolve_resource_path(parent.name, plugin_ref)
    # The plugin almost always lives in the package that declares the dependency
    # ('plugin: :name'), and that package is 'parent' - which is loaded, because
    # it is what is being imported from. Reach for any other one only if asked.
    source = parent if package_name == parent.name else ctx.get_project(package_name)
    if source is None:
        pc_logging.debug("Cannot version the plugin cache: package not loaded: %s" % package_name)
        return None

    config = (source.config_obj.get("repositories") or {}).get(repository_name)
    if not isinstance(config, dict) or not config.get("path"):
        return None
    return os.path.join(source.config_dir, config["path"])


def _read_declared_cache_version(path: str) -> int:
    """The cache version the script states, or 0 if it states none.

    The number says when the plugin's answers stopped meaning what they used to
    mean. It belongs to the plugin and to nobody else: a package that imports a
    plugin-backed library has no way of knowing that the library now serves its
    parts the other way up, and should not have to be told. So this is read out
    of the plugin, not out of the configuration of whoever imports it.

    It is *read* rather than asked for, because the answer is needed before the
    first question can be asked: it names both the cache the answers are kept in
    and the directory the plugin's own files are materialized into. The script is
    parsed, never executed - a module-level 'CACHE_VERSION = <int>' and nothing
    else.
    """
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
    """The version the plugin states, read once per reference per context.

    Read again when the script has changed, so that a daemon holding a context
    open does not hold an answer the script has withdrawn - but re-read from the
    path already found, never by resolving one again through whoever is asking.
    Only the root of a hierarchy can resolve it; a child asks with its own parent
    and would come back empty, and writing that back would leave every later
    lookup, the root's included, reading 0 from a plugin that states a version.

    For the same reason a failure to locate the script is not remembered: there
    is nothing to stat, so the entry could never expire, and the first caller
    that happened not to see the package would settle the answer for the rest.
    """
    with _declared_versions_lock:
        known = _declared_versions.setdefault(ctx, {})
        entry = known.get(plugin_ref)
    if entry is not None:
        path, stat, version = entry
        if file_stat(path) != stat:
            version = _read_declared_cache_version(path)
        else:
            return version
    else:
        path = _locate_plugin_script(ctx, parent, plugin_ref)
        if path is None:
            return 0
        version = _read_declared_cache_version(path)
    with _declared_versions_lock:
        known[plugin_ref] = (path, file_stat(path), version)
    return version


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
