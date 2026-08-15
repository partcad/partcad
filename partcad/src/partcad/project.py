#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.

from __future__ import annotations

import asyncio
import copy
import os
import re
import tempfile
import threading
import typing

# from pprint import pformat
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

import ruamel.yaml

from . import assembly, assembly_config, assembly_guide
from . import assembly_factory_alias as afa
from . import consts, document as pc_document, factory, interface
from . import logging as pc_logging
from . import part_config
from . import part_factory_alias as pfa
from . import (
    plugin_config,
    plugin_provider,
    plugin_repository,
    project_config,
    sketch,
    sketch_config,
)
from . import sketch_factory_alias as sfa
from . import telemetry
from .document_pdf import render_pdf_async
from .exception import EmptyShapesError
from .part import Part
from .render import render_cfg_merge
from .utils import normalize_resource_path, resolve_resource_path

if TYPE_CHECKING:
    from partcad.context import Context
    from partcad.shape import Shape


# The kinds of first-class objects a package may contain, mapped to the
# 'partcad.yaml' section that declares them. Kept as data so that introducing a
# new kind of object does not require touching the per-kind accessor plumbing.
OBJECT_KINDS = ("interface", "sketch", "part", "assembly", "provider", "repository", "partType")
OBJECT_KIND_SECTIONS = {
    "interface": "interfaces",
    "sketch": "sketches",
    "part": "parts",
    "assembly": "assemblies",
    "provider": "providers",
    "repository": "repositories",
    # A 'partType' is a package-defined way to construct parts (e.g. a wrapper
    # script). It is enumerable like any other object, but it is not a shape and
    # is never instantiated: parts whose 'type' references it are constructed by
    # PartFactoryWrapper, which looks the definition up here.
    "partType": "partTypes",
}


@telemetry.instrument()
class Project(project_config.Configuration):
    sketches: dict[str, sketch.Sketch]
    parts: dict[str, Part]
    assemblies: dict[str, assembly.Assembly]
    providers: dict[str, plugin_provider.Provider]
    repositories: dict[str, plugin_repository.Repository]

    class InterfaceLock(object):
        def __init__(self, prj, interface_name: str):
            prj.interface_locks_lock.acquire()
            if not interface_name in prj.interface_locks:
                prj.interface_locks[interface_name] = threading.Lock()
            self.lock = prj.interface_locks[interface_name]
            prj.interface_locks_lock.release()

        def __enter__(self, *_args):
            self.lock.acquire()

        def __exit__(self, *_args):
            self.lock.release()

    class SketchLock(object):
        def __init__(self, prj, sketch_name: str):
            prj.sketch_locks_lock.acquire()
            if not sketch_name in prj.sketch_locks:
                prj.sketch_locks[sketch_name] = threading.Lock()
            self.lock = prj.sketch_locks[sketch_name]
            prj.sketch_locks_lock.release()

        def __enter__(self, *_args):
            self.lock.acquire()

        def __exit__(self, *_args):
            self.lock.release()

    class PartLock(object):
        def __init__(self, prj, part_name: str):
            prj.part_locks_lock.acquire()
            if not part_name in prj.part_locks:
                prj.part_locks[part_name] = threading.Lock()
            self.lock = prj.part_locks[part_name]
            prj.part_locks_lock.release()

        def __enter__(self, *_args):
            self.lock.acquire()

        def __exit__(self, *_args):
            self.lock.release()

    class AssemblyLock(object):
        def __init__(self, prj, assembly_name: str):
            prj.assembly_locks_lock.acquire()
            if not assembly_name in prj.assembly_locks:
                prj.assembly_locks[assembly_name] = threading.Lock()
            self.lock = prj.assembly_locks[assembly_name]
            prj.assembly_locks_lock.release()

        def __enter__(self, *_args):
            self.lock.acquire()

        def __exit__(self, *_args):
            self.lock.release()

    class ProviderLock(object):
        def __init__(self, prj, provider_name: str):
            prj.provider_locks_lock.acquire()
            if not provider_name in prj.provider_locks:
                prj.provider_locks[provider_name] = threading.Lock()
            self.lock = prj.provider_locks[provider_name]
            prj.provider_locks_lock.release()

        def __enter__(self, *_args):
            self.lock.acquire()

        def __exit__(self, *_args):
            self.lock.release()

    class RepositoryLock(object):
        def __init__(self, prj, repository_name: str):
            prj.repository_locks_lock.acquire()
            if not repository_name in prj.repository_locks:
                prj.repository_locks[repository_name] = threading.Lock()
            self.lock = prj.repository_locks[repository_name]
            prj.repository_locks_lock.release()

        def __enter__(self, *_args):
            self.lock.acquire()

        def __exit__(self, *_args):
            self.lock.release()

    def __init__(
        self,
        ctx: Context,
        name: str,
        path: str,
        config_obj: dict | None = None,
        inherited_config: dict | None = None,
    ):
        super().__init__(
            name,
            path,
            config_obj=config_obj,
            inherited_config=inherited_config,
        )
        self.ctx = ctx

        # Protect the critical sections from access in different threads
        self.lock = threading.Lock()

        # self._object_configs[kind] holds the declared configuration of every
        # object of that kind. 'None' means "not enumerated yet": a local
        # package knows everything from its parsed 'partcad.yaml' and populates
        # all kinds here, while a plugin-backed package (see ProjectPlugin)
        # leaves them None and fills them on demand through the accessors
        # (object_config / object_configs / object_names).
        self._object_configs: dict[str, typing.Optional[dict]] = {
            kind: self._initial_object_configs(kind) for kind in OBJECT_KINDS
        }

        # The instantiated objects of each kind, filled lazily by the getters.
        self.interfaces = {}
        self.interface_locks = {}
        self.interface_locks_lock = threading.Lock()

        self.sketches = {}
        self.sketch_locks = {}
        self.sketch_locks_lock = threading.Lock()

        self.parts = {}
        self.part_locks = {}
        self.part_locks_lock = threading.Lock()

        self.assemblies = {}
        self.assembly_locks = {}
        self.assembly_locks_lock = threading.Lock()

        self.providers = {}
        self.provider_locks = {}
        self.provider_locks_lock = threading.Lock()

        self.repositories = {}
        self.repository_locks = {}
        self.repository_locks_lock = threading.Lock()

        if (
            "desc" in self.config_obj
            and not self.config_obj["desc"] is None
            and isinstance(self.config_obj["desc"], str)
        ):
            self.desc = self.config_obj["desc"].strip()
        else:
            self.desc = ""

        self._instantiate_objects()

    def _initial_object_configs(self, kind: str):
        """The configs of the given kind known at construction time.

        A local package returns everything its configuration declares. A
        plugin-backed package overrides this to return None, deferring
        enumeration until the data is actually requested.
        """
        cfg = self.config_obj.get(OBJECT_KIND_SECTIONS[kind])
        return {} if cfg is None else cfg

    def _instantiate_objects(self):
        """Instantiate the package's objects.

        Split out of the constructor so that a plugin-backed package can
        override it to instantiate lazily, on demand, instead of enumerating
        and instantiating everything up front.
        """
        self.init_sketches()
        self.init_interfaces()  # After sketches
        self.init_mates()  # After interfaces
        self.init_parts()  # After sketches and interfaces, and mates
        self.init_assemblies()  # after parts
        self.init_providers()  # after parts
        self.init_suppliers()  # after providers
        self.init_repositories()  # after parts

    # The generic object-access layer. Every read of a package's declared
    # objects goes through these three methods so that a plugin-backed package
    # can source the same data lazily without changing any caller.

    def object_configs(self, kind: str) -> dict:
        """All declared configs of 'kind', enumerating on demand if needed."""
        configs = self._object_configs.get(kind)
        if configs is None:
            configs = self._enumerate_object_configs(kind)
            self._object_configs[kind] = configs
        return configs

    def object_config(self, kind: str, name: str):
        """The config of a single object, fetched individually when possible.

        For a plugin-backed package this avoids a full enumeration: it asks the
        plugin for just this one object and only falls back to listing
        everything if the targeted fetch is not supported.
        """
        configs = self._object_configs.get(kind)
        if configs is not None and name in configs:
            return configs[name]
        # Not in the (possibly already enumerated) set: try a targeted single
        # fetch. A plugin-backed package can serve objects beyond what it
        # enumerates - e.g. the first page of a large, paginated catalog - so
        # any addressable object remains reachable even when it was not listed.
        one = self._fetch_object_config(kind, name)
        if one is not None:
            return one
        if configs is None:
            return self.object_configs(kind).get(name)
        return None

    def object_names(self, kind: str) -> list:
        return list(self.object_configs(kind).keys())

    # Hooks for plugin-backed packages. Never reached for a local package,
    # whose '_object_configs' are all populated at construction.
    def _enumerate_object_configs(self, kind: str) -> dict:
        return {}

    def _fetch_object_config(self, kind: str, name: str):
        return None

    def dependencies(self) -> dict:
        """The declared child-package dependencies of this package.

        Routed through an accessor so that a plugin-backed package can source
        its children from the repository (see ProjectExternalRepository) instead
        of from a 'dependencies' section on disk.
        """
        deps = self.config_obj.get("dependencies")
        return deps if deps else {}

    async def ensure_enumerated_async(self):
        """Warm any lazily-enumerated data from within an async context.

        A no-op for a local package (enumerated at construction). A plugin-backed
        package overrides this to await its repository, so the synchronous
        consumers downstream only ever hit the cache. Called from the import
        traversal (see Context._import_all_recursive).
        """
        return None

    def object_count(self, kind: str) -> int:
        """Number of declared objects of a kind, without instantiating them."""
        return len(self.object_configs(kind))

    # Backward-compatible views onto the object-access layer. These keep the
    # historical 'self.<kind>_configs' attribute name working (now sourced
    # through the accessor, so plugin packages enumerate lazily here too).
    @property
    def interface_configs(self) -> dict:
        return self.object_configs("interface")

    @property
    def sketch_configs(self) -> dict:
        return self.object_configs("sketch")

    @property
    def part_configs(self) -> dict:
        return self.object_configs("part")

    @property
    def assembly_configs(self) -> dict:
        return self.object_configs("assembly")

    @property
    def provider_configs(self) -> dict:
        return self.object_configs("provider")

    @property
    def repository_configs(self) -> dict:
        return self.object_configs("repository")

    # TODO(clairbee): Implement get_cover()
    # def get_cover(self):
    #     if not "cover" in self.config_obj or self.config_obj["cover"] is None:
    #         return None
    #     if isinstance(self.config_obj["cover"], str):
    #         return os.path.join(self.config_dir, self.config_obj["cover"])
    #     elif "package" in self.config_obj["cover"]:
    #         return self.ctx.get_project(
    #             self.path + "/" + self.config_obj["cover"]["package"]
    #         ).get_cover()

    def info(self) -> dict:
        """Return package-level information (name, description, URLs).

        Mirrors the object factories' ``info()`` so that ``pc info`` can render
        a package the same way it renders parts, sketches and assemblies. It
        intentionally does not enumerate the package's objects.
        """
        info = {"Path": self.name}
        if "url" in self.config_obj and self.config_obj["url"] is not None:
            info["Url"] = self.config_obj["url"]
        if "importUrl" in self.config_obj and self.config_obj["importUrl"] is not None:
            info["ImportUrl"] = self.config_obj["importUrl"]
        if self.desc:
            info["Desc"] = self.desc
        return info

    def matches(self, keyword: str) -> bool:
        if not keyword:
            return False
        keyword = keyword.lower()

        if keyword in str(self.config_obj).lower() or keyword in self.name.lower():
            return True
        return False

    def relocate(self, pattern: str) -> str:
        """Rewrites a reference this package authored against its own name.

        A package declares its identity ('name' in its configuration) but may
        be loaded at a different location, e.g. when it is vendored into
        another package tree. References it makes to itself are written using
        the identity, because that is what resolves while the package is being
        developed standalone. Point them back at wherever this instance
        actually lives, so that a vendored copy uses itself instead of pulling
        a second instance in from the package it was copied from.

        The rewrite is per-instance state: two copies of the same package
        loaded at two locations relocate independently and never interact.
        """
        declared_name = self.declared_name
        if not declared_name or declared_name == self.name:
            # The common case: loaded exactly where it says it belongs.
            return pattern

        if (
            pattern == declared_name
            or pattern.startswith(declared_name + "/")
            or pattern.startswith(declared_name + ":")
        ):
            relocated = self.name + pattern[len(declared_name) :]
            pc_logging.debug("%s: relocated the reference '%s' to '%s'" % (self.name, pattern, relocated))
            return relocated

        return pattern

    def resolve(self, pattern: str):
        """Resolves a reference authored by this package into (package, item)."""
        return resolve_resource_path(self.name, self.relocate(pattern))

    def normalize(self, pattern: str) -> str:
        """Resolves a reference authored by this package into 'package:item'."""
        return normalize_resource_path(self.name, self.relocate(pattern))

    def get_child_project_names(self, absolute: bool = True):
        if self.broken:
            pc_logging.info("Ignoring the broken package: %s" % self.name)
            return

        children = list()
        if os.path.isdir(self.config_dir):
            sub_folders = [f.name for f in os.scandir(self.config_dir) if f.is_dir()]
            for subdir in list(sub_folders):
                if os.path.exists(
                    os.path.join(
                        self.config_dir,
                        subdir,
                        consts.DEFAULT_PACKAGE_CONFIG,
                    )
                ):
                    children.append(self.name + "/" + subdir if absolute else subdir)

        dependencies = self.dependencies()
        if dependencies:
            if not self.config_obj.get("isRoot", False):
                dependencies = [
                    x for x in dependencies if "onlyInRoot" not in dependencies[x] or not dependencies[x]["onlyInRoot"]
                ]
            if absolute:
                children.extend([self.name + "/" + project_name for project_name in dependencies])
            else:
                children.extend(list(dependencies))
        return children

    def init_mates(self):
        mates = self.config_obj.get("mates", {})
        for source_interface_name, mate_config in mates.items():
            if not ":" in source_interface_name:
                source_interface_name = self.name + ":" + source_interface_name
            source_package_name, short_source_interface_name = self.resolve(source_interface_name)

            # Short-circuit the case when the source package is the current one
            # to avoid recursive package loading
            if source_package_name == self.name:
                source_package = self
            else:
                source_package = self.ctx.get_project(source_package_name)

            source_interface = source_package.get_interface(short_source_interface_name)
            if source_interface is None:
                raise Exception("Failed to find the source interface to mate: %s" % source_interface_name)
            source_interface.add_mates(self, mate_config)

    def get_interface_config(self, interface_name):
        return self.object_config("interface", interface_name)

    def init_interfaces(self):
        for interface_name in self.object_names("interface"):
            config = self.get_interface_config(interface_name)
            config["name"] = interface_name
            self.init_interface_by_config(config)

    def init_interface_by_config(self, config, source_project=None):
        if source_project is None:
            source_project = self

        interface_name: str = config["name"]
        self.interfaces[interface_name] = interface.Interface(interface_name, source_project, config)

    def get_interface(self, interface_name) -> interface.Interface:
        self.lock.acquire()

        # See if it's already available
        if interface_name in self.interfaces and not self.interfaces[interface_name] is None:
            p = self.interfaces[interface_name]
            self.lock.release()
            return p

        with Project.InterfaceLock(self, interface_name):
            # Release the project lock, and continue with holding the interface lock only
            self.lock.release()

            # This is just a regular interface name, no params (interface_name == result_name)
            if not interface_name in self.interface_configs:
                # We don't know anything about such a interface
                pc_logging.error(
                    "Interface '%s' not found in '%s'",
                    interface_name,
                    self.name,
                )
                return None
            # This is not yet created (invalidated?)
            config = self.get_interface_config(interface_name)
            config["name"] = interface_name
            self.init_interface_by_config(config)
            return self.interfaces[interface_name]

    def get_sketch_config(self, sketch_name):
        return self.object_config("sketch", sketch_name)

    def set_sketch_config(self, sketch_name, sketch_config):
        """
        Save the updated sketch configuration to the project configuration file.
        """
        if "name" in sketch_config:
            del sketch_config["name"]
        if "orig_name" in sketch_config:
            del sketch_config["orig_name"]

        if "offset" in sketch_config and isinstance(sketch_config["offset"], list):
            sketch_config["offset"] = ruamel.yaml.comments.CommentedSeq(sketch_config["offset"])
            sketch_config["offset"].fa.set_flow_style()

        yaml = ruamel.yaml.YAML()
        yaml.preserve_quotes = True

        with self.lock:
            try:
                with open(self.config_path) as fp:
                    package_config = yaml.load(fp)

                if "sketches" in package_config:
                    sketches = package_config["sketches"]
                    sketches[sketch_name] = sketch_config
                else:
                    package_config["sketches"] = {sketch_name: sketch_config}

                with open(self.config_path, "w") as fp:
                    yaml.dump(package_config, fp)

            except (IOError, OSError) as e:
                pc_logging.error(f"Failed to update sketch configuration: {e}")
                raise
            except Exception as e:
                pc_logging.error(f"Unexpected error updating sketch configuration: {e}")
                raise

    def get_part_config(self, part_name):
        return self.object_config("part", part_name)

    def get_assembly_config(self, assembly_name):
        return self.object_config("assembly", assembly_name)

    def get_provider_config(self, provider_name):
        return self.object_config("provider", provider_name)

    def get_repository_config(self, repository_name):
        return self.object_config("repository", repository_name)

    def get_part_type_config(self, part_type_name):
        return self.object_config("partType", part_type_name)

    def get_object_config(self, object_name, configs: dict[str, dict[str, typing.Any]]):
        if not object_name in configs:
            return None
        return configs[object_name]

    def init_sketches(self):
        return self.init_objects(
            "sketch",
            self.sketch_configs,
            sketch_config.SketchConfiguration,
            sfa.SketchFactoryAlias,
            self.get_sketch_config,
        )

    def init_parts(self):
        return self.init_objects(
            "part",
            self.part_configs,
            part_config.PartConfiguration,
            pfa.PartFactoryAlias,
            self.get_part_config,
        )

    def init_assemblies(self):
        return self.init_objects(
            "assembly",
            self.assembly_configs,
            assembly_config.AssemblyConfiguration,
            afa.AssemblyFactoryAlias,
            self.get_assembly_config,
        )

    def init_providers(self):
        return self.init_objects(
            "provider",
            self.provider_configs,
            plugin_config.PluginConfiguration,
            None,
            self.get_provider_config,
        )

    def init_repositories(self):
        return self.init_objects(
            "repository",
            self.repository_configs,
            plugin_config.PluginConfiguration,
            None,
            self.get_repository_config,
        )

    def init_objects(
        self,
        factory_name: str,
        configs: dict[str, dict[str, typing.Any]],
        config_class,
        alias_class,
        get_config: callable,
    ):
        if configs is None:
            return

        for name in configs:
            config = get_config(name)
            full_object_name = f"{self.name}:{name}"
            config = config_class.normalize(name, config, full_object_name)
            self.init_object_by_config(factory_name, config_class, alias_class, config)

    def init_sketch_by_config(self, config, source_project=None):
        self.init_object_by_config(
            "sketch", sketch_config.SketchConfiguration, sfa.SketchFactoryAlias, config, source_project
        )

    def init_part_by_config(self, config, source_project=None):
        self.init_object_by_config("part", part_config.PartConfiguration, pfa.PartFactoryAlias, config, source_project)

    def init_provider_by_config(self, config, source_project=None):
        self.init_object_by_config("provider", plugin_config.PluginConfiguration, None, config, source_project)

    def init_repository_by_config(self, config, source_project=None):
        self.init_object_by_config("repository", plugin_config.PluginConfiguration, None, config, source_project)

    def init_object_by_config(self, factory_name: str, config_class, alias_class, config, source_project=None):
        if source_project is None:
            source_project = self
        factory.instantiate(factory_name, config["type"], self.ctx, source_project, self, config)

        # Initialize aliases if they are declared implicitly
        if alias_class and config.get("aliases"):
            object_name = config["name"]
            for alias in config["aliases"]:
                if ";" in object_name:
                    # Copy parameters
                    alias += object_name[object_name.index(";") :]
                alias_object_config = {
                    "type": "alias",
                    "name": alias,
                    "source": ":" + object_name,
                }
                # User configuration may override the parameters of the alias
                # itself, so the alias (with the parameters copied above, if
                # any) is what the fully qualified name is built from - not the
                # object the alias points at.
                full_alias_name = f"{self.name}:{alias}"
                alias_object_config = config_class.normalize(alias, alias_object_config, full_alias_name)
                alias_class(self.ctx, source_project, self, alias_object_config)

    def get_sketch(self, sketch_name, func_params=None) -> Optional[sketch.Sketch]:
        return self.get_object(
            "sketch",
            Project.SketchLock,
            self.sketches,
            self.sketch_configs,
            self.get_sketch_config,
            sketch_config.SketchConfiguration,
            sfa.SketchFactoryAlias,
            sketch_name,
            func_params,
        )

    def get_part(self, part_name, func_params=None, quiet=False) -> Optional[Part]:
        return self.get_object(
            "part",
            Project.PartLock,
            self.parts,
            self.part_configs,
            self.get_part_config,
            part_config.PartConfiguration,
            pfa.PartFactoryAlias,
            part_name,
            func_params,
            quiet=quiet,
        )

    def get_assembly(self, assembly_name, func_params=None) -> Optional[assembly.Assembly]:
        return self.get_object(
            "assembly",
            Project.AssemblyLock,
            self.assemblies,
            self.assembly_configs,
            self.get_assembly_config,
            assembly_config.AssemblyConfiguration,
            afa.AssemblyFactoryAlias,
            assembly_name,
            func_params,
        )

    def get_provider(self, provider_name, func_params=None) -> Optional[plugin_provider.Provider]:
        return self.get_object(
            "provider",
            Project.ProviderLock,
            self.providers,
            self.provider_configs,
            self.get_provider_config,
            plugin_config.PluginConfiguration,
            None,
            provider_name,
            func_params,
        )

    def get_repository(self, repository_name, func_params=None) -> Optional[plugin_repository.Repository]:
        return self.get_object(
            "repository",
            Project.RepositoryLock,
            self.repositories,
            self.repository_configs,
            self.get_repository_config,
            plugin_config.PluginConfiguration,
            None,
            repository_name,
            func_params,
        )

    def get_object(
        self,
        factory_name: str,
        lock_class,
        objects,
        object_configs: dict[str, dict[str, typing.Any]],
        get_config: callable,
        config_class,
        alias_class,
        object_name: str,
        func_params=None,
        quiet=False,
    ):
        if func_params is None or not func_params:
            has_func_params = False
        else:
            has_func_params = True

        params: dict[str, typing.Any] = {}
        if ";" in object_name:
            has_name_params = True
            base_object_name = object_name.split(";")[0]
            object_name_params_string = object_name.split(";")[1]

            for kv in object_name_params_string.split(","):
                k, v = kv.split("=")
                params[k] = v
        else:
            has_name_params = False
            base_object_name = object_name

        if has_func_params:
            params = {**params, **func_params}
            has_name_params = True

        if not has_name_params:
            result_name = object_name
        else:
            # Determine the name we want this parameterized object to have
            result_name = base_object_name + ";"
            result_name += ",".join(map(lambda n: n + "=" + str(params[n]), sorted(params)))

        self.lock.acquire()

        # See if it's already available
        if result_name in objects and not objects[result_name] is None:
            p = objects[result_name]
            self.lock.release()
            return p

        with lock_class(self, result_name):
            # Release the project lock, and continue with holding the part lock only
            self.lock.release()

            if not has_name_params:
                # This is just a regular object name, no params (object_name == result_name).
                # Resolve through 'get_config' rather than a membership test on
                # the enumerated set, so a plugin-backed package can serve an
                # object it did not enumerate (a targeted single fetch).
                config = get_config(object_name)
                if config is None:
                    # We don't know anything about such an object
                    if not quiet:
                        pc_logging.error(
                            "Object '%s' not found in '%s'",
                            object_name,
                            self.name,
                        )
                    return None
                full_object_name = f"{self.name}:{object_name}"
                config = config_class.normalize(object_name, config, full_object_name)
                self.init_object_by_config(factory_name, config_class, alias_class, config)

                if not object_name in objects or objects[object_name] is None:
                    pc_logging.error("Failed to instantiate a non-parametrized object %s" % object_name)
                return objects[object_name]

            # This object has params (part_name != result_name). Only the base
            # object's *config* is needed to derive the parametrized variant
            # (see 'object_configs[base_object_name]' below), so check the
            # enumerable configs rather than the instantiated 'objects' dict -
            # a plugin-backed package enumerates lazily and may not have
            # instantiated the base yet.
            if base_object_name not in object_configs:
                pc_logging.error(
                    "Base object '%s' not found in '%s'",
                    base_object_name,
                    self.name,
                )
                return None
            pc_logging.debug("Found the base object: %s" % base_object_name)

            # Now we have the original assembly name and the complete set of parameters
            config = object_configs[base_object_name]
            if config is None:
                pc_logging.error(
                    "The config for the base object '%s' is not found in '%s'",
                    base_object_name,
                    self.name,
                )
                return None

            config = copy.deepcopy(config)
            if (not "parameters" in config or config["parameters"] is None) and (config["type"] != "enrich"):
                pc_logging.error(
                    "Attempt to parametrize '%s' of '%s' which has no parameters: %s",
                    base_object_name,
                    self.name,
                    str(config),
                )
                return None

            # Expand the config object so that the parameter values can be set
            full_object_name = f"{self.name}:{result_name}"
            config = config_class.normalize(result_name, config, full_object_name)
            config["orig_name"] = base_object_name

            # Fill in the parameter values
            param_name: str
            if "parameters" in config and not config["parameters"] is None:
                # Filling "parameters"
                for param_name, param_value in params.items():
                    if config["parameters"][param_name]["type"] == "string":
                        config["parameters"][param_name]["default"] = str(param_value)
                    elif config["parameters"][param_name]["type"] == "int":
                        config["parameters"][param_name]["default"] = int(param_value)
                    elif config["parameters"][param_name]["type"] == "float":
                        config["parameters"][param_name]["default"] = float(param_value)
                    elif config["parameters"][param_name]["type"] == "bool":
                        if isinstance(param_value, str):
                            if param_value.lower() == "true":
                                config["parameters"][param_name]["default"] = True
                            else:
                                config["parameters"][param_name]["default"] = False
                        else:
                            config["parameters"][param_name]["default"] = bool(param_value)
                    elif config["parameters"][param_name]["type"] == "array":
                        config["parameters"][param_name]["default"] = param_value
            else:
                # Filling "with"
                if not "with" in config:
                    config["with"] = {}
                for param_name, param_value in params.items():
                    config["with"][param_name] = param_value

            # Now initialize the object
            pc_logging.debug("Initializing a parametrized object: %s" % result_name)
            # pc_logging.debug(
            #     "Initializing a parametrized object using the following config: %s"
            #     % pformat(config)
            # )
            factory.instantiate(factory_name, config["type"], self.ctx, self, self, config)

            # See if it worked
            if not result_name in objects:
                pc_logging.error(
                    "Failed to instantiate parameterized object '%s' in '%s'",
                    result_name,
                    self.name,
                )
                return None

            return objects[result_name]

    def get_suppliers(self):
        return {
            supplier_name if ":" in supplier_name else f"{self.name}:{supplier_name}": supplier
            for supplier_name, supplier in self.suppliers.items()
        }

    def init_suppliers(self):
        cfg = self.config_obj.get("suppliers", {})
        if isinstance(cfg, str):
            cfg = {cfg: {}}
        elif isinstance(cfg, list):
            cfg = {c: {} for c in cfg}
        elif not isinstance(cfg, dict):
            pc_logging.error(
                "Invalid suppliers configuration in '%s': %s",
                self.name,
                str(cfg),
            )
            return

        self.suppliers = cfg

    def add_import(self, alias, location):
        if ":" in location:
            location_param = "url"
            if location.endswith(".tar.gz"):
                location_type = "tar"
            else:
                location_type = "git"
        else:
            location_param = "path"
            location_type = "local"

        yaml = ruamel.yaml.YAML()
        yaml.preserve_quotes = True
        with open(self.config_path) as fp:
            config = yaml.load(fp)
            fp.close()

        if "import" in config and "dependencies" not in config:
            config["dependencies"] = config["import"]
        if config["dependencies"] is None:
            config["dependencies"] = {}
        config["dependencies"][alias] = {
            location_param: location,
            "type": location_type,
        }
        with open(self.config_path, "w") as fp:
            yaml.dump(config, fp)
            fp.close()

    def rel_path(self, path) -> str:
        """Render a filesystem path for display, relative to this package.

        Paths that belong to a package are reported relative to that package's
        directory, so the output does not depend on the caller's working
        directory. That matters because the caller is not always the process
        doing the work: the JSON-RPC daemon runs detached with ``cwd=/``, and
        receives absolute paths from its clients. A path outside the package is
        reported in full, since it has no package-relative form.
        """
        if not path:
            return path
        abs_path = os.path.abspath(str(path))
        root = os.path.abspath(self.config_dir)
        if abs_path == root or abs_path.startswith(root + os.sep):
            return os.path.relpath(abs_path, root).replace("\\", "/")
        return abs_path

    def _validate_path(self, path, extension) -> tuple[bool, str, str]:
        if not os.path.isabs(path):
            path = os.path.abspath(path)
        root = self.config_dir
        if not os.path.isabs(root):
            root = os.path.abspath(root)

        if not path.startswith(root):
            pc_logging.error("Can't add files outside of the package")
            return False, None, None

        path = os.path.relpath(path, root).replace("\\", "/")
        name = path
        if name.lower().endswith((".%s" % extension).lower()):
            name = name[: -len(extension) - 1]

        return True, path, name

    def _add_component(
        self,
        kind: str,
        path: str,
        section: str,
        ext_by_kind: dict[str, str],
        component_config,
    ) -> bool:
        if kind in ext_by_kind:
            ext = ext_by_kind[kind]
        else:
            ext = kind

        if ext:
            # This is a file type.
            # Remove the extension from the name.
            valid, path, name = self._validate_path(path, ext)
            if not valid:
                return False
        else:
            # This is not a file type.
            # The user provided value is not a path. It's just the name itself.
            name = path
            path = None

        yaml = ruamel.yaml.YAML()
        yaml.preserve_quotes = True
        with open(self.config_path) as fp:
            config = yaml.load(fp)
            fp.close()

        obj = {"type": kind, **component_config}
        if name == path:
            obj["path"] = path

        found = False
        for elem in config:
            if elem == section:
                config_section = config[section]
                if config_section is None:
                    config_section = {}
                config_section[name] = obj
                config[section] = config_section
                found = True
                break  # no need to iterate further
        if not found:
            config[section] = {name: obj}

        with open(self.config_path, "w") as fp:
            yaml.dump(config, fp)
            fp.close()

        return True

    def add_sketch(self, kind: str, path: str, config={}) -> bool:
        pc_logging.info("Adding the sketch %s of type %s" % (self.rel_path(path), kind))
        ext_by_kind = {
            "cadquery": "py",
            "build123d": "py",
            "basic": None,
        }
        return self._add_component(
            kind,
            path,
            "sketches",
            ext_by_kind,
            config,
        )

    def add_part(self, kind: str, path: str, config={}) -> bool:
        pc_logging.info("Adding the part %s of type %s" % (self.rel_path(path), kind))
        ext_by_kind = {
            "cadquery": "py",
            "build123d": "py",
            "sdf": "py",
        }
        return self._add_component(
            kind,
            path,
            "parts",
            ext_by_kind,
            config,
        )

    def add_assembly(self, kind: str, path: str, config={}) -> bool:
        pc_logging.info("Adding the assembly %s of type %s" % (self.rel_path(path), kind))
        ext_by_kind = {}
        return self._add_component(
            kind,
            path,
            "assemblies",
            ext_by_kind,
            config,
        )

    def set_part_config(self, part_name, part_config):
        if "name" in part_config:
            del part_config["name"]
        if "orig_name" in part_config:
            del part_config["orig_name"]

        if "offset" in part_config and isinstance(part_config["offset"], list):
            part_config["offset"] = ruamel.yaml.comments.CommentedSeq(part_config["offset"])
            part_config["offset"].fa.set_flow_style()

        yaml = ruamel.yaml.YAML()
        yaml.preserve_quotes = True
        with open(self.config_path) as fp:
            package_config = yaml.load(fp)
            fp.close()

        if "parts" in package_config:
            parts = package_config["parts"]
            parts[part_name] = part_config
        else:
            package_config["parts"] = {part_name: part_config}

        with open(self.config_path, "w") as fp:
            yaml.dump(package_config, fp)
            fp.close()

    def update_part_config(self, part_name, part_config_update: dict[str, typing.Any]):
        pc_logging.debug("Updating part config: %s: %s" % (part_name, part_config_update))
        yaml = ruamel.yaml.YAML()
        yaml.preserve_quotes = True
        with open(self.config_path) as fp:
            config = yaml.load(fp)
            fp.close()

        if "parts" in config:
            parts = config["parts"]
            if part_name in parts:
                part_config = parts[part_name]
                for key, value in part_config_update.items():
                    if value is not None:
                        part_config[key] = value
                    else:
                        if key in part_config:
                            del part_config[key]

                with open(self.config_path, "w") as fp:
                    yaml.dump(config, fp)
                    fp.close()

    async def _run_test_async(self, ctx, tests: list, use_wrapper: bool = False) -> bool:
        if tests is None:
            tests = ctx.get_all_tests()

        tasks = []
        test_method = "test_log_wrapper" if use_wrapper else "test_cached"

        def get_objects(config_dict, getter):
            for name in config_dict:
                obj = getter(name)
                # skip testing objects that are not finalized
                if obj and (not hasattr(obj, "finalized") or obj.finalized):
                    yield obj

        tasks.extend(
            asyncio.create_task(obj.test_async()) for obj in get_objects(self.interface_configs, self.get_interface)
        )

        for config_dict, getter in [
            (self.sketch_configs, self.get_sketch),
            (self.part_configs, self.get_part),
            (self.assembly_configs, self.get_assembly),
        ]:
            tasks.extend(
                asyncio.create_task(getattr(t, test_method)(tests, ctx, obj))
                for obj in get_objects(config_dict, getter)
                for t in tests
            )

        return all(await asyncio.gather(*tasks))

    async def test_async(self, ctx, tests=None) -> bool:
        return await self._run_test_async(ctx, tests, use_wrapper=False)

    def test(self, ctx, tests=None) -> bool:
        return asyncio.run(self.test_async(ctx, tests))

    async def test_log_wrapper_async(self, ctx, tests=None) -> bool:
        return await self._run_test_async(ctx, tests, use_wrapper=True)

    def test_log_wrapper(self, ctx, tests=None) -> bool:
        return asyncio.run(self.test_log_wrapper_async(ctx, tests))

    async def render_async(
        self,
        sketches: Optional[List] = None,
        interfaces: Optional[List] = None,
        parts: Optional[List] = None,
        assemblies: Optional[List] = None,
        format: Optional[str] = None,
        output_dir: Optional[Path] = None,
        ignore_manufacturability: bool = False,
    ):
        with pc_logging.Action("RenderPkg", self.name):
            # Override the default output_dir.
            # TODO(clairbee): pass the preference downstream without making a
            # persistent change.

            if output_dir:
                self.config_obj.setdefault("render", {})["output_dir"] = output_dir

            render = self.config_obj.get("render", {})
            shapes: List[Shape] = self._enumerate_shapes(sketches, interfaces, parts, assemblies)

            if None in shapes:
                raise EmptyShapesError

            tasks = []
            render_formats = ["svg", "png", "dxf", "step", "stl", "3mf", "threejs", "obj", "gltf", "brep", "iges"]

            for shape in shapes:
                # A deep copy: 'render_cfg_merge()' merges nested dictionaries in
                # place, so a shallow copy would let one shape's settings leak
                # into the package's own configuration and into every shape
                # rendered after it.
                shape_render = render_cfg_merge(copy.deepcopy(render), shape.config.get("render", {}))

                for format_name in render_formats:
                    if self._should_render_format(format_name, shape_render, format, shape.kind):
                        if not hasattr(shape, "finalized") or shape.finalized:
                            tasks.append(
                                shape.render_async(
                                    ctx=self.ctx,
                                    format_name=format_name,
                                    project=self,
                                    filepath=None,
                                )
                            )

            await asyncio.gather(*tasks)

            # The package document lists what the package declares; an assembly
            # document lists what that assembly is made of, and the assembly
            # instruction book how to put it together. An assembly gets one of
            # its own when it is the object the document was asked for, or when
            # it asks for one in its own configuration.
            for document_format in ("readme",) + assembly_guide.GUIDE_FORMATS:
                for assembly_name in self._assembly_documents_to_render(shapes, assemblies, format, document_format):
                    if document_format == "readme":
                        await self.render_assembly_readme_async(assembly_name, render, output_dir)
                    else:
                        await self.render_assembly_guide_async(
                            assembly_name,
                            document_format,
                            render,
                            output_dir,
                            ignore_manufacturability,
                        )

            # The package document is skipped when specific assemblies were asked
            # for: their own documents are what was requested.
            if (format == "readme" and not assemblies) or (format is None and "readme" in render):
                self.render_readme_async(render, output_dir)

    def _assembly_documents_to_render(self, shapes, assemblies, format, document_format):
        """Which assemblies get a document of the given kind out of this run."""
        if format is not None and format != document_format:
            return []
        names = []
        for shape in shapes:
            if shape.kind != "assembly":
                continue
            if (format == document_format and assemblies) or document_format in (shape.config.get("render") or {}):
                names.append(shape.name)
        return names

    def _enumerate_shapes(self, sketches, interfaces, parts, assemblies):
        def get_keys(name):
            # A section that is present but empty (e.g. `sketches:` with no
            # entries, as `pc init` writes it) parses as None; treat it as {}.
            return list((self.config_obj.get(name) or {}).keys()) if name in self.config_obj else []

        sketches = sketches or get_keys("sketches")
        # interfaces = sketches or get_keys("interfaces")
        parts = parts or get_keys("parts")
        assemblies = assemblies or get_keys("assemblies")

        shapes = []
        for name in sketches:
            shapes.append(self.get_sketch(name))
        for name in parts:
            shapes.append(self.get_part(name))
        for name in assemblies:
            shapes.append(self.get_assembly(name))
        # TODO(clairbee): interfaces are not yet renderable.
        # for name in interfaces: shapes.append(self.get_interface(name))

        return shapes

    def _should_render_format(
        self, format_name: str, shape_render: dict, current_format: typing.Optional[str], shape_kind: str
    ) -> bool:
        """Helper function to determine if a format should be rendered"""
        plural_shape_kind = {
            "part": "parts",
            "assembly": "assemblies",
            "sketch": "sketches",
            "interface": "interfaces",
            "providers": "providers",
        }
        if (
            format_name in shape_render
            and shape_render[format_name] is not None
            and not isinstance(shape_render[format_name], str)
            and plural_shape_kind.get(shape_kind, None) in shape_render.get(format_name, {}).get("exclude", [])
        ):
            return False
        return (current_format is None and format_name in shape_render) or (
            current_format is not None and current_format == format_name
        )

    def render(
        self,
        sketches: Optional[list] = None,
        interfaces: Optional[list] = None,
        parts: Optional[list] = None,
        assemblies: Optional[list] = None,
        format: Optional[str] = None,
        output_dir: Optional[Path] = None,
        ignore_manufacturability: bool = False,
    ):
        asyncio.run(
            self.render_async(sketches, interfaces, parts, assemblies, format, output_dir, ignore_manufacturability)
        )

    def readme_image_path(self, name, render_cfg, return_path, config=None):
        """Where the projection of the shape called 'name' is.

        Returns a '(src, test_path)' pair: 'src' is the path to write into a
        document that links to the image, relative to the document being
        generated, and 'test_path' is where the image file is expected relative
        to the output directory, so that the caller can check whether it has been
        rendered at all. Both are 'None' when the package renders neither SVG nor
        PNG.
        """
        if "svg" in render_cfg or (config is not None and config.get("type") == "svg"):
            image_cfg = render_cfg.get("svg", {})
            extension = ".svg"
        elif "png" in render_cfg:
            image_cfg = render_cfg["png"]
            extension = ".png"
        else:
            return None, None

        if isinstance(image_cfg, str):
            image_cfg = {"prefix": image_cfg}
        if image_cfg is None:
            image_cfg = {}
        prefix = image_cfg.get("prefix", ".")

        image_path = os.path.join(return_path, prefix, name + extension)
        test_image_path = os.path.join(prefix, name + extension)
        return image_path, test_image_path

    def _readme_image(self, name, render_cfg, return_path, config=None):
        """The '<img>' markup for the projection of the shape called 'name'."""
        src, test_image_path = self.readme_image_path(name, render_cfg, return_path, config)
        if src is None:
            return None, None
        markup = '<img src="%s" alt="%s" style="%s">' % (src, name, pc_document.MARKDOWN_IMAGE_STYLE)
        return markup, test_image_path

    def _assembly_document_target(self, format, extension, assembly_name, render_cfg=None, output_dir=None):
        """Where a document of one assembly goes, and what it is about.

        Returns '(assembly, path, dir_path, return_path, render_cfg, output_dir)',
        or 'None' if this package has no such assembly.
        """
        assembly = self.get_assembly(assembly_name)
        if assembly is None:
            return None

        if render_cfg is None:
            render_cfg = self.config_obj.get("render", {}) or {}
        if output_dir is None:
            output_dir = self.config_dir

        # Only the assembly's own configuration is consulted for the path here:
        # the package-level setting points at the package document, and reusing
        # it would have the assembly overwrite it.
        cfg = (assembly.config.get("render") or {}).get(format, {})
        if isinstance(cfg, str):
            cfg = {"path": cfg}
        if cfg is None:
            cfg = {}

        # 'assembly.name' rather than the requested name: a parameterized
        # assembly is known by the name its parameter values resolve to, which is
        # also the name its images are rendered under.
        path = os.path.join(output_dir, cfg.get("path", assembly.name + extension))
        dir_path = os.path.dirname(path)
        return_path = os.path.relpath(output_dir, dir_path)
        return assembly, path, dir_path, return_path, render_cfg, output_dir

    async def render_assembly_readme_async(self, assembly_name, render_cfg=None, output_dir=None):
        """Generate the markdown document of a single assembly.

        Where the package document lists what the package declares, this one lists
        what the assembly is made of: every part and every sub-assembly it uses,
        recursively, grouped by the package they come from and counted.

        Returns the path of the generated document, or 'None' if there is no such
        assembly in this package.
        """
        target = self._assembly_document_target("readme", ".md", assembly_name, render_cfg, output_dir)
        if target is None:
            return None
        assembly, path, dir_path, return_path, render_cfg, output_dir = target

        images = assembly_guide.PackageImages(self, render_cfg, output_dir, return_path)
        document = await assembly_guide.build_readme_document(self, assembly, images, dir_path)

        lines = pc_document.render_markdown(document)
        with open(path, "w") as f:
            f.writelines(map(lambda s: s + "\n", lines))
        return path

    def render_assembly_readme(self, assembly_name, render_cfg=None, output_dir=None):
        return asyncio.run(self.render_assembly_readme_async(assembly_name, render_cfg, output_dir))

    async def render_assembly_guide_async(
        self,
        assembly_name,
        format="pdf",
        render_cfg=None,
        output_dir=None,
        ignore_manufacturability=False,
    ):
        """Generate the assembly instruction book of a single assembly.

        'format' is "pdf" or "html": the same document either way, laid out on
        paper or as pages to flip through in a browser.

        Returns the path of the generated document, or 'None' if there is no such
        assembly in this package. Raises 'AssemblyDocumentError' if the assembly
        is not one an instruction book can be written for (see
        'assembly_guide.check_source').
        """
        if format not in assembly_guide.GUIDE_FORMATS:
            raise ValueError("Unsupported assembly document format: %s" % format)

        target = self._assembly_document_target(format, "." + format, assembly_name, render_cfg, output_dir)
        if target is None:
            return None
        assembly, path, dir_path, _return_path, render_cfg, output_dir = target

        assembly = assembly_guide.resolve_alias(self.ctx, assembly)
        assembly_guide.check_source(assembly, ignore_manufacturability)

        with pc_logging.Action("Guide%s" % format.upper(), self.name, assembly.name):
            # The illustrations exist for this document alone - most of them show
            # something that is not an object of any package - so they are
            # rendered into a directory of their own and thrown away with it.
            with tempfile.TemporaryDirectory() as assets_dir:
                images = assembly_guide.RenderedImages(self.ctx, self, assets_dir)
                document = await assembly_guide.build_guide_document(self.ctx, self, assembly, images, dir_path)

                self.ctx.ensure_dirs_for_file(path)
                if format == "html":
                    with open(path, "w") as f:
                        f.write(pc_document.render_html(document))
                else:
                    await render_pdf_async(self.ctx, document, path)

        return path

    def render_assembly_guide(
        self,
        assembly_name,
        format="pdf",
        render_cfg=None,
        output_dir=None,
        ignore_manufacturability=False,
    ):
        return asyncio.run(
            self.render_assembly_guide_async(assembly_name, format, render_cfg, output_dir, ignore_manufacturability)
        )

    def render_readme_async(self, render_cfg, output_dir):
        if output_dir is None:
            output_dir = self.config_dir

        if render_cfg is None:
            render_cfg = {}
        cfg = render_cfg.get("readme", {})
        if isinstance(cfg, str):
            cfg = {"path": cfg}
        if cfg is None:
            cfg = {}

        path = os.path.join(output_dir, cfg.get("path", "README.md"))
        dir_path = os.path.dirname(path)
        return_path = os.path.relpath(output_dir, dir_path)

        exclude = cfg.get("exclude", [])
        if exclude is None:
            exclude = []

        name = self.name
        desc = self.desc
        docs = self.config_obj.get("docs", None)
        intro = None
        usage = None
        if docs:
            name = docs.get("name", name)
            intro = docs.get("intro", None)
            usage = docs.get("usage", None)

        lines = []
        lines += ["# %s" % name]
        lines += [""]
        if desc:
            lines += [desc]
            lines += [""]
        if intro:
            lines += [intro]
            lines += [""]

        if usage:
            lines += ["## Usage"]
            lines += [usage]
            lines += [""]

        if self.config_obj.get("dependencies", None) is not None and not "packages" in exclude:
            dependencies = copy.copy(self.config_obj["dependencies"])
            child_packages = self.get_child_project_names(absolute=False)
            display_dependencies = []
            for alias in child_packages:
                if alias in dependencies and dependencies[alias].get("onlyInRoot", False) and self.name != "//":
                    continue
                display_dependencies.append(alias)

            if display_dependencies:
                lines += ["## Sub-Packages"]
                lines += [""]
                for alias in display_dependencies:
                    import_config = dependencies.get(alias, {})
                    columns = []

                    if "type" not in import_config or import_config["type"] == "local":
                        lines += [
                            "### [%s](%s)"
                            % (
                                alias,
                                os.path.join(
                                    return_path,
                                    import_config.get("path", alias),
                                    "README.md",
                                ),
                            )
                        ]
                    elif import_config["type"] == "git":
                        lines += ["### [%s](%s)" % (import_config["name"], import_config["url"])]
                    else:
                        lines += ["### %s" % import_config.get("name", alias)]

                    if "desc" in import_config:
                        columns += [import_config["desc"]]
                    elif not columns:
                        # TODO(clairbee): is there an easy and reiable way to pull the descriptions from sub-packages?
                        # columns += ["***Not documented yet.***"]
                        pass

                    if len(columns) > 1:
                        lines += ["<table><tr>"]
                        lines += map(lambda c: "<td valign=top>" + c + "</td>", columns)
                        lines += ["</tr></table>"]
                    else:
                        lines += columns
                    lines += [""]

        def add_section(name, display_name, shape, render_cfg):
            config = shape.config

            if "type" in config and config["type"] == "alias" and "aliases" in exclude:
                return []

            path = None
            if "path" in config:
                path = config["path"]
            else:
                path = name
                if "type" in config:
                    if config["type"] == "cadquery" or config["type"] == "build123d" or config["type"] == "sdf":
                        path += ".py"
                    elif config["type"] == "openscad":
                        path += ".scad"
                    else:
                        path += "." + config["type"]

            columns = []
            img_text, test_image_path = self._readme_image(name, render_cfg, return_path, config)

            if img_text is None or not os.path.exists(os.path.join(output_dir, test_image_path)):
                pc_logging.warn("Skipping rendering of %s: no image found at %s" % (name, test_image_path))
                return []

            if path:
                img_text = '<a href="%s">%s</a>' % (path, img_text)
            columns += [img_text]

            if "desc" in config:
                columns += [config["desc"]]

            if "parameters" in config:
                parameters = "Parameters:<br/><ul>\n"
                for param_name, param in config["parameters"].items():
                    if "enum" in param:
                        value = "<ul>\n"
                        for enum_value in param["enum"]:
                            if enum_value == param["default"]:
                                value += "<li><b>%s</b></li>\n" % enum_value
                            else:
                                value += "<li>%s</li>" % enum_value
                        value += "</ul>\n"
                    else:
                        value = param["default"]
                    parameters += "<li>%s: %s</li>\n" % (param_name, value)
                parameters += "</ul>\n"
                columns += [parameters]

            if not "images" in config and "desc" in config and "INSERT_IMAGE_HERE" in config["desc"]:
                config["images"] = list(
                    re.findall(
                        r"INSERT_IMAGE_HERE\(([^)]*)\)",
                        config["desc"],
                        re.MULTILINE,
                    ),
                )
            if "images" in config:
                images = "Input images:\n"
                for image in config["images"]:
                    images += (
                        '</br><img src="%s" alt="%s" style="width: auto; height: auto; max-width: 200px; max-height: 200px;" />\n'
                        % (
                            image,
                            image,
                        )
                    )
                columns += [images]

            if "aliases" in config:
                aliases = "Aliases:<br/><ul>"
                for alias in config["aliases"]:
                    aliases += "<li>%s</li>" % alias
                aliases += "</ul>"
                columns += [aliases]

            if hasattr(shape, "interfaces"):
                interfaces = "Interfaces:<br/>"
                for interface in shape.interfaces:
                    interfaces += "- %s<br/>" % interface.name
                columns += [interfaces]

            lines = ["### %s" % display_name]
            if len(columns) > 1:
                lines += ["<table><tr>"]
                lines += map(lambda c: "<td valign=top>" + c + "</td>", columns)
                lines += ["</tr></table>"]
            else:
                lines += columns
            lines += [""]
            return lines

        if self.assemblies and not "assemblies" in exclude:
            lines += ["## Assemblies"]
            lines += [""]
            shape_names = sorted(self.assemblies.keys())
            for name in shape_names:
                shape = self.assemblies[name]
                if shape.config["type"] == "alias":
                    source_path = self.normalize(shape.config["source_resolved"])
                    shape = self.ctx.get_assembly(source_path)
                    display_name = name + " (alias to " + shape.name + ")"
                else:
                    display_name = name
                lines += add_section(name, display_name, shape, render_cfg)

        if self.parts and not "parts" in exclude:
            lines += ["## Parts"]
            lines += [""]
            shape_names = sorted(self.parts.keys())
            for name in shape_names:
                shape = self.parts[name]
                if shape.config["type"] == "alias":
                    source_path = self.normalize(shape.config["source_resolved"])
                    shape = self.ctx.get_part(source_path)
                    display_name = name + " (alias to " + shape.name + ")"
                else:
                    display_name = name
                lines += add_section(name, display_name, shape, render_cfg)

        if self.interfaces and not "interfaces" in exclude:
            lines += ["## Interfaces"]
            lines += [""]
            shape_names = sorted(self.interfaces.keys())
            for name in shape_names:
                shape = self.interfaces[name]
                lines += add_section(name, name, shape, render_cfg)

        if self.sketches and not "sketches" in exclude:
            lines += ["## Sketches"]
            lines += [""]
            shape_names = sorted(self.sketches.keys())
            for name in shape_names:
                shape = self.sketches[name]
                lines += add_section(name, name, shape, render_cfg)

        lines += [
            "<br/><br/>",
            "",
            "*Generated by [PartCAD](https://partcad.org/)*",
        ]

        lines = map(lambda s: s + "\n", lines)

        f = open(path, "w")
        f.writelines(lines)
        f.close()
