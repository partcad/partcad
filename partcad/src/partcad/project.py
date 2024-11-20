#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.

import asyncio
import copy
import os

# from pprint import pformat
import ruamel.yaml
import threading
import typing

from . import consts
from . import factory
from . import logging as pc_logging
from . import project_config
from . import interface
from . import sketch
from . import sketch_config
from .sketch_factory_alias import SketchFactoryAlias
from .sketch_factory_enrich import SketchFactoryEnrich
from .sketch_factory_basic import SketchFactoryBasic
from .sketch_factory_dxf import SketchFactoryDxf
from .sketch_factory_svg import SketchFactorySvg
from .sketch_factory_build123d import SketchFactoryBuild123d
from .sketch_factory_cadquery import SketchFactoryCadquery
from . import part
from . import part_config
from .part_factory_extrude import PartFactoryExtrude
from . import part_factory_scad as pfscad
from . import part_factory_step as pfs
from . import part_factory_stl as pfstl
from . import part_factory_3mf as pf3
from .part_factory_ai_cadquery import PartFactoryAiCadquery
from .part_factory_ai_build123d import PartFactoryAiBuild123d
from .part_factory_ai_openscad import PartFactoryAiScad
from . import part_factory_cadquery as pfc
from . import part_factory_build123d as pfb
from . import part_factory_alias as pfa
from . import part_factory_enrich as pfe
from . import assembly
from . import assembly_config
from . import provider
from . import provider_config
from .render import render_cfg_merge
from .utils import resolve_resource_path, normalize_resource_path


# TODO FIXME NOCOMMIT: switch from RLock back to Lock


class Project(project_config.Configuration):

    class InterfaceLock(object):
        def __init__(self, prj, interface_name: str):
            prj.interface_locks_lock.acquire()
            if not interface_name in prj.interface_locks:
                prj.interface_locks[interface_name] = threading.RLock()
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
                prj.sketch_locks[sketch_name] = threading.RLock()
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
                prj.part_locks[part_name] = threading.RLock()
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
                prj.assembly_locks[assembly_name] = threading.RLock()
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
                prj.provider_locks[provider_name] = threading.RLock()
            self.lock = prj.provider_locks[provider_name]
            prj.provider_locks_lock.release()

        def __enter__(self, *_args):
            self.lock.acquire()

        def __exit__(self, *_args):
            self.lock.release()

    def __init__(self, ctx, name, path, include_paths=[]):
        super().__init__(name, path, include_paths)
        self.ctx = ctx

        # Protect the critical sections from access in different threads
        self.lock = threading.Lock()

        # The 'path' parameter is the config filename or the directory
        # where 'partcad.yaml' is present.
        # 'self.path' has to be set to the directory name.
        dir_name = path
        if not os.path.isdir(dir_name):
            dir_name = os.path.dirname(os.path.abspath(dir_name))
        self.path = dir_name

        # self.interface_configs contains the configs of all the interfaces in this project
        if (
            "interfaces" in self.config_obj
            and not self.config_obj["interfaces"] is None
        ):
            self.interface_configs = self.config_obj["interfaces"]
            # pc_logging.debug(
            #     "Interfaces: %s" % str(self.interface_configs.keys())
            # )
        else:
            self.interface_configs = {}
        # self.interfaces contains all the initialized interfaces in this project
        self.interfaces = {}
        self.interface_locks = {}
        self.interface_locks_lock = threading.Lock()

        # self.sketch_configs contains the configs of all the sketches in this project
        if (
            "sketches" in self.config_obj
            and not self.config_obj["sketches"] is None
        ):
            self.sketch_configs = self.config_obj["sketches"]
        else:
            self.sketch_configs = {}
        # self.sketches contains all the initialized sketches in this project
        self.sketches = {}
        self.sketch_locks = {}
        self.sketch_locks_lock = threading.Lock()

        # self.part_configs contains the configs of all the parts in this project
        if "parts" in self.config_obj and not self.config_obj["parts"] is None:
            self.part_configs = self.config_obj["parts"]
        else:
            self.part_configs = {}
        # self.parts contains all the initialized parts in this project
        self.parts = {}
        self.part_locks = {}
        self.part_locks_lock = threading.Lock()

        # self.assembly_configs contains the configs of all the assemblies in this project
        if (
            "assemblies" in self.config_obj
            and not self.config_obj["assemblies"] is None
        ):
            self.assembly_configs = self.config_obj["assemblies"]
        else:
            self.assembly_configs = {}
        # self.assemblies contains all the initialized assemblies in this project
        self.assemblies = {}
        self.assembly_locks = {}
        self.assembly_locks_lock = threading.Lock()

        # self.provider_configs contains the configs of all the providers in this project
        if (
            "providers" in self.config_obj
            and not self.config_obj["providers"] is None
        ):
            self.provider_configs = self.config_obj["providers"]
        else:
            self.provider_configs = {}
        # self.providers contains all the initialized providers in this project
        self.providers = {}
        self.provider_locks = {}
        self.provider_locks_lock = threading.Lock()

        if (
            "desc" in self.config_obj
            and not self.config_obj["desc"] is None
            and isinstance(self.config_obj["desc"], str)
        ):
            self.desc = self.config_obj["desc"].strip()
        else:
            self.desc = ""

        self.init_sketches()
        self.init_interfaces()  # After sketches
        self.init_mates()  # After interfaces
        self.init_parts()  # After sketches and interfaces, and mates
        self.init_assemblies()  # after parts
        self.init_providers()  # after parts
        self.init_suppliers()  # after suppliers

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

    def get_child_project_names(self):
        if self.broken:
            pc_logging.info("Ignoring the broken package: %s" % self.name)
            return

        children = list()
        subfolders = [f.name for f in os.scandir(self.config_dir) if f.is_dir()]
        for subdir in list(subfolders):
            if os.path.exists(
                os.path.join(
                    self.config_dir,
                    subdir,
                    consts.DEFAULT_PACKAGE_CONFIG,
                )
            ):
                children.append(self.name + "/" + subdir)

        if (
            "import" in self.config_obj
            and not self.config_obj["import"] is None
        ):
            imports = self.config_obj["import"]
            if not self.config_obj.get("isRoot", False):
                filtered = filter(
                    lambda x: "onlyInRoot" not in imports[x]
                    or not imports[x]["onlyInRoot"],
                    imports,
                )
                imports = list(filtered)
            children.extend(
                list(
                    map(
                        lambda project_name: self.name + "/" + project_name,
                        imports,
                    )
                )
            )
        return children

    def init_mates(self):
        mates = self.config_obj.get("mates", {})
        for source_interface_name, mate_config in mates.items():
            if not ":" in source_interface_name:
                source_interface_name = self.name + ":" + source_interface_name
            source_package_name, short_source_interface_name = (
                resolve_resource_path(self.name, source_interface_name)
            )

            # Short-circut the case when the source package is the current one
            # to avoid recursive package loading
            if source_package_name == self.name:
                source_package = self
            else:
                source_package = self.ctx.get_project(source_package_name)

            source_interface = source_package.get_interface(
                short_source_interface_name
            )
            if source_interface is None:
                raise Exception(
                    "Failed to find the source interface to mate: %s"
                    % source_interface_name
                )
            source_interface.add_mates(self, mate_config)

    def get_interface_config(self, interface_name):
        if not interface_name in self.interface_configs:
            return None
        return self.interface_configs[interface_name]

    def init_interfaces(self):
        if self.interface_configs is None:
            return

        for interface_name in self.interface_configs.keys():
            config = self.get_interface_config(interface_name)
            config["name"] = interface_name
            self.init_interface_by_config(config)

    def init_interface_by_config(self, config, source_project=None):
        if source_project is None:
            source_project = self

        interface_name: str = config["name"]
        self.interfaces[interface_name] = interface.Interface(
            interface_name, source_project, config
        )

    def get_interface(self, interface_name) -> interface.Interface:
        self.lock.acquire()

        # See if it's already available
        if (
            interface_name in self.interfaces
            and not self.interfaces[interface_name] is None
        ):
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
        if not sketch_name in self.sketch_configs:
            return None
        return self.sketch_configs[sketch_name]

    def init_sketches(self):
        if self.sketch_configs is None:
            return

        for sketch_name in self.sketch_configs:
            config = self.get_sketch_config(sketch_name)
            config = sketch_config.SketchConfiguration.normalize(
                sketch_name, config
            )
            self.init_sketch_by_config(config)

    def init_sketch_by_config(self, config, source_project=None):
        if source_project is None:
            source_project = self

        sketch_name: str = config["name"]

        if not "type" in config:
            raise Exception(
                "ERROR: Sketch type is not specified: %s: %s"
                % (sketch_name, config)
            )
        elif config["type"] == "build123d":
            SketchFactoryBuild123d(self.ctx, source_project, self, config)
        elif config["type"] == "cadquery":
            SketchFactoryCadquery(self.ctx, source_project, self, config)
        elif config["type"] == "dxf":
            SketchFactoryDxf(self.ctx, source_project, self, config)
        elif config["type"] == "svg":
            SketchFactorySvg(self.ctx, source_project, self, config)
        elif config["type"] == "basic":
            SketchFactoryBasic(self.ctx, source_project, self, config)
        elif config["type"] == "alias":
            SketchFactoryAlias(self.ctx, source_project, self, config)
        elif config["type"] == "enrich":
            SketchFactoryEnrich(self.ctx, source_project, self, config)
        else:
            pc_logging.error(
                "Invalid sketch type encountered: %s: %s"
                % (sketch_name, config)
            )
            return None

        # Initialize aliases if they are declared implicitly
        if "aliases" in config and not config["aliases"] is None:
            for alias in config["aliases"]:
                if ";" in sketch_name:
                    # Copy parameters
                    alias += sketch_name[sketch_name.index(";") :]
                alias_sketch_config = {
                    "type": "alias",
                    "name": alias,
                    "source": ":" + sketch_name,
                }
                alias_sketch_config = (
                    sketch_config.SketchConfiguration.normalize(
                        alias, alias_sketch_config
                    )
                )
                pfa.SketchFactoryAlias(
                    self.ctx, source_project, self, alias_sketch_config
                )

    def get_sketch(self, sketch_name, func_params=None) -> sketch.Sketch:
        if func_params is None or not func_params:
            has_func_params = False
        else:
            has_func_params = True

        params: dict[str, typing.Any] = {}
        if ";" in sketch_name:
            has_name_params = True
            base_sketch_name = sketch_name.split(";")[0]
            sketch_name_params_string = sketch_name.split(";")[1]

            for kv in sketch_name_params_string.split[","]:
                k, v = kv.split("")
                params[k] = v
        else:
            has_name_params = False
            base_sketch_name = sketch_name

        if has_func_params:
            params = {**params, **func_params}
            has_name_params = True

        if not has_name_params:
            result_name = sketch_name
        else:
            # Determine the name we want this parameterized sketch to have
            result_name = base_sketch_name + ";"
            result_name += ",".join(
                map(lambda n: n + "=" + str(params[n]), sorted(params))
            )

        self.lock.acquire()

        # See if it's already available
        if (
            result_name in self.sketches
            and not self.sketches[result_name] is None
        ):
            p = self.sketches[result_name]
            self.lock.release()
            return p

        with Project.SketchLock(self, result_name):
            # Release the project lock, and continue with holding the sketch lock only
            self.lock.release()

            if not has_name_params:
                # This is just a regular sketch name, no params (sketch_name == result_name)
                if not sketch_name in self.sketch_configs:
                    # We don't know anything about such a sketch
                    pc_logging.error(
                        "Sketch '%s' not found in '%s'", sketch_name, self.name
                    )
                    return None
                # This is not yet created (invalidated?)
                config = self.get_sketch_config(sketch_name)
                config = sketch_config.SketchConfiguration.normalize(
                    sketch_name, config
                )
                self.init_sketch_by_config(config)

                if (
                    not sketch_name in self.sketches
                    or self.sketches[sketch_name] is None
                ):
                    pc_logging.error(
                        "Failed to instantiate a non-parametrized sketch %s"
                        % sketch_name
                    )
                return self.sketches[sketch_name]

            # This sketch has params (sketch_name != result_name)
            if not base_sketch_name in self.sketches:
                pc_logging.error(
                    "Base sketch '%s' not found in '%s'",
                    base_sketch_name,
                    self.name,
                )
                return None
            pc_logging.debug("Found the base sketch: %s" % base_sketch_name)

            # Now we have the original sketch name and the complete set of parameters
            config = self.sketch_configs[base_sketch_name]
            if config is None:
                pc_logging.error(
                    "The config for the base sketch '%s' is not found in '%s'",
                    base_sketch_name,
                    self.name,
                )
                return None

            config = copy.deepcopy(config)
            if (
                not "parameters" in config or config["parameters"] is None
            ) and (config["type"] != "enrich"):
                pc_logging.error(
                    "Attempt to parametrize '%s' of '%s' which has no parameters: %s",
                    base_sketch_name,
                    self.name,
                    str(config),
                )
                return None

            # Expand the config object so that the parameter values can be set
            config = sketch_config.SketchConfiguration.normalize(
                result_name, config
            )
            config["orig_name"] = base_sketch_name

            # Fill in the parameter values
            param_name: str
            if "parameters" in config and not config["parameters"] is None:
                # Filling "parameters"
                for param_name, param_value in params.items():
                    if config["parameters"][param_name]["type"] == "string":
                        config["parameters"][param_name]["default"] = str(
                            param_value
                        )
                    elif config["parameters"][param_name]["type"] == "int":
                        config["parameters"][param_name]["default"] = int(
                            param_value
                        )
                    elif config["parameters"][param_name]["type"] == "float":
                        config["parameters"][param_name]["default"] = float(
                            param_value
                        )
                    elif config["parameters"][param_name]["type"] == "bool":
                        if isinstance(param_value, str):
                            if param_value.lower() == "true":
                                config["parameters"][param_name][
                                    "default"
                                ] = True
                            else:
                                config["parameters"][param_name][
                                    "default"
                                ] = False
                        else:
                            config["parameters"][param_name]["default"] = bool(
                                param_value
                            )
                    elif config["parameters"][param_name]["type"] == "array":
                        config["parameters"][param_name][
                            "default"
                        ] = param_value
            else:
                # Filling "with"
                if not "with" in config:
                    config["with"] = {}
                for param_name, param_value in params.items():
                    config["with"][param_name] = param_value

            # Now initialize the sketch
            pc_logging.debug(
                "Initializing a parametrized sketch: %s" % result_name
            )
            # pc_logging.debug(
            #     "Initializing a parametrized sketch using the following config: %s"
            #     % pformat(config)
            # )
            self.init_sketch_by_config(config)

            # See if it worked
            if not result_name in self.sketches:
                pc_logging.error(
                    "Failed to instantiate parameterized sketch '%s' in '%s'",
                    result_name,
                    self.name,
                )
                return None

            return self.sketches[result_name]

    def get_part_config(self, part_name):
        if not part_name in self.part_configs:
            return None
        return self.part_configs[part_name]

    def init_parts(self):
        if self.part_configs is None:
            return

        for part_name in self.part_configs:
            config = self.get_part_config(part_name)
            config = part_config.PartConfiguration.normalize(part_name, config)
            self.init_part_by_config(config)

    def init_part_by_config(self, config, source_project=None):
        if source_project is None:
            source_project = self

        part_name: str = config["name"]

        if not "type" in config:
            raise Exception(
                "ERROR: Part type is not specified: %s: %s"
                % (part_name, config)
            )
        elif config["type"] == "ai-cadquery":
            PartFactoryAiCadquery(self.ctx, source_project, self, config)
        elif config["type"] == "ai-build123d":
            PartFactoryAiBuild123d(self.ctx, source_project, self, config)
        elif config["type"] == "ai-openscad":
            PartFactoryAiScad(self.ctx, source_project, self, config)
        elif config["type"] == "cadquery":
            pfc.PartFactoryCadquery(self.ctx, source_project, self, config)
        elif config["type"] == "build123d":
            pfb.PartFactoryBuild123d(self.ctx, source_project, self, config)
        elif config["type"] == "step":
            pfs.PartFactoryStep(self.ctx, source_project, self, config)
        elif config["type"] == "stl":
            pfstl.PartFactoryStl(self.ctx, source_project, self, config)
        elif config["type"] == "3mf":
            pf3.PartFactory3mf(self.ctx, source_project, self, config)
        elif config["type"] == "scad":
            pfscad.PartFactoryScad(self.ctx, source_project, self, config)
        elif config["type"] == "extrude":
            PartFactoryExtrude(self.ctx, source_project, self, config)
        elif config["type"] == "alias":
            pfa.PartFactoryAlias(self.ctx, source_project, self, config)
        elif config["type"] == "enrich":
            pfe.PartFactoryEnrich(self.ctx, source_project, self, config)
        else:
            pc_logging.error(
                "Invalid part type encountered: %s: %s" % (part_name, config)
            )
            return None

        # Initialize aliases if they are declared implicitly
        if "aliases" in config and not config["aliases"] is None:
            for alias in config["aliases"]:
                if ";" in part_name:
                    # Copy parameters
                    alias += part_name[part_name.index(";") :]
                alias_part_config = {
                    "type": "alias",
                    "name": alias,
                    "source": ":" + part_name,
                }
                alias_part_config = part_config.PartConfiguration.normalize(
                    alias, alias_part_config
                )
                pfa.PartFactoryAlias(
                    self.ctx, source_project, self, alias_part_config
                )

    def get_part(self, part_name, func_params=None, quiet=False) -> part.Part:
        if func_params is None or not func_params:
            has_func_params = False
        else:
            has_func_params = True

        params: dict[str, typing.Any] = {}
        if ";" in part_name:
            has_name_params = True
            base_part_name = part_name.split(";")[0]
            part_name_params_string = part_name.split(";")[1]

            for kv in part_name_params_string.split(","):
                k, v = kv.split("=")
                params[k] = v
        else:
            has_name_params = False
            base_part_name = part_name

        if has_func_params:
            params = {**params, **func_params}
            has_name_params = True

        if not has_name_params:
            result_name = part_name
        else:
            # Determine the name we want this parameterized part to have
            result_name = base_part_name + ";"
            result_name += ",".join(
                map(lambda n: n + "=" + str(params[n]), sorted(params))
            )

        self.lock.acquire()

        # See if it's already available
        if result_name in self.parts and not self.parts[result_name] is None:
            p = self.parts[result_name]
            self.lock.release()
            return p

        with Project.PartLock(self, result_name):
            # Release the project lock, and continue with holding the part lock only
            self.lock.release()

            if not has_name_params:
                # This is just a regular part name, no params (part_name == result_name)
                if not part_name in self.part_configs:
                    # We don't know anything about such a part
                    if not quiet:
                        pc_logging.error(
                            "Part '%s' not found in '%s'", part_name, self.name
                        )
                    return None
                # This is not yet created (invalidated?)
                config = self.get_part_config(part_name)
                config = part_config.PartConfiguration.normalize(
                    part_name, config
                )
                self.init_part_by_config(config)

                if not part_name in self.parts or self.parts[part_name] is None:
                    pc_logging.error(
                        "Failed to instantiate a non-parametrized part %s"
                        % part_name
                    )
                return self.parts[part_name]

            # This part has params (part_name != result_name)
            if not base_part_name in self.parts:
                pc_logging.error(
                    "Base part '%s' not found in '%s'",
                    base_part_name,
                    self.name,
                )
                return None
            pc_logging.debug("Found the base part: %s" % base_part_name)

            # Now we have the original part name and the complete set of parameters
            config = self.part_configs[base_part_name]
            if config is None:
                pc_logging.error(
                    "The config for the base part '%s' is not found in '%s'",
                    base_part_name,
                    self.name,
                )
                return None

            config = copy.deepcopy(config)
            if (
                not "parameters" in config or config["parameters"] is None
            ) and (config["type"] != "enrich"):
                pc_logging.error(
                    "Attempt to parametrize '%s' of '%s' which has no parameters: %s",
                    base_part_name,
                    self.name,
                    str(config),
                )
                return None

            # Expand the config object so that the parameter values can be set
            config = part_config.PartConfiguration.normalize(
                result_name, config
            )
            config["orig_name"] = base_part_name

            # Fill in the parameter values
            param_name: str
            if "parameters" in config and not config["parameters"] is None:
                # Filling "parameters"
                for param_name, param_value in params.items():
                    if config["parameters"][param_name]["type"] == "string":
                        config["parameters"][param_name]["default"] = str(
                            param_value
                        )
                    elif config["parameters"][param_name]["type"] == "int":
                        config["parameters"][param_name]["default"] = int(
                            param_value
                        )
                    elif config["parameters"][param_name]["type"] == "float":
                        config["parameters"][param_name]["default"] = float(
                            param_value
                        )
                    elif config["parameters"][param_name]["type"] == "bool":
                        if isinstance(param_value, str):
                            if param_value.lower() == "true":
                                config["parameters"][param_name][
                                    "default"
                                ] = True
                            else:
                                config["parameters"][param_name][
                                    "default"
                                ] = False
                        else:
                            config["parameters"][param_name]["default"] = bool(
                                param_value
                            )
                    elif config["parameters"][param_name]["type"] == "array":
                        config["parameters"][param_name][
                            "default"
                        ] = param_value
            else:
                # Filling "with"
                if not "with" in config:
                    config["with"] = {}
                for param_name, param_value in params.items():
                    config["with"][param_name] = param_value

            # Now initialize the part
            pc_logging.debug(
                "Initializing a parametrized part: %s" % result_name
            )
            # pc_logging.debug(
            #     "Initializing a parametrized part using the following config: %s"
            #     % pformat(config)
            # )
            self.init_part_by_config(config)

            # See if it worked
            if not result_name in self.parts:
                pc_logging.error(
                    "Failed to instantiate parameterized part '%s' in '%s'",
                    result_name,
                    self.name,
                )
                return None

            return self.parts[result_name]

    def get_assembly_config(self, assembly_name):
        if not assembly_name in self.assembly_configs:
            return None
        return self.assembly_configs[assembly_name]

    def init_assemblies(self):
        if self.assembly_configs is None:
            return

        for assembly_name in self.assembly_configs:
            config = self.get_assembly_config(assembly_name)
            config = assembly_config.AssemblyConfiguration.normalize(
                assembly_name, config
            )
            factory.instantiate(
                "assembly", config["type"], self.ctx, self, self, config
            )

    def get_assembly(
        self, assembly_name, func_params=None
    ) -> assembly.Assembly:
        if func_params is None or not func_params:
            has_func_params = False
        else:
            has_func_params = True

        params: dict[str, typing.Any] = {}
        if ";" in assembly_name:
            has_name_params = True
            base_assembly_name = assembly_name.split(";")[0]
            assembly_name_params_string = assembly_name.split(";")[1]

            for kv in assembly_name_params_string.split(","):
                k, v = kv.split("=")
                params[k] = v
        else:
            has_name_params = False
            base_assembly_name = assembly_name

        if has_func_params:
            params = {**params, **func_params}
            has_name_params = True

        if not has_name_params:
            result_name = assembly_name
        else:
            # Determine the name we want this parameterized assembly to have
            result_name = base_assembly_name + ";"
            result_name += ",".join(
                map(lambda n: n + "=" + str(params[n]), sorted(params))
            )

        self.lock.acquire()

        # See if it's already available
        if (
            result_name in self.assemblies
            and not self.assemblies[result_name] is None
        ):
            p = self.assemblies[result_name]
            self.lock.release()
            return p

        with Project.AssemblyLock(self, result_name):
            # Release the project lock, and continue with holding the part lock only
            self.lock.release()

            if not has_name_params:
                # This is just a regular assembly name, no params (assembly_name == result_name)
                if not assembly_name in self.assembly_configs:
                    # We don't know anything about such an assembly
                    pc_logging.error(
                        "Assembly '%s' not found in '%s'",
                        assembly_name,
                        self.name,
                    )
                    return None
                # This is not yet created (invalidated?)
                config = self.get_assembly_config(assembly_name)
                config = assembly_config.AssemblyConfiguration.normalize(
                    assembly_name, config
                )
                factory.instantiate(
                    "assembly", config["type"], self.ctx, self, self, config
                )

                if (
                    not assembly_name in self.assemblies
                    or self.assemblies[assembly_name] is None
                ):
                    pc_logging.error(
                        "Failed to instantiate a non-parametrized assembly %s"
                        % assembly_name
                    )
                return self.assemblies[assembly_name]

            # This assembly has params (part_name != result_name)
            if not base_assembly_name in self.assemblies:
                pc_logging.error(
                    "Base assembly '%s' not found in '%s'",
                    base_assembly_name,
                    self.name,
                )
                return None
            pc_logging.debug("Found the base assembly: %s" % base_assembly_name)

            # Now we have the original assembly name and the complete set of parameters
            config = self.assembly_configs[base_assembly_name]
            if config is None:
                pc_logging.error(
                    "The config for the base assembly '%s' is not found in '%s'",
                    base_assembly_name,
                    self.name,
                )
                return None

            config = copy.deepcopy(config)
            if (
                not "parameters" in config or config["parameters"] is None
            ) and (config["type"] != "enrich"):
                pc_logging.error(
                    "Attempt to parametrize '%s' of '%s' which has no parameters: %s",
                    base_assembly_name,
                    self.name,
                    str(config),
                )
                return None

            # Expand the config object so that the parameter values can be set
            config = assembly_config.AssemblyConfiguration.normalize(
                result_name, config
            )
            config["orig_name"] = base_assembly_name

            # Fill in the parameter values
            param_name: str
            if "parameters" in config and not config["parameters"] is None:
                # Filling "parameters"
                for param_name, param_value in params.items():
                    if config["parameters"][param_name]["type"] == "string":
                        config["parameters"][param_name]["default"] = str(
                            param_value
                        )
                    elif config["parameters"][param_name]["type"] == "int":
                        config["parameters"][param_name]["default"] = int(
                            param_value
                        )
                    elif config["parameters"][param_name]["type"] == "float":
                        config["parameters"][param_name]["default"] = float(
                            param_value
                        )
                    elif config["parameters"][param_name]["type"] == "bool":
                        if isinstance(param_value, str):
                            if param_value.lower() == "true":
                                config["parameters"][param_name][
                                    "default"
                                ] = True
                            else:
                                config["parameters"][param_name][
                                    "default"
                                ] = False
                        else:
                            config["parameters"][param_name]["default"] = bool(
                                param_value
                            )
                    elif config["parameters"][param_name]["type"] == "array":
                        config["parameters"][param_name][
                            "default"
                        ] = param_value
            else:
                # Filling "with"
                if not "with" in config:
                    config["with"] = {}
                for param_name, param_value in params.items():
                    config["with"][param_name] = param_value

            # Now initialize the assembly
            pc_logging.debug(
                "Initializing a parametrized assembly: %s" % result_name
            )
            # pc_logging.debug(
            #     "Initializing a parametrized assembly using the following config: %s"
            #     % pformat(config)
            # )
            factory.instantiate(
                "assembly", config["type"], self.ctx, self, self, config
            )

            # See if it worked
            if not result_name in self.assemblies:
                pc_logging.error(
                    "Failed to instantiate parameterized assembly '%s' in '%s'",
                    result_name,
                    self.name,
                )
                return None

            return self.assemblies[result_name]

    def get_provider_config(self, provider_name):
        if not provider_name in self.provider_configs:
            return None
        return self.provider_configs[provider_name]

    def init_providers(self):
        if self.provider_configs is None:
            return

        for provider_name in self.provider_configs:
            config = self.get_provider_config(provider_name)
            config = provider_config.ProviderConfiguration.normalize(
                provider_name, config
            )
            factory.instantiate(
                "provider", config["type"], self.ctx, self, self, config
            )

    # TODO(clairbee): either call init_*_by_config or call
    #                  factory->instantite everywhere.
    #                  Recall what waas the thinking about it when the factory
    #                  class was introduced.

    def init_provider_by_config(self, config, source_project=None):
        if source_project is None:
            source_project = self
        factory.instantiate(
            "provider", config["type"], self.ctx, source_project, self, config
        )

    def get_provider(
        self, provider_name, func_params=None
    ) -> provider.Provider:
        if func_params is None or not func_params:
            has_func_params = False
        else:
            has_func_params = True

        params: dict[str, typing.Any] = {}
        if ";" in provider_name:
            has_name_params = True
            base_provider_name = provider_name.split(";")[0]
            provider_name_params_string = provider_name.split(";")[1]

            for kv in provider_name_params_string.split(","):
                k, v = kv.split("=")
                params[k] = v
        else:
            has_name_params = False
            base_provider_name = provider_name

        if has_func_params:
            params = {**params, **func_params}
            has_name_params = True

        if not has_name_params:
            result_name = provider_name
        else:
            # Determine the name we want this parameterized provider to have
            result_name = base_provider_name + ";"
            result_name += ",".join(
                map(lambda n: n + "=" + str(params[n]), sorted(params))
            )

        self.lock.acquire()

        # See if it's already available
        if (
            result_name in self.providers
            and not self.providers[result_name] is None
        ):
            p = self.providers[result_name]
            self.lock.release()
            return p

        with Project.ProviderLock(self, result_name):
            # Release the project lock, and continue with holding the part lock only
            self.lock.release()

            if not has_name_params:
                # This is just a regular provider name, no params (provider_name == result_name)
                if not provider_name in self.provider_configs:
                    # We don't know anything about such an provider
                    pc_logging.error(
                        "Provider '%s' not found in '%s'",
                        provider_name,
                        self.name,
                    )
                    return None
                # This is not yet created (invalidated?)
                config = self.get_provider_config(provider_name)
                config = provider_config.ProviderConfiguration.normalize(
                    provider_name, config
                )
                factory.instantiate(
                    "provider", config["type"], self.ctx, self, self, config
                )

                if (
                    not provider_name in self.providers
                    or self.providers[provider_name] is None
                ):
                    pc_logging.error(
                        "Failed to instantiate a non-parametrized provider %s"
                        % provider_name
                    )
                return self.providers[provider_name]

            # This provider has params (part_name != result_name)
            if not base_provider_name in self.providers:
                pc_logging.error(
                    "Base provider '%s' not found in '%s'",
                    base_provider_name,
                    self.name,
                )
                return None
            pc_logging.debug("Found the base provider: %s" % base_provider_name)

            # Now we have the original assembly name and the complete set of parameters
            config = self.provider_configs[base_provider_name]
            if config is None:
                pc_logging.error(
                    "The config for the base provider '%s' is not found in '%s'",
                    base_provider_name,
                    self.name,
                )
                return None

            config = copy.deepcopy(config)
            if (
                not "parameters" in config or config["parameters"] is None
            ) and (config["type"] != "enrich"):
                pc_logging.error(
                    "Attempt to parametrize '%s' of '%s' which has no parameters: %s",
                    base_provider_name,
                    self.name,
                    str(config),
                )
                return None

            # Expand the config object so that the parameter values can be set
            config = provider_config.ProviderConfiguration.normalize(
                result_name, config
            )
            config["orig_name"] = base_provider_name

            # Fill in the parameter values
            param_name: str
            if "parameters" in config and not config["parameters"] is None:
                # Filling "parameters"
                for param_name, param_value in params.items():
                    if config["parameters"][param_name]["type"] == "string":
                        config["parameters"][param_name]["default"] = str(
                            param_value
                        )
                    elif config["parameters"][param_name]["type"] == "int":
                        config["parameters"][param_name]["default"] = int(
                            param_value
                        )
                    elif config["parameters"][param_name]["type"] == "float":
                        config["parameters"][param_name]["default"] = float(
                            param_value
                        )
                    elif config["parameters"][param_name]["type"] == "bool":
                        if isinstance(param_value, str):
                            if param_value.lower() == "true":
                                config["parameters"][param_name][
                                    "default"
                                ] = True
                            else:
                                config["parameters"][param_name][
                                    "default"
                                ] = False
                        else:
                            config["parameters"][param_name]["default"] = bool(
                                param_value
                            )
                    elif config["parameters"][param_name]["type"] == "array":
                        config["parameters"][param_name][
                            "default"
                        ] = param_value
            else:
                # Filling "with"
                if not "with" in config:
                    config["with"] = {}
                for param_name, param_value in params.items():
                    config["with"][param_name] = param_value

            # Now initialize the provider
            pc_logging.debug(
                "Initializing a parametrized provider: %s" % result_name
            )
            # pc_logging.debug(
            #     "Initializing a parametrized provider using the following config: %s"
            #     % pformat(config)
            # )
            factory.instantiate(
                "provider", config["type"], self.ctx, self, self, config
            )

            # See if it worked
            if not result_name in self.providers:
                pc_logging.error(
                    "Failed to instantiate parameterized assembly '%s' in '%s'",
                    result_name,
                    self.name,
                )
                return None

            return self.providers[result_name]

    def get_suppliers(self, part_spec):
        # TODO(clirbee): return the eligible subset of suppliers
        # part_name = part_spec["name"]
        return self.suppliers

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

        for elem in config:
            if elem == "import":
                imports = config["import"]
                imports[alias] = {
                    location_param: location,
                    "type": location_type,
                }
                break  # no need to iterate further
        with open(self.config_path) as fp:
            yaml.dump(config, fp)
            fp.close()

    def _validate_path(self, path, extension) -> tuple[bool, str, str]:
        if not os.path.isabs(path):
            path = os.path.abspath(path)
        root = self.config_dir
        if not os.path.isabs(root):
            root = os.path.abspath(root)

        if not path.startswith(root):
            pc_logging.error("Can't add files outside of the package")
            return False, None, None

        path = path[len(root) :]
        if path[0] == os.path.sep:
            path = path[1:]

        name = path
        if name.endswith(".%s" % extension):
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

        valid, path, name = self._validate_path(path, ext)
        if not valid:
            return False

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

    def add_part(self, kind: str, path: str, config={}) -> bool:
        pc_logging.info("Adding the part %s of type %s" % (path, kind))
        ext_by_kind = {
            "cadquery": "py",
            "build123d": "py",
            "ai-cadquery": "py",
            "ai-openscad": "scad",
        }
        return self._add_component(
            kind,
            path,
            "parts",
            ext_by_kind,
            config,
        )

    def add_assembly(self, kind: str, path: str, config={}) -> bool:
        pc_logging.info("Adding the assembly %s of type %s" % (path, kind))
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

    def update_part_config(
        self, part_name, part_config_update: dict[str, typing.Any]
    ):
        pc_logging.debug(
            "Updating part config: %s: %s" % (part_name, part_config_update)
        )
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

    async def test_async(self):
        tasks = []
        for interface in self.interfaces.values():
            tasks.append(asyncio.create_task(interface.test_async()))
        for sketch in self.sketches.values():
            tasks.append(asyncio.create_task(sketch.test_async()))
        for part in self.parts.values():
            tasks.append(asyncio.create_task(part.test_async()))
        for assembly in self.assemblies.values():
            tasks.append(asyncio.create_task(assembly.test_async()))
        return await asyncio.gather(*tasks)

    def test(self):
        asyncio.run(self.test_async())

    async def render_async(
        self,
        sketches=None,
        interfaces=None,
        parts=None,
        assemblies=None,
        format=None,
        output_dir=None,
    ):
        with pc_logging.Action("RenderPkg", self.name):
            # Override the default output_dir.
            # TODO(clairbee): pass the preference downstream without making a
            # persistent change.
            if not output_dir is None:
                if (
                    not "render" in self.config_obj
                    or self.config_obj["render"] is None
                ):
                    self.config_obj["render"] = {}
                self.config_obj["render"]["output_dir"] = output_dir

            render = self.config_obj.get("render", {})
            if render is None:
                render = {}

            # Enumerating all parts and assemblies
            if sketches is None:
                sketches = []
                if (
                    "sketches" in self.config_obj
                    and not self.config_obj["sketches"] is None
                ):
                    sketches = self.config_obj["sketches"].keys()
            if interfaces is None:
                interfaces = []
                if (
                    "interfaces" in self.config_obj
                    and not self.config_obj["interfaces"] is None
                ):
                    interfaces = self.config_obj["interfaces"].keys()
            if parts is None:
                parts = []
                if (
                    "parts" in self.config_obj
                    and not self.config_obj["parts"] is None
                ):
                    parts = self.config_obj["parts"].keys()
            if assemblies is None:
                assemblies = []
                if (
                    "assemblies" in self.config_obj
                    and not self.config_obj["assemblies"] is None
                ):
                    assemblies = self.config_obj["assemblies"].keys()

            # Enumerate
            shapes = []
            for name in sketches:
                shape = self.get_sketch(name)
                shapes.append(shape)
            for name in interfaces:
                shape = self.get_interface(name)
                # TODO(clairbee): interfaces are not yet renderable.
                # shapes.append(shape)
            for name in parts:
                shape = self.get_part(name)
                shapes.append(shape)
            for name in assemblies:
                shape = self.get_assembly(name)
                shapes.append(shape)

            # Render
            tasks = []
            for shape in shapes:
                shape_render = copy.copy(render)
                if (
                    "render" in shape.config
                    and not shape.config["render"] is None
                ):
                    shape_render = render_cfg_merge(
                        shape_render, shape.config["render"]
                    )

                # Determine which formats need to be rendered.
                # The format needs to be rendered either if it's mentioned in the config
                # or if it's explicitly requested in the params (e.g. comes from the
                # command line).
                if (
                    "svg" in shape_render
                    and shape_render["svg"] is not None
                    and not isinstance(shape_render["svg"], str)
                    and shape.kind
                    in shape_render.get("svg", {}).get("exclude", [])
                ):
                    render_svg = False
                elif format is None and "svg" in shape_render:
                    render_svg = True
                elif not format is None and format == "svg":
                    render_svg = True
                else:
                    render_svg = False

                if (
                    "png" in shape_render
                    and shape_render["png"] is not None
                    and not isinstance(shape_render["png"], str)
                    and shape.kind
                    in shape_render.get("png", {}).get("exclude", [])
                ):
                    render_png = False
                elif format is None and "png" in shape_render:
                    render_png = True
                elif not format is None and format == "png":
                    render_png = True
                else:
                    render_png = False

                if (
                    "step" in shape_render
                    and shape_render["step"] is not None
                    and not isinstance(shape_render["step"], str)
                    and shape.kind
                    in shape_render.get("step", {}).get("exclude", [])
                ):
                    render_step = False
                elif format is None and "step" in shape_render:
                    render_step = True
                elif not format is None and format == "step":
                    render_step = True
                else:
                    render_step = False

                if (
                    "stl" in shape_render
                    and shape_render["stl"] is not None
                    and not isinstance(shape_render["stl"], str)
                    and shape.kind
                    in shape_render.get("stl", {}).get("exclude", [])
                ):
                    render_stl = False
                elif format is None and "stl" in shape_render:
                    render_stl = True
                elif not format is None and format == "stl":
                    render_stl = True
                else:
                    render_stl = False

                if (
                    "3mf" in shape_render
                    and shape_render["3mf"] is not None
                    and not isinstance(shape_render["3mf"], str)
                    and shape.kind
                    in shape_render.get("3mf", {}).get("exclude", [])
                ):
                    render_3mf = False
                elif format is None and "3mf" in shape_render:
                    render_3mf = True
                elif not format is None and format == "3mf":
                    render_3mf = True
                else:
                    render_3mf = False

                if (
                    "threejs" in shape_render
                    and shape_render["threejs"] is not None
                    and not isinstance(shape_render["threejs"], str)
                    and shape.kind
                    in shape_render.get("threejs", {}).get("exclude", [])
                ):
                    render_threejs = False
                elif format is None and "threejs" in shape_render:
                    render_threejs = True
                elif not format is None and format == "threejs":
                    render_threejs = True
                else:
                    render_threejs = False

                if (
                    "obj" in shape_render
                    and shape_render["obj"] is not None
                    and not isinstance(shape_render["obj"], str)
                    and shape.kind
                    in shape_render.get("obj", {}).get("exclude", [])
                ):
                    render_obj = False
                elif format is None and "obj" in shape_render:
                    render_obj = True
                elif not format is None and format == "obj":
                    render_obj = True
                else:
                    render_obj = False

                if (
                    "gltf" in shape_render
                    and shape_render["gltf"] is not None
                    and not isinstance(shape_render["gltf"], str)
                    and shape.kind
                    in shape_render.get("gltf", {}).get("exclude", [])
                ):
                    render_gltf = False
                elif format is None and "gltf" in shape_render:
                    render_gltf = True
                elif not format is None and format == "gltf":
                    render_gltf = True
                else:
                    render_gltf = False

                if render_svg:
                    tasks.append(shape.render_svg_async(self.ctx, self))
                if render_png:
                    tasks.append(shape.render_png_async(self.ctx, self))
                if render_step:
                    tasks.append(shape.render_step_async(self.ctx, self))
                if render_stl:
                    tasks.append(shape.render_stl_async(self.ctx, self))
                if render_3mf:
                    tasks.append(shape.render_3mf_async(self.ctx, self))
                if render_threejs:
                    tasks.append(shape.render_threejs_async(self.ctx, self))
                if render_obj:
                    tasks.append(shape.render_obj_async(self.ctx, self))
                if render_gltf:
                    tasks.append(shape.render_gltf_async(self.ctx, self))

            await asyncio.gather(*tasks)

            if format == "readme" or (format is None and "readme" in render):
                self.render_readme_async(render, output_dir)

    def render(
        self,
        sketches=None,
        interfaces=None,
        parts=None,
        assemblies=None,
        format=None,
        output_dir=None,
    ):
        asyncio.run(
            self.render_async(
                sketches, interfaces, parts, assemblies, format, output_dir
            )
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

        if (
            self.config_obj.get("import", None) is not None
            and not "packages" in exclude
        ):
            imports = self.config_obj["import"]
            display_imports = []
            for alias in imports:
                if imports[alias].get("onlyInRoot", False):
                    continue
                display_imports.append(alias)

            if display_imports:
                lines += ["## Sub-Packages"]
                lines += [""]
                for alias in display_imports:
                    import_config = imports[alias]
                    columns = []

                    if (
                        "type" not in import_config
                        or import_config["type"] == "local"
                    ):
                        lines += [
                            "### [%s](./%s)"
                            % (
                                import_config["name"],
                                os.path.join(
                                    return_path,
                                    import_config["path"],
                                    "README.md",
                                ),
                            )
                        ]
                    elif import_config["type"] == "git":
                        lines += [
                            "### [%s](%s)"
                            % (import_config["name"], import_config["url"])
                        ]
                    else:
                        lines += ["### %s" % import_config["name"]]

                    if "desc" in import_config:
                        columns += [import_config["desc"]]
                    elif not columns:
                        columns += ["***Not documented yet.***"]

                    if len(columns) > 1:
                        lines += ["<table><tr>"]
                        lines += map(
                            lambda c: "<td valign=top>" + c + "</td>", columns
                        )
                        lines += ["</tr></table>"]
                    else:
                        lines += columns
                    lines += [""]

        def add_section(name, display_name, shape, render_cfg):
            config = shape.config

            if (
                "type" in config
                and config["type"] == "alias"
                and "aliases" in exclude
            ):
                return []

            path = None
            if "path" in config:
                path = config["path"]
            else:
                path = name
                if "type" in config:
                    if (
                        config["type"] == "cadquery"
                        or config["type"] == "build123d"
                        or config["type"] == "ai-cadquery"
                        or config["type"] == "ai-build123d"
                    ):
                        path += ".py"
                    elif (
                        config["type"] == "openscad"
                        or config["type"] == "ai-openscad"
                    ):
                        path += ".scad"
                    else:
                        path += "." + config["type"]

            columns = []
            if "svg" in render_cfg or (
                "type" in config and config["type"] == "svg"
            ):
                svg_cfg = render_cfg["svg"] if "svg" in render_cfg else {}
                if isinstance(svg_cfg, str):
                    svg_cfg = {"prefix": svg_cfg}
                svg_cfg = svg_cfg if svg_cfg is not None else {}
                image_path = os.path.join(
                    return_path,
                    svg_cfg.get("prefix", "."),
                    shape.name + ".svg",
                )
                test_image_path = os.path.join(
                    svg_cfg.get("prefix", "."),
                    shape.name + ".svg",
                )
                img_text = (
                    '<img src="%s" style="width: auto; height: auto; max-width: 200px; max-height: 200px;">'
                    % image_path
                )
                if path:
                    img_text = '<a href="%s">%s</a>' % (path, img_text)
                columns += [img_text]
            elif "png" in render_cfg:
                png_cfg = render_cfg["png"]
                png_cfg = png_cfg if png_cfg is not None else {}
                image_path = os.path.join(
                    return_path,
                    png_cfg.get("prefix", "."),
                    shape.name + ".png",
                )
                test_image_path = os.path.join(
                    png_cfg.get("prefix", "."),
                    shape.name + ".png",
                )
                img_text = (
                    '<img src="%s" style="width: auto; height: auto; max-width: 200px; max-height: 200px;">'
                    % image_path
                )
                if path:
                    img_text = '<a href="%s">%s</a>' % (path, img_text)
                columns += [img_text]
            else:
                image_path = None
                test_image_path = None

            if image_path is None or not os.path.exists(
                os.path.join(output_dir, test_image_path)
            ):
                pc_logging.warn(
                    "Skipping rendering of %s: no image found at %s"
                    % (name, test_image_path)
                )
                return []

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
                    source_path = normalize_resource_path(
                        self.name, shape.config["source_resolved"]
                    )
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
                    source_path = normalize_resource_path(
                        self.name, shape.config["source_resolved"]
                    )
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
