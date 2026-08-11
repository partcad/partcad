#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The 'urdf' assembly type: a URDF file used directly as a PartCAD assembly.

A URDF describes a robot as links joined by joints. PartCAD's assembly is a
static tree of placed shapes, so the two meet at the URDF's zero configuration:
every link is placed where its joints put it with all of them at zero, and the
result is the very same in-memory representation an ASSY file produces - a tree
of 'Assembly'/'AssemblyChild' objects wrapping 'Part's. Everything downstream
(rendering, export, BoM, inspection, caching) therefore treats a URDF assembly
and an ASSY assembly identically.

The reading is done by wrapper_import_urdf inside a python sandbox: URDF is
parsed with ROS's own 'urdf_parser_py', which PartCAD does not depend on, and
URDF's primitive shapes need OCCT, which the core process never loads. What
comes back here is plain data.

A URDF says a great deal that a PartCAD assembly has nowhere to put - masses,
inertia tensors, joint types, axes and limits, materials, sensors, Gazebo
plugins. All of it is dropped, and what was dropped is reported rather than
passed over in silence. docs/source/design.rst describes what it would take to
keep it.
"""

import asyncio
import hashlib
import os

from . import logging as pc_logging
from . import sandbox_versions, shape_envelope, telemetry, wrapper
from .assembly import Assembly, AssemblyChild
from .assembly_factory_file import AssemblyFactoryFile
from .geom import Location
from .part_config import PartConfiguration

# How a counter from the wrapper's 'dropped' summary is worded in the log.
DROPPED_LABELS = {
    "inertial": "link inertial properties (mass, centre of mass, inertia tensor)",
    "material": "materials and colors",
    "joint_kinematics": "movable joints (flattened to their zero position)",
    "joint_limits": "joint limits",
    "joint_dynamics": "joint dynamics (damping, friction)",
    "collision": "collision geometry",
    "visual": "visual geometry",
    "transmission": "transmissions",
    "gazebo": "Gazebo extensions",
    "sensor": "sensors",
}


@telemetry.instrument()
class AssemblyFactoryUrdf(AssemblyFactoryFile):
    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitURDF", source_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config, extension=".urdf")
            self._create(config)
            # Which parts a URDF resolves to is only known once it is read, so
            # the dependency set cannot be hashed up front - the same reason the
            # ASSY factory marks itself this way.
            self.assembly.cache_dependencies_broken = True
            for dep in self.config.get("dependencies", []):
                self.assembly.cache_dependencies.append(os.path.join(self.project.config_dir, dep))
            # part file (+ scale) -> the Part registered for it, so a mesh reused
            # by several links is registered once.
            self._parts = {}
            # What the last read of the URDF found, for 'pc info'.
            self.urdf_info = {}

    def instantiate(self, assembly):
        asyncio.run(self.instantiate_async(assembly))

    async def instantiate_async(self, assembly):
        await super().instantiate(assembly)

        with pc_logging.Action("URDF", assembly.project_name, assembly.name):
            result = await self._read_async()
            self._report(result)

            root = result["root"]
            # The robot's root link *is* this assembly, so its children become
            # this assembly's children. Nesting it one level deeper instead
            # would make a URDF round trip grow a wrapper level every time.
            await self.handle_node_list(assembly, root.get("links") or [])

            if not assembly.children:
                pc_logging.warning("Assembly is empty")

            self.ctx.stats_assemblies_instantiated += 1

    async def _read_async(self):
        """Run the URDF reader in a sandbox and return its data tree."""
        runtime = self.ctx.get_python_runtime(version=sandbox_versions.DEFAULT_PYTHON_VERSION)
        await runtime.ensure_async(sandbox_versions.URDF_PARSER_PY)
        # Only needed to turn URDF's box/cylinder/sphere primitives into
        # geometry, but the sandbox is shared and asking for it here keeps the
        # wrapper's own imports unconditional.
        await runtime.ensure_async(sandbox_versions.CADQUERY_OCP)

        request = {
            "operation": "import_urdf",
            "urdf_file": os.path.abspath(self.path),
            "output_folder": self._generated_dir(),
            "package_paths": self._package_paths(),
            "geometry": self.config.get("geometry", "visual"),
            "precision": 6,
        }

        wrapper_path = wrapper.get("import_urdf.py")
        command = [wrapper_path, "import_urdf"]
        exitcode, response_serialized, errors = await runtime.run_async(
            command, shape_envelope.serialize(request)
        )
        if exitcode != 0 and not errors:
            errors = "reading the URDF failed with exit code %s" % exitcode
        if errors:
            pc_logging.error(errors)
            raise Exception(errors)

        result = shape_envelope.deserialize(response_serialized)
        if not result.get("success", False):
            raise Exception(result.get("exception") or "reading the URDF failed")
        return result

    def _generated_dir(self):
        """Where geometry generated for URDF primitives is written.

        Under PartCAD's own state directory rather than inside the package: a
        'box' or 'cylinder' link is derived data, and instantiating an assembly
        should not drop files into the user's source tree.
        """
        digest = hashlib.sha256(os.path.abspath(self.path).encode()).hexdigest()[:16]
        return os.path.join(self.ctx.user_config.internal_state_dir, "urdf", digest)

    def _package_paths(self):
        """Roots to resolve 'package://' mesh references against.

        The package directory and the URDF's own directory, plus whatever the
        assembly configuration names. Outside a ROS workspace there is no
        ROS_PACKAGE_PATH to consult, so this is what a standalone URDF gets.
        """
        paths = [self.project.config_dir, os.path.dirname(os.path.abspath(self.path))]
        for extra in self.config.get("packagePaths") or []:
            paths.append(extra if os.path.isabs(extra) else os.path.join(self.project.config_dir, extra))
        return paths

    def info(self, shape):
        """The usual shape info, plus what this URDF said and what was dropped."""
        info = super().info(shape)
        if self.urdf_info.get("robot_name"):
            info["Robot"] = self.urdf_info["robot_name"]
            info["RootLink"] = self.urdf_info.get("root_link")
        dropped = self.urdf_info.get("dropped") or {}
        if dropped:
            info["UrdfDropped"] = {DROPPED_LABELS.get(key, key): count for key, count in sorted(dropped.items())}
        joints = self.urdf_info.get("movable_joints") or []
        if joints:
            info["UrdfMovableJoints"] = ["%s (%s)" % (joint["name"], joint["type"]) for joint in joints]
        return info

    def _report(self, result):
        """Record and log the parser's complaints and what could not be kept."""
        self.urdf_info = {
            "robot_name": result.get("robot_name"),
            "root_link": result.get("root_link"),
            "dropped": result.get("dropped") or {},
            "movable_joints": result.get("movable_joints") or [],
        }

        for warning in result.get("warnings") or []:
            pc_logging.warning("%s: %s" % (self.name, warning))

        dropped = self.urdf_info["dropped"]
        if dropped:
            described = ", ".join(
                "%s: %d" % (DROPPED_LABELS.get(key, key), count) for key, count in sorted(dropped.items())
            )
            pc_logging.info(
                "%s: a PartCAD assembly cannot hold all of what this URDF says; dropped %s" % (self.name, described)
            )
        for joint in result.get("movable_joints") or []:
            pc_logging.debug(
                "%s: the %s joint '%s' is placed at its zero position" % (self.name, joint["type"], joint["name"])
            )

    async def handle_node_list(self, assembly, nodes):
        for node in nodes:
            child = await self.handle_node(assembly, node)
            if child is not None:
                assembly.children.append(child)

    async def handle_node(self, assembly, node):
        """Turn one node of the wrapper's tree into an AssemblyChild."""
        name = node.get("name")
        location = Location(node["location"]) if node.get("location") else Location()

        if node["type"] == "assembly":
            item = Assembly(
                assembly.project_name,
                {
                    "name": "%s:%s" % (self.name, name),
                    "child": True,
                    "cache": self.ctx.user_config.cache,
                    "cache_dependencies_ignore": self.ctx.user_config.cache_dependencies_ignore,
                },
            )
            # Keep it uncacheable before the parts info is in the hashing context
            item.cacheable = False
            item.instantiate = lambda _self: True
            await self.handle_node_list(item, node.get("links") or [])
            if not item.children:
                return None
        else:
            item = self._part_for(node)
            if item is None:
                return None

        return AssemblyChild(item, name, location)

    def _part_for(self, node):
        """The Part for a geometry node, registering it on first use.

        The parts a URDF resolves to are not declared in 'partcad.yaml' - they
        are whatever files the URDF points at - so they are registered into the
        package in memory only. They are reachable by name, but they do not
        appear in the package configuration and 'pc list parts' does not show
        them.
        """
        part_file = os.path.abspath(node["part_file"])
        scale = float(node.get("scale") or 1.0)
        key = (part_file, round(scale, 9))
        if key in self._parts:
            return self._parts[key]

        part_name = self._part_name(node, part_file)
        config = {
            "type": node["part_type"],
            "name": part_name,
            "orig_name": part_name,
            "path": part_file,
            # An implementation detail of this assembly, not something the
            # package offers: reachable by name once the assembly is built, but
            # not documented in the package README.
            "internal": True,
        }
        # URDF states mesh coordinates in metres after applying the mesh's own
        # 'scale'; PartCAD works in millimetres. The wrapper reduces the two to a
        # single factor, which is 1.0 for the millimetre meshes PartCAD writes.
        if abs(scale - 1.0) > 1e-9:
            config["scale"] = scale

        full_name = "%s:%s" % (self.project.name, part_name)
        config = PartConfiguration.normalize(part_name, config, full_name)
        try:
            self.project.init_part_by_config(config)
        except Exception as e:
            pc_logging.error("%s: failed to add the part '%s': %s" % (self.name, part_name, e))
            return None

        part = self.project.parts.get(part_name)
        if part is None:
            pc_logging.error("%s: the part '%s' failed to instantiate" % (self.name, part_name))
            return None
        self.assembly.cache_dependencies.append(part_file)
        self._parts[key] = part
        return part

    def _part_name(self, node, part_file):
        """A package-unique name for a part a URDF pointed at.

        Namespaced under the assembly, so two URDFs in one package that both
        have a 'base' link do not collide, and so a URDF-derived part never
        shadows a part the package actually declares.
        """
        base = "%s/%s" % (self.name, node.get("name") or os.path.splitext(os.path.basename(part_file))[0])
        candidate = base
        suffix = 1
        while candidate in self.project.parts:
            candidate = "%s_%d" % (base, suffix)
            suffix += 1
        return candidate
