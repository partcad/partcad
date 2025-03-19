#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-01-06
#
# Licensed under Apache License, Version 2.0.
#

import asyncio
from jinja2 import Environment, FileSystemLoader
import fnmatch
import os
import yaml

from OCP.gp import gp_Trsf
import build123d as b3d

from .assembly import Assembly, AssemblyChild
from .assembly_factory_file import AssemblyFactoryFile
from . import logging as pc_logging
from .utils import normalize_resource_path


class AssemblyFactoryAssy(AssemblyFactoryFile):
    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitASSY", source_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config, extension=".assy")
            # Complement the config object here if necessary
            self._create(config)
            self.assembly.cache_dependencies_broken = True
            for dep in self.config.get("dependencies", []):
                self.assembly.cache_dependencies.append(os.path.join(self.project.config_dir, dep))

    def instantiate(self, assembly):
        # # This method is best executed on a thread but the current Python version
        # # might not be good enough to do that.
        # try:
        #     # Try running on the current event loop if any.
        #     loop = asyncio.get_running_loop()
        #     # task = loop.create_task(self.instantiate_async(assembly))
        #     # task.
        #     f = asyncio.run_coroutine_threadsafe(self.instantiate_async(assembly), loop)
        #     raise Exception("IT WORKS")
        # except RuntimeError as e:
        #     print(e)
        #     # Running on a dedicated thread and there is no event loop here yet.
        asyncio.run(self.instantiate_async(assembly))

    async def instantiate_async(self, assembly):
        await super().instantiate(assembly)

        with pc_logging.Action("ASSY", assembly.project_name, assembly.name):
            assy = {}
            if os.path.exists(self.path):
                params = {}
                if "parameters" in self.config:
                    for param_name, param in self.config["parameters"].items():
                        params["param_" + param_name] = param["default"]
                params["name"] = self.config["name"]

                # Read the body of the configuration file
                fp = open(self.path, "r")
                config = fp.read()
                fp.close()

                # Resolve Jinja templates
                template = Environment(
                    loader=FileSystemLoader(os.path.dirname(self.path) + os.path.sep),
                    autoescape=True,
                ).from_string(config)
                config = template.render(params)

                # Parse the resulting config
                try:
                    assy = yaml.safe_load(config)
                except Exception as e:
                    pc_logging.error("ERROR: Failed to parse the assembly file %s" % self.path)
                if assy is None:
                    assy = {}
            else:
                pc_logging.error("ERROR: Assembly file not found: %s" % self.path)

            result = await self.handle_node(assembly, assy)
            if result is not None:
                assembly.children.append(AssemblyChild(result[0], result[1], result[2]))
            else:
                pc_logging.warning("Assembly is empty")

            self.ctx.stats_assemblies_instantiated += 1

    async def handle_node_list(self, assembly, node_list):
        tasks = []

        async def wait_for_tasks():
            nonlocal tasks
            while len(tasks) > 0:
                task = tasks.pop(0)
                f = await asyncio.tasks.wait([task])
                result = f[0].pop().result()
                if result is not None:
                    assembly.children.append(AssemblyChild(result[0], result[1], result[2]))

        for link in node_list:
            if "connect" in link or "connectPorts" in link:
                # wait for all previous nodes to get added first
                await wait_for_tasks()
            tasks.append(asyncio.create_task(self.handle_node(assembly, link)))
        await wait_for_tasks()

    async def handle_node(self, assembly, node):
        # "name" is an optional parameter for both parts and assemblies
        if "name" in node:
            name = node["name"]
        else:
            name = None

        connect = None
        connect_with_iface = None
        connect_with_params = None
        connect_with_instance = None
        connect_with_instance_pattern = None
        connect_with_port = None
        connect_with_port_pattern = None
        connect_to_name = None
        connect_to_iface = None
        connect_to_params = None
        connect_to_instance = None
        connect_to_instance_pattern = None
        connect_to_port = None
        connect_to_port_pattern = None
        # "location" is an optional parameter for both parts and assemblies
        if "location" in node:
            l = node["location"]
            location = b3d.Location((l[0][0], l[0][1], l[0][2]), (l[1][0], l[1][1], l[1][2]), l[2])
        elif "connect" in node:
            connect = node["connect"]
            connect_with_iface = connect.get("with", None)
            if connect_with_iface is not None and ":" not in connect_with_iface:
                connect_with_iface = self.project.name + ":" + connect_with_iface
            connect_with_params = connect.get("withParams", None)
            connect_with_instance = connect.get("withInstance", None)
            connect_with_port = connect.get("withPort", None)

            connect_to_name = connect.get("name", None)

            connect_to_iface = connect.get("to", None)
            if connect_to_iface is not None and ":" not in connect_to_iface:
                connect_to_iface = self.project.name + ":" + connect_to_iface
            connect_to_params = connect.get("toParams", None)
            connect_to_instance = connect.get("toInstance", None)
            connect_to_port = connect.get("toPort", None)
            location = None
        elif "connectPorts" in node:
            connect = node["connectPorts"]
            connect_with_port = connect.get("with", None)
            connect_to_name = connect.get("name", None)
            connect_to_port = connect.get("to", None)
            location = None
        else:
            location = b3d.Location((0, 0, 0), (0, 0, 1), 0)

        if connect_with_instance is not None and "*" in connect_with_instance:
            connect_with_instance_pattern = connect_with_instance
            connect_with_instance = None
        if connect_to_instance is not None and "*" in connect_to_instance:
            connect_to_instance_pattern = connect_to_instance
            connect_to_instance = None

        if connect_with_port is not None and "*" in connect_with_port:
            connect_with_port_pattern = connect_with_port
            connect_with_port = None
        if connect_to_port is not None and "*" in connect_to_port:
            connect_to_port_pattern = connect_to_port
            connect_to_port = None

        # Check if this node is for an assembly
        if "links" in node and not node["links"] is None:
            item = Assembly(
                assembly.project_name,
                {
                    "name": f"{self.name}:{name}",
                    "child": True,
                    "cache": self.ctx.user_config.cache,
                    "cache_dependencies_ignore": self.ctx.user_config.cache_dependencies_ignore,
                }
            )  # TODO(clairbee): revisit why node["links"]) was used there
            item.cacheable = False  # Keep it uncacheable before parts info is in the hashing context
            item.instantiate = lambda x: True
            await self.handle_node_list(item, node["links"])
        else:
            # This is a node for a part or an assembly
            params = {}
            if "params" in node:
                for paramName in node["params"]:
                    params[paramName] = node["params"][paramName]

            if "assembly" in node:
                assy_name = node["assembly"]
                if name is None:
                    name = assy_name
                if "package" in node:
                    assy_name = node["package"] + ":" + assy_name
                elif not ":" in assy_name:
                    assy_name = ":" + assy_name
                assy_name = normalize_resource_path(self.project.name, assy_name)
                item = self.ctx._get_assembly(assy_name, params)
                if item is None:
                    pc_logging.error("Assembly not found: %s" % name)
                    raise Exception("Assembly not found")
            elif "part" in node:
                part_name = node["part"]
                if name is None:
                    name = part_name
                if "package" in node:
                    part_name = node["package"] + ":" + part_name
                elif not ":" in part_name:
                    part_name = ":" + part_name
                part_name = normalize_resource_path(self.project.name, part_name)
                item = self.ctx._get_part(part_name, params)
                if item is None:
                    pc_logging.error("Part not found: %s in %s" % (name, self.name))
                    raise Exception("Part not found: %s in %s" % (name, self.name))
            else:
                item = None

            if connect is not None:
                pc_logging.debug("Attempting to connect %s" % name)
                source_port = None
                source_iface = None
                source_iface_obj = None
                source_offsets = []
                source_iface_instance = None
                target_part = None
                target_part_location = None
                target_port = None
                target_iface = None
                target_iface_obj = None
                target_offsets = []
                target_iface_instance = None
                # trsf = None # TODO(clairbee): implement offsets

                for child in assembly.children:
                    # if hasattr(child, "name"):
                    #     pc_logging.debug("Found part: %s" % child.name)
                    if hasattr(child, "name") and child.name == connect_to_name:
                        # pc_logging.debug(
                        #     "Found target part: %s" % connect_to_name
                        # )

                        target_part = child.item
                        break

                if target_part is None:
                    pc_logging.error("Target part not found: %s" % connect_to_name)
                else:
                    if hasattr(child, "location"):
                        target_part_location = child.location
                    else:
                        target_part_location = b3d.Location((0, 0, 0), (0, 0, 1), 0)

                    # If there is no source interface specified,
                    # but there is only one present, then use it
                    if (
                        connect_with_iface is None
                        and item.with_ports is not None
                        and not "ports" in item.with_ports.config
                        and len(list(item.with_ports.get_interfaces().keys())) == 1
                    ):
                        connect_with_iface = list(item.with_ports.get_interfaces().keys())[0]
                        pc_logging.debug("Using the only source interface: %s" % connect_with_iface)

                    # If there is only one source port, then just use it.
                    if connect_with_port is None:
                        if len(list(item.with_ports.get_ports().keys())) == 1:
                            connect_with_port = list(item.with_ports.get_ports().keys())[0]
                            pc_logging.debug("Using the only source port: %s" % connect_with_port)
                            # If the instance is known and the port pattern is configured
                        elif connect_with_port_pattern is not None:
                            matched = []
                            for port in item.with_ports.get_ports().values():
                                if fnmatch.fnmatch(port, connect_with_port_pattern):
                                    matched.append(port)

                            if len(matched) == 1:
                                connect_with_port = matched[0]
                                pc_logging.debug("Found source port by pattern: %s" % connect_with_port)
                            elif len(matched) > 1:
                                pc_logging.debug(
                                    "Multiple source ports are matching the pattern, pending interface checks: %s"
                                    % matched
                                )

                    # If the source port is known, then use it
                    if not connect_with_port is None:
                        source_port = item.with_ports.get_ports()[connect_with_port]
                        pc_logging.debug("Configured source port: %s" % source_port.name)
                    else:
                        # Source port is not configured.
                        # It needs to be determined below.
                        pass

                    # If there is no target interface specified,
                    # but there is only one present, then use it
                    if (
                        connect_to_iface is None
                        and target_part.with_ports is not None
                        and not "ports" in target_part.with_ports.config
                        and len(list(target_part.with_ports.get_interfaces().keys())) == 1
                    ):
                        connect_to_iface = list(target_part.with_ports.get_interfaces().keys())[0]
                        pc_logging.debug("Using the only target interface: %s" % connect_to_iface)

                    # If there is only one target port, then just use it.
                    if connect_to_port is None:
                        if len(list(target_part.with_ports.get_ports().keys())) == 1:
                            connect_to_port = list(target_part.with_ports.get_ports().keys())[0]
                            pc_logging.debug("Using the only target port: %s" % connect_to_port)
                        elif connect_to_port_pattern is not None:
                            matched = []
                            for port in target_part.with_ports.get_ports().keys():
                                if fnmatch.fnmatch(port, connect_to_port_pattern):
                                    matched.append(port)

                            if len(matched) == 1:
                                connect_to_port = matched[0]
                                pc_logging.debug("Found target port by pattern: %s" % connect_to_port)
                            elif len(matched) > 1:
                                pc_logging.debug(
                                    "Multiple target ports are matching the pattern, pending interface checks: %s"
                                    % matched
                                )

                    # If the target port is configured, then use it
                    if not connect_to_port is None:
                        target_port = target_part.with_ports.get_ports()[connect_to_port]
                        pc_logging.debug("Configured target port: %s" % target_port.name)
                    else:
                        # Target port is not configured.
                        # It needs to be determined below.
                        pass

                    # If we have either source or target interface/port missing,
                    # then we need to use mating information to determine them.
                    if (connect_with_port is None and connect_with_iface is None) or (
                        connect_to_port is None and connect_to_iface is None
                    ):
                        # FIXME: PC-10:
                        # Brake the following step up into two:
                        # 1. If we know the port name but not the interface,
                        #    learn which interface it belons to.
                        # 2. Get the list of interface for each part for which
                        #    we don't know the interface yet.
                        # 3. Given two lists of interfaces, find the mating
                        #    candidates.
                        (
                            source_candidate_interfaces,
                            target_candidate_interfaces,
                        ) = self.project.ctx.find_mating_interfaces(item, target_part)

                        # If it's the source interface that we need to auto-detect
                        if connect_with_port is None and connect_with_iface is None:
                            if len(source_candidate_interfaces) == 1:
                                connect_with_iface = source_candidate_interfaces.pop()
                            elif len(source_candidate_interfaces) > 1:
                                # FIXME(clairbee): what if we have patterns configured?
                                pc_logging.debug(
                                    "Multiple source interfaces are candidates for connection: %s"
                                    % source_candidate_interfaces
                                )
                            else:
                                pc_logging.debug("No source interfaces are candidates for connection")

                        # If it's the target interface that we need to auto-detect
                        if connect_to_port is None and connect_to_iface is None:
                            if len(target_candidate_interfaces) == 1:
                                connect_to_iface = target_candidate_interfaces.pop()
                            elif len(target_candidate_interfaces) > 1:
                                # FIXME(clairbee): what if we have patterns configured?
                                pc_logging.debug(
                                    "Multiple target interfaces are candidates for connection: %s"
                                    % target_candidate_interfaces
                                )
                            else:
                                pc_logging.debug("No target interfaces are candidates for connection")

                    # Resolve interface names
                    if connect_with_iface is not None:
                        source_iface = item.with_ports.get_interface(connect_with_iface)
                        source_iface_obj = self.project.ctx.get_interface(connect_with_iface)
                    if connect_to_iface is not None:
                        target_iface = target_part.with_ports.get_interface(connect_to_iface)
                        target_iface_obj = self.project.ctx.get_interface(connect_to_iface)

                    # If we know the source interface but not the port
                    if connect_with_port is None and source_iface_obj is not None:
                        # If the instance is specified, then find it
                        pc_logging.debug("Source interface instances: %s" % source_iface.keys())

                        # If there is an instance pattern configured
                        if (
                            source_iface is not None
                            and source_iface_instance is None
                            and connect_with_instance_pattern is not None
                        ):
                            matched = []
                            for instance in source_iface.values():
                                if fnmatch.fnmatch(instance, connect_with_instance_pattern):
                                    matched.append(instance)

                            if len(matched) == 1:
                                connect_with_instance = matched[0]
                                pc_logging.debug("Found source instance by pattern: %s" % connect_with_instance)
                            elif len(matched) > 1:
                                pc_logging.debug("Multiple source instances are matching the pattern: %s" % matched)

                            if connect_with_instance is None:
                                pc_logging.error(
                                    "Connect %s to %s: instance is not found by pattern: %s"
                                    % (
                                        name,
                                        connect_to_name,
                                        connect_with_instance_pattern,
                                    )
                                )

                        if not connect_with_instance is None:
                            if not connect_with_instance in source_iface:
                                pc_logging.error(
                                    "Connect %s to %s: source instance is not found: %s"
                                    % (
                                        name,
                                        connect_to_name,
                                        connect_with_instance,
                                    )
                                )
                            else:
                                source_iface_instance = source_iface[connect_with_instance]
                        # If there is only one instance, then use it
                        elif len(list(source_iface.values())) == 1:
                            source_iface_instance = list(source_iface.values())[0]
                        elif len(list(source_iface.values())) > 1:
                            # This could be ok if we have a port name or pattern
                            pc_logging.debug(
                                "Missing instance specification for the source interface: %s" % connect_with_iface
                            )

                        # If the instance is known and it has only one port, then use it
                        if (
                            source_iface_instance is not None
                            and connect_with_port is None
                            and len(list(source_iface_instance.values())) == 1
                        ):
                            connect_with_port = list(source_iface_instance.values())[0]
                        # If the instance is known and the port pattern is configured
                        elif (
                            source_iface_instance is not None
                            and connect_with_port is None
                            and connect_with_port_pattern is not None
                        ):
                            matched = []
                            for port in source_iface_instance.values():
                                if fnmatch.fnmatch(port, connect_with_port_pattern):
                                    matched.append(port)

                            if len(matched) == 1:
                                connect_with_port = matched[0]
                                pc_logging.debug("Found source port by pattern: %s" % connect_with_port)
                            elif len(matched) > 1:
                                pc_logging.debug("Multiple source ports are matching the pattern: %s" % matched)

                            if connect_with_port is None:
                                pc_logging.error(
                                    "Connect %s to %s: port is not found by pattern: %s"
                                    % (
                                        name,
                                        connect_to_name,
                                        connect_with_port_pattern,
                                    )
                                )
                        # If the instance is known and the interface has the lead port
                        elif (
                            source_iface_instance is not None
                            and connect_with_port is None
                            and source_iface_obj.lead_port is not None
                        ):
                            for port in source_iface_instance.values():
                                if fnmatch.fnmatch(port, "*" + source_iface_obj.lead_port):
                                    connect_with_port = port
                                    break
                            if connect_with_port is None:
                                pc_logging.error(
                                    "Connect %s to %s: lead port is not found: %s"
                                    % (
                                        name,
                                        connect_to_name,
                                        source_iface_obj.lead_port,
                                    )
                                )
                        # pc_logging.info("Found source interface: %s" % source_iface.name)

                    # If we know the target interface but not the port
                    if connect_to_port is None and target_iface_obj is not None:
                        # If the instance is specified, then find it
                        pc_logging.debug("Target interface instances: %s" % target_iface.keys())

                        # If there is an instance pattern configured and there is only one match
                        if (
                            target_iface is not None
                            and target_iface_instance is None
                            and connect_to_instance_pattern is not None
                        ):
                            matched = []
                            for instance in list(target_iface.keys()):
                                pc_logging.debug("Instance: %s" % instance)
                                pc_logging.debug("Pattern: %s" % connect_to_instance_pattern)
                                if fnmatch.fnmatch(instance, connect_to_instance_pattern):
                                    matched.append(instance)

                            if len(matched) == 1:
                                connect_to_instance = matched[0]
                                pc_logging.debug("Found target instance by pattern: %s" % connect_to_instance)
                            elif len(matched) > 1:
                                pc_logging.debug("Multiple target instances are matching the pattern: %s" % matched)

                            if connect_to_instance is None:
                                pc_logging.error(
                                    "Connect %s to %s: instance is not found by pattern: %s"
                                    % (
                                        name,
                                        connect_to_name,
                                        connect_to_instance_pattern,
                                    )
                                )

                        if not connect_to_instance is None:
                            if not connect_to_instance in target_iface:
                                pc_logging.error(
                                    "Connect %s to %s: target instance is not found: %s"
                                    % (
                                        name,
                                        connect_to_name,
                                        connect_to_instance,
                                    )
                                )
                            else:
                                target_iface_instance = target_iface[connect_to_instance]
                        # If there is only one instance, then use it
                        elif len(list(target_iface.values())) == 1:
                            target_iface_instance = list(target_iface.values())[0]
                        elif len(list(target_iface.values())) > 1:
                            # This could be ok if we have a port name or pattern
                            pc_logging.debug(
                                "Missing instance specification for the target interface: %s" % connect_to_iface
                            )

                        # If the instance is known and it has only one port, then use it
                        if (
                            target_iface_instance is not None
                            and connect_to_port is None
                            and len(list(target_iface_instance.values())) == 1
                        ):
                            connect_to_port = list(target_iface_instance.values())[0]
                        # If the instance is known and the port pattern is configured
                        elif (
                            target_iface_instance is not None
                            and connect_to_port is None
                            and connect_to_port_pattern is not None
                        ):
                            matched = []
                            for port in target_iface_instance.values():
                                if fnmatch.fnmatch(port, connect_to_port_pattern):
                                    matched.append(port)

                            if len(matched) == 1:
                                connect_to_port = matched[0]
                                pc_logging.debug("Found target port by pattern: %s" % connect_to_port)
                            elif len(matched) > 1:
                                pc_logging.debug("Multiple target ports are matching the pattern: %s" % matched)

                            if connect_to_port is None:
                                pc_logging.error(
                                    "Connect %s to %s: port is not found by pattern: %s"
                                    % (
                                        name,
                                        connect_to_name,
                                        connect_to_port_pattern,
                                    )
                                )
                        # If the instance is known and the interface has the lead port
                        elif (
                            target_iface_instance is not None
                            and connect_to_port is None
                            and target_iface_obj.lead_port is not None
                        ):
                            for port in target_iface_instance.values():
                                if fnmatch.fnmatch(port, "*" + target_iface_obj.lead_port):
                                    connect_to_port = port
                                    break
                            if connect_to_port is None:
                                pc_logging.error(
                                    "Connect %s to %s: lead port is not found: %s"
                                    % (
                                        name,
                                        connect_to_name,
                                        target_iface_obj.lead_port,
                                    )
                                )
                        # pc_logging.info("Found target interface: %s" % target_iface.name)

                    # We know both interface instances but we don't know one of the ports
                    # FIXME(claibee): it is currently working only for cases where we don't know both ports
                    # TODO(clairbee): should the following condition drop the check for iface_instance?
                    #                 shouldn't we try to match ports even if there is no mating information?
                    if (
                        source_iface_instance is not None
                        and target_iface_instance is not None
                        # FIXME(clairbee): what if we only know one?
                        and connect_with_port is None
                        and connect_to_port is None
                    ):
                        pc_logging.debug("Trying to match ports by name")
                        # Both interfaces are known but they have more than one port each.
                        # Let's find a matching pair of ports.
                        source_ports = sorted(list(source_iface_instance.keys()))
                        target_ports = sorted(list(target_iface_instance.keys()))
                        if source_ports == target_ports:
                            # FIXME(clairbee): so what? what if we have patterns configured?
                            # The interfaces have the same number of ports and the same names.
                            # We can connect them using any pair of matching ports.
                            connect_with_port = source_iface_instance[source_ports[0]]
                            connect_to_port = target_iface_instance[target_ports[0]]
                        else:
                            connect_with_port_index = -1
                            connect_to_port_index = -1
                            if len(source_ports) != 1:
                                if connect_with_port_pattern is None and connect_to_port_pattern is None:
                                    if len(source_ports) == len(target_ports):
                                        pc_logging.debug(
                                            "Connect %s to %s: port mating is not detected deterministically on BOTH ends, guessing alphabetically..."
                                            % (name, connect_to_name)
                                        )
                                        connect_with_port_index = 0
                                        connect_to_port_index = 0
                                    else:
                                        pc_logging.error(
                                            "Connect %s to %s: port mating is not detected deterministically on BOTH ends, different number of ports"
                                            % (name, connect_to_name)
                                        )

                                if connect_with_port_pattern is not None:
                                    for i, port in enumerate(source_ports):
                                        if fnmatch.fnmatch(port, connect_with_port_pattern):
                                            connect_with_port_index = i
                                            break
                                if connect_to_port_pattern is not None:
                                    for i, port in enumerate(target_ports):
                                        if fnmatch.fnmatch(port, connect_to_port_pattern):
                                            connect_to_port_index = i
                                            break

                                if (
                                    len(source_ports) == len(target_ports)
                                    and connect_with_port_index != -1
                                    and connect_to_port_index == -1
                                ):
                                    pc_logging.debug(
                                        "Connect %s to %s: port selection is not detected on the target end, guessing alphabetically..."
                                        % (name, connect_to_name)
                                    )
                                    connect_to_port_index = connect_with_port_index
                                if (
                                    len(source_ports) == len(target_ports)
                                    and connect_with_port_index == -1
                                    and connect_to_port_index != -1
                                ):
                                    pc_logging.debug(
                                        "Connect %s to %s: port selection is not detected on the source end, guessing alphabetically..."
                                        % (name, connect_to_name)
                                    )
                                    connect_with_port_index = connect_to_port_index

                            if connect_with_port_index != -1:
                                connect_with_port = source_iface_instance[source_ports[connect_with_port_index]]
                            if connect_to_port_index != -1:
                                connect_to_port = target_iface_instance[target_ports[connect_to_port_index]]

                    # If the source port is determined, then use it
                    if not connect_with_port is None and source_port is None:
                        source_port = item.with_ports.get_ports()[connect_with_port]
                        pc_logging.debug("Found source port: %s" % source_port.name)
                    if connect_with_port is not None and connect_with_port_pattern is not None:
                        if not fnmatch.fnmatch(connect_with_port, connect_with_port_pattern):
                            pc_logging.error(
                                "The determined source port does not match the pattern: %s" % connect_with_port_pattern
                            )

                    # If the target port is determined, then use it
                    if not connect_to_port is None and target_port is None:
                        target_port = target_part.with_ports.get_ports()[connect_to_port]
                        pc_logging.debug("Found target port: %s" % target_port.name)
                    if connect_to_port is not None and connect_to_port_pattern is not None:
                        if not fnmatch.fnmatch(connect_to_port, connect_to_port_pattern):
                            pc_logging.error(
                                "The determined target port does not match the pattern: %s" % connect_to_port_pattern
                            )

                    # TODO(clairbee): before the next step, deduce the interface
                    #                 based on the port name if the interface is missing

                    # Now calculate offsets based on params.
                    # This requires an interface object to be present, as that's where the params are defined.
                    # If the source interface params are passed, calculate the offsets
                    if source_iface_obj is not None and connect_with_params is not None:
                        pc_logging.debug("Source params are found")
                        for (
                            param_name,
                            param_value,
                        ) in connect_with_params.items():
                            pc_logging.debug("Source param: %s" % param_name)
                            param = source_iface_obj.params.get(param_name, None)
                            pc_logging.debug("Source param: %s" % param)
                            if param is not None:
                                offsets = param.get_offsets(param_value)
                                pc_logging.debug("Source offsets: %s" % offsets)
                                source_offsets.extend(offsets)

                    # If the target interface params are passed, calculate the offsets
                    if target_iface_obj is not None and connect_to_params is not None:
                        pc_logging.debug("Target params are found")
                        for (
                            param_name,
                            param_value,
                        ) in connect_to_params.items():
                            pc_logging.debug("Target param: %s" % param_name)
                            pc_logging.debug("Target info: %s" % target_iface_obj.info())
                            param = target_iface_obj.params.get(param_name, None)
                            pc_logging.debug("Target param: %s" % param)
                            if param is not None:
                                offsets = param.get_offsets(param_value)
                                pc_logging.debug("Target offsets: %s" % offsets)
                                target_offsets.extend(offsets)

                    if (source_port is None and target_port is not None) or (
                        source_port is not None and target_port is None
                    ):
                        # One of the parts may have no parts declared.
                        # TODO(clairbee): Do we need to support this?
                        pc_logging.warning("Peer port auto-detection has failed: %s" % name)

                    turn_around = b3d.Location(
                        (0, 0, 0),
                        (0.71, 0.71, 0),
                        180,
                    ).wrapped.Transformation()

                    if source_port is not None and target_port is not None:
                        pc_logging.debug(
                            "Connected %s of %s to %s of %s"
                            % (
                                connect_with_port,
                                name,
                                connect_to_port,
                                connect_to_name,
                            )
                        )

                        trsf = target_part_location.wrapped.Transformation()
                        trsf.Multiply(target_port.location.wrapped.Transformation())
                        trsf.Multiply(turn_around)
                        for target_offset in target_offsets:
                            pc_logging.debug("Target offset: %s" % target_offset)
                            trsf.Multiply(target_offset)
                        for source_offset in source_offsets:
                            trsf.Multiply(source_offset)
                        trsf.Multiply(source_port.location.wrapped.Transformation().Inverted())
                        location = b3d.Location(trsf)
                    elif source_port is None and target_port is not None:
                        pc_logging.debug(
                            "Connected %s to %s of %s"
                            % (
                                name,
                                connect_to_port,
                                connect_to_name,
                            )
                        )

                        trsf = target_part_location.wrapped.Transformation()
                        trsf.Multiply(target_port.location.wrapped.Transformation())
                        trsf.Multiply(turn_around)
                        for target_offset in target_offsets:
                            trsf.Multiply(target_offset)
                        location = b3d.Location(trsf)
                    elif source_port is not None and target_port is None:
                        pc_logging.debug("Connected %s of %s to %s" % (connect_with_port, name, connect_to_name))
                        trsf = target_part_location.wrapped.Transformation()
                        trsf.Multiply(turn_around)
                        for source_offset in source_offsets:
                            trsf.Multiply(source_offset)
                        trsf.Multiply(source_port.location.wrapped.Transformation().Inverted())
                        location = b3d.Location(trsf)
                    elif source_port is None and target_port is None:
                        pc_logging.debug("Connected %s to %s" % (name, connect_to_name))
                        trsf = target_part_location.wrapped.Transformation()
                        trsf.Multiply(turn_around)
                        location = b3d.Location(trsf)
                    else:
                        pc_logging.error("Not enough data to connect %s" % name)
                        location = b3d.Location((0, 0, 0), (0, 0, 1), 0)

        if not item is None:
            return [item, name, location]
        else:
            return None
