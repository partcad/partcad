#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.

import asyncio
import os
import sys
import time
import socket
import threading
from typing import Optional, Any

from .cache import Cache
from .cache_shape import ShapeCache
from . import consts
from . import logging as pc_logging
from .mating import Mating
from . import output
from . import runtime_javascript_all
from . import runtime_python_all
from . import sandbox_versions
from . import tags as pc_tags
from . import project_factory_local as rfl
from . import project_factory_git as rfg
from . import project_factory_tar as rft
from . import project_factory_external as rfe
from .sync_threads import threadpool_manager
from .user_config import UserConfig
from .utils import *
from .part import Part
from .project import Project
from .plugin_request_provider_quote import ProviderRequestQuote
from .plugin_provider_data_cart import *
from . import telemetry
from .test.all import tests as all_tests


def param_getters(attr_name: str):
    if attr_name == "import_project":

        def import_project_attr_getter(*args, **_kwargs):
            return {"package_name": args[2]["name"]}

        return import_project_attr_getter
    return lambda *_args, **_kwargs: {}


# Context
@telemetry.instrument(attr_getters=param_getters)
class Context:
    """Stores and caches all imported objects.

    Note that this class deliberately does not derive from 'Configuration'.
    It used to, for a single reason: 'Configuration' parsed 'partcad.yaml' and
    thus knew how to pick up the root package's 'name' override. Now that
    configuration parsing lives in 'ProjectLocal', there is nothing left to
    inherit - the context is not a package and has no configuration file of its
    own. It holds the root package in 'self.root' and adopts its name instead.
    """

    stats_packages: int
    stats_packages_instantiated: int
    stats_sketches: int
    stats_sketches_instantiated: int
    stats_interfaces: int
    stats_interfaces_instantiated: int
    stats_parts: int
    stats_parts_instantiated: int
    stats_assemblies: int
    stats_assemblies_instantiated: int
    stats_plugins: int
    stats_plugin_queries: int
    stats_providers: int
    stats_repositories: int
    stats_memory: int
    stats_git_ops: int

    # name is the package path (not a filesystem path) of the root package
    # in case it's configured to be something other than '//' (default)
    name: str

    # root_path is the absolute filesystem path to the root package (for monorepo's)
    root_path: str

    # root is the root package itself. It is None if it failed to load.
    root: Optional[Project]

    # current_project_path is the package path (not a filesystem path) of the current package
    # It is expected to match 'self.name' of the current package's object
    current_project_path: str

    mates: dict[str, dict[str, Mating]]

    # The tags true of this context: what this machine is (architecture,
    # operating system, that system's version) plus whatever the user
    # configuration adds. A package or an object may name the tags it does not
    # work under ('unless'), and is skipped where one of them is in here.
    tags: set[str]

    class PackageLock(object):
        def __init__(self, ctx, package_name: str):
            ctx.project_locks_lock.acquire()
            if not package_name in ctx.project_locks:
                ctx.project_locks[package_name] = threading.Lock()
            self.lock = ctx.project_locks[package_name]
            ctx.project_locks_lock.release()

        def __enter__(self, *_args):
            self.lock.acquire()

        def __exit__(self, *_args):
            self.lock.release()

    def _check_connectivity(self):
        try:
            socket.create_connection(("8.8.8.8", 53), timeout=3.0)
            return True
        except OSError:
            pc_logging.warning("No internet connection. Running in offline mode")
            return False

    def is_connected(self):
        if self.user_config.offline:
            return False

        now = time.time()
        # Use cached state if available and force_update is not set
        if not self.user_config.force_update and self.connection_status:
            # Set the expected time-to-live(ttl) to 60s for online(connected) and 300s for offline(disconnected)
            ttl = 60 if self.connection_status["is_connected"] else 300

            # Check if cached data has exceeded its ttl
            # If not, return the cached value
            if now - self.connection_status["last_checked"] <= ttl:
                return self.connection_status["is_connected"]

        # Check internet connection and update state
        connected = self._check_connectivity()
        self.connection_status = dict(last_checked=now, is_connected=connected)

        return connected

    def __init__(self, root_path=None, search_root=True, user_config=UserConfig()):
        """Initializes the context and loads the root project."""
        # Protect the critical sections from access in different threads
        self.lock = threading.RLock()

        self.option_create_dirs = False
        self.runtimes_python = {}
        self.runtimes_python_lock = threading.Lock()
        # Python versions already reported as held down to MAX_PYTHON_VERSION_CAD,
        # so the warning is said once rather than once per part.
        self.python_versions_held = set()
        self.runtimes_javascript = {}
        self.runtimes_javascript_lock = threading.Lock()

        self.stats_packages = 0
        self.stats_packages_instantiated = 0
        self.stats_interfaces = 0
        self.stats_interfaces_instantiated = 0
        self.stats_sketches = 0
        self.stats_sketches_instantiated = 0
        self.stats_parts = 0
        self.stats_parts_instantiated = 0
        self.stats_assemblies = 0
        self.stats_assemblies_instantiated = 0
        self.stats_plugins = 0
        self.stats_plugin_queries = 0
        self.stats_providers = 0
        self.stats_repositories = 0
        self.stats_memory = 0
        self.stats_git_ops = 0

        self.mates = {}
        # self.projects contains all projects known to this context
        self.projects = {}
        self.project_locks = {}
        self.project_locks_lock = threading.Lock()
        self._projects_being_loaded = {}
        self.user_config = user_config

        # Computed once, here, rather than per package: every 'unless' in the
        # whole package graph is answered against the same set, and the answer
        # cannot change while the context lives.
        self.tags = pc_tags.context_tags(user_config)

        self.cache_shapes = ShapeCache(user_config=self.user_config)
        self.cache_tests = Cache("tests", user_config=self.user_config)
        self.cache_lints = Cache("lints", user_config=self.user_config)

        self.connection_status = {}

        root_file = ""
        if root_path is None:
            # Find the top folder containing "partcad.yaml"
            root_path = "."
        else:
            if os.path.isfile(root_path):
                root_file = os.path.basename(root_path)
                root_path = os.path.dirname(root_path)
        initial_root_path = os.path.abspath(root_path)
        if search_root:
            while os.path.exists(os.path.join(root_path, "..", "partcad.yaml")):
                root_path = os.path.join(root_path, "..")
        self.root_path = os.path.abspath(root_path)
        if self.root_path == initial_root_path and root_file != "":
            self.root_path = os.path.join(self.root_path, root_file)

        self.path = os.path.abspath(root_path)
        # 'config_dir' is not read from a configuration file here (the context
        # has none), but 'ProjectFactory' expects it on the parent-less path.
        self.config_dir = self.path

        # 'initial_root_path' and 'search_root_path' are kept around because
        # 'current_project_path' can only be computed once the root package's
        # name is known, which is not until the root package has been loaded.
        # Both are stored absolute: 'os.path.relpath()' resolves a relative
        # argument against the current working directory, which would make
        # '_recompute_current_project_path()' depend on where it is called from.
        self._initial_root_path = initial_root_path
        self._search_root_path = os.path.abspath(root_path)

        # The root package's name is whatever its 'partcad.yaml' says it is, so
        # it is unknown until that package is loaded, and the package cannot be
        # loaded without a name to key it by. Break the cycle by loading it
        # under the default name and adopting the real one afterwards.
        # 'import_project()' performs the adoption, because it has to happen
        # before anything else can observe these two attributes.
        self.name = consts.ROOT
        self.current_project_path = consts.ROOT

        # The version is on this line because it is the first thing logged in
        # every run, and the first question asked of any report ("which PartCAD
        # is that?"). Read through sys.modules, as elsewhere in the package: this
        # module is imported by 'partcad/__init__.py', so it cannot import
        # '__version__' from it at module scope.
        version = sys.modules["partcad"].__version__
        with pc_logging.Process("InitCtx", self.config_dir, "v%s" % version):
            self.root = self.import_project(
                None,  # parent
                {
                    "name": consts.ROOT,
                    "type": "local",
                    "path": self.root_path,
                    "canBeEmpty": True,
                    "isRoot": True,
                },
            )
            if self.root is None:
                # Leave the provisional name in place. 'get_project()' returns
                # None for every lookup in that state, which is how a failed
                # root load has always been reported.
                pc_logging.error("Failed to load the root package: %s" % self.root_path)

    def _recompute_current_project_path(self):
        """Derives 'current_project_path' from the (possibly adopted) root name.

        Must be called whenever 'self.name' changes: 'current_project_path' is
        the root package's name followed by the relative path from the root
        package to the directory this context was created for.
        """
        current_project_path = self.name
        if not current_project_path.endswith("/"):
            current_project_path += "/"
        current_project_path += os.path.relpath(
            self._initial_root_path,
            self._search_root_path,
        ).replace(os.path.sep, "/")
        if current_project_path == self.name + "/." or (
            self.name.endswith("/") and current_project_path == self.name + "."
        ):
            current_project_path = self.name
        self.current_project_path = current_project_path

    def stats_recalc(self, verbose=False):
        self.stats_memory = total_size(self, verbose)

    def get_current_project_path(self):
        p = self.current_project_path
        while len(p) > 1 and not (len(p) == 2 and p == "//") and p.endswith("/"):
            p = p[:-1]
        return p

    def import_project(self, parent, project_import_config):
        pc_logging.debug("Importing project: %s" % project_import_config)
        if "name" not in project_import_config or "type" not in project_import_config:
            pc_logging.error("Invalid project configuration found: %s" % project_import_config)
            return None

        name = project_import_config["name"]
        with self.PackageLock(self, name):
            if name in self.projects:
                return self.projects[name]

            with pc_logging.Action("Import", name):
                if name in self._projects_being_loaded:
                    pc_logging.error("Recursive project loading detected (%s), aborting." % name)
                    return None
                self._projects_being_loaded[name] = True

                # Depending on the project type, use different factories
                if "type" not in project_import_config or project_import_config["type"] == "local":
                    with pc_logging.Action("Local", name):
                        rfl.ProjectFactoryLocal(self, parent, project_import_config)
                        pc_logging.debug("Local project loaded: %s" % name)
                elif project_import_config["type"] == "git":
                    with pc_logging.Action("Git", name):
                        rfg.ProjectFactoryGit(self, parent, project_import_config)
                elif project_import_config["type"] == "tar":
                    with pc_logging.Action("Tar", name):
                        rft.ProjectFactoryTar(self, parent, project_import_config)
                elif project_import_config["type"] == "external":
                    with pc_logging.Action("External", name):
                        rfe.ProjectFactoryExternal(self, parent, project_import_config)
                else:
                    pc_logging.error("Invalid project type found: %s." % name)
                    del self._projects_being_loaded[name]
                    return None

                # Check whether the factory was able to successfully add the project
                if name not in self.projects:
                    pc_logging.error("Failed to create the project: %s" % project_import_config)
                    del self._projects_being_loaded[name]
                    return None

                imported_project = self.projects[name]
                if imported_project is None:
                    pc_logging.error("Failed to import the package: %s" % name)
                    del self._projects_being_loaded[name]
                    return None
                if imported_project.broken:
                    pc_logging.error("Failed to parse the package's 'partcad.yaml': %s" % name)

                # A package is addressed by where it was loaded, never by the
                # name it declares for itself: the same package vendored into
                # two different locations is two independent instances, each
                # reachable at its own path. 'Configuration' therefore forces
                # 'name' to the location for every package but the root, which
                # has no location to be derived from and so adopts the name it
                # declares. Re-key that one.
                if imported_project.name != name:
                    assert name == consts.ROOT, "Only the root package may adopt its declared name"
                    self.projects[imported_project.name] = self.projects.pop(name)

                if project_import_config.get("isRoot", False):
                    # Adopt the root package's name before returning: the
                    # context's own name and 'current_project_path' are derived
                    # from it, and everything downstream resolves against them.
                    self.name = imported_project.name
                    self._recompute_current_project_path()

                self.stats_packages += 1
                self.stats_packages_instantiated += 1

                del self._projects_being_loaded[name]
                return imported_project

    def resolve_package_path(self, package: str):
        """ "
        Get the absolute path to the package.
        """
        if package is None:
            return self.get_current_project_path()

        # Remove trailing slashes, except the initial two
        while len(package) > 1 and not package == "//" and package.endswith("/"):
            package = package[:-1]

        # If package is the root package, return the root package path (can be a longer absolute path)
        if package == "/" or package == "//":
            return self.name

        # If package is empty or the explicit reference to the current package, return current package
        if package == "" or package == ".":
            return self.get_current_project_path()

        # Make it absolute
        if not package.startswith("/"):
            package = self.get_current_project_path() + "/" + package

        # For backward compatibility '/' -> '//'
        if package.startswith("/") and not package.startswith("//"):
            pc_logging.warning(f"{package}: using '/' as the root package path is deprecated. Use '//' instead.")
            package = "/" + package

        return package

    def get_project_abs_path(self, rel_project_path: str):
        """
        Get the full package path (not a filesystem path) of a package
        given the relative path from the current package
        """
        if rel_project_path.startswith("//"):
            return rel_project_path

        project_path = self.current_project_path

        if rel_project_path == ".":
            rel_project_path = ""
        if rel_project_path == "":
            return project_path

        return get_child_project_path(project_path, rel_project_path)

    def _get_builtin_project(self, project_path: str) -> Optional[Project]:
        """Load one of the packages that ship inside 'partcad' itself.

        '//builtin' and its children are not reachable the way every other
        package is: they have no place in the root package's directory tree and
        nothing depends on them, yet they have to resolve in every context,
        whatever the root package is called. They are therefore loaded on demand
        straight from the 'partcad' installation, and only when something asks
        for them - a context that never writes an output file never pays for it.

        Returns None for any other path, which is what makes this safe to call
        on the way into 'get_project()'.
        """
        path = output.BUILTIN_PATHS.get(project_path)
        if path is None:
            return None
        if project_path in self.projects:
            return self.projects[project_path]
        return self.import_project(
            None,  # parent: there is nothing above '//builtin'
            {
                "name": project_path,
                "type": "local",
                "path": path,
            },
        )

    def get_project(self, rel_project_path: str) -> Optional[Project]:
        project_path = self.get_project_abs_path(rel_project_path)

        builtin_project = self._get_builtin_project(project_path)
        if builtin_project is not None:
            return builtin_project

        with self.lock:
            # Check if it's an explicit reference outside of the root project
            if not project_path.startswith(self.name):
                pc_logging.debug("Project path is outside of the root project: %s" % project_path)
                # In case of an explicit reference outside of the root project,
                # assume that the root package has an 'onlyInRoot' dependency
                # present to facilitate such a reference in a standalone
                # development environment.

            # Strip the first '//' (absolute path always starts with a '//'``)
            if self.name != "//" and project_path.startswith(self.name):
                # The root package is not '//', need to skip the root package name
                len_to_skip = len(self.name) + 1
            else:
                len_to_skip = 2
            project_path = project_path[len_to_skip:]

            if self.name not in self.projects:
                return None
            project = self.projects[self.name]

            if project_path == "":
                return project
            else:
                import_list = project_path.split("/")

            return self._get_project_recursive(project, import_list)

    def _get_project_recursive(self, project, import_list: list[str]):
        """Load the dependencies recursively"""
        if len(import_list) == 0:
            # Found what we are looking for
            return project

        # A skipped package is still addressable - it resolves, empty, above -
        # but nothing below it is. Skipping a package means skipping what it
        # brings in, and a child reached through it would otherwise load as if
        # its parent had never opted out.
        if project.skipped:
            return None

        # next_import is the next of the import we need to load now
        next_import = import_list[0]
        # import_list is reduced to contain only the items that will remain to
        # bt loaded after this import
        import_list = import_list[1:]

        # next_project will reference the project we are importing now
        next_project = None
        # next_project_path is the full path of the project we are importing now
        next_project_path = get_child_project_path(project.name, next_import)

        # see if the wanted project is already initialized
        if next_project_path in self.projects:
            return self._get_project_recursive(self.projects[next_project_path], import_list)

        # Check if there is a matching subfolder
        subfolders = [f.name for f in os.scandir(project.config_dir) if f.is_dir()]
        if next_import in list(subfolders):
            if os.path.exists(
                os.path.join(
                    project.config_dir,
                    next_import,
                    consts.DEFAULT_PACKAGE_CONFIG,
                )
            ):
                pc_logging.debug("Importing a subfolder (get): %s..." % next_project_path)
                prj_conf = {
                    "name": next_project_path,
                    "type": "local",
                    "path": next_import,
                }
                next_project = self.import_project(project, prj_conf)
                if not next_project is None:
                    result = self._get_project_recursive(next_project, import_list)
                    return result
        else:
            # Resolve a declared child dependency. Go through the 'dependencies()'
            # accessor rather than 'config_obj' directly so that a plugin-backed
            # package's children - reported by its repository instead of a
            # 'dependencies' section on disk - are resolvable here too.
            dependencies = project.dependencies()
            if dependencies:
                for prj_name in dependencies:
                    pc_logging.debug(f"Checking the dependency: {prj_name} vs {next_import}...")
                    if prj_name != next_import:
                        continue
                    prj_conf = dependencies[prj_name]
                    if prj_conf.get("onlyInRoot", False):
                        next_project_path = "//" + prj_name
                    pc_logging.debug(f"Loading the dependency: {next_project_path}...")
                    if "name" in prj_conf:
                        prj_conf["orig_name"] = prj_conf["name"]
                    prj_conf["name"] = next_project_path
                    next_project = self.import_project(project, prj_conf)
                    if not next_project is None:
                        result = self._get_project_recursive(next_project, import_list)
                        return result
                    break

        return next_project

    def import_all(self, parent_name=None):
        if parent_name is None:
            parent_name = self.name
        asyncio.run(self._import_all_wrapper(self.projects[parent_name]))

    async def _import_all_wrapper(self, project):
        iterate_tasks = []
        import_tasks = []

        iterate_tasks.append(asyncio.create_task(self._import_all_recursive(project)))

        while iterate_tasks or import_tasks:
            if iterate_tasks:
                iterate_done, iterate_tasks_set = await asyncio.tasks.wait(iterate_tasks)
                iterate_tasks = list(iterate_tasks_set)
                for iterate_task in iterate_done:
                    new_import_tasks = iterate_task.result()
                    import_tasks.extend(new_import_tasks)

            if import_tasks:
                import_done, import_tasks_set = await asyncio.tasks.wait(import_tasks)
                import_tasks = list(import_tasks_set)
                for import_task in import_done:
                    next_project = import_task.result()
                    iterate_tasks.append(asyncio.create_task(self._import_all_recursive(next_project)))

    async def _import_all_recursive(self, project):
        tasks = []

        if project.broken:
            pc_logging.warn("Ignoring the broken package: %s" % project.name)
            return []

        # A plugin-backed package is enumerated here, inside the async traversal,
        # so that the synchronous consumers downstream (e.g. get_packages, the
        # CLI 'list' commands) observe a populated package without having to
        # bridge to async themselves.
        await project.ensure_enumerated_async()

        # Nothing under a skipped package is imported either. The package itself
        # already said why, once, when it was loaded. Checked after the
        # enumeration above rather than before it, because that is where a
        # plugin-backed package's 'unless' arrives from: its configuration comes
        # over the wire, not from a file the constructor could read.
        if project.skipped:
            return []

        # First, iterate all explicitly mentioned "dependencies"s.
        # Do it before iterating subdirectories, as it may kick off a long
        # background task. 'dependencies()' is an accessor so that a plugin
        # package can report its children from the repository.
        all_dependencies = project.dependencies()
        if all_dependencies:
            dependencies = all_dependencies
            pc_logging.debug("Checking the dependency: %s...(1)" % project.name)
            if not project.config_obj.get("isRoot", False):
                filtered = filter(
                    lambda x: "onlyInRoot" not in dependencies[x] or not dependencies[x]["onlyInRoot"],
                    dependencies,
                )
                dependencies = list(filtered)

            for prj_name in dependencies:
                prj_conf = all_dependencies[prj_name]
                pc_logging.debug("Checking the dependency: %s...." % prj_name)

                if prj_conf.get("onlyInRoot", False):
                    next_project_path = "//" + prj_name
                else:
                    next_project_path = get_child_project_path(project.name, prj_name)
                if next_project_path == self.name:
                    # Avoid circular dependencies of the root package
                    # TODO(clairbee): fix circular dependencies in general
                    continue
                pc_logging.debug("Importing: %s..." % next_project_path)

                if "name" in prj_conf:
                    prj_conf["orig_name"] = prj_conf["name"]
                prj_conf["name"] = next_project_path

                tasks.append(asyncio.create_task(threadpool_manager.run(self.import_project, project, prj_conf)))

        # Second, iterate over all subfolder and check for packages. A
        # plugin-backed package has no directory on disk, so there is nothing to
        # scan; its children came from 'dependencies()' above.
        subfolders = (
            [f.name for f in os.scandir(project.config_dir) if f.is_dir()] if os.path.isdir(project.config_dir) else []
        )
        for subdir in list(subfolders):
            if os.path.exists(
                os.path.join(
                    project.config_dir,
                    subdir,
                    consts.DEFAULT_PACKAGE_CONFIG,
                )
            ):
                # TODO(clairbee): check if this subdir is already imported
                next_project_path = get_child_project_path(project.name, subdir)

                # Here, we do not jump over the projects that are already imported,
                # because we want to import all sub-folders, even if their parent
                # is already imported.

                pc_logging.debug("Importing a subfolder (import all): %s..." % next_project_path)
                prj_conf = {
                    "name": next_project_path,
                    "type": "local",
                    "path": subdir,
                }

                tasks.append(asyncio.create_task(threadpool_manager.run(self.import_project, project, prj_conf)))

        return tasks

    def get_all_packages(self, parent_name=None, has_stuff: bool = True):
        # TODO(clairbee): leverage root_project.get_child_project_names()
        self.import_all(parent_name)
        return self.get_packages(parent_name=parent_name, has_stuff=has_stuff)

    def get_packages(self, parent_name: str = None, has_stuff: bool = True) -> list[dict[str, str]]:
        projects = self.projects.values()
        if parent_name is not None:
            projects = filter(lambda x: x.name.startswith(parent_name), projects)

        # Unconditionally, not only under 'has_stuff': a skipped package holds
        # no objects, so the filter below would drop it anyway, but a caller
        # that asks for the empty ones too (the interface listing does) is
        # asking for packages it can look inside - which this one is not.
        projects = filter(lambda x: not x.skipped, projects)

        if has_stuff:
            # Filter out projects that don't contain anything the user might be interested in.
            # TODO(clairbee): Add interfaces and providers to this list when the UIs are ready to display them
            # Count via the object accessors (enumeration) rather than the
            # instantiated dicts, so a plugin-backed package - which enumerates
            # lazily and does not instantiate up front - is counted correctly.
            projects = filter(
                lambda x: x.object_count("sketch") + x.object_count("part") + x.object_count("assembly") > 0,
                projects,
            )
        return list(
            map(
                lambda pkg: {"name": pkg.name, "desc": pkg.desc},
                projects,
            )
        )

    def add_mate(self, source_interface, target_interface, mate_target_config: dict):
        self._add_mate(
            source_interface,
            target_interface,
            mate_target_config,
            reverse=False,
        )
        if target_interface != source_interface:
            self._add_mate(
                target_interface,
                source_interface,
                mate_target_config,
                reverse=True,
            )

    def _add_mate(
        self,
        source_interface,
        target_interface,
        mate_target_config: dict[str, Any],
        reverse: bool,
    ):
        source_interface_name = source_interface.full_name
        target_interface_name = target_interface.full_name

        if not source_interface_name in self.mates:
            self.mates[source_interface_name] = {}
        if target_interface_name in self.mates[source_interface_name]:
            pc_logging.debug("Mate already exists: %s -> %s" % (source_interface_name, target_interface_name))
            # TODO(clairbee): identify discrepancies in mate_target_config
            return

        mate = Mating(source_interface, target_interface, mate_target_config, reverse)
        self.mates[source_interface_name][target_interface_name] = mate

    def get_mate(self, source_interface_name, target_interface_name) -> Mating | None:
        if not source_interface_name in self.mates:
            return None
        if not target_interface_name in self.mates[source_interface_name]:
            return None

        return self.mates[source_interface_name][target_interface_name]

    def find_mating_interfaces(self, source_shape, target_shape):
        source_interfaces = set(source_shape.with_ports.get_interfaces().keys())

        # compatible_source_interfaces is the list of all interfaces they are
        # compatible with (implement them and only them)
        compatible_source_interfaces = set(
            [
                compatible_interface
                for interface in source_interfaces
                for compatible_interface in self.get_interface(interface).compatible_with
            ]
        )

        # real_source_interfaces is the map of source interfaces to the set of
        # interfaces they are compatible with (including themselves). It's
        # called 'real', because it allows to perform a lookup of
        # the actual (real) source interface(s) which brought in the given
        # compatible interface.
        real_source_interfaces = {interface: set([interface]) for interface in source_interfaces}
        for interface in source_interfaces:
            for compatible_interface in self.get_interface(interface).compatible_with:
                if not compatible_interface in real_source_interfaces:
                    real_source_interfaces[compatible_interface] = set()
                real_source_interfaces[compatible_interface].add(interface)

        # Now, extend the source_interfaces to include all of the interfaces at
        # least one of the source interfaces is compatible with
        source_interfaces = source_interfaces.union(compatible_source_interfaces)
        pc_logging.debug("Source interfaces: %s" % source_interfaces)

        # Now do the same for the target interfaces
        target_interfaces = set(target_shape.with_ports.get_interfaces().keys())
        compatible_target_interfaces = set(
            [
                compatible_interface
                for interface in target_interfaces
                for compatible_interface in self.get_interface(interface).compatible_with
            ]
        )
        real_target_interfaces = {interface: set([interface]) for interface in target_interfaces}
        for interface in target_interfaces:
            for compatible_interface in self.get_interface(interface).compatible_with:
                if not compatible_interface in real_target_interfaces:
                    real_target_interfaces[compatible_interface] = set()
                real_target_interfaces[compatible_interface].add(interface)
        target_interfaces = target_interfaces.union(compatible_target_interfaces)
        pc_logging.debug("Target interfaces: %s" % target_interfaces)

        source_interfaces_mates = set(
            [
                peer_interface
                for source_interface in source_interfaces
                for peer_interface in self.mates.get(source_interface, {}).keys()
            ]
        )
        target_interfaces_mates = set(
            [
                peer_interface
                for target_interface in target_interfaces
                for peer_interface in self.mates.get(target_interface, {}).keys()
            ]
        )
        source_candidate_interfaces = source_interfaces.intersection(target_interfaces_mates)
        real_source_candidate_interfaces = set()
        for source_interface in source_candidate_interfaces:
            real_source_candidate_interfaces = real_source_candidate_interfaces.union(
                real_source_interfaces[source_interface]
            )
        source_candidate_interfaces = real_source_candidate_interfaces
        pc_logging.debug("Source candidate interfaces: %s" % source_candidate_interfaces)

        target_candidate_interfaces = target_interfaces.intersection(source_interfaces_mates)
        real_target_candidate_interfaces = set()
        for target_interface in target_candidate_interfaces:
            real_target_candidate_interfaces = real_target_candidate_interfaces.union(
                real_target_interfaces[target_interface]
            )
        target_candidate_interfaces = real_target_candidate_interfaces
        pc_logging.debug("Target candidate interfaces: %s" % target_candidate_interfaces)

        return source_candidate_interfaces, target_candidate_interfaces

    def _get_sketch(self, sketch_spec, params=None):
        project_name, sketch_name = resolve_resource_path(
            self.current_project_path,
            sketch_spec,
        )
        prj = self.get_project(project_name)
        if prj is None:
            pc_logging.error("Package %s not found" % project_name)
            pc_logging.error("Packages found: %s" % str(self.projects))
            return None
        pc_logging.debug("Retrieving %s from %s" % (sketch_name, project_name))
        return prj.get_sketch(sketch_name, params)

    def get_sketch(self, sketch_spec, params=None):
        return self._get_sketch(sketch_spec, params)

    def get_sketch_shape(self, sketch_spec, params=None):
        return asyncio.run(self._get_sketch(sketch_spec, params).get_wrapped(self))

    def convert_sketch(self, sketch_spec, part_type, params=None, **kwargs):
        """Convert the sketch to 'part_type' and return the result in memory.

        See 'Shape.convert()' for the supported part types and return types.
        """
        return asyncio.run(self._get_sketch(sketch_spec, params).convert(part_type, self, **kwargs))

    def get_sketch_cadquery(self, sketch_spec, params=None):
        """Thin alias for convert_sketch(sketch_spec, "cadquery", params)."""
        return self.convert_sketch(sketch_spec, "cadquery", params)

    def get_sketch_build123d(self, sketch_spec, params=None):
        """Thin alias for convert_sketch(sketch_spec, "build123d", params)."""
        return self.convert_sketch(sketch_spec, "build123d", params)

    def _get_interface(self, interface_spec):
        project_name, interface_name = resolve_resource_path(
            self.current_project_path,
            interface_spec,
        )
        prj = self.get_project(project_name)
        if prj is None:
            pc_logging.error("Package %s not found" % project_name)
            pc_logging.error("Packages found: %s" % str(self.projects))
            return None
        pc_logging.debug("Retrieving %s from %s" % (interface_name, project_name))
        return prj.get_interface(interface_name)

    def get_interface(self, interface_spec):
        return self._get_interface(interface_spec)

    def get_interface_shape(self, interface_spec):
        return asyncio.run(self._get_interface(interface_spec).get_wrapped(self))

    async def find_suppliers(self, cart: ProviderCart) -> dict[str, list[str]]:
        """Find suppliers for each of the parts in the cart"""
        suppliers = {}
        for name, part_spec in cart.parts.items():
            suppliers_per_part = await self.find_part_suppliers(part_spec, cart)

            if not suppliers_per_part:
                pc_logging.error(f"No supplier found for {name}")

            suppliers[name] = suppliers_per_part

        # TODO(clairbee): calculate the recommended suppliers and reorder the results accordingly
        return suppliers

    async def find_part_suppliers(self, part_item: ProviderCartItem, cart: ProviderCart = None) -> dict[str, list[str]]:
        """Find suppliers for a specific part. Optionally, use a cart for requirements and preferences.

        Args:
            part_spec (ProviderCartItem): The part to find suppliers for.
            cart (ProviderCart, optional): Use this cart for requirements and preferences. Defaults to None.

        Returns:
            list[str]: list of provider names that can supply the part.
        """
        providers = []

        project_name, part_name = resolve_resource_path(
            self.current_project_path,
            part_item.name,
        )
        prj = self.get_project(project_name)
        if prj is None:
            pc_logging.error("Package %s not found" % project_name)
            pc_logging.error("Packages found: %s" % str(self.projects))
            return {}
        pc_logging.debug("Retrieving suppliers from %s" % project_name)

        part_suppliers = prj.get_suppliers()
        if len(part_suppliers) == 0:
            pc_logging.error("No suppliers found for %s in %s" % (part_name, project_name))
            return {}
        else:
            pc_logging.debug("Part suppliers: %s" % str(part_suppliers))

        pc_logging.debug("Part: %s" % str(part_item))
        for provider_name, provider_extra_config in part_suppliers.items():
            provider = self.get_provider(provider_name, provider_extra_config)
            if not await provider.is_part_available(part_item):
                continue
            if cart and cart.qos is not None and not provider.is_qos_available(cart.qos):
                continue

            providers.append(provider_name)

        return providers

    def select_preferred_supplier(self, suppliers: list[str]):
        """From a list of suppliers, select the preferred one."""
        return suppliers[0]

    def select_preferred_suppliers(self, suppliers_per_part: dict[str, list[str]]) -> dict[str, str]:
        """Given a list of suppliers per part, select the preferred supplier for each."""
        preferred_suppliers = {}
        for name, suppliers in suppliers_per_part.items():
            supplier = self.select_preferred_supplier(suppliers)
            preferred_suppliers[name] = supplier

        return preferred_suppliers

    async def select_supplier(self, provider, cart: ProviderCart) -> dict[str, str]:
        """Given a specific provider, confirm it can provide all the parts."""
        if cart.qos is not None and not provider.is_qos_available(cart.qos):
            pc_logging.error(f"QoS {cart.qos} is not available from {provider}")
            return
        suppliers = {}
        tasks = []

        async def _set_supplier(name, cart_item):
            if not await provider.is_part_available(cart_item):
                pc_logging.error("Part %s is not available from %s" % (name, provider.name))
                suppliers[str(cart_item)] = ""
            else:
                pc_logging.debug("Cart item: %s" % str(cart_item))
                suppliers[str(cart_item)] = provider.name

        for name, cart_item in cart.parts.items():
            tasks.append(asyncio.create_task(_set_supplier(name, cart_item)))
        await asyncio.gather(*tasks)

        return suppliers

    async def prepare_supplier_carts(self, preferred_suppliers: dict[str, str]) -> dict[str, ProviderCart]:
        """Given the list of preferred suppliers, prepare the supplier carts."""
        supplier_carts: dict[str, ProviderCart] = {}

        # Create a supplier cart for each supplier
        provider_names = set(preferred_suppliers.values())
        for provider_name in provider_names:
            supplier_carts[provider_name] = ProviderCart()

        # Place each part in the corresponding supplier cart
        for part_spec, provider_name in preferred_suppliers.items():
            if not provider_name in supplier_carts:
                supplier_carts[provider_name] = ProviderCart()
            cart_item = await supplier_carts[provider_name].add_part_spec(self, part_spec)

            # If it's not 'None' which means no provider found
            if provider_name:
                # Load the provider-supported CAD mode.
                # This is what makes it a 'supplier cart' instead of a regular cart.
                provider = self.get_provider(provider_name)
                await provider.load(cart_item)

        return supplier_carts

    async def supplier_carts_to_quotes(
        self, preferred_suppliers: dict[str, ProviderCart]
    ) -> dict[str, ProviderRequestQuote]:
        """Given the list of suppliers, and a supplier-customized carts,
        convert them to quotes"""
        quotes = {}
        for provider_name, supplier_cart in preferred_suppliers.items():

            pc_logging.debug("Supplier: %s" % str(provider_name))

            quote = ProviderRequestQuote(supplier_cart)

            if provider_name:
                # If it's not 'None' which means no provider found
                provider = self.get_provider(provider_name)
                quote_result = await provider.query_quote(quote)
                quote.set_result(quote_result)
            quotes[provider_name] = quote
        return quotes

    def get_provider(self, part_spec, params=None):
        pc_logging.debug(f"Getting provider for {part_spec}")
        project_name, part_name = resolve_resource_path(
            self.current_project_path,
            part_spec,
        )
        prj = self.get_project(project_name)
        if prj is None:
            pc_logging.error("Package %s not found" % project_name)
            pc_logging.error("Packages found: %s" % str(self.projects))
            return None
        pc_logging.debug("Retrieving %s from %s" % (part_name, project_name))
        return prj.get_provider(part_name, params)

    def _resolve_part_project(self, part_spec):
        """(project, part name) for a spec, or None once the miss is reported."""
        project_name, part_name = resolve_resource_path(
            self.current_project_path,
            part_spec,
        )
        prj = self.get_project(project_name)
        if prj is None:
            pc_logging.error("Package %s not found" % project_name)
            pc_logging.error("Packages found: %s" % str(self.projects))
            return None
        pc_logging.debug("Retrieving %s from %s" % (part_name, project_name))
        return prj, part_name

    def _get_part(self, part_spec, params=None) -> Optional[Part]:
        resolved = self._resolve_part_project(part_spec)
        if resolved is None:
            return None
        prj, part_name = resolved
        return prj.get_part(part_name, params)

    async def _get_part_async(self, part_spec, params=None) -> Optional[Part]:
        """'_get_part()' for a caller already running on a loop.

        Resolving a part may have to build the assembly that produces it, and
        that is asynchronous. A coroutine has to await it rather than let the
        synchronous accessor drive it, which it cannot do from a thread that
        already owns a loop -- see 'Project._materialize_derived_part()'.
        """
        resolved = self._resolve_part_project(part_spec)
        if resolved is None:
            return None
        prj, part_name = resolved
        return await prj.get_part_async(part_name, params)

    def get_part(self, part_spec, params=None) -> Optional[Part]:
        return self._get_part(part_spec, params)

    async def get_part_async(self, part_spec, params=None) -> Optional[Part]:
        return await self._get_part_async(part_spec, params)

    def get_part_shape(self, part_spec, params=None):
        return asyncio.run(self._get_part(part_spec, params).get_wrapped(self))

    def convert_part(self, part_spec, part_type, params=None, **kwargs):
        """Convert the part to 'part_type' and return the result in memory.

        See 'Shape.convert()' for the supported part types and return types.
        """
        return asyncio.run(self._get_part(part_spec, params).convert(part_type, self, **kwargs))

    def get_part_cadquery(self, part_spec, params=None):
        """Thin alias for convert_part(part_spec, "cadquery", params)."""
        return self.convert_part(part_spec, "cadquery", params)

    def get_part_build123d(self, part_spec, params=None):
        """Thin alias for convert_part(part_spec, "build123d", params)."""
        return self.convert_part(part_spec, "build123d", params)

    def get_part_sdf(self, part_spec, params=None):
        """Return the SDF part's mesh (normalized in the sandbox at build time)."""
        return asyncio.run(self._get_part(part_spec, params).get_wrapped(self))

    def _get_assembly(self, assembly_spec, params=None):
        project_name, assembly_name = resolve_resource_path(
            self.current_project_path,
            assembly_spec,
        )
        prj = self.get_project(project_name)
        if prj is None:
            pc_logging.error("Package %s not found" % project_name)
            return None
        pc_logging.debug("Retrieving %s from %s" % (assembly_name, project_name))
        return prj.get_assembly(assembly_name, params)

    def get_assembly(self, assembly_spec, params=None):
        return self._get_assembly(assembly_spec, params)

    def get_assembly_shape(self, assembly_spec, params=None):
        return asyncio.run(self._get_assembly(assembly_spec, params).get_wrapped(self))

    def convert_assembly(self, assembly_spec, part_type, params=None, **kwargs):
        """Convert the assembly to 'part_type' and return the result in memory.

        See 'Shape.convert()' for the supported part types and return types.
        """
        return asyncio.run(self._get_assembly(assembly_spec, params).convert(part_type, self, **kwargs))

    def get_assembly_cadquery(self, assembly_spec, params=None):
        """Thin alias for convert_assembly(assembly_spec, "cadquery", params)."""
        return self.convert_assembly(assembly_spec, "cadquery", params)

    def get_assembly_build123d(self, assembly_spec, params=None):
        """Thin alias for convert_assembly(assembly_spec, "build123d", params)."""
        return self.convert_assembly(assembly_spec, "build123d", params)

    async def render_async(
        self,
        project_path=None,
        format=None,
        output_dir=None,
        options_package=None,
        ignore_manufacturability=False,
    ):
        if project_path is None:
            project_path = self.get_current_project_path()
        pc_logging.debug("Rendering all objects in %s..." % project_path)
        project = self.get_project(project_path)
        await project.render_async(
            format=format,
            output_dir=output_dir,
            options_package=options_package,
            ignore_manufacturability=ignore_manufacturability,
        )

    def render(
        self,
        project_path=None,
        format=None,
        output_dir=None,
        options_package=None,
        ignore_manufacturability=False,
    ):
        if project_path is None:
            project_path = self.get_current_project_path()
        pc_logging.debug("Rendering all objects in %s..." % project_path)
        project = self.get_project(project_path)
        project.render(
            format=format,
            output_dir=output_dir,
            options_package=options_package,
            ignore_manufacturability=ignore_manufacturability,
        )

    # TODO(clairbee): convert it into: ctx.get_runtime("python", "conda", {"version": "3.11"})
    def get_python_runtime(self, version=None, python_runtime=None):
        with self.runtimes_python_lock:
            if version is None:
                version = sandbox_versions.DEFAULT_PYTHON_VERSION
            # A version like 3.11 declared in YAML arrives as a float; keep it a
            # string so the runtime name below can be built by concatenation.
            version = str(version)

            # Every Python sandbox is given the CAD stack (see
            # runtime_python.once), so the ceiling belongs here rather than in
            # the handful of factories that happen to render with it: above it,
            # pip finds no wheel for anything the sandbox is preloaded with and
            # every part rendered in it dies on an import of something that was
            # never installed. Held rather than refused, because a package
            # asking for a Python newer than these pins is asking for something
            # reasonable that PartCAD cannot supply yet, and the pins move.
            #
            # Only the ceiling. The floor is CadQuery's alone and stays with the
            # factories that need CadQuery: a 3.10 sandbox is a perfectly good
            # place to convert an STL.
            requested = version
            try:
                version = sandbox_versions.at_most(version, sandbox_versions.MAX_PYTHON_VERSION_CAD)
            except ValueError:
                # The schema's 'pythonVersion' pattern permits a leading ">=",
                # and 'pc init' writes ">=<the host's version>" into every new
                # package, so a value that is not a plain "<major>.<minor>" is
                # something a real package really does carry. It is already not
                # a version this or the sandbox naming can reason about, and
                # making the bound the thing that discovers that would turn a
                # long-standing oddity into a crash. Pass it through untouched,
                # exactly as before.
                pass
            if version != requested and requested not in self.python_versions_held:
                self.python_versions_held.add(requested)
                pc_logging.warning(
                    "Python %s was asked for, but the CAD packages PartCAD pins are built for %s at the newest;"
                    " using %s instead" % (requested, sandbox_versions.MAX_PYTHON_VERSION_CAD, version)
                )

            if python_runtime is None:
                python_runtime = self.user_config.python_sandbox
            runtime_name = python_runtime + "-" + version
            if not runtime_name in self.runtimes_python:
                self.runtimes_python[runtime_name] = runtime_python_all.create(self, version, python_runtime)
            return self.runtimes_python[runtime_name]

    def get_javascript_runtime(self, version=None, javascript_runtime=None):
        """The sandboxed Node.js of the given major version.

        The JavaScript twin of get_python_runtime(). 'version' is normalized to
        the major line, which is the granularity Node.js sandboxes are
        provisioned at (see sandbox_versions.node_major_version).
        """
        with self.runtimes_javascript_lock:
            if version is None:
                version = sandbox_versions.DEFAULT_NODE_VERSION
            # A version like 22 declared in YAML arrives as an int, and one like
            # 22.11 as a float; both name the same major line.
            version = sandbox_versions.node_major_version(str(version))
            if javascript_runtime is None:
                javascript_runtime = self.user_config.javascript_sandbox
            runtime_name = javascript_runtime + "-" + version
            if runtime_name not in self.runtimes_javascript:
                runtime = runtime_javascript_all.create(self, version, javascript_runtime)
                # A runtime does not have to end up being the version that was
                # asked for: the 'none' sandbox is whatever Node.js the host
                # has, and reports that (see NoneJavaScriptRuntime). Two
                # requests that resolve to the same one have to be the same
                # object, or they would hold separate in-process locks over one
                # sandbox directory and each re-check its install guards.
                resolved_name = javascript_runtime + "-" + runtime.version
                runtime = self.runtimes_javascript.setdefault(resolved_name, runtime)
                self.runtimes_javascript[runtime_name] = runtime
            return self.runtimes_javascript[runtime_name]

    def ensure_dirs(self, path):
        if not self.option_create_dirs:
            return
        os.makedirs(path)

    def ensure_dirs_for_file(self, filename):
        if not self.option_create_dirs:
            return
        path = os.path.dirname(filename)
        if path:
            os.makedirs(path, exist_ok=True)

    def get_all_tests(self):
        return all_tests(self.user_config.threads_max)
