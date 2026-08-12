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

Every link becomes one part, registered into the package as
``<assembly name>/<link name>``. Those parts are ordinary parts: they can be
inspected, rendered and exported on their own. They are not declared in
``partcad.yaml`` - the URDF is what declares them - so a package resolves such a
name by building the assembly that owns it first (see
``Project._derived_part_owner``).

The reading is done by wrapper_import_urdf inside a python sandbox: URDF is
parsed with ROS's own 'urdf_parser_py', which PartCAD does not depend on, and
turning URDF geometry into shapes needs OCCT, which the core process never
loads. What comes back here is plain data.

What a URDF says about a link that PartCAD does not model - mass, inertia,
materials, the geometry it did not build the shape from, Gazebo extensions - is
carried verbatim in the part's ``physics`` section rather than thrown away. What
cannot be carried at all is counted and reported. docs/source/simulation.rst
describes the gap and what closing it would take.
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
            # 'pc convert assembly -t assy' needs the joint table and the
            # per-link data, which only this factory has. The Assembly object is
            # what a caller holds, so it is what points back here.
            self.assembly.urdf_factory = self
            # Which parts a URDF resolves to is only known once it is read, so
            # the dependency set cannot be hashed up front - the same reason the
            # ASSY factory marks itself this way.
            self.assembly.cache_dependencies_broken = True
            for dep in self.config.get("dependencies", []):
                self.assembly.cache_dependencies.append(os.path.join(self.project.config_dir, dep))
            # node name -> the Part registered for it, and link name -> whatever
            # the link resolved to (that same part, or the sub-assembly of its
            # several shapes).
            self._parts = {}
            self._items = {}
            # What the last read of the URDF found: 'pc info' reports it and
            # 'pc convert assembly' builds the ASSY file out of it.
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
            # would make a URDF round trip grow a wrapper level every time. By
            # the same token, what the root link said about itself belongs to
            # the assembly - otherwise an export would have nowhere to put it
            # back and would invent a link to hang the rest off.
            if root.get("physics"):
                assembly.config["physics"] = root["physics"]
            await self.handle_node_list(assembly, root.get("links") or [])

            if not assembly.children:
                pc_logging.warning("Assembly is empty")

            self.ctx.stats_assemblies_instantiated += 1

    async def read_async(self):
        """Read the URDF and return the wrapper's full result.

        Public because ``pc convert assembly -t assy`` needs the joint table and
        the per-link data, not just the tree the assembly is built from.
        """
        result = await self._read_async()
        self._report(result)
        return result

    def link_item(self, link_name):
        """What a link resolved to: its part, or the sub-assembly of its shapes.

        Only populated once the assembly has been built. ``pc convert assembly
        -t assy`` uses it to render one mesh per link whatever the link is made
        of.
        """
        return self._items.get(link_name)

    async def _read_async(self):
        """Run the URDF reader in a sandbox and return its data tree."""
        runtime = self.ctx.get_python_runtime(version=sandbox_versions.DEFAULT_PYTHON_VERSION)
        await runtime.ensure_async(sandbox_versions.URDF_PARSER_PY)
        # Only URDF's box/cylinder/sphere have to be turned into geometry - a
        # mesh is referenced where it lies and read by the part factory for its
        # format, in that factory's own runtime.
        await runtime.ensure_async(sandbox_versions.CADQUERY_OCP)

        request = {
            "operation": "import_urdf",
            "urdf_file": os.path.abspath(self.path),
            "output_folder": self._generated_dir(),
            "package_paths": self._package_paths(),
            "ignoreCollision": self.config.get("ignoreCollision", False),
            "precision": 6,
        }

        wrapper_path = wrapper.get("import_urdf.py")
        command = [wrapper_path, "import_urdf"]
        exitcode, response_serialized, errors = await runtime.run_async(command, shape_envelope.serialize(request))
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
        """Where geometry generated for a link is written.

        Under PartCAD's own state directory rather than inside the package: a
        link built from primitives, or from several visuals combined, is derived
        data, and instantiating an assembly should not drop files into the
        user's source tree. ``pc convert assembly -t assy`` is the command that
        deliberately materializes them into the package.
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
            "links": result.get("links") or {},
            "joints": result.get("joints") or {},
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
        for joint in self.urdf_info["movable_joints"]:
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
            config = {
                "name": "%s:%s" % (self.name, name),
                "child": True,
                "cache": self.ctx.user_config.cache,
                "cache_dependencies_ignore": self.ctx.user_config.cache_dependencies_ignore,
            }
            # A sub-assembly that *is* a URDF link carries what the link said
            # about itself, so the export finds it where it expects to.
            if node.get("physics"):
                config["physics"] = node["physics"]
            item = Assembly(assembly.project_name, config)
            # Keep it uncacheable before the parts info is in the hashing context
            item.cacheable = False
            item.instantiate = lambda _self: True
            await self.handle_node_list(item, node.get("links") or [])
            if not item.children:
                return None
        else:
            item = self.part_for(node)
            if item is None:
                return None

        if node.get("link") and node["link"] not in self._items:
            # What a link resolved to - a part, or the sub-assembly of its
            # several shapes. 'pc convert assembly -t assy' renders it.
            self._items[node["link"]] = item

        return AssemblyChild(item, name, location)

    def part_name(self, node_name):
        """The package-wide name of the part a URDF shape becomes.

        ``<assembly>/<link>`` for a link that is one shape, and
        ``<assembly>/<link>/<name or index>`` for one of several.
        """
        return "%s/%s" % (self.name, node_name)

    def part_for(self, node):
        """The Part for one URDF shape, registering it on first use.

        The part reads the very file the URDF named - a mesh is never copied or
        rewritten - so what a link's ``<origin>`` said stays a location in the
        assembly rather than becoming a transform baked into new geometry.

        The parts are registered in memory only - the URDF is what declares
        them, not ``partcad.yaml`` - which is why 'Project.get_part' builds the
        owning assembly when it is handed one of these names.
        """
        node_name = node["name"]
        if node_name in self._parts:
            return self._parts[node_name]

        part_name = self.part_name(node_name)
        part_file = os.path.abspath(node["part_file"])
        scale = float(node.get("scale") or 1.0)
        config = {
            "type": node["part_type"],
            "name": part_name,
            "orig_name": part_name,
            "path": part_file,
            "desc": "Link '%s' of the URDF assembly '%s'" % (node.get("link") or node_name, self.name),
        }
        # URDF states mesh coordinates in metres after applying the mesh's own
        # 'scale'; PartCAD works in millimetres. The wrapper reduces the two to a
        # single factor, which is 1.0 for the millimetre meshes PartCAD writes.
        if abs(scale - 1.0) > 1e-9:
            config["scale"] = scale
        # What URDF says about this link that PartCAD does not model, carried
        # verbatim so the export can put it back.
        if node.get("physics"):
            config["physics"] = node["physics"]

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
        self._parts[node_name] = part
        return part
