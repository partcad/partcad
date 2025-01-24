#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.

import asyncio
import os
import threading

from .cache import Cache
from .cache_shape import ShapeCache
from . import consts
from . import logging as pc_logging
from .mating import Mating
from . import project_config
from . import runtime_python_all
from . import project_factory_local as rfl
from . import project_factory_git as rfg
from . import project_factory_tar as rft
from . import sync_threads
from .user_config import user_config
from .utils import *
from .provider_request_quote import ProviderRequestQuote
from .provider_data_cart import *


# Context
class Context(project_config.Configuration):
    """Stores and caches all imported objects."""

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
    stats_providers: int
    stats_provider_queries: int
    stats_memory: int
    stats_git_ops: int

    # name is the package path (not a filesystem path) of the root package
    # in case it's configured to be something other than '//' (default)
    name: str

    # root_path is the absolute filesystem path to the root package (for monorepo's)
    root_path: str

    # current_project_path is the package path (not a filesystem path) of the current package
    # It is expected to match 'self.name' of the current package's object
    current_project_path: str

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

    def __init__(self, root_path=None, search_root=True):
        """Initializes the context and loads the root project."""
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

        super().__init__(consts.ROOT, self.root_path)
        self.current_project_path = self.name
        if not self.current_project_path.endswith("/"):
            self.current_project_path += "/"
        self.current_project_path += os.path.relpath(
            initial_root_path,
            root_path,
        ).replace(os.path.sep, "/")
        if self.current_project_path == self.name + "/." or (
            self.name.endswith("/") and self.current_project_path == self.name + "."
        ):
            self.current_project_path = self.name

        self.cache_shapes = ShapeCache()
        self.cache_tests = Cache("tests")

        # Protect the critical sections from access in different threads
        self.lock = threading.RLock()

        self.option_create_dirs = False
        self.runtimes_python = {}
        self.runtimes_python_lock = threading.Lock()

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
        self.stats_providers = 0
        self.stats_provider_queries = 0
        self.stats_memory = 0
        self.stats_git_ops = 0

        self.mates = {}
        # self.projects contains all projects known to this context
        self.projects = {}
        self.project_locks = {}
        self.project_locks_lock = threading.Lock()
        self._projects_being_loaded = {}

        with pc_logging.Process("InitCtx", self.config_dir):
            self.import_project(
                None,  # parent
                {
                    "name": self.name,
                    "type": "local",
                    "path": self.config_path,
                    "maybeEmpty": True,
                    "isRoot": True,
                },
            )

    def stats_recalc(self, verbose=False):
        self.stats_memory = total_size(self, verbose)

    def get_current_project_path(self):
        return self.current_project_path

    def import_project(self, parent, project_import_config):
        if not "name" in project_import_config or not "type" in project_import_config:
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
                if not "type" in project_import_config or project_import_config["type"] == "local":
                    with pc_logging.Action("Local", name):
                        rfl.ProjectFactoryLocal(self, parent, project_import_config)
                elif project_import_config["type"] == "git":
                    with pc_logging.Action("Git", name):
                        rfg.ProjectFactoryGit(self, parent, project_import_config)
                elif project_import_config["type"] == "tar":
                    with pc_logging.Action("Tar", name):
                        rft.ProjectFactoryTar(self, parent, project_import_config)
                else:
                    pc_logging.error("Invalid project type found: %s." % name)
                    del self._projects_being_loaded[name]
                    return None

                # Check whether the factory was able to successfully add the project
                if not name in self.projects:
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

                self.stats_packages += 1
                self.stats_packages_instantiated += 1

                del self._projects_being_loaded[name]
                return imported_project

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

    def get_project(self, rel_project_path: str):
        project_path = self.get_project_abs_path(rel_project_path)

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
            # Otherwise, iterate all subfolders and check if any of them are packages
            if "dependencies" in project.config_obj and project.config_obj["dependencies"] is not None:
                dependencies = project.config_obj["dependencies"]
                # TODO(clairbee): revisit if this code path is needed when the
                #                 user explicitly asked for a particular package
                # if not project.config_obj.get("isRoot", False):
                #     filtered = filter(
                #         lambda x: "onlyInRoot" not in dependencies[x]
                #         or not dependencies[x]["onlyInRoot"],
                #         dependencies,
                #     )
                #     dependencies = list(filtered)
                for prj_name in dependencies:
                    pc_logging.debug(f"Checking the dependency: {prj_name} vs {next_import}...")
                    if prj_name != next_import:
                        continue
                    prj_conf = project.config_obj["dependencies"][prj_name]
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

        # First, iterate all explicitly mentioned "dependencies"s.
        # Do it before iterating subdirectories, as it may kick off a long
        # background task.
        if "dependencies" in project.config_obj and project.config_obj["dependencies"] is not None:
            dependencies = project.config_obj["dependencies"]
            if not project.config_obj.get("isRoot", False):
                filtered = filter(
                    lambda x: "onlyInRoot" not in dependencies[x] or not dependencies[x]["onlyInRoot"],
                    dependencies,
                )
                dependencies = list(filtered)

            for prj_name in dependencies:
                prj_conf = project.config_obj["dependencies"][prj_name]

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

                tasks.append(asyncio.create_task(sync_threads.run(self.import_project, project, prj_conf)))

        # Second, iterate over all subfolder and check for packages
        subfolders = [f.name for f in os.scandir(project.config_dir) if f.is_dir()]
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

                if next_project_path in self.projects:
                    # This project is already imported (e.g. the current one)
                    # TODO(clairbee): is this worth a warning?
                    pc_logging.debug("Skipping already imported: %s" % subdir)
                    continue

                pc_logging.debug("Importing a subfolder (import all): %s..." % next_project_path)
                prj_conf = {
                    "name": next_project_path,
                    "type": "local",
                    "path": subdir,
                }

                tasks.append(asyncio.create_task(sync_threads.run(self.import_project, project, prj_conf)))

        return tasks

    def get_all_packages(self, parent_name=None):
        # TODO(clairbee): leverage root_project.get_child_project_names()
        self.import_all(parent_name)
        return self.get_packages(parent_name)

    def get_packages(self, parent_name=None):
        projects = self.projects.values()
        if parent_name is not None:
            projects = filter(lambda x: x.name.startswith(parent_name), projects)
        return map(
            lambda pkg: {"name": pkg.name, "desc": pkg.desc},
            filter(
                # FIXME(clairbee): parameterize interfaces before displaying them
                # lambda x: len(x.interfaces) + len(x.sketches) + len(x.parts) + len(x.assemblies)
                lambda x: len(x.sketches) + len(x.parts) + len(x.assemblies) > 0,
                projects,
            ),
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
        mate_target_config: dict,
        reverse: bool,
    ):
        source_interface_name = source_interface.full_name
        target_interface_name = target_interface.full_name

        if not source_interface_name in self.mates:
            self.mates[source_interface_name] = {}
        if target_interface_name in self.mates[source_interface_name]:
            pc_logging.error("Mate already exists: %s -> %s" % (source_interface_name, target_interface_name))
            return

        mate = Mating(source_interface, target_interface, mate_target_config, reverse)
        self.mates[source_interface_name][target_interface_name] = mate

    def get_mate(self, source_interface_name, target_interface_name):
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
        # called 'real', beacuase it allows to perform a lookup of
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

    def get_sketch_cadquery(self, sketch_spec, params=None):
        return asyncio.run(self._get_sketch(sketch_spec, params).get_cadquery(self))

    def get_sketch_build123d(self, sketch_spec, params=None):
        return asyncio.run(self._get_sketch(sketch_spec, params).get_build123d(self))

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

    def _get_part(self, part_spec, params=None):
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
        return prj.get_part(part_name, params)

    def get_part(self, part_spec, params=None):
        return self._get_part(part_spec, params)

    def get_part_shape(self, part_spec, params=None):
        return asyncio.run(self._get_part(part_spec, params).get_wrapped(self))

    def get_part_cadquery(self, part_spec, params=None):
        return asyncio.run(self._get_part(part_spec, params).get_cadquery(self))

    def get_part_build123d(self, part_spec, params=None):
        return asyncio.run(self._get_part(part_spec, params).get_build123d(self))

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

    def get_assembly_cadquery(self, assembly_spec, params=None):
        return asyncio.run(self._get_assembly(assembly_spec, params).get_cadquery(self))

    def get_assembly_build123d(self, assembly_spec, params=None):
        return asyncio.run(self._get_assembly(assembly_spec, params).get_build123d(self))

    async def render_async(self, project_path=None, format=None, output_dir=None):
        if project_path is None:
            project_path = self.get_current_project_path()
        pc_logging.debug("Rendering all objects in %s..." % project_path)
        project = self.get_project(project_path)
        await project.render_async(format=format, output_dir=output_dir)

    def render(self, project_path=None, format=None, output_dir=None):
        if project_path is None:
            project_path = self.get_current_project_path()
        pc_logging.debug("Rendering all objects in %s..." % project_path)
        project = self.get_project(project_path)
        project.render(format=format, output_dir=output_dir)

    def get_python_runtime(self, version=None, python_runtime=None):
        with self.runtimes_python_lock:
            if version is None:
                version = "%d.%d" % (
                    sys.version_info.major,
                    sys.version_info.minor,
                )
            if python_runtime is None:
                python_runtime = user_config.python_runtime
            runtime_name = python_runtime + "-" + version
            if not runtime_name in self.runtimes_python:
                self.runtimes_python[runtime_name] = runtime_python_all.create(self, version, python_runtime)
            return self.runtimes_python[runtime_name]

    def ensure_dirs(self, path):
        if not self.option_create_dirs:
            return
        os.makedirs(path)

    def ensure_dirs_for_file(self, filename):
        if not self.option_create_dirs:
            return
        path = os.path.dirname(filename)
        os.makedirs(path)
