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

Two more sections are resolved by exactly the same machinery and produce no
output file at all -- 'import:' (who *reads* a file format into a PartCAD
object) and 'simulation:' (who runs a scene). See SIMULATE and IMPORT below.

A section has one subsection per file type, whose fields are that type's
parameters. Some of them are not parameters but say how the file is produced -
'path' (the implementation script), 'package' (where that script lives),
'pythonRequirements' and 'pythonVersion' (what its sandbox needs, and which
interpreter it is) - and three more describe where the output goes rather than
what goes in it. Everything else is handed to the implementation verbatim, which
is what lets a package add a parameter (say, a 'comment' for STEP) without
PartCAD having to know about it.

The first four are not layered like the rest. 'path' and 'package' say whose
script this is, and 'pythonVersion' and 'pythonRequirements' describe the
environment that script needs - which only the package that wrote it can
answer. All four are therefore read from that package alone; a copy of them
that reaches the merged options from a calling package is inert (see
'Implementation.python_version()').

The built-in implementations are not special-cased anywhere: they are declared
in exactly this form by three packages that ship inside 'partcad' itself and
that every context can reach -- '//builtin/export', '//builtin/render' and
'//builtin/import' (see 'builtin/'). Resolving a file type means layering the configuration of the
package that asked for it on top of the built-in package's, so a package that
declares 'path' for a type replaces the implementation for itself and one that
declares only a parameter keeps the built-in implementation and re-tunes it.
"""

from __future__ import annotations

import base64
import copy
import os
from typing import Optional

from . import logging as pc_logging
from . import sandbox_versions

# The two output sections, which are also the two built-in packages' names.
EXPORT = "export"
RENDER = "render"
SECTIONS = (EXPORT, RENDER)

# The analysis section, which is an output section of the same shape and is
# deliberately not one of 'SECTIONS'. A file type declared under 'cae:' is
# produced by a script exactly as an export or a render one is - same 'path',
# same 'package', same sandbox, same parameters - and 'Implementation' below
# serves it unchanged. What differs is who asks for it and what comes back:
# 'pc cae fea' asks, and the implementation answers with findings beside the
# file it wrote (see 'partcad.cae').
#
# It stays out of 'SECTIONS' because 'SECTIONS' answers the question "which
# sections does a file type of 'pc export'/'pc render' live in": a 'fea' left in
# there would be offered to 'pc render -t' and would fall back to a 'render:'
# implementation, and neither is a thing a solver can do.
CAE = "cae"
ANALYSIS_SECTIONS = (CAE,)

# The manufacturing section, which is an output section of the same shape again:
# a file type declared under 'cam:' is produced by a script exactly as an export
# or a render one is, and 'Implementation' below serves it unchanged. What
# differs is who asks for it and what the file is - 'pc cam' asks, and what comes
# back is the program a machine runs (see 'partcad.cam').
#
# Out of 'SECTIONS' for the reason 'cae:' is: a route is not a file another CAD
# tool opens as a part, so offering it to 'pc export -t'/'pc render -t' would
# offer a file type nothing downstream of those two can read - and falling back
# to a 'render:' implementation for it would answer a request for a machine
# program with a drawing.
#
# Out of 'ANALYSIS_SECTIONS' too, and that one is not a technicality. An
# analysis answers a question *about* an object -- and reports findings, which
# 'pc test' fails on; a route says how to *make* one, and what it reports is how
# long the job is. Nothing a caller does with the one is what it does with the
# other, and the two are unalike even in their bottom layer: 'cae:' has no
# built-in package and this one does (see BUILTIN_PACKAGES).
CAM = "cam"
MANUFACTURING_SECTIONS = (CAM,)

ALL_SECTIONS = SECTIONS + ANALYSIS_SECTIONS + MANUFACTURING_SECTIONS

# Another section resolved the same way that produces no output file at all:
# 'simulation:' declares the plugins 'pc sim' runs a scene through. Out of
# 'SECTIONS' for the reason 'cae:' is, and out of 'ANALYSIS_SECTIONS' too -- a
# simulation names no file type, so there is nothing for 'pc export -t' or
# 'pc cae' to be offered. It is an 'Implementation' like any other: a script,
# the sandbox it needs, and the parameters it is handed. See
# 'partcad.simulation'.
#
# Like 'cae:', PartCAD implements *nothing* of it. There is no
# '//builtin/simulate', on purpose and for the reason there is no built-in
# solver: a simulator is somebody's program with a release cycle of its own, and
# shipping one inside the wheel would make every PartCAD release a statement
# about which version of it you get. PartCAD ships the concept -- this section,
# 'wrappers/wrapper_simulate.py', the runner in 'partcad.simulation', and the
# MJCF export a plugin is handed a scene through -- and a package supplies the
# simulator. The MuJoCo one is 'partcad/partcad-sim-mujoco'.
SIMULATE = "simulation"

# The fourth, and the mirror image of 'export:': 'import:' declares who turns a
# file of some third-party format *into* a PartCAD object. It is not in SECTIONS
# for the same reason 'simulation:' is not -- everything reading that tuple is
# asking "which output file types are there", and an importer produces no file.
#
# It exists because reading a format and writing it are one piece of knowledge.
# A package that teaches PartCAD to write MJCF knows MJCF; making it declare the
# reader beside the writer is what lets the pair travel together, be versioned
# together, and be replaced together. Before this section there was no way to
# say it: every reader was a factory class registered in 'globals.py', so adding
# one meant editing PartCAD.
#
# Unlike 'simulation:', this one does have a built-in package. A reader is not a
# simulator: it is XML and geometry, it depends on nothing with a release cycle
# of its own, and 'urdf' in particular describes a robot rather than any one
# engine's world, so it ships here. The two that *are* an engine's own scene
# format live with that engine's plugin -- 'mjcf' in 'partcad/partcad-sim-mujoco'
# and 'world' in 'partcad/partcad-sim-gazebo'.
#
# 'import:' was the historical spelling of 'dependencies:', which is why a
# package whose 'import:' describes transports rather than readers is told to
# rename it rather than quietly migrated ('ProjectConfiguration' used to copy
# the value into 'dependencies'; see 'project_config.py'). The name is this
# section's now, and it is the right one: what an entry declares is how a file
# of that format is read *in*, which is the mirror of 'export:' and reads that
# way beside it.
#
# What an entry declares, beyond the implementation keys every section shares:
#
#   'kinds'      which object kinds the reader can produce ('assembly',
#                'scene', or both). A format used for one thing only says so,
#                and declaring it under the wrong section is then an error a
#                package gets told about rather than a tree that comes out
#                empty.
#   'extension'  the source file's extension, used to find the file when the
#                declaration names no 'path'.
#   'noun'       what one of these is called in a log line ('model', 'world').
#   'dropped'    what each counter of the reader's 'dropped' summary is called
#                when it is reported -- the reader counts, the declaration
#                words it.
#
# Everything else is handed to the reader as a parameter, which is what lets a
# format carry its own options ('ignoreCollision', 'modelPaths') without PartCAD
# knowing they exist.
IMPORT = "import"

# The fifth, and the only one whose implementation is not a script: 'open:'
# declares the third-party applications 'pc open' can launch. An entry is data
# and nothing else -- where the application is on each operating system, what to
# run it as, which container to fall back to, and what it can read -- because
# the one thing that would be code is the same for every tool there is, and
# lives once in 'partcad_client.external'.
#
# It is resolved the same way as the rest, and for the same reason: an
# application belongs to whoever knows it. Gazebo and MuJoCo are declared by
# their engine's plugin package, beside the exporter, the reader and the
# simulator for that engine's own scene format; a package that wraps some other
# tool adds it without PartCAD having heard of it.
#
# 'pc open' is a client-side command that deliberately needs no package graph
# (see 'partcad_cli.click.commands.open'), so the built-in half of this table is
# read straight off disk out of the wheel and needs no context at all. Only a
# tool a *package* declares needs one, and that is the daemon's to answer.
OPEN = "open"

# Where the built-in packages live, both as package paths and on disk. They are
# inside the 'partcad' Python package so that they ship with it and are always
# present, wheel or frozen bundle alike.
BUILTIN_ROOT_PACKAGE = "//builtin"
BUILTIN_PACKAGES = {
    EXPORT: "//builtin/export",
    RENDER: "//builtin/render",
    IMPORT: "//builtin/import",
    OPEN: "//builtin/open",
    # Unlike 'cae:', this section has a built-in implementation, and the reason
    # is the test the other three pass: a route is arithmetic on the object's
    # own outline, with no third-party program and no release cycle of anybody
    # else's behind it. So PartCAD ships one the way it ships DXF, and the
    # default 'camImplementation' names it rather than naming a package a user
    # has to go and find.
    CAM: "//builtin/cam",
}
# The one built-in package that declares objects rather than implementations:
# the scene a 'simulate:' that names no scene of its own is run in, whose
# 'subject' parameter is whatever is being simulated. Unlike the simulator that
# runs it, an empty world costs nothing to ship and depends on nothing.
BUILTIN_SCENE_PACKAGE = "//builtin/scene"
BUILTIN_ROOT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "builtin")
BUILTIN_PATHS = {
    BUILTIN_ROOT_PACKAGE: BUILTIN_ROOT_PATH,
    BUILTIN_PACKAGES[EXPORT]: os.path.join(BUILTIN_ROOT_PATH, EXPORT),
    BUILTIN_PACKAGES[RENDER]: os.path.join(BUILTIN_ROOT_PATH, RENDER),
    BUILTIN_PACKAGES[IMPORT]: os.path.join(BUILTIN_ROOT_PATH, IMPORT),
    BUILTIN_PACKAGES[OPEN]: os.path.join(BUILTIN_ROOT_PATH, OPEN),
    BUILTIN_PACKAGES[CAM]: os.path.join(BUILTIN_ROOT_PATH, CAM),
    BUILTIN_SCENE_PACKAGE: os.path.join(BUILTIN_ROOT_PATH, "scene"),
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
# 'path' that was never meant to exist - unless the package names one, see
# 'is_document_format()'.
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


def name_to_path(name: str, suffix: str = "") -> str:
    """The file an object's name names, relative to the directory it goes in.

    An object's name may carry '/'. The objects another file materializes are
    named that way -- a STEP assembly's components are the parts
    '<assembly>/<component>', a URDF's links '<assembly>/<link>', a Gazebo
    world's '<scene>/<model>/<link>' -- and a package is free to declare one
    like that itself, which is what 'examples/feature_import' does.

    Everything up to the last '/' is a directory the file goes in, and only what
    follows it names the file: no filesystem takes a '/' in a file name, so the
    alternative is not a flat file called 'a/b.step' but no file at all. The
    directories are created when the file is written -- see
    'Context.ensure_dirs_for_file()'.

    The separator in a name is always '/', on every platform: it is part of a
    name written in 'partcad.yaml' or in somebody else's model file, not a path
    anybody typed. Splitting on it here and joining with 'os.path.join()' is
    what makes Windows put the file in the same directory Linux and macOS put it
    in, rather than in a directory called 'a/b' that only one of the three can
    read back.
    """
    *directories, stem = name.split("/")
    return os.path.join(*directories, stem + suffix)


def is_document_format(format_name: str, section_obj) -> bool:
    """Whether PartCAD assembles this file itself instead of running a script.

    True for the file types of NON_WRAPPER_FORMATS - and only for as long as
    nobody implements them. A configuration that names a 'path' for one is a
    package saying that its 'pdf' is a file of its own (a drawing, a datasheet)
    rather than the assembly instruction book, and PartCAD produces it the way
    it produces every other file type a package implements.

    'readme' is the one that cannot be taken over in practice, not because it is
    special-cased here but because there is nothing to name: PartCAD does not
    ship an implementation of it for a package to replace (see
    'builtin/render/partcad.yaml').
    """
    if format_name not in NON_WRAPPER_FORMATS:
        return False
    if not isinstance(section_obj, dict):
        return True
    return not normalize(section_obj.get(format_name)).get("path")


# The fields of a file type's configuration that are not parameters.
#
# The first group picks the implementation, the second places the output file.
# What is left over is what the implementation is handed, so adding a field here
# hides it from every implementation - including the ones packages write.
IMPLEMENTATION_KEYS = frozenset(
    {"path", "package", "pythonRequirements", "pythonVersion", "dockerImage", "decode", "container"}
)
OUTPUT_KEYS = frozenset({"extension", "prefix", "exclude", "output_dir"})
RESERVED_KEYS = IMPLEMENTATION_KEYS | OUTPUT_KEYS | frozenset({"desc"})

# The same, for the 'simulation:' section. Both say how the scene reaches the
# plugin rather than what the plugin is handed once it has it: 'format' is the
# file type it is exported to, and 'formatOptions' the export parameters that
# go with it (a physics simulation wants every body free to move, which is the
# opposite of what a scene means on its own). They configure the run, so they
# are held out of the plugin's request for the same reason 'path' is.
SIMULATION_KEYS = frozenset({"format", "formatOptions"})

# The same, for the 'import:' section. None of these is a parameter of the
# reader: 'kinds' says which object kinds may be declared with this type,
# 'noun' and 'dropped' are how the core words what the reader reports, and
# 'extension' (already reserved above) is how the source file is found. The
# reader is handed everything else.
IMPORT_KEYS = frozenset({"kinds", "noun", "dropped"})

# The request key the implementation script's path travels under. It is passed
# in the request rather than on the command line because the two positional
# arguments of a wrapper are already spent on the output path and the working
# directory (see wrappers/wrapper_export.py, which spells this out again -- a
# wrapper runs in a sandbox and cannot import 'partcad').
SCRIPT_KEY = "__script__"

# The request key a file type sets to 'true' to be handed what the shapes it is
# given report about themselves. It is an ordinary export parameter rather than
# a reserved one - a format with no way to state a material or a mass never
# declares it - and it is named here so that the core can tell whether the
# properties will be read at all. Its twin is 'wrapper_export.PROPERTIES_KEY',
# spelled out there for the same reason SCRIPT_KEY is: a wrapper runs in a
# sandbox and cannot import this.
PROPERTIES_KEY = "properties"

# The request key that says whether the sandbox rebuilds the shape and assembly
# envelopes into live OCCT geometry before the implementation sees them. The
# wrapper has to know before it deserializes anything, which is why it travels
# in the request rather than being read off the configuration. Declared on a file type as 'decode: false',
# which is what an implementation asks for when it needs what an envelope says
# *about* a node: decoding mirrors the assembly tree in nested compounds, but
# geometry is all it keeps - every node's 'name' and 'label' is dropped, and its
# placement is baked into the shape instead of staying readable as data.
DECODE_KEY = "__decode__"

# The request key that says whether this file has to come out the same every
# time it is produced, from the same object.
#
# It is part of the protocol rather than one file type's parameter, and it is in
# *every* request - export, render, analysis, route - whether or not anybody
# declared it. An implementation that has nothing to decide reads it and ignores
# it; one that does reads it without having to ask whether the key is there,
# which is what makes 'reproducible' mean the same thing in a package PartCAD
# has never heard of as it does in '//builtin/render'.
#
# Why it exists at all: some of what PartCAD writes is only reproducible if it
# is asked for, and asking costs something.
#
#   - The SVG projection has two hidden-line algorithms behind it. The exact one
#     works from the surfaces; the polygonal one works from a triangulation,
#     which is floating point all the way down, so the same shape meshed to the
#     same deflection comes out with a slightly different silhouette on a
#     different architecture. The polygonal one is also the
#     only one that does not walk off the end of an OCCT allocation, and it is
#     minutes faster on a large assembly - so it is what a render gets unless
#     the caller says the bytes matter more than that (see
#     'builtin/render/render_svg.py', which spells the trade out in full).
#   - A DXF is stamped with the wall clock and a fresh pair of GUIDs on every
#     save, and a drawing that differs from the last one only in when it was
#     written is a drawing nothing can be compared against.
#
# 'False' is the default, and deliberately: a render is normally produced to be
# looked at, and the fastest correct picture is the right one to hand back. A
# drawing that is *kept* - checked into a repository next to the model, so that
# 'git diff' answers whether it changed - is the case that has to say so, and
# every image under 'examples/' does.
#
# It is a floor rather than a promise, and worth saying so where the word is
# defined: what it removes is everything PartCAD chooses - which algorithm, how
# a number is written, the clock, the GUIDs, the iteration order of a set. What
# is left is the CAD kernel's own arithmetic, and two machines that disagree
# about a transcendental function in the last bit can still find one
# intersection more than each other along a curved silhouette. So two renders on
# one machine are the same file, and two machines agree on everything but the
# hardest subjects.
#
# Not to be confused with the other 'reproducible' in this package, which is
# about whether an *object* can be made twice: 'file_factory.unreproducible_reason()'
# asks whether what a part is built from is pinned, and 'pc test' fails a part
# that is not. That one is a property of a declaration; this one is a property of
# a file somebody wrote.
#
# Declared on a file type as an ordinary field, so a package writes
#
#     render:
#       svg:
#         reproducible: true
#
# and so does a shape overriding its package. It is not one of RESERVED_KEYS
# precisely because implementations are meant to see it.
REPRODUCIBLE_KEY = "reproducible"


def as_flag(value, name: str = REPRODUCIBLE_KEY) -> bool:
    """One of the protocol's boolean fields, however it was written.

    YAML gives back a real bool, and that is what a 'partcad.yaml' produces. The
    other clients are not YAML: the CLI and the JSON-RPC callers hand values
    through as they parsed them, and a 'reproducible' that arrived as the string
    "false" would otherwise be true - which is the silent kind of wrong, since
    what it turns off is a guarantee nobody checks until the bytes move.

    Anything that is not a boolean, a boolean's name, or nothing at all is a
    caller saying something this cannot act on, so it says so rather than
    guessing.
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "yes", "on", "1"):
            return True
        if text in ("false", "no", "off", "0", ""):
            return False
    raise ValueError("'%s' must be true or false, got: %r" % (name, value))


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
        # Whether the sandbox decodes the envelopes into live geometry for this
        # implementation. Off for one that needs the assembly tree's structure
        # rather than the compound it decodes to.
        self.decode = config.get("decode", True) is not False

    @property
    def reproducible(self) -> bool:
        """Whether this file type was asked for byte-for-byte reproducibly.

        Read from the layered configuration rather than from the implementing
        package alone, unlike 'python_version()' and the rest: this is not a
        statement about what the script needs to run but about what the caller
        wants out of it, and the caller is exactly who gets to say. A package
        that keeps its drawings in the repository sets it on the file type; a
        package that only looks at them leaves it alone.

        See REPRODUCIBLE_KEY for what it costs and why 'False' is the default.
        """
        return as_flag(self.config.get(REPRODUCIBLE_KEY))

    @property
    def reserved(self) -> frozenset:
        """The fields of this configuration that are not parameters."""
        if self.section == SIMULATE:
            return RESERVED_KEYS | SIMULATION_KEYS
        if self.section == IMPORT:
            return RESERVED_KEYS | IMPORT_KEYS
        return RESERVED_KEYS

    @property
    def parameters(self) -> dict:
        """The fields handed to the implementation as its 'request'."""
        return {key: value for key, value in self.config.items() if key not in self.reserved}

    def extension(self, default: str) -> str:
        return self.config.get("extension") or default

    def _declared(self, key):
        """What the implementing package says about this file type, if anything.

        Read from that package's own configuration rather than from the layered
        options: the layers below this one are the built-in defaults and the
        layers above are callers, and neither is describing the environment this
        script needs. The file type is looked up in both sections, owning
        section last, which is the order the options themselves are layered in.
        """
        if self.project is None:
            return None
        value = None
        for section_name in config_sections(self.section):
            section_obj = self.project.config_obj.get(section_name)
            if isinstance(section_obj, dict):
                value = normalize(section_obj.get(self.format_name)).get(key) or value
        return value

    def python_version(self) -> str:
        """Which sandbox interpreter runs this implementation.

        The package that ships the script decides. It is that package's code
        that has to run and its requirements that have to resolve around it: a
        drawing implementation whose dependencies want build123d 0.11 only on
        3.13 says '3.13' once, beside the requirement, and every package that
        draws with it gets that interpreter without having to know why.

        Nobody else has an opinion worth reading. A package that asks for a
        drawing is a caller - it may be a package of STEP files with no Python
        in it at all - so its own interpreter says nothing about what somebody
        else's script needs, and is not consulted. A 'pythonVersion' that
        reaches the merged options from there is not overridden here; it is
        never read.

        Where the implementing package says nothing, the answer is a fixed
        default rather than the interpreter PartCAD itself runs on: the latter
        would scatter the render sandbox across versions depending on how the
        user installed PartCAD.
        """
        return (
            self._declared("pythonVersion")
            or getattr(self.project, "python_version_declared", None)
            or sandbox_versions.DEFAULT_PYTHON_VERSION
        )

    @property
    def container(self) -> Optional[dict]:
        """The container this implementation runs in, if it does not run in a sandbox.

        A Python sandbox can only bring what pip can install, and some
        implementations need more than that: a native solver, a mesher with no
        wheel for this platform, a whole third-party application. Such an
        implementation declares an image instead, and PartCAD runs it there --

            cae:
              fea:
                path: fea_calculix.py
                container:
                  image: ghcr.io/example/solver:1a2b3c4d5e6f

        which is how a plugin becomes responsible for its own dependencies
        rather than asking every user to install them. `port` defaults to the
        5000 that `tools/containers/_common/pc-container-json-rpc.py` listens
        on; `name` defaults to one derived from the image, so that two packages
        naming the same image share a container rather than starting two.

        The implementing package's declaration and nobody else's, for the reason
        `python_version()` gives at length: this describes what *that* package's
        script needs to run, and a caller asking for an analysis has no opinion
        about it worth reading.
        """
        declared = self._declared("container")
        if not declared:
            return None
        if isinstance(declared, str):
            # The short form: the image and nothing else.
            declared = {"image": declared}
        if not isinstance(declared, dict) or not declared.get("image"):
            raise ValueError(
                "The '%s' implementation declares a 'container:' that names no 'image:': %r"
                % (self.format_name, declared)
            )
        return dict(declared)

    @property
    def docker_image(self) -> Optional[str]:
        """The image this implementation's sandbox is built from, if it named one.

        Read from the file type first and from the implementing package second,
        exactly as `python_version()` is and for the same reason: what a script
        needs to run is known to whoever wrote it, and a caller asking for a
        part has no opinion about it worth reading. The package-level fallback
        is what lets a plugin say it once rather than on every file type it
        implements.

        Unlike `container`, this does not say "instead of a sandbox". It says
        which image the `docker` sandbox is built from, and a machine using
        another sandbox ignores it and installs `python_requirements` -- which
        is why a package that declares one still has to declare those.
        """
        declared = self._declared("dockerImage")
        if declared:
            return str(declared)
        if self.project is not None:
            fallback = getattr(self.project, "docker_image_declared", None)
            if fallback:
                return str(fallback)
        return None

    @property
    def python_requirements(self) -> list:
        """What the sandbox needs installed before this implementation runs.

        The implementing package's again, and for the same reason: these are the
        imports of its script, resolved against the interpreter it asked for.
        The package-level requirements of that package are installed too, by
        'RuntimePython.prepare_for_package()'; this is what the file type adds
        on top of them.
        """
        return list(self._declared("pythonRequirements") or [])


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

    'cae:' and 'cam:' are each read alone. Neither has a fallback and neither is
    anybody's: an analysis is not a file another CAD tool opens, a route is a
    program a machine runs rather than a shape at all, and no export or render
    implementation could stand in for either.

    For the other two, both sections are read either way, and the one that owns
    the file type is read last so that it wins. What the other one provides is a
    fallback:

    Neither a 'simulation:' nor an 'import:' has such a fallback, and neither
    ever will: an export implementation writes a file, an importer reads one and
    a simulation plugin runs one, so none of the three is usable where another
    is asked for. An 'import:' in particular is the one section whose entries
    share their names with 'export:' entries on purpose -- 'mjcf' is both the
    format written and the format read -- and reading either as a fallback for
    the other would hand a writer a file to parse.

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
    if section in (CAE, CAM, SIMULATE, IMPORT, OPEN):
        return (section,)
    return (RENDER, EXPORT) if section == EXPORT else (EXPORT, RENDER)


def split_format(project_name: str, format_name):
    """A file type's name, and the package that implements it when one is named.

    An export or a render format is ordinarily a bare name -- 'step', 'png' --
    and every package with an opinion about it is layered on top of the built-in
    one. It may also be written as a full resource path, 'sim-mujoco:mjcf',
    which names the package the implementation lives in.

    That spelling is not new here: it is what the other three sections resolved
    through this module already take -- 'import:' in 'import_declaration()',
    'simulation:' in 'partcad.simulation.resolve_plugin()', 'cae:' in
    'pc cae --implementation' -- and it is here for the reason it is there. A
    format PartCAD ships no implementation of has no other way to be reached:
    nothing in '//builtin/export' writes MJCF or SDFormat, because an engine's
    own scene format travels with that engine's plugin package, so
    'pc export -t mjcf' has nothing to resolve and 'pc export -t sim-mujoco:mjcf'
    has.

    Returns the bare name and the package path, or the name and None. Turning
    that path into a package is the caller's, because the caller is the one with
    a context to turn it in.
    """
    if not isinstance(format_name, str) or ":" not in format_name:
        return format_name, None
    # Late, for the reason 'import_declaration()' imports it late: this module
    # is imported from 'factory' and must not drag the package machinery in.
    from .utils import resolve_resource_path

    package, name = resolve_resource_path(project_name, format_name)
    return name, package


def builtin_project(ctx, section: str):
    """The package that declares the built-in implementations of a section.

    None for 'cae:', which has no built-in implementations and is not meant to
    get one: PartCAD ships no solver, and the default implementation of each
    analysis is a package path in the user configuration (see
    'UserConfig.cae_fea_implementation'). Everything downstream therefore has to
    cope with a section whose bottom layer is missing - which is already the case
    for a file type a package declares that '//builtin' has never heard of.

    'cam:' is not that case and has a built-in package like the first three: see
    BUILTIN_PACKAGES for why a route ships where a solver does not.
    """
    package = BUILTIN_PACKAGES.get(section)
    return ctx.get_project(package) if package else None


def builtin_formats(ctx, section: str) -> dict:
    """The file types a section declares built-in implementations for."""
    if section not in BUILTIN_PACKAGES:
        return {}
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


def import_declaration(ctx, project, type_name: str):
    """The 'import:' implementation for an object type, or None if there is none.

    'type_name' is what a declaration's 'type:' said, and comes in two spellings
    that mean the same thing in the end:

      'mjcf'                a bare name. Layered the way a file type is - the
                            built-in package underneath, the package that
                            declares the object on top - so a package can
                            re-tune a reader's parameters, or replace the reader
                            outright, for its own objects.
      'sim-mujoco:mjcf'     a full path, resolved against 'project' exactly as
                            a 'simulation:' plugin is. This is how a
                            package names a reader that is nobody's built-in,
                            and it is the spelling a plugin's own README gives.

    Returns None rather than raising for an unknown name: the caller is
    'factory.instantiate()', where "nothing declares this type" is the ordinary
    'UnknownTypeException' path and has a better message than anything here
    could produce.
    """
    if not isinstance(type_name, str) or not type_name or ctx is None or project is None:
        # Nothing to resolve against. Reached by a caller that is asking whether
        # a type exists at all rather than building anything with it, and the
        # answer there is the same as for a name nobody declared.
        return None

    layers = []
    if ":" in type_name:
        # Late, to keep this module importable from 'factory' without dragging
        # the package machinery in behind it.
        from .utils import resolve_resource_path

        plugin_package, format_name = resolve_resource_path(project.name, type_name)
        # From the package that declared the object, not from the root: this
        # runs while that package is still being loaded (its objects are created
        # as part of loading it), and the root is not registered until that
        # finishes. See 'Context.get_project_from()'.
        plugin_project = ctx.get_project_from(project, plugin_package)
        if plugin_project is None:
            pc_logging.error(
                "The package implementing the '%s' object type is not found: %s" % (format_name, plugin_package)
            )
            return None
        layers.append((plugin_project.name, plugin_project.config_obj))
    else:
        format_name = type_name
        builtin = builtin_project(ctx, IMPORT)
        if builtin is not None:
            layers.append((builtin.name, builtin.config_obj))
        # The declaring package itself, taken as the object it is rather than
        # looked up by name: a package's 'name:' is what it calls itself, and
        # the context registers the root one under '//' whatever that says, so
        # a lookup here would miss exactly the package that is asking.
        layers.append((project.name, project.config_obj))

    opts = {}
    found = False
    for layer_package, config_obj in layers:
        section_obj = config_obj.get(IMPORT)
        if not isinstance(section_obj, dict) or format_name not in section_obj:
            continue
        found = True
        opts = merge(opts, stamp(normalize(section_obj[format_name]), layer_package))
    if not found:
        return None
    return Implementation(IMPORT, format_name, opts)


def import_kinds(impl) -> tuple:
    """The object kinds an importer declares it can produce.

    A declaration that says nothing can produce either, which is what an
    importer with no opinion means: the format describes a tree of placed
    shapes, and whether that tree is a product or an arrangement of products is
    what the section it is declared in says (see 'partcad.scene').
    """
    kinds = impl.config.get("kinds")
    if isinstance(kinds, str):
        kinds = [kinds]
    if not isinstance(kinds, (list, tuple)) or not kinds:
        return ("assembly", "scene")
    return tuple(str(kind) for kind in kinds)


def all_formats(ctx) -> list:
    """Every file type with a built-in implementation, render before export.

    The order is the order 'Project.render_async()' produces a package's outputs
    in, and 2D first is deliberate: it is what the README generator needs.
    """
    formats = []
    for section in (RENDER, EXPORT):
        formats.extend(name for name in format_names(builtin_formats(ctx, section)) if name not in formats)
    return formats


async def materialize_script(ctx, impl) -> str:
    """The on-disk path of the script that implements a file type or a plugin.

    For a local package - which the built-in ones are - that is a file in the
    package. For a plugin-backed package it is fetched from the plugin (like a
    file-backed object) and written into the package's cache directory, the same
    way a partType's wrapper script is.

    Here rather than on 'Shape' because the answer is about the implementation
    and not about what it is being run for: an export writes a shape out, a
    simulation runs a scene, and both are a script named by a package that has
    to be found the same way and confined to that package the same way.
    """
    builtin_package = BUILTIN_PACKAGES.get(impl.section)
    if not impl.script:
        if builtin_package is None:
            # A section with no built-in package to fall back to - 'cae:', and
            # 'simulation:' once PartCAD stopped shipping one - so an unresolved
            # implementation means the configured one was not found rather than
            # that somebody forgot a 'path'. Name both knobs and say which is
            # which: the user configuration holds the default, and
            # '--implementation' overrides one run.
            if impl.section == CAE:
                raise Exception(
                    "No implementation of '%s' is declared. Name one in a 'cae:' section, "
                    "override it for one run with 'pc cae %s --implementation <package>:<type>', "
                    "or set the default in the 'cae%sImplementation' user configuration option"
                    % (impl.format_name, impl.format_name, impl.format_name.capitalize())
                )
            # Every other section with no built-in. A simulation plugin has no
            # '--implementation' flag and no user-configuration default to name,
            # so saying it has both sends the reader looking for switches that
            # do not exist.
            raise Exception(
                "No implementation of '%s' is declared: name one with a 'path' in a '%s:' section, "
                "or import a package that provides it" % (impl.format_name, impl.section)
            )
        raise Exception(
            "No implementation of '%s' is declared: neither %s nor this package provides a 'path'"
            % (impl.format_name, builtin_package)
        )

    # 'stamp()' fills 'package' in for every layer that names a 'path', so the
    # fallback is only reached by a file type whose implementation is the
    # built-in one. A section with no built-in - 'cae:' and 'simulation:' -
    # cannot reach here without a package.
    package_name = impl.config.get("package") or builtin_package
    if package_name is None:
        raise Exception("The implementation of '%s' does not say which package it lives in" % impl.format_name)
    project = ctx.get_project(package_name)
    if project is None:
        raise Exception("The package implementing '%s' is not found: %s" % (impl.format_name, package_name))
    impl.project = project

    # The script is named by the package's own configuration and is about to be
    # executed, so it has to come from inside that package: a 'path' of
    # '../../..' would otherwise both read and, for a plugin-backed package,
    # write outside it.
    config_dir = os.path.abspath(project.config_dir)
    script_abs = os.path.abspath(os.path.join(config_dir, impl.script))
    if os.path.commonpath([config_dir, script_abs]) != config_dir:
        raise Exception("The implementation of '%s' is outside its package: %s" % (impl.format_name, impl.script))
    if os.path.exists(script_abs):
        return script_abs

    get_data_async = getattr(project, "get_data_async", None)
    if get_data_async is None:
        raise Exception("The implementation of '%s' is not found: %s" % (impl.format_name, script_abs))

    data = await get_data_async("files/" + impl.script)
    if data is None:
        raise Exception(
            "The repository did not provide the implementation of '%s': %s" % (impl.format_name, impl.script)
        )
    content = base64.b64decode(data) if isinstance(data, str) else bytes(data)
    dirs = os.path.dirname(script_abs)
    if dirs and not os.path.exists(dirs):
        os.makedirs(dirs, exist_ok=True)
    with open(script_abs, "wb") as f:
        f.write(content)
    return script_abs
