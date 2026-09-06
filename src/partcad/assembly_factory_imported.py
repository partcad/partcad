#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Any object type that is somebody else's file format, read by a plugin.

This is one factory for every ``import:`` type there is or ever will be -- the
three PartCAD ships (see 'builtin/import/'), and any a package supplies. Which
format it is reading is not a fact about this module: it is the declaration the
object's ``type:`` names, which says what the reader script is, what sandbox it
needs, which object kinds it may produce, and how to word what it could not
keep.

There used to be one of these per format -- 'assembly_factory_urdf',
'assembly_factory_mjcf', 'scene_factory_world' -- and they were the same file
three times over. Everything below the reader is format-independent: run it in
a sandbox, walk the tree of placed shapes it returns, register a part for each
leaf, report what was dropped. Only the reader knows XML. So the reader became
a plugin and this is what is left, which is also what makes a *new* format a
package rather than a patch to PartCAD.

**What the tree means.** A node is either an assembly (children under
``links``) or a part, and a part names the *file* its geometry is read from
rather than carrying geometry: the part factory for that file's own format
reads it afterwards, in its own runtime. So a mesh a URDF or an MJCF references
is never copied or rewritten, and what the source said about where it sits
stays a location in the tree instead of being baked into new geometry. Only a
format's primitives -- a box, a cylinder, a sphere -- have no file to name, and
the reader writes those out itself.

**Parts are registered in memory, not declared.** ``<object>/<node>`` is the
name each becomes, and the source file is what declares them, not
``partcad.yaml`` -- which is why 'Project.get_part' builds the owning object
when it is handed one of these names.

**Reading is not running.** An MJCF model is read here with the standard
library's XML parser and no MuJoCo; a URDF needs no ROS. Running a model is a
different thing entirely and is what a simulation plugin does (see
'partcad.simulation'). That is why the same package declares both and why
neither implies the other.
"""

import asyncio
import hashlib
import os

from . import logging as pc_logging
from . import output, shape_envelope, telemetry, wrapper
from .assembly import AssemblyChild
from .assembly_factory_file import AssemblyFactoryFile
from .geom import Location
from .part_config import PartConfiguration
from .scene_factory import SceneFactoryMixin

# What a node of the reader's tree may say about the shape it becomes. A reader
# speaks its own format's vocabulary and keeps these side by side; a PartCAD
# configuration groups them under 'properties:', which is where every consumer
# of a shape - the export above all - looks for them.
NODE_PROPERTIES = ("physics", "material", "color")


def node_properties(node):
    """The 'properties:' section for one node of the reader's tree."""
    return {key: node[key] for key in NODE_PROPERTIES if node.get(key)}


class ImportedTypeError(Exception):
    """The declaration names an 'import:' type that cannot serve it.

    Either nothing declares the type, or what does declare it says it produces
    a different kind of object than the section it was declared in asks for.
    """


@telemetry.instrument()
class AssemblyFactoryImported(AssemblyFactoryFile):
    # 'OBJECT_KIND' - 'assembly' here, 'scene' under the mixin below - is
    # inherited from 'AssemblyFactory' and is what decides both which kind this
    # produces and which kind the declaration has to say it can produce.

    def __init__(self, ctx, source_project, target_project, config):
        self.impl = output.import_declaration(ctx, target_project, config.get("type"))
        if self.impl is None:
            raise ImportedTypeError(
                "no 'import:' section declares the object type '%s'" % config.get("type"),
            )
        kinds = output.import_kinds(self.impl)
        if self.OBJECT_KIND not in kinds:
            raise ImportedTypeError(
                "the object type '%s' reads %s, so it cannot be declared as %s"
                % (
                    config.get("type"),
                    " or ".join("a %s" % kind for kind in kinds),
                    "an assembly" if self.OBJECT_KIND == "assembly" else "a scene",
                )
            )
        # What one of these is called in a log line. The declaration's word for
        # it, because 'reading the model' and 'reading the world' are what the
        # formats call themselves.
        self.noun = self.impl.config.get("noun") or self.impl.format_name
        self.dropped_labels = self.impl.config.get("dropped") or {}

        extension = "." + self.impl.extension(self.impl.format_name)
        with pc_logging.Action("Init:" + self.impl.format_name, source_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config, extension=extension)
            self._create(config)
            # Which parts the file resolves to is only known once it is read, so
            # the dependency set cannot be hashed up front - the same reason the
            # ASSY factory marks itself this way.
            self.assembly.cache_dependencies_broken = True
            for dep in self.config.get("dependencies", []):
                self.assembly.cache_dependencies.append(os.path.join(self.project.config_dir, dep))
            # What a caller holds is the object, so it is what points back here.
            # 'pc convert' needs the per-node data, which only this factory has.
            self.assembly.import_factory = self
            # node name -> the Part registered for it.
            self._parts = {}
            # source element -> what it resolved to. See 'link_item'.
            self._items = {}
            # What the last read found: 'pc info' reports it and 'pc convert'
            # builds the ASSY file out of it.
            self.import_info = {}

    def instantiate(self, assembly):
        asyncio.run(self.instantiate_async(assembly))

    async def instantiate_async(self, assembly):
        await super().instantiate(assembly)

        with pc_logging.Action(self.impl.format_name.upper(), assembly.project_name, assembly.name):
            result = await self._read_async()
            self._report(result)

            root = result["root"]
            await self.handle_node_list(assembly, root.get("links") or [])
            # Geometry the tree does not place: a link's visual shapes when it
            # was built from its collision geometry, and the other way round.
            # They are parts like any other - inspectable and exportable - they
            # are just not part of this static configuration.
            for node in root.get("parts") or []:
                self.part_for(node)

            if not assembly.children:
                pc_logging.warning("%s is empty" % self.OBJECT_KIND.capitalize())

            self.count_instantiated()

    async def read_async(self):
        """Read the file and return the reader's full result.

        Public because ``pc convert`` needs the whole tree, not just the
        children the object is built from.
        """
        result = await self._read_async()
        self._report(result)
        return result

    def link_item(self, link_name):
        """What one element of the source resolved to: a part, or a sub-assembly.

        Only populated once the object has been built. ``pc convert -t assy``
        uses it to render one mesh per source element whatever that element is
        made of.
        """
        return self._items.get(link_name)

    async def _read_async(self):
        """Run the reader in a sandbox and return its data tree."""
        script = await output.materialize_script(self.ctx, self.impl)

        request = {
            # The file an object is declared by is a Jinja2 template like every
            # other, so what is parsed is the *rendered* file - which is the
            # file itself unless the template said something. 'base_dir' is the
            # directory the package declared it in, and is what the meshes and
            # included files it names are still resolved against.
            "source_file": os.path.abspath(self.rendered_source()),
            "base_dir": os.path.dirname(os.path.abspath(self.path)),
            "output_folder": self._generated_dir(),
            "kind": self.OBJECT_KIND,
            "object_name": self.name,
            "search_paths": self._search_paths(),
        }
        # Every parameter the declaration carries, then whatever the object
        # itself said about them: a package tunes a reader per object (a
        # 'strict', an 'ignoreCollision') the same way it tunes an exporter.
        request.update(self.impl.parameters)
        request.update(self._declared_parameters())
        request[output.SCRIPT_KEY] = os.path.abspath(script)

        runtime = self.ctx.get_python_runtime(version=self.impl.python_version())
        await runtime.prepare_for_package(self.impl.project)
        # Installed one at a time, not with asyncio.gather(): the order matters,
        # since build123d overwrites the OCP native module that cadquery-ocp
        # installs (see sandbox_versions.GUARD_INVALIDATED_BY).
        for dep in self.impl.python_requirements:
            await runtime.ensure_async(dep)

        command = [
            wrapper.get("import.py"),
            os.path.abspath(self.impl.project.config_dir),
        ]
        exitcode, response_serialized, errors = await runtime.run_async(command, shape_envelope.serialize(request))
        if exitcode != 0 and not errors:
            errors = "reading the %s failed with exit code %s" % (self.noun, exitcode)
        if errors:
            pc_logging.error(errors)
            raise Exception(errors)

        result = shape_envelope.deserialize(response_serialized)
        if not result.get("success", False):
            raise Exception(result.get("exception") or "reading the %s failed" % self.noun)
        return result

    # What an object may call the extra roots it wants references resolved
    # against. One meaning, three spellings: 'package://' is what a URDF says
    # and 'model://' is what SDFormat says, so each format's users named the
    # setting after their own scheme long before there was one reader.
    SEARCH_PATH_KEYS = ("searchPaths", "packagePaths", "modelPaths")

    def _search_paths(self):
        """Roots to resolve the file's own references against.

        The package directory and the source file's own directory, plus whatever
        the object names. Outside a ROS workspace or a Gazebo installation there
        is no ROS_PACKAGE_PATH and no model database to consult, so this is what
        a standalone file gets.
        """
        paths = [self.project.config_dir, os.path.dirname(os.path.abspath(self.path))]
        for key in self.SEARCH_PATH_KEYS:
            for extra in self.config.get(key) or []:
                paths.append(extra if os.path.isabs(extra) else os.path.join(self.project.config_dir, extra))
        return paths

    def _declared_parameters(self):
        """What the object's own declaration says about the reader's parameters.

        Only the ones the reader has: an object's configuration carries a great
        deal that is not a reader parameter ('name', 'type', 'path', 'desc'),
        and handing all of it over would let a key of PartCAD's own quietly
        become one of the format's.
        """
        return {key: self.config[key] for key in self.impl.parameters if key in self.config}

    def _generated_dir(self):
        """Where geometry generated for a primitive is written.

        Under PartCAD's own state directory rather than inside the package: a
        shape built from a primitive is derived data, and instantiating an
        object should not drop files into the user's source tree. ``pc convert
        -t assy`` is the command that deliberately materializes them into the
        package.
        """
        digest = hashlib.sha256(os.path.abspath(self.path).encode()).hexdigest()[:16]
        return os.path.join(self.ctx.user_config.internal_state_dir, self.impl.format_name, digest)

    def info(self, shape):
        """The usual shape info, plus what the file said and what was dropped.

        The file is read here when it has not been read yet. Asking for a
        shape's info does not necessarily build it - its geometry may come
        straight from the cache - and then none of what follows would have
        anything to report, so 'pc info' would say less about an imported
        object the more often it had been used.

        What is reported *about the format* is the reader's own 'info' block,
        display-ready and in the format's vocabulary: PartCAD has no business
        deciding that a URDF's root link is interesting and an MJCF's timestep
        is not. The one thing the core words itself is 'dropped', because the
        reader counts and the declaration names.
        """
        info = super().info(shape)
        if not self.import_info:
            self._read_for_info()
        for key, value in (self.import_info.get("info") or {}).items():
            if value not in (None, "", [], {}):
                info[key] = value
        dropped = self.import_info.get("dropped") or {}
        if dropped:
            info["Dropped"] = {self.dropped_labels.get(key, key): count for key, count in sorted(dropped.items())}
        return info

    def _read_for_info(self):
        """Read the file just to populate 'import_info', reporting rather than raising.

        Driven with 'asyncio.run()' on the calling thread. Its one caller,
        'info()', is synchronous and is reached synchronously -- the daemon's
        'info' and 'info.object' operations are ordinary handlers -- so there is
        no loop here to collide with, and a thread of its own would be invisible
        to 'threads_max'.

        A file that cannot be read is a problem for building the object, not for
        describing it, so it is logged and the rest of the info still shows.
        """
        try:
            self._report(asyncio.run(self._read_async()))
        except Exception as e:  # pylint: disable=broad-except
            pc_logging.error("%s: could not read the %s: %s" % (self.name, self.noun, e))

    def _report(self, result):
        """Record and log the reader's complaints and what could not be kept."""
        # Everything the reader said, not a chosen few keys: what is interesting
        # about a format is the format's business, and 'pc convert' reads the
        # per-node data straight out of here.
        self.import_info = {key: value for key, value in result.items() if key not in ("success", "exception")}

        for warning in self.import_info.get("warnings") or []:
            pc_logging.warning("%s: %s" % (self.name, warning))

        dropped = self.import_info.get("dropped") or {}
        if dropped:
            described = ", ".join(
                "%s: %d" % (self.dropped_labels.get(key, key), count) for key, count in sorted(dropped.items())
            )
            pc_logging.info(
                "%s: a PartCAD %s cannot hold all of what this %s says; dropped %s"
                % (self.name, self.OBJECT_KIND, self.noun, described)
            )

    async def handle_node_list(self, assembly, nodes):
        for node in nodes:
            child = await self.handle_node(assembly, node)
            if child is not None:
                assembly.children.append(child)

    async def handle_node(self, assembly, node):
        """Turn one node of the reader's tree into an AssemblyChild."""
        name = node.get("name")
        location = Location(node["location"]) if node.get("location") else Location()

        if node["type"] == "assembly":
            config = {
                "name": "%s:%s" % (self.name, name),
                "child": True,
                "cache": self.ctx.user_config.cache,
                "cache_dependencies_ignore": self.ctx.user_config.cache_dependencies_ignore,
            }
            # A sub-assembly that *is* a source element carries what that
            # element said about itself, so the export finds it where it
            # expects to.
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

        if node.get("link") and node["link"] not in self._items:
            self._items[node["link"]] = item

        return AssemblyChild(item, name, location)

    def part_name(self, node_name):
        """The package-wide name of the part one node becomes.

        ``<object>/<element>`` for an element that is one shape, and
        ``<object>/<element>/<name or index>`` for one of several.
        """
        return "%s/%s" % (self.name, node_name)

    def part_for(self, node):
        """The Part for one node, registering it on first use."""
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
            "desc": "%s '%s' of the %s %s '%s'"
            % (
                (node.get("element_noun") or "Element").capitalize(),
                node.get("link") or node.get("body") or node_name,
                self.impl.format_name.upper(),
                self.OBJECT_KIND,
                self.name,
            ),
        }
        # A format that states mesh coordinates in anything but millimetres has
        # the reader reduce its own units and the asset's own scale to a single
        # factor, which is 1.0 for the millimetre meshes PartCAD writes.
        if abs(scale - 1.0) > 1e-9:
            config["scale"] = scale
        properties = node_properties(node)
        if properties:
            config[shape_envelope.KEY_PROPERTIES] = properties

        full_name = "%s:%s" % (self.project.name, part_name)
        config = PartConfiguration.normalize(part_name, config, full_name)
        try:
            part = self.project.materialize_part_by_config(config)
        except Exception as e:  # pylint: disable=broad-except
            pc_logging.error("%s: failed to add the part '%s': %s" % (self.name, part_name, e))
            return None

        if part is None:
            pc_logging.error("%s: the part '%s' failed to instantiate" % (self.name, part_name))
            return None
        self.assembly.cache_dependencies.append(part_file)
        self._parts[node_name] = part
        return part


@telemetry.instrument()
class SceneFactoryImported(SceneFactoryMixin, AssemblyFactoryImported):
    """The same reader, producing a scene.

    Which of the two a given file becomes is decided by the section that
    declares it, exactly as it is for an ASSY file: a model in ``assemblies:``
    is a product, one in ``scenes:`` is an arrangement of things. A format used
    for only one of them says so with ``kinds:`` in its declaration, and
    declaring it in the other section is then an error rather than a tree that
    comes out surprising.

    Everything that makes it a scene - the kind, the class, the counters - comes
    from 'SceneFactoryMixin', which is mixed in ahead of the factory so its
    values win.
    """
