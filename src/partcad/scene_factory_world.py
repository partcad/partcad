#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The 'world' scene type: a Gazebo world file used directly as a PartCAD scene.

A ``.world`` file is SDFormat: models placed in a world, each made of links,
each link made of shapes. That is a placed arrangement and nothing more, which
is exactly what a scene is -- so the two meet at the world's initial state, and
what comes out here is the very same tree an ASSY scene produces. Everything
downstream (rendering, export, bill of materials, inspection, caching) treats a
world scene and an ASSY scene identically, and 'pc convert scene' turns either
into the other.

Every link becomes one part, registered into the package as
``<scene name>/<model>/<link>``. Those parts are ordinary parts: they can be
inspected, rendered and exported on their own. They are not declared in
``partcad.yaml`` -- the world file is what declares them -- so a package
resolves such a name by building the scene that owns it first (see
``Project._derived_part_owner``).

The reading is done by 'wrapper_import_world' inside a Python sandbox: turning
the primitives a world names (a box, a cylinder, a sphere) into geometry needs
OCCT, which the core process never loads. What comes back here is plain data.

**It is a best-effort reader.** SDFormat describes a running simulation and a
scene describes where things are, so what a static arrangement cannot hold --
joints, lights, sensors, plugins, actors, physics settings, the ground plane --
is counted and reported rather than passed over in silence. See
docs/source/simulation.rst.

Note that "SDF" means SDFormat here and nowhere else in PartCAD: the ``sdf``
*part* type is a signed distance function and has nothing to do with this. The
file type is called ``world`` throughout, after the files it lives in, which is
also the identifier a scene is exported to it under.
"""

import asyncio
import hashlib
import os
import threading

from . import logging as pc_logging
from . import sandbox_versions, shape_envelope, telemetry, wrapper
from .assembly import AssemblyChild
from .assembly_factory_file import AssemblyFactoryFile
from .geom import Location
from .part_config import PartConfiguration
from .scene import Scene
from .scene_factory import SceneFactoryMixin

# How a counter from the wrapper's 'dropped' summary is worded in the log.
DROPPED_LABELS = {
    "joint": "joints (the scene shows the models at their initial pose)",
    "light": "lights",
    "sensor": "sensors",
    "plugin": "simulator plugins",
    "actor": "actors",
    "physics": "physics settings",
    "collision": "collision geometry (kept as parts of its own, but not placed)",
    "visual": "visual geometry (kept as parts of its own, but not placed)",
    "geometry": "shapes PartCAD has no geometry for",
    "include": "included models that could not be resolved",
}

# What a node of the wrapper's tree may say about the shape it becomes. The
# wrapper speaks SDFormat's vocabulary and keeps these side by side; a PartCAD
# configuration groups them under 'properties:', which is where every consumer
# of a shape - the export above all - looks for them.
NODE_PROPERTIES = ("physics", "material", "color")


def node_properties(node):
    """The 'properties:' section for one node of the wrapper's tree."""
    return {key: node[key] for key in NODE_PROPERTIES if node.get(key)}


@telemetry.instrument()
class SceneFactoryWorld(SceneFactoryMixin, AssemblyFactoryFile):
    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitWorld", source_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config, extension=".world")
            self._create(config)
            # Which parts a world resolves to is only known once it is read, so
            # the dependency set cannot be hashed up front - the same reason the
            # ASSY factory marks itself this way.
            self.assembly.cache_dependencies_broken = True
            for dep in self.config.get("dependencies", []):
                self.assembly.cache_dependencies.append(os.path.join(self.project.config_dir, dep))
            # 'pc convert scene -t assy' needs the per-node data, which only
            # this factory has. The Scene object is what a caller holds, so it
            # is what points back here.
            self.assembly.world_factory = self
            # node name -> the Part registered for it.
            self._parts = {}
            # What the last read of the world found: 'pc info' reports it and
            # 'pc convert scene' builds the ASSY file out of it.
            self.world_info = {}

    def instantiate(self, assembly):
        asyncio.run(self.instantiate_async(assembly))

    async def instantiate_async(self, assembly):
        await super().instantiate(assembly)

        with pc_logging.Action("World", assembly.project_name, assembly.name):
            result = await self._read_async()
            self._report(result)

            root = result["root"]
            await self.handle_node_list(assembly, root.get("links") or [])
            # Geometry the scene does not place: the visual shapes of a link
            # built from its collision geometry, and the other way round.
            for node in root.get("parts") or []:
                self.part_for(node)

            if not assembly.children:
                pc_logging.warning("Scene is empty")

            self.count_instantiated()

    async def read_async(self):
        """Read the world and return the wrapper's full result.

        Public because ``pc convert scene -t assy`` needs the whole tree, not
        just the children the scene is built from.
        """
        result = await self._read_async()
        self._report(result)
        return result

    async def _read_async(self):
        """Run the world reader in a sandbox and return its data tree."""
        runtime = self.ctx.get_python_runtime(version=sandbox_versions.DEFAULT_PYTHON_VERSION)
        # Only SDFormat's box/cylinder/sphere have to be turned into geometry -
        # a mesh is referenced where it lies and read by the part factory for
        # its format, in that factory's own runtime. The XML is parsed with the
        # standard library, so nothing else is needed.
        await runtime.ensure_async(sandbox_versions.CADQUERY_OCP)

        request = {
            "operation": "import_world",
            # A world file is a Jinja2 template like every other file an object
            # is declared by, so what is parsed is the rendered file - which is
            # the file itself unless the template said something. 'base_dir' is
            # the directory the package declared it in, and is what the meshes
            # and models it names are still resolved against.
            "world_file": os.path.abspath(self.rendered_source()),
            "base_dir": os.path.dirname(os.path.abspath(self.path)),
            "output_folder": self._generated_dir(),
            "model_paths": self._model_paths(),
            "ignoreCollision": self.config.get("ignoreCollision", False),
            "precision": 6,
        }

        wrapper_path = wrapper.get("import_world.py")
        command = [wrapper_path, "import_world"]
        exitcode, response_serialized, errors = await runtime.run_async(command, shape_envelope.serialize(request))
        if exitcode != 0 and not errors:
            errors = "reading the world failed with exit code %s" % exitcode
        if errors:
            pc_logging.error(errors)
            raise Exception(errors)

        result = shape_envelope.deserialize(response_serialized)
        if not result.get("success", False):
            raise Exception(result.get("exception") or "reading the world failed")
        return result

    def _generated_dir(self):
        """Where geometry generated for a link is written.

        Under PartCAD's own state directory rather than inside the package, for
        the reason 'AssemblyFactoryUrdf' gives: a shape built from a primitive
        is derived data, and instantiating a scene should not drop files into
        the user's source tree. ``pc convert scene -t assy`` is the command that
        deliberately materializes them into the package.
        """
        digest = hashlib.sha256(os.path.abspath(self.path).encode()).hexdigest()[:16]
        return os.path.join(self.ctx.user_config.internal_state_dir, "world", digest)

    def _model_paths(self):
        """Roots to resolve ``model://`` references against.

        The package directory and the world file's own directory, plus whatever
        the scene configuration names. Outside a Gazebo installation there is
        no model database to consult, so this is what a standalone world gets.
        """
        paths = [self.project.config_dir, os.path.dirname(os.path.abspath(self.path))]
        for extra in self.config.get("modelPaths") or []:
            paths.append(extra if os.path.isabs(extra) else os.path.join(self.project.config_dir, extra))
        return paths

    def info(self, shape):
        """The usual shape info, plus what this world said and what was dropped.

        The world is read here when it has not been read yet, for the reason
        'AssemblyFactoryUrdf.info' gives: asking for a shape's info does not
        necessarily build it, and then none of what follows would have anything
        to report.
        """
        info = super().info(shape)
        if not self.world_info:
            self._read_world_for_info()
        if self.world_info.get("world_name"):
            info["World"] = self.world_info["world_name"]
        dropped = self.world_info.get("dropped") or {}
        if dropped:
            info["WorldDropped"] = {DROPPED_LABELS.get(key, key): count for key, count in sorted(dropped.items())}
        return info

    def _read_world_for_info(self):
        """Read the world just to populate 'world_info', reporting rather than raising.

        On a thread of its own, for the reason 'Project._materialize_derived_part'
        gives: this is reached from synchronous callers and from coroutines
        alike, and 'asyncio.run' raises in a thread that already has a loop.
        """
        failure = []

        def read():
            try:
                self._report(asyncio.run(self._read_async()))
            except Exception as e:  # pylint: disable=broad-except
                failure.append(e)

        thread = threading.Thread(target=read, daemon=True)
        thread.start()
        thread.join()
        if failure:
            pc_logging.error("%s: could not read the world: %s" % (self.name, failure[0]))

    def _report(self, result):
        """Record and log the reader's complaints and what could not be kept."""
        self.world_info = {
            "world_name": result.get("world_name"),
            "warnings": result.get("warnings") or [],
            "dropped": result.get("dropped") or {},
            "root": result.get("root") or {},
        }

        for warning in self.world_info["warnings"]:
            pc_logging.warning("%s: %s" % (self.name, warning))

        dropped = self.world_info["dropped"]
        if dropped:
            described = ", ".join(
                "%s: %d" % (DROPPED_LABELS.get(key, key), count) for key, count in sorted(dropped.items())
            )
            pc_logging.info(
                "%s: a PartCAD scene cannot hold all of what this world says; dropped %s" % (self.name, described)
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
            item = Scene(assembly.project_name, config)
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
        """The package-wide name of the part a world shape becomes.

        ``<scene>/<model>/<link>`` for a link that is one shape, and
        ``<scene>/<model>/<link>/<name or index>`` for one of several.
        """
        return "%s/%s" % (self.name, node_name)

    def part_for(self, node):
        """The Part for one world shape, registering it on first use.

        The part reads the very file the world named - a mesh is never copied
        or rewritten - so what a link's ``<pose>`` said stays a location in the
        scene rather than becoming a transform baked into new geometry.

        The parts are registered in memory only - the world file is what
        declares them, not ``partcad.yaml`` - which is why 'Project.get_part'
        builds the owning scene when it is handed one of these names.
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
            "desc": "Link '%s' of the world scene '%s'" % (node.get("link") or node_name, self.name),
        }
        # SDFormat states mesh coordinates in metres after applying the mesh's
        # own 'scale'; PartCAD works in millimetres. The wrapper reduces the two
        # to a single factor, which is 1.0 for the millimetre meshes PartCAD
        # writes.
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
