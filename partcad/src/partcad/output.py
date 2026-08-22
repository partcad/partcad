#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""How an output file type is configured and who implements it.

PartCAD writes output files in two flavours, each declared in a section of
'partcad.yaml' of the same name:

    'export:'   the 3D and CAD formats 'pc export' writes
    'render:'   the 2D projections 'pc render' writes

A section has one subsection per file type, whose fields are that type's
parameters. Three of them are not parameters but say how the file is produced -
'path' (the implementation script), 'package' (where that script lives) and
'pythonRequirements' (what its sandbox needs) - and three more describe where
the output goes rather than what goes in it. Everything else is handed to the
implementation verbatim, which is what lets a package add a parameter (say, a
'comment' for STEP) without PartCAD having to know about it.

The built-in implementations are not special-cased anywhere: they are declared
in exactly this form by two packages that ship inside 'partcad' itself and that
every context can reach, '//builtin/export' and '//builtin/render' (see
'builtin/'). Resolving a file type means layering the configuration of the
package that asked for it on top of the built-in package's, so a package that
declares 'path' for a type replaces the implementation for itself and one that
declares only a parameter keeps the built-in implementation and re-tunes it.
"""

from __future__ import annotations

import copy
import os
from typing import Optional

from . import logging as pc_logging
from . import sandbox_versions

# The two output sections, which are also the two built-in packages' names.
EXPORT = "export"
RENDER = "render"
SECTIONS = (EXPORT, RENDER)

# Where the built-in packages live, both as package paths and on disk. They are
# inside the 'partcad' Python package so that they ship with it and are always
# present, wheel or frozen bundle alike.
BUILTIN_ROOT_PACKAGE = "//builtin"
BUILTIN_PACKAGES = {
    EXPORT: "//builtin/export",
    RENDER: "//builtin/render",
}
BUILTIN_ROOT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "builtin")
BUILTIN_PATHS = {
    BUILTIN_ROOT_PACKAGE: BUILTIN_ROOT_PATH,
    BUILTIN_PACKAGES[EXPORT]: os.path.join(BUILTIN_ROOT_PATH, EXPORT),
    BUILTIN_PACKAGES[RENDER]: os.path.join(BUILTIN_ROOT_PATH, RENDER),
}

# File types declared in a 'render:' section like any other, but which no
# implementation script produces: PartCAD assembles them itself out of what the
# package declares and the images the other formats leave behind.
#
#   'readme'          -- the package (or assembly) document, see
#                        Project.render_readme_async(). 'markdown' is its old name.
#   'pdf' and 'html'  -- the assembly instruction book, see
#                        Project.render_assembly_guide_async(). They are
#                        assembly_guide.GUIDE_FORMATS, repeated here rather than
#                        imported because 'assembly_guide' imports this module.
#
# Held out wherever a section is read as a list of file types to run an
# implementation for, so that declaring one does not send PartCAD looking for a
# 'path' that was never meant to exist.
NON_WRAPPER_FORMATS = frozenset({"readme", "markdown", "pdf", "html"})

# Keys of a section that configure the section itself rather than name a file
# type. Everything else under 'export:'/'render:' is a file type, so these have
# to be held out wherever the section is read as a list of them.
SECTION_KEYS = frozenset({"output_dir"})


def format_names(section_obj) -> list:
    """The file types a section names, without its own settings."""
    if not isinstance(section_obj, dict):
        return []
    return [name for name in section_obj if name not in SECTION_KEYS]


# The fields of a file type's configuration that are not parameters.
#
# The first group picks the implementation, the second places the output file.
# What is left over is what the implementation is handed, so adding a field here
# hides it from every implementation - including the ones packages write.
IMPLEMENTATION_KEYS = frozenset({"path", "package", "pythonRequirements", "pythonVersion", "decode"})
OUTPUT_KEYS = frozenset({"extension", "prefix", "exclude", "output_dir"})
RESERVED_KEYS = IMPLEMENTATION_KEYS | OUTPUT_KEYS | frozenset({"desc"})

# The request key the implementation script's path travels under. It is passed
# in the request rather than on the command line because the two positional
# arguments of a wrapper are already spent on the output path and the working
# directory (see wrappers/wrapper_export.py, which spells this out again -- a
# wrapper runs in a sandbox and cannot import 'partcad').
SCRIPT_KEY = "__script__"

# The request key that says whether the sandbox rebuilds the shape and assembly
# envelopes into live OCCT geometry before the implementation sees them. It
# travels beside the script path for the same reason: the wrapper has to know
# before it deserializes anything. Declared on a file type as 'decode: false',
# which is what an implementation asks for when it needs what an envelope says
# *about* a node: decoding mirrors the assembly tree in nested compounds, but
# geometry is all it keeps - every node's 'name' and 'label' is dropped, and its
# placement is baked into the shape instead of staying readable as data.
DECODE_KEY = "__decode__"

# A parameter, not a reserved key: a file type declares 'properties: true' to be
# handed what the shapes state about themselves ('physics', 'material',
# 'color'), keyed by full name, instead of the flag. Named here so the core and
# the implementations agree on the spelling.
PROPERTIES_KEY = "properties"


class Implementation:
    """Who writes a file of a given type, and with what.

    'script' is whatever 'path' said, relative to 'project'; resolving it to a
    file on disk (and, for a plugin-backed package, fetching it) is
    'Shape._materialize_output_script()', which also fills 'project' in.
    """

    def __init__(self, section: str, format_name: str, config: dict, project=None):
        self.section = section
        self.format_name = format_name
        self.config = config
        self.project = project
        self.script = config.get("path")
        self.python_requirements = list(config.get("pythonRequirements") or [])
        # Whether the sandbox decodes the envelopes into live geometry for this
        # implementation. Off for one that needs the assembly tree's structure
        # rather than the compound it decodes to.
        self.decode = config.get("decode", True) is not False

    @property
    def parameters(self) -> dict:
        """The fields handed to the implementation as its 'request'."""
        return {key: value for key, value in self.config.items() if key not in RESERVED_KEYS}

    def extension(self, default: str) -> str:
        return self.config.get("extension") or default

    def python_version(self) -> str:
        """Which sandbox interpreter runs this implementation.

        Not taken from the implementing package's 'pythonVersion': that
        defaults to whatever interpreter PartCAD itself happens to run on,
        which would scatter the render sandbox across versions depending on how
        the user installed PartCAD. An implementation that genuinely needs
        another interpreter says so on the format itself.
        """
        return self.config.get("pythonVersion") or sandbox_versions.DEFAULT_PYTHON_VERSION


def normalize(config) -> dict:
    """A file type's configuration as a dict.

    A bare string is the historical short form for the output location, e.g.
    'stl: ./' - the same thing as 'stl: {prefix: ./}'. A section that is present
    but empty ('svg:' with nothing under it) parses as None.
    """
    if config is None:
        return {}
    if isinstance(config, str):
        return {"prefix": config}
    return copy.copy(config)


def merge(base: dict, overlay: dict) -> dict:
    """Layer one file-type configuration on top of another.

    Unlike 'render_cfg_merge', a list in the overlay replaces the one it covers
    rather than extending it: these lists are 'pythonRequirements' and viewport
    vectors, where appending the overlay to the base would produce something
    neither layer asked for.
    """
    result = copy.copy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = value
    return result


def stamp(config: dict, package_name: str) -> dict:
    """Record which package a configuration layer came from.

    Only matters for a layer that names an implementation: 'path' is relative to
    the package that declared it, and once layers are merged there is no telling
    them apart. A layer that names 'package' explicitly is pointing at someone
    else's implementation and is left alone.
    """
    if not config.get("path"):
        return config
    if config.get("package"):
        return config
    config = copy.copy(config)
    config["package"] = package_name
    return config


def config_sections(section: str) -> tuple:
    """The 'partcad.yaml' sections a file type's configuration is read from.

    Both sections are read either way, and the one that owns the file type is
    read last so that it wins. What the other one provides is a fallback:

    'export:' falls back to 'render:' for history. PartCAD had only a 'render:'
    section before 'export:' existed, and packages configured their STEP and
    STL output there; those configurations keep working.

    'render:' falls back to 'export:' because an export implementation is
    usable as a render one. An export format is a file a CAD tool can open as a
    part or a sketch, which is a stricter thing to be than an output file in
    general - so it also serves where any output file would do. The reverse
    does not hold: a drawing or a picture is not a part, which is why an
    'export:' request never falls back to a 'render:' implementation for a
    format that 'render:' owns.
    """
    return (RENDER, EXPORT) if section == EXPORT else (EXPORT, RENDER)


def builtin_project(ctx, section: str):
    """The package that declares the built-in implementations of a section."""
    return ctx.get_project(BUILTIN_PACKAGES[section])


def builtin_formats(ctx, section: str) -> dict:
    """The file types a section declares built-in implementations for."""
    project = builtin_project(ctx, section)
    if project is None:
        pc_logging.error("The built-in package is missing: %s" % BUILTIN_PACKAGES[section])
        return {}
    return project.config_obj.get(section) or {}


def section_of(ctx, format_name: str) -> Optional[str]:
    """Which section a file type belongs to, or None if nothing declares it.

    Decided by the built-in packages rather than by a hard-coded list, so a
    format is wherever its implementation is declared.
    """
    for section in SECTIONS:
        if format_name in builtin_formats(ctx, section):
            return section
    return None


def all_formats(ctx) -> list:
    """Every file type with a built-in implementation, render before export.

    The order is the order 'Project.render_async()' produces a package's outputs
    in, and 2D first is deliberate: it is what the README generator needs.
    """
    formats = []
    for section in (RENDER, EXPORT):
        formats.extend(name for name in format_names(builtin_formats(ctx, section)) if name not in formats)
    return formats
