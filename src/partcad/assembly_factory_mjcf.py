#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The 'mjcf' assembly type: a MuJoCo model used directly as a PartCAD assembly.

MJCF is what MuJoCo describes a simulated model in: a ``<worldbody>`` holding
bodies, each body holding geoms and further bodies. PartCAD's assembly is a
static tree of placed shapes, so the two meet at the model's initial state --
every body where its own ``pos`` and orientation put it, every geom where its
own put it inside its body -- and the result is the very same in-memory
representation an ASSY file produces. Everything downstream (rendering, export,
bill of materials, inspection, caching) therefore treats an MJCF object and an
ASSY one identically.

The same file is also a *scene* type ('SceneFactoryMjcf' below), and which of
the two a given file is read as is decided by the section that declares it, not
by the file: an MJCF model of a robot arm is an assembly, an MJCF model of the
table it stands on is a scene. That is the same split ``urdf`` and ``world``
already have, and MJCF is the one format that is routinely used for both.

Every geom becomes one part, registered into the package as
``<object name>/<body>`` -- or ``<object name>/<body>/<geom>`` where a body
holds several. Those parts are ordinary parts: they can be inspected, rendered
and exported on their own. They are not declared in ``partcad.yaml`` -- the
MJCF file is what declares them -- so a package resolves such a name by
building the object that owns it first (see ``Project._derived_part_owner``).

The reading is done by 'wrapper_import_mjcf' inside a Python sandbox: turning
the primitives MJCF names (a box, a cylinder, a sphere) into geometry needs
OCCT, which the core process never loads. What comes back here is plain data,
and no MuJoCo installation is involved -- MJCF is XML, and PartCAD reads it with
the standard library. Running the model is a different thing entirely, and is
what a simulation plugin does (see 'partcad.simulation').

**It is a best-effort reader.** MJCF describes a running simulation and a
PartCAD tree describes where things are, so what a static arrangement cannot
hold -- joints, actuators, tendons, sensors, lights, cameras, contacts,
keyframes -- is counted and reported rather than passed over in silence. See
docs/source/simulation.rst.
"""

import asyncio
import hashlib
import os

from . import logging as pc_logging
from . import sandbox_versions, shape_envelope, telemetry, wrapper
from .assembly import AssemblyChild
from .assembly_factory_file import AssemblyFactoryFile
from .geom import Location
from .part_config import PartConfiguration

# How a counter from the wrapper's 'dropped' summary is worded in the log.
DROPPED_LABELS = {
    "joint": "joints (the object shows the bodies at their initial pose)",
    "actuator": "actuators",
    "tendon": "tendons",
    "equality": "equality constraints",
    "contact": "contact pairs and exclusions",
    "sensor": "sensors",
    "light": "lights",
    "camera": "cameras",
    "site": "sites",
    "keyframe": "keyframes",
    "plugin": "engine plugins",
    "geometry": "geoms PartCAD has no shape for",
    "include": "included files that could not be resolved",
}

# What a node of the wrapper's tree may say about the shape it becomes. The
# wrapper speaks MJCF's vocabulary and keeps these side by side; a PartCAD
# configuration groups them under 'properties:', which is where every consumer
# of a shape - the export above all - looks for them.
NODE_PROPERTIES = ("physics", "material", "color")


def node_properties(node):
    """The 'properties:' section for one node of the wrapper's tree."""
    return {key: node[key] for key in NODE_PROPERTIES if node.get(key)}


@telemetry.instrument()
class AssemblyFactoryMjcf(AssemblyFactoryFile):
    # What the object is called in a message. Overridden by the scene factory
    # below, which is the same reader producing a scene.
    OBJECT_NOUN = "assembly"

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitMJCF", source_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config, extension=".xml")
            self._create(config)
            # Which parts an MJCF file resolves to is only known once it is
            # read, so the dependency set cannot be hashed up front - the same
            # reason the ASSY factory marks itself this way.
            self.assembly.cache_dependencies_broken = True
            for dep in self.config.get("dependencies", []):
                self.assembly.cache_dependencies.append(os.path.join(self.project.config_dir, dep))
            # What a caller holds is the object, so it is what points back here.
            self.assembly.mjcf_factory = self
            # node name -> the Part registered for it.
            self._parts = {}
            # What the last read of the model found: 'pc info' reports it.
            self.mjcf_info = {}

    def instantiate(self, assembly):
        asyncio.run(self.instantiate_async(assembly))

    async def instantiate_async(self, assembly):
        await super().instantiate(assembly)

        with pc_logging.Action("MJCF", assembly.project_name, assembly.name):
            result = await self._read_async()
            self._report(result)

            root = result["root"]
            await self.handle_node_list(assembly, root.get("links") or [])
            for node in root.get("parts") or []:
                self.part_for(node)

            if not assembly.children:
                pc_logging.warning("%s is empty" % self.OBJECT_NOUN.capitalize())

            self.count_instantiated()

    async def read_async(self):
        """Read the model and return the wrapper's full result."""
        result = await self._read_async()
        self._report(result)
        return result

    async def _read_async(self):
        """Run the MJCF reader in a sandbox and return its data tree."""
        runtime = self.ctx.get_python_runtime(version=sandbox_versions.DEFAULT_PYTHON_VERSION)
        # Only MJCF's box/cylinder/sphere have to be turned into geometry - a
        # mesh is referenced where it lies and read by the part factory for its
        # format, in that factory's own runtime. The XML is parsed with the
        # standard library, so nothing else is needed. In particular 'mujoco'
        # itself is not: reading a model is not running one.
        await runtime.ensure_async(sandbox_versions.CADQUERY_OCP)

        request = {
            "operation": "import_mjcf",
            # An MJCF file is a Jinja2 template like every other file an object
            # is declared by, so what is parsed is the rendered file - which is
            # the file itself unless the template said something. 'base_dir' is
            # the directory the package declared it in, and is what the meshes
            # and included files it names are still resolved against.
            "mjcf_file": os.path.abspath(self.rendered_source()),
            "base_dir": os.path.dirname(os.path.abspath(self.path)),
            "output_folder": self._generated_dir(),
            "precision": 6,
        }

        wrapper_path = wrapper.get("import_mjcf.py")
        command = [wrapper_path, "import_mjcf"]
        exitcode, response_serialized, errors = await runtime.run_async(command, shape_envelope.serialize(request))
        if exitcode != 0 and not errors:
            errors = "reading the MJCF model failed with exit code %s" % exitcode
        if errors:
            pc_logging.error(errors)
            raise Exception(errors)

        result = shape_envelope.deserialize(response_serialized)
        if not result.get("success", False):
            raise Exception(result.get("exception") or "reading the MJCF model failed")
        return result

    def _generated_dir(self):
        """Where geometry generated for a geom is written.

        Under PartCAD's own state directory rather than inside the package, for
        the reason 'AssemblyFactoryUrdf' gives: a shape built from a primitive
        is derived data, and instantiating an object should not drop files into
        the user's source tree.
        """
        digest = hashlib.sha256(os.path.abspath(self.path).encode()).hexdigest()[:16]
        return os.path.join(self.ctx.user_config.internal_state_dir, "mjcf", digest)

    def info(self, shape):
        """The usual shape info, plus what this model said and what was dropped.

        The model is read here when it has not been read yet, for the reason
        'AssemblyFactoryUrdf.info' gives: asking for a shape's info does not
        necessarily build it, and then none of what follows would have anything
        to report.
        """
        info = super().info(shape)
        if not self.mjcf_info:
            self._read_mjcf_for_info()
        if self.mjcf_info.get("model_name"):
            info["Model"] = self.mjcf_info["model_name"]
        dropped = self.mjcf_info.get("dropped") or {}
        if dropped:
            info["MjcfDropped"] = {DROPPED_LABELS.get(key, key): count for key, count in sorted(dropped.items())}
        return info

    def _read_mjcf_for_info(self):
        """Read the model just to populate 'mjcf_info', reporting rather than raising.

        Driven with 'asyncio.run()' on the calling thread, exactly as
        'AssemblyFactoryUrdf._read_urdf_for_info' is and for the reason stated
        there: its one caller is synchronous and is reached synchronously, so
        there is no loop here to collide with, and a thread of its own would be
        invisible to 'threads_max'.
        """
        try:
            self._report(asyncio.run(self._read_async()))
        except Exception as e:  # pylint: disable=broad-except
            pc_logging.error("%s: could not read the MJCF model: %s" % (self.name, e))

    def _report(self, result):
        """Record and log the reader's complaints and what could not be kept."""
        self.mjcf_info = {
            "model_name": result.get("model_name"),
            "warnings": result.get("warnings") or [],
            "dropped": result.get("dropped") or {},
            "root": result.get("root") or {},
        }

        for warning in self.mjcf_info["warnings"]:
            pc_logging.warning("%s: %s" % (self.name, warning))

        dropped = self.mjcf_info["dropped"]
        if dropped:
            described = ", ".join(
                "%s: %d" % (DROPPED_LABELS.get(key, key), count) for key, count in sorted(dropped.items())
            )
            pc_logging.info(
                "%s: a PartCAD %s cannot hold all of what this MJCF model says; dropped %s"
                % (self.name, self.OBJECT_NOUN, described)
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
            properties = node_properties(node)
            if properties:
                config[shape_envelope.KEY_PROPERTIES] = properties
            item = self.OBJECT_CLASS(assembly.project_name, config)
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

        return AssemblyChild(item, name, location)

    def part_name(self, node_name):
        """The package-wide name of the part an MJCF geom becomes.

        ``<object>/<body>`` for a body that is one geom, and
        ``<object>/<body>/<name or index>`` for one of several.
        """
        return "%s/%s" % (self.name, node_name)

    def part_for(self, node):
        """The Part for one MJCF geom, registering it on first use.

        The part reads the very file the model's asset named - a mesh is never
        copied or rewritten - so what a geom's ``pos`` said stays a location in
        the tree rather than becoming a transform baked into new geometry.

        The parts are registered in memory only - the MJCF file is what declares
        them, not ``partcad.yaml`` - which is why 'Project.get_part' builds the
        owning object when it is handed one of these names.
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
            "desc": "Body '%s' of the MJCF %s '%s'" % (node.get("body") or node_name, self.OBJECT_NOUN, self.name),
        }
        # MJCF states mesh coordinates in metres after applying the asset's own
        # 'scale'; PartCAD works in millimetres. The wrapper reduces the two to
        # a single factor, which is 1.0 for the millimetre meshes PartCAD writes.
        if abs(scale - 1.0) > 1e-9:
            config["scale"] = scale
        properties = node_properties(node)
        if properties:
            config[shape_envelope.KEY_PROPERTIES] = properties

        full_name = "%s:%s" % (self.project.name, part_name)
        config = PartConfiguration.normalize(part_name, config, full_name)
        try:
            part = self.project.materialize_part_by_config(config)
        except Exception as e:
            pc_logging.error("%s: failed to add the part '%s': %s" % (self.name, part_name, e))
            return None

        if part is None:
            pc_logging.error("%s: the part '%s' failed to instantiate" % (self.name, part_name))
            return None
        self.assembly.cache_dependencies.append(part_file)
        self._parts[node_name] = part
        return part
