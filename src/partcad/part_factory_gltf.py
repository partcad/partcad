#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A part read from a glTF file: '.gltf' with its buffers, or a single '.glb'.

glTF is how meshes travel between renderers, game engines and the web, and what
`pc export -t gltf` writes. The file is read by 'wrappers/wrapper_import_gltf.py':
the triangles of every mesh the scene draws, placed by the node tree and stated
in millimetres, made into a solid per closed piece, each face in its material's
colour. What the web's compression extensions store is decoded on the way
('wrappers/gltf_document.py'); for Draco that takes DracoPy, which the sandbox
is given only for a file that uses it.

A part with no 'path' is '<name>.gltf', or '<name>.glb' when that is the file
there is.
"""

import json
import os
from pathlib import Path
from urllib.parse import unquote

from . import logging as pc_logging
from . import sandbox_versions, shape_envelope, telemetry, wrapper
from .part_factory_file import PartFactoryFile
from .part_factory_homogen import PartFactoryHomogen
from .process_crash import command_failure

# The first four bytes of every binary glTF ('.glb') file, by the specification:
# 'glTF' in ASCII. A '.gltf' is JSON and starts with '{' (or whitespace).
GLB_MAGIC = b"glTF"

# The two files a glTF part may be, in the order a part with no 'path' looks for them.
EXTENSIONS = (".gltf", ".glb")

# The extension whose primitives only DracoPy decodes.
DRACO = "KHR_draco_mesh_compression"


def gltf_json(source_path):
    """The JSON a glTF file holds - a '.gltf' itself, a '.glb''s first chunk - or None if it holds none.

    Read here, without the sandbox, for what the core has to know before the
    reader runs: which files to hash with it, and what the sandbox needs.
    """
    try:
        with open(source_path, "rb") as f:
            head = f.read(20)
            if head[: len(GLB_MAGIC)] == GLB_MAGIC:
                # The header, then the first chunk: its length, its type, and
                # its bytes, which are all that is read of a '.glb'.
                if len(head) < 20 or head[16:20] != b"JSON":
                    return None
                data = f.read(int.from_bytes(head[12:16], "little"))
            else:
                data = head + f.read()
    except OSError:
        return None  # nothing there yet: 'fileFrom' has not fetched it
    try:
        # From bytes, which 'json' decodes the way the glTF specification says
        # a '.gltf' is encoded (UTF-8), and refuses if it is not JSON at all.
        document = json.loads(data)
    except ValueError:
        return None  # not glTF at all; the reader says so, with the file named
    return document if isinstance(document, dict) else None


def gltf_extensions(source_path) -> set:
    """The extensions a glTF file says it uses ('extensionsUsed'); empty if it is not one."""
    document = gltf_json(source_path)
    used = document.get("extensionsUsed") if document is not None else None
    return {name for name in used if isinstance(name, str)} if isinstance(used, list) else set()


def gltf_companions(source_path) -> list:
    """The files a '.gltf' file names beside itself, its buffers and its images, relative to it.

    A '.glb' carries them inside, and a URI that is a 'data:' URL or a web
    address is not a file; anything else is a percent-encoded path relative to
    the '.gltf', and the part cannot be read without it.
    """
    source_path = Path(source_path)
    try:
        with open(source_path, "rb") as f:
            if f.read(len(GLB_MAGIC)) == GLB_MAGIC:
                return []  # a '.glb', whatever it is named: its buffers are inside it
    except OSError:
        return []  # nothing there yet: 'fileFrom' has not fetched it
    document = gltf_json(source_path)
    if document is None:
        return []
    found = []
    for section in ("buffers", "images"):
        for item in document.get(section) or []:
            uri = item.get("uri") if isinstance(item, dict) else None
            if not isinstance(uri, str) or not uri or ":" in uri:
                continue  # inside the file, or not a file at all
            relative = unquote(uri)
            # Only what sits at or below the '.gltf': a copy must land inside
            # the package it is imported into.
            if ":" in relative or relative.startswith(("/", "\\")) or ".." in Path(relative).parts:
                continue
            if (source_path.parent / relative).is_file() and relative not in found:
                found.append(relative)
    return found


@telemetry.instrument()
class PartFactoryGltf(PartFactoryHomogen, PartFactoryFile):
    # Its version covers the modules it reads and builds with ('gltf_document',
    # 'meshopt_decode', 'mesh_brep'), which state none of their own.
    WRAPPERS = ("import_gltf.py",)

    PYTHON_SANDBOX_VERSION = sandbox_versions.DEFAULT_PYTHON_VERSION

    def __init__(self, ctx, source_project, target_project, config):
        with pc_logging.Action("InitGLTF", target_project.name, config["name"]):
            super().__init__(ctx, source_project, target_project, config, extension=EXTENSIONS)
            self._create(config)
            self.runtime = None  # Lazy initialization for the sandbox runtime

    def post_create(self) -> None:
        # What the '.gltf' names is read with it, so a new buffer is a new part.
        if self.path and os.path.isfile(self.path):
            for relative in gltf_companions(self.path):
                self.part.cache_dependencies.append(os.path.join(os.path.dirname(self.path), relative))
        super().post_create()

    async def instantiate(self, part):
        await super().instantiate(part)

        with pc_logging.Action("GLTF", part.project_name, part.name):
            if self.runtime is None:
                self.runtime = self.ctx.get_python_runtime(self.PYTHON_SANDBOX_VERSION)

            request = {"name": "%s:%s" % (part.project_name, part.name), "label": part.name}
            # Validated and moved by the wrapper, while the shape is live (see 'Shape.finish_request').
            request[shape_envelope.KEY_FINISH] = part.finish_request()
            request_serialized = shape_envelope.serialize(request)

            await self.runtime.ensure_async(sandbox_versions.OCP_TESSELLATE)
            await self.runtime.ensure_async(sandbox_versions.TYPING_EXTENSIONS)
            await self.runtime.ensure_async(sandbox_versions.OCPSVG)
            await self.runtime.ensure_async(sandbox_versions.BUILD123D)
            await self.runtime.ensure_async(sandbox_versions.OCP)
            if DRACO in gltf_extensions(self.path):
                # Only a file that is Draco-compressed needs the decoder.
                await self.runtime.ensure_async(sandbox_versions.DRACOPY)

            command = [wrapper.get("import_gltf.py"), os.path.abspath(self.path)]
            with telemetry.start_as_current_span("*PartFactoryGltf.instantiate.{runtime.run_async}"):
                exitcode, response_serialized, errors = await self.runtime.run_async(command, request_serialized)
            if exitcode != 0 and len(errors) == 0:
                errors = command_failure(command, exitcode)
            if errors:
                pc_logging.error(errors)
                raise Exception(errors)

            result = shape_envelope.deserialize(response_serialized)
            if not result["success"]:
                pc_logging.error(result["exception"])
                raise Exception(result["exception"])

            # What the file holds that the part does not: point and line
            # primitives, animations, open pieces read as surfaces.
            for warning in result.get("warnings") or []:
                pc_logging.warning("%s:%s: %s" % (part.project_name, part.name, warning))

            self.ctx.stats_parts_instantiated += 1
            return result["shape"]
