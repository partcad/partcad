#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Opening a file in a third-party application, on the machine the client runs on.

This is a client's job by construction, and it is why the code sits here rather
than behind an RPC method. A daemon can be remote: "open this in FreeCAD" sent to
one would start a window on somebody else's desk, on a machine that may have no
display at all -- and the file named on the command line is the client's own,
found by a path that means nothing on the other side of the wire. So `pc open`
never speaks to a daemon, the way `pc lint --file` and `pc upgrade` do not, and
the VS Code extension reaches this code by running `pc open` rather than by
reimplementing it in TypeScript.

Two ways to run a tool, tried in this order:

* **Natively**, when the machine has the application installed. Nothing is
  containerised, nothing is downloaded, and the application sees the file at the
  path the user typed.
* **In a container**, when it does not, Docker is available, and the caller
  passed ``use_docker``. One long-lived container per tool, named
  ``partcad-<tool>`` -- a *container* name, not an image name, so a user can
  create, inspect, customise or `docker rm` theirs, and the next `pc open` finds
  and reuses whatever is there.

The container mounts the workspace root **at the same absolute path** it has on
the host, along with the directory holding the workspace's daemon socket. Same
path on both sides is what keeps the arrangement honest: the file argument, an
error message, and anything the application writes back all name one path that
means the same thing inside the container, on the host, and to the daemon.

Some applications read triangles and nothing else. Blender is the one PartCAD
knows about: its command line takes a `.blend` to open, and any other geometry
has to be *imported*, which only a mesh format can be. So a file that is not
already a mesh is converted to STL first, and the application is handed that
instead. Which types are meshes is `partcad_client.object_types`; making one out
of a solid is CAD work, so it is not done here -- the caller passes a
``transcode`` callback, and `pc open` implements it as the same `adhoc.convert`
the daemon serves `pc adhoc convert` with. The converted copy is written under
the workspace's own state directory, which is already mounted into the container
at the path it has here, so one name means the same thing on both sides.

Some read a *scene* and only their own description of one. MuJoCo is that one:
it reads MJCF, and a Gazebo world handed to it is not a slow way of opening a
scene, it is a file it cannot read. So the same thing happens for the same
reason -- the scene is written out as MJCF first, through the very same
``transcode`` callback with ``kind="scene"``. The two conversions differ in what
they ask of the file (does it hold triangles, versus which description language
is it) and in what they convert (a part, versus a scene); everything after that
is shared, which is why one callback serves both.

A containerised GUI needs an X server on the host, which is the one place where
this cannot paper over the difference between platforms. On Linux the display is
usually a socket that can simply be shared, cookie and all, and nothing has to be
set up; on macOS and Windows -- and on Linux over a forwarded display -- it is a
TCP connection to an X server the user has to install and allow. There is no way
to do that for them, so when it is missing they get told which one to install and
what to run, rather than a container that starts and silently never shows a window.
"""

import contextlib
import glob
import hashlib
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from partcad_utils.workspace import determine_root_path, socket_path

from . import __version__, object_types

__all__ = [
    "ExternalToolError",
    "OpenResult",
    "Tool",
    "TOOLS",
    "open_file",
    "tool_names",
    "transcode_path",
]

# How long to wait for the `docker` commands that only ask a question. Generous
# enough for a busy daemon, short enough that a wedged one is reported rather
# than hanging an editor's context menu.
DOCKER_TIMEOUT = 60.0

# The container's name is derived from the tool's, so `pc open --with freecad`
# uses `partcad-freecad`. Deliberately a fixed name rather than a fresh
# container each time: the user can prepare theirs (install add-ons, keep
# preferences) and PartCAD will keep using it.
CONTAINER_PREFIX = "partcad-"


class ExternalToolError(Exception):
    """No way to open the file, with a message saying what would fix that."""


@dataclass(frozen=True)
class Tool:
    """A third-party application PartCAD knows how to launch.

    Everything platform-specific about finding one is data, so that adding the
    second tool is a table entry rather than another copy of the logic below.
    """

    name: str
    display_name: str
    # The image a container is created from when the machine has no local copy.
    image: str
    # Executable names to look for, both on this machine's PATH and inside the
    # container. Ordered: the first one found wins.
    binaries: Tuple[str, ...] = ()
    # macOS application bundles, looked for under /Applications and ~/Applications.
    macos_apps: Tuple[str, ...] = ()
    # The executable inside the macOS bundle, relative to it, for an application
    # that is handed arguments rather than a document. `open -a` is how macOS
    # launches one and is used everywhere else, but it hands a *running* copy
    # nothing at all -- so an application whose file arrives as an argument (see
    # `file_args`) would silently open nothing the second time.
    macos_executable: Optional[str] = None
    # Windows install locations, as globs relative to the directories in
    # `windows_roots`, so a versioned directory name still matches.
    windows_globs: Tuple[str, ...] = ()
    flatpak_id: Optional[str] = None
    # Extra arguments the application needs before the file name, if any.
    args: Tuple[str, ...] = field(default_factory=tuple)
    # The same, for one executable in particular. An application with more than
    # one front end needs it: Gazebo's world file is `gz sim <world>` through
    # the current command and a bare `gazebo <world>` through the old one, and
    # which of the two is on the machine decides.
    binary_args: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    # Extensions this application actually opens, when the file it is handed is
    # not one of them and one of these sits beside it. A PartCAD `kicad` part
    # *is* the STEP file KiCad's CLI writes out of the board; the board itself --
    # what somebody opening KiCad means -- is the project file next to it, and
    # the tree has no other name for it.
    companions: Tuple[str, ...] = ()
    # How the file reaches the application, when being the last argument is not
    # it. Blender's command line takes a `.blend` to open and imports anything
    # else through a line of Python, which is a fact about Blender and lives
    # with the rest of them.
    file_args: Optional[Callable[[str], Tuple[str, ...]]] = None
    # The format a file that is not already a mesh is converted to before this
    # application sees it, for an application that reads meshes and nothing
    # else. None -- every other tool in the table -- means the file is handed
    # over as it is, whatever it holds.
    mesh_via: Optional[str] = None
    # Extensions this application opens whatever they contain, because they are
    # its own: a `.blend` is not a mesh and must not be converted into one.
    own_formats: Tuple[str, ...] = ()
    # The mesh formats this application imports, for one that reads meshes only.
    # A second question from `mesh_via`, and a different one: PartCAD's tables
    # say whether a file holds triangles, and this says whether *this*
    # application can read the file that holds them. 3MF is the case that makes
    # it two questions -- it is a mesh, and Blender ships no importer for it, so
    # it takes the STL route like a solid does.
    imports: Tuple[str, ...] = ()
    # The PartCAD *scene* type this application reads, for one that reads a
    # description of an arrangement rather than geometry. MuJoCo is the one
    # PartCAD knows about: it reads MJCF and no other model format, so a Gazebo
    # world it is pointed at is written out as MJCF first.
    #
    # Deliberately a separate field from `mesh_via` rather than a generalization
    # of it, because the two ask different questions of the file. `mesh_via`
    # asks whether it holds triangles, which is a property of what is in it;
    # this asks which description language it is written in, which is a property
    # of the file itself. One tool sets one of the two.
    scene_type: Optional[str] = None

    @property
    def container_name(self) -> str:
        return CONTAINER_PREFIX + self.name

    def launch_args(self, executable: str) -> Tuple[str, ...]:
        """The arguments that go before the file name for this executable.

        Keyed on the name of the program itself, so it answers for a binary
        found on the PATH, in a container, or under a Windows install alike. A
        launcher that is not the program -- macOS's `open -a`, `flatpak run` --
        has no entry and gets `args`, which is right: each of those bundles one
        front end and knows which of its own arguments to supply.
        """
        stem = os.path.splitext(os.path.basename(executable))[0]
        return self.binary_args.get(stem, self.args)

    def file_arguments(self, path: str) -> Tuple[str, ...]:
        """The arguments that name ``path`` to this application.

        The path itself for every application that takes a file name, which is
        all of them but Blender; see `file_args`.
        """
        if self.file_args is None:
            return (path,)
        return tuple(self.file_args(path))

    def needs_mesh(self, path: str, object_type: Optional[str] = None) -> bool:
        """Whether ``path`` has to be converted before this application sees it.

        False for every application that takes what it is given, and false for
        one that reads meshes when the file already is a mesh it can read -- or
        is the application's own project format, which is not a mesh and is not
        to be converted into one. A mesh in a format it has no importer for is
        converted like a solid: the point is a file the application opens.
        """
        if self.mesh_via is None:
            return False
        extension = os.path.splitext(path)[1].lower()
        if extension in self.own_formats:
            return False
        if object_types.is_mesh(path, object_type) is not True:
            return True
        # A mesh this application has no importer for is no better off than a
        # solid: it is converted too, to the one format that always works.
        return extension not in self.imports

    def needs_scene(self, path: str, object_type: Optional[str] = None) -> bool:
        """Whether ``path`` has to be converted into this application's own format.

        False for every application that takes what it is given, and false for
        one that reads a scene description when the file already is one it
        reads. A file that is no scene at all comes back True and is refused
        with the reason by `_transcode_scene`, which is better than handing a
        simulator a STEP file and letting it say something of its own.
        """
        if self.scene_type is None:
            return False
        return object_types.readable_scene_type(path, object_type) != self.scene_type

    def file_for(self, path: str) -> str:
        """The file this application is really given, from the one it was handed.

        Unchanged unless the tool declares `companions` and the path is not one
        of them: then the first companion that exists beside it wins. Nothing is
        created and nothing is converted -- `pc open` renders nothing -- so a
        file with no companion is handed over as it is and the application says
        what it thinks of it.
        """
        if not self.companions:
            return path
        stem, extension = os.path.splitext(path)
        if extension.lower() in self.companions:
            return path
        for companion in self.companions:
            candidate = stem + companion
            if os.path.isfile(candidate):
                return candidate
        return path


FREECAD = Tool(
    name="freecad",
    display_name="FreeCAD",
    # `:latest`, not a pinned tag: a user asking for a container wants the
    # current FreeCAD, and a pin here would quietly age into a version nobody
    # chose. The image is a community one because the FreeCAD project publishes
    # none -- the `freecad/freecad` repository on Docker Hub has never had an
    # image pushed to it -- and it is this one because it carries a GUI FreeCAD
    # on `PATH` and is still being rebuilt. `--docker-image` overrides it, which
    # is also the answer for anyone who would rather run their own.
    image="linuxserver/freecad:latest",
    binaries=("freecad", "FreeCAD", "freecad-daily"),
    macos_apps=("FreeCAD.app",),
    windows_globs=("FreeCAD*/bin/FreeCAD.exe", "FreeCAD*/FreeCAD.exe"),
    flatpak_id="org.freecad.FreeCAD",
)

GAZEBO = Tool(
    name="gazebo",
    display_name="Gazebo",
    # The simulator's own image for the current Gazebo. `:latest`, for the
    # reason FreeCAD's is: a user asking for a container wants the current
    # Gazebo, and `--docker-image` is the answer for anyone who wants another
    # one (`osrf/gazebo` for Gazebo Classic, say).
    image="gazebosim/gz-harmonic:latest",
    # Three generations of one program, newest first: `gz sim` today, `ign
    # gazebo` in the Ignition years, and `gazebo` for Gazebo Classic. Whichever
    # the machine has is the one used.
    binaries=("gz", "ign", "gazebo"),
    binary_args={"gz": ("sim",), "ign": ("gazebo",)},
    macos_apps=("Gazebo.app",),
    windows_globs=("Gazebo*/bin/gz.exe",),
    flatpak_id="org.gazebosim.Gazebo",
)

KICAD = Tool(
    name="kicad",
    display_name="KiCad",
    # The image PartCAD already builds and uses for `kicad` parts (see
    # 'partcad.part_factory_kicad'), pinned to this release the same way: it is
    # `kicad/kicad` with PartCAD's own environment on top, so the GUI is in it
    # and there is one KiCad container in the product rather than two. It is
    # `linux/amd64` only, as KiCad's own images are; a machine that cannot run
    # it almost certainly has KiCad installed, which is used first anyway.
    image="ghcr.io/partcad/partcad-container-kicad:" + __version__,
    binaries=("kicad",),
    macos_apps=("KiCad/KiCad.app", "KiCad.app"),
    windows_globs=("KiCad/*/bin/kicad.exe",),
    flatpak_id="org.kicad.KiCad",
    # What a `kicad` part points at is the STEP file KiCad's CLI generates from
    # the board. The board is the project beside it, and that is what opening
    # KiCad means.
    companions=(".kicad_pro", ".kicad_pcb", ".kicad_sch"),
)

# The Python Blender is asked to run when it is handed geometry rather than one
# of its own files. `blender <file>` *opens* a file, and the only thing Blender
# opens is a `.blend`: everything else is an import, which is an operator call
# and nothing else. Written as one expression on the command line rather than a
# script file because it has to work identically in a container, where a script
# file would be one more thing to make visible on both sides of the mount.
#
# Two names per format: Blender 4.x replaced the old Python importers with C++
# ones under different operator names ('wm.stl_import' for what used to be
# 'import_mesh.stl'), and both releases are in use. Whichever exists answers;
# the loop tries them in turn, newest first, and says so if none does. Reading
# a home file with no contents first is what leaves the imported object alone in
# the scene instead of inside Blender's default cube.
_BLENDER_IMPORT = """\
import bpy, os
path = {path!r}
importers = {{
    '.stl': ('wm.stl_import', 'import_mesh.stl'),
    '.obj': ('wm.obj_import', 'import_scene.obj'),
    '.ply': ('wm.ply_import', 'import_mesh.ply'),
    '.gltf': ('import_scene.gltf',),
    '.glb': ('import_scene.gltf',),
    '.json': ('import_scene.gltf',),
    '.fbx': ('import_scene.fbx',),
    '.x3d': ('import_scene.x3d',),
}}
extension = os.path.splitext(path)[1].lower()
bpy.ops.wm.read_homefile(use_empty=True)
for name in importers.get(extension, ()):
    category, _, operator = name.partition('.')
    try:
        getattr(getattr(bpy.ops, category), operator)(filepath=path)
        break
    except Exception as e:
        print('PartCAD: bpy.ops.' + name + ' did not import ' + path + ': ' + str(e))
else:
    print('PartCAD: this Blender has no importer for ' + (extension or path))
"""


def _blender_arguments(path: str) -> Tuple[str, ...]:
    """How Blender is told about ``path``: opened if it is a `.blend`, else imported."""
    if os.path.splitext(path)[1].lower() == ".blend":
        return (path,)
    return ("--python-expr", _BLENDER_IMPORT.format(path=path))


BLENDER = Tool(
    name="blender",
    display_name="Blender",
    # `:latest`, for the reason FreeCAD's is: a user asking for a container
    # wants the current Blender. The image is a community one because the
    # Blender project publishes none, and it is this one because it carries a
    # GUI Blender on `PATH` and is still being rebuilt. `--docker-image`
    # overrides it, as it does for every other tool here.
    image="linuxserver/blender:latest",
    binaries=("blender",),
    macos_apps=("Blender.app",),
    # Not through `open -a`: the arguments below are the whole point of the
    # launch, and `open -a` drops them on a Blender that is already running.
    macos_executable="Contents/MacOS/Blender",
    windows_globs=("Blender Foundation/Blender*/blender.exe", "Blender*/blender.exe"),
    flatpak_id="org.blender.Blender",
    file_args=_blender_arguments,
    # What the expression above knows how to import. '.json' is deliberately
    # absent: PartCAD writes both glTF and three.js to it, and only one of the
    # two is a file Blender reads -- so a '.json' is converted rather than
    # guessed at.
    imports=(".stl", ".obj", ".ply", ".gltf", ".glb", ".fbx", ".x3d"),
    # Blender reads triangles. Anything else -- a STEP file, a CadQuery script,
    # a part PartCAD builds -- reaches it as the STL PartCAD makes out of it.
    # STL rather than a richer mesh format because every part type converts to
    # it, which is what makes this one rule rather than a table of exceptions.
    mesh_via="stl",
    # A `.blend` is Blender's own file: not a mesh, and not something to convert
    # into one.
    own_formats=(".blend",),
)


MUJOCO = Tool(
    name="mujoco",
    display_name="MuJoCo",
    # DeepMind's own image, `:latest` for the reason every other one here is:
    # a user asking for a container wants the current MuJoCo, and
    # `--docker-image` is the answer for anyone who wants another.
    image="ghcr.io/google-deepmind/mujoco:latest",
    # `simulate` is the viewer the MuJoCo release ships; `mujoco` is what a
    # distribution package sometimes calls it. Whichever the machine has is the
    # one used.
    binaries=("simulate", "mujoco"),
    macos_apps=("MuJoCo.app",),
    macos_executable="Contents/MacOS/simulate",
    windows_globs=("MuJoCo*/bin/simulate.exe", "mujoco*/bin/simulate.exe"),
    # MuJoCo reads MJCF and no other model format. A scene given as anything
    # else -- a Gazebo world, above all -- is written out as MJCF first, which
    # is `pc export -t mjcf` and so is the daemon's work.
    scene_type="mjcf",
)


# The tools `pc open --with` accepts. Each is a row here, not a branch anywhere
# below.
TOOLS: Dict[str, Tool] = {tool.name: tool for tool in (FREECAD, GAZEBO, KICAD, BLENDER, MUJOCO)}


def tool_names() -> List[str]:
    """The tools that can be named, in the order they are offered."""
    return list(TOOLS)


@dataclass
class OpenResult:
    """What was opened, and how -- so a caller can say so rather than guess."""

    tool: str
    # "native" or "docker": which of the two routes below actually ran.
    method: str
    path: str
    command: List[str]
    detail: str
    # The file the caller named, when the application was given another one --
    # the board beside a KiCad part's STEP, the mesh made out of a solid. None
    # when it was handed exactly what it was asked about, which is the usual
    # case; a caller that reports "opened <path>" then needs no special case.
    source: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "tool": self.tool,
            "method": self.method,
            "path": self.path,
            "source": self.source,
            "command": list(self.command),
            "detail": self.detail,
        }


def open_file(
    path: str,
    tool: str = FREECAD.name,
    use_docker: bool = False,
    image: Optional[str] = None,
    log: Optional[Callable[[str], None]] = None,
    object_type: Optional[str] = None,
    transcode: Optional[Callable[..., None]] = None,
) -> OpenResult:
    """Open ``path`` in ``tool``, natively if it is installed, else in a container.

    ``use_docker`` is the caller's permission to fall back to a container, not a
    demand for one: a machine with the application installed uses it either way.
    Without that permission, and without a local installation, this raises rather
    than pulling an image nobody asked for.

    ``object_type`` is the PartCAD type the object was declared with, when the
    caller knows it -- the VS Code tree does, and a file name does not always say
    (a '.py' is three different script types). It decides nothing on its own; it
    is one of the two things `object_types.is_mesh` reads.

    ``transcode`` is how a file this application cannot read becomes one it can:
    a mesh for an application that reads nothing else, an MJCF model for one that
    reads only its own scene description. Called as
    ``transcode(source, source_type, target, target_type, kind)`` -- where
    ``kind`` is "part" or "scene" -- and expected to leave ``target`` on disk. It
    is a callback rather than something done here because both conversions are
    CAD work: they belong to the daemon, and this module is the half that must
    keep running without one. A caller that passes none can still open a mesh in
    Blender and an MJCF model in MuJoCo; anything needing a conversion is refused
    with the reason.
    """
    say = log or (lambda _message: None)

    spec = TOOLS.get(tool)
    if spec is None:
        raise ExternalToolError(
            "Unknown application '%s'. PartCAD can open files in: %s." % (tool, ", ".join(tool_names()))
        )

    named = os.path.abspath(os.path.expanduser(path))
    if not os.path.exists(named):
        raise ExternalToolError("No such file: %s" % named)
    resolved = spec.file_for(named)

    # The workspace is worked out from the file the caller named, before any
    # conversion: a converted copy lives under that workspace's own state
    # directory, and asking which workspace *it* is in would answer with the
    # state directory itself.
    root = _workspace_for(resolved)
    opened = resolved
    if spec.needs_mesh(resolved, object_type):
        opened = _transcode(spec, resolved, root, object_type, transcode, say)
    elif spec.needs_scene(resolved, object_type):
        opened = _transcode_scene(spec, resolved, root, object_type, transcode, say)

    native = native_command(spec)
    if native is not None:
        command = list(native) + list(spec.launch_args(native[-1])) + list(spec.file_arguments(opened))
        say("Opening %s in %s..." % (opened, spec.display_name))
        _spawn(command)
        return OpenResult(
            tool=spec.name,
            method="native",
            path=opened,
            source=None if opened == named else named,
            command=command,
            detail="%s is installed on this machine." % spec.display_name,
        )

    if not use_docker:
        raise ExternalToolError(
            "%s was not found on this machine.\n"
            "Install it, or let PartCAD run it in a container: pass --use-docker to `pc open` "
            "(the 'partcad.open.useDocker' setting in the VS Code extension)." % spec.display_name
        )

    return _open_in_container(spec, opened, root, image, say, source=None if opened == named else named)


# ---------------------------------------------------------------------------
# Making something the application can read out of what it cannot
# ---------------------------------------------------------------------------


def transcode_path(root: str, source: str, output_type: str) -> str:
    """Where the converted copy of ``source`` goes.

    Under the workspace's own directory on this machine -- the one that holds
    its daemon socket -- rather than beside the file. Two reasons, and both are
    the reason it is not a temporary directory either:

    * nothing PartCAD generates belongs in the user's source tree, where it
      would turn up in `git status` after opening a part; and
    * that directory is mounted into the container, at the path it has here, so
      the converted file has one name that means the same thing on both sides.

    The name carries a digest of the source path, so two parts called `cube` in
    different packages do not overwrite each other's mesh, and is otherwise
    stable, so opening the same part twice reuses the same file.
    """
    digest = hashlib.sha256(os.path.realpath(source).encode("utf-8")).hexdigest()[:16]
    stem = os.path.splitext(os.path.basename(source))[0]
    return os.path.join(_state_dir(root), "open", "%s-%s.%s" % (stem, digest, output_type))


def _transcode(
    spec: Tool,
    source: str,
    root: str,
    object_type: Optional[str],
    transcode: Optional[Callable[..., None]],
    say: Callable[[str], None],
) -> str:
    """Convert ``source`` to the mesh format ``spec`` reads, and return that file."""
    source_type = object_types.readable_type(source, object_type)
    reason = object_types.PACKAGE_ONLY_TYPES.get((source_type or "").lower())
    if reason is not None:
        raise ExternalToolError(
            "%s cannot open %s: %s, so it only means anything inside a package and there is "
            "nothing here to convert.\n"
            "Export the object to a mesh first, and open that: pc export -t stl -O <file> <object>"
            % (spec.display_name, source, reason)
        )
    if source_type is None:
        candidates = object_types.types_of_extension(os.path.splitext(source)[1])
        raise ExternalToolError(
            "%s reads meshes, and PartCAD cannot tell from its name what %s holds%s.\n"
            "Say so with --type ('pc open --type ...'); the VS Code extension passes the "
            "declared type of the object you clicked."
            % (
                spec.display_name,
                source,
                (" (it could be: %s)" % ", ".join(candidates)) if candidates else "",
            )
        )
    if transcode is None:
        # A caller inside `pc open` always passes one. Anything else reaching
        # here is a caller that cannot convert, and saying so beats opening an
        # application on a file it will refuse.
        raise ExternalToolError(
            "%s reads meshes, and %s is not one. Converting it needs the PartCAD daemon; "
            "run `pc open` rather than calling this directly." % (spec.display_name, source)
        )

    return _produce(spec, source, source_type, root, spec.mesh_via, spec.mesh_via, "part", transcode, say)


def _transcode_scene(
    spec: Tool,
    source: str,
    root: str,
    object_type: Optional[str],
    transcode: Optional[Callable[..., None]],
    say: Callable[[str], None],
) -> str:
    """Convert ``source`` into the scene description ``spec`` reads, and return it.

    The counterpart of `_transcode` for an application that reads an arrangement
    rather than geometry, and it refuses for its own reasons: a file that is no
    scene at all cannot become one (a STEP file is a shape, and there is nothing
    to place it in), and an ASSY file is a set of references to the parts of a
    package, so there is nothing here to resolve them against.
    """
    source_type = object_types.readable_scene_type(source, object_type)
    if source_type is None:
        raise ExternalToolError(
            "%s reads %s, and %s is not one -- PartCAD can convert a scene into it, and this is not a "
            "scene file it knows (it reads: %s).\n"
            "If it is one, say so with --type ('pc open --type ...'); the VS Code extension passes the "
            "declared type of the object you clicked."
            % (
                spec.display_name,
                spec.scene_type.upper(),
                source,
                ", ".join(sorted(object_types.SCENE_TYPE_EXTENSION)),
            )
        )
    reason = object_types.PACKAGE_ONLY_TYPES.get(source_type)
    if reason is not None:
        raise ExternalToolError(
            "%s cannot open %s: %s, so it only means anything inside a package and there is "
            "nothing here to convert.\n"
            "Export the scene from its package instead, and open that: pc export -S -t %s -O <dir> <scene>"
            % (spec.display_name, source, reason, spec.scene_type)
        )
    if transcode is None:
        raise ExternalToolError(
            "%s reads %s, and %s is not one. Converting it needs the PartCAD daemon; "
            "run `pc open` rather than calling this directly." % (spec.display_name, spec.scene_type.upper(), source)
        )

    extension = object_types.SCENE_TYPE_EXTENSION[spec.scene_type]
    return _produce(spec, source, source_type, root, spec.scene_type, extension, "scene", transcode, say)


def _produce(
    spec: Tool,
    source: str,
    source_type: str,
    root: str,
    target_type: str,
    extension: str,
    kind: str,
    transcode: Callable[..., None],
    say: Callable[[str], None],
) -> str:
    """Run one conversion and return the file it left behind.

    Shared by the two above: what differs between them is what is converted and
    what makes it necessary, and none of that is here.
    """
    target = transcode_path(root, source, extension)
    if os.path.isfile(target) and os.path.getmtime(target) >= os.path.getmtime(source):
        # The conversion is the slow part of opening a part, and the source has
        # not changed since the last one. A `touch` of the source is enough to
        # ask for it again, and so is deleting the file.
        say("Reusing %s..." % target)
        return target

    with contextlib.suppress(OSError):
        os.makedirs(os.path.dirname(target), exist_ok=True)
    say("Converting %s to %s for %s..." % (source, target_type.upper(), spec.display_name))
    transcode(source, source_type, target, target_type, kind)
    if not os.path.isfile(target):
        raise ExternalToolError(
            "Failed to convert %s to %s for %s; the conversion wrote nothing to %s."
            % (source, target_type.upper(), spec.display_name, target)
        )
    return target


# ---------------------------------------------------------------------------
# A local installation
# ---------------------------------------------------------------------------


def native_command(spec: Tool) -> Optional[List[str]]:
    """The command that runs a locally installed ``spec``, or None if there is none.

    Every platform's usual answers, in the order a user would expect them: what
    is on the PATH first, because that is what they chose to put there, then the
    places an installer puts things.
    """
    for binary in spec.binaries:
        found = shutil.which(binary)
        if found:
            return [found]

    system = platform.system()
    if system == "Darwin":
        for app in spec.macos_apps:
            for directory in ("/Applications", os.path.expanduser("~/Applications")):
                bundle = os.path.join(directory, app)
                if not os.path.isdir(bundle):
                    continue
                if spec.macos_executable is not None:
                    # The executable inside the bundle, because this application
                    # is handed arguments and `open -a` drops them on a copy
                    # that is already running -- which would open nothing at
                    # all, silently, from the second `pc open` onwards.
                    executable = os.path.join(bundle, spec.macos_executable)
                    if os.path.isfile(executable):
                        return [executable]
                    continue
                # Through `open`, not the executable inside the bundle: it is
                # how macOS launches an application, and it reuses a running
                # instance instead of starting a second one.
                return ["open", "-a", bundle]
    elif system == "Windows":  # pragma: no cover - exercised only on Windows
        for root in _windows_roots():
            for pattern in spec.windows_globs:
                matches = sorted(glob.glob(os.path.join(root, pattern.replace("/", os.sep))))
                if matches:
                    # Newest-looking last, so a machine with two versions gets
                    # the later one.
                    return [matches[-1]]
    elif spec.flatpak_id is not None and shutil.which("flatpak"):
        # Asked only once nothing else has matched: it costs a process, and a
        # flatpak is rarely the only copy on a machine that has one.
        if _run(["flatpak", "info", spec.flatpak_id]).returncode == 0:
            return ["flatpak", "run", spec.flatpak_id]

    return None


def _windows_roots() -> List[str]:  # pragma: no cover - exercised only on Windows
    """The directories Windows installers put applications in."""
    roots = []
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        value = os.environ.get(variable)
        if value:
            roots.append(value)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots.append(os.path.join(local, "Programs"))
    return roots


# ---------------------------------------------------------------------------
# A container
# ---------------------------------------------------------------------------


def _open_in_container(
    spec: Tool,
    path: str,
    root: str,
    image: Optional[str],
    say: Callable[[str], None],
    source: Optional[str] = None,
) -> OpenResult:
    """Run ``spec`` in its container, creating and starting one as needed.

    ``root`` is the workspace to mount, worked out by the caller from the file
    it was asked about rather than from ``path``: the two differ when ``path``
    is a mesh PartCAD made, which lives under that workspace's state directory
    and is not in a workspace of its own.
    """
    if not _docker_available():
        raise ExternalToolError(
            "%s is not installed on this machine and Docker is not available to run it in a container.\n"
            "Install %s, or install Docker and make sure `docker info` succeeds."
            % (spec.display_name, spec.display_name)
        )

    # Worked out before anything is created or started: a container that cannot
    # show a window is not worth starting, and the message below is the whole
    # point of the check.
    x11_env, x11_mounts, x11_advice = _x11_forwarding(spec)
    display = x11_env["DISPLAY"]

    state = _container_state(spec.container_name)
    if state is None:
        say("Creating the '%s' container from %s..." % (spec.container_name, image or spec.image))
        _create_container(spec, image or spec.image, root, x11_mounts, x11_env)
    else:
        _check_container_mounts(spec, root)
        if state != "running":
            say("Starting the '%s' container..." % spec.container_name)
            _start_container(spec.container_name)

    binary = _container_binary(spec)
    # The display travels on the exec rather than being left to what the
    # container was created with: the container outlives the session, and the
    # display the user is on now is the one the window has to come out on.
    command = [
        "docker",
        "exec",
        "--detach",
        *_env_args(x11_env),
        "--workdir",
        root,
        spec.container_name,
        binary,
        *spec.launch_args(binary),
        *spec.file_arguments(path),
    ]
    say("Opening %s in %s (container '%s', DISPLAY=%s)..." % (path, spec.display_name, spec.container_name, display))
    result = _run(command)
    if result.returncode != 0:
        raise ExternalToolError(
            "Failed to start %s in the '%s' container: %s"
            % (spec.display_name, spec.container_name, _message(result) or "docker exec failed")
        )

    detail = "%s runs in the '%s' container, displaying on %s." % (spec.display_name, spec.container_name, display)
    if x11_advice:
        detail += "\n" + x11_advice
    return OpenResult(tool=spec.name, method="docker", path=path, source=source, command=command, detail=detail)


def _env_args(env: Dict[str, str]) -> List[str]:
    """``--env K=V`` for each entry, in a fixed order so a command line is stable."""
    args = []
    for key in sorted(env):
        args += ["--env", "%s=%s" % (key, env[key])]
    return args


def _state_dir(root: str) -> str:
    """The workspace's own directory on this machine, holding its daemon socket.

    Derived from `socket_path` rather than named again, because this is the
    directory `_create_container` mounts: a converted mesh is written into it
    (see `transcode_path`) precisely so that it arrives inside the container,
    and two ways of spelling one directory is how that would quietly stop being
    true.
    """
    return os.path.dirname(socket_path(root))


def _workspace_for(path: str) -> str:
    """The workspace to mount into the container so that ``path`` is inside it.

    The one this command runs in, when it holds the file: that is the workspace
    whose daemon socket is worth mounting beside it, and the one the caller
    means -- an editor runs `pc open` in the window's workspace folder. A file
    somewhere else gets its own workspace mounted instead, which still contains
    it; there is simply no daemon of this workspace's to offer it.
    """
    root = determine_root_path()
    if _is_within(path, root):
        return root
    return determine_root_path(os.path.dirname(path))


def _docker_available() -> bool:
    """True when there is a `docker` that answers -- not merely one on the PATH.

    A CLI with no daemon behind it is the common case (Docker Desktop not
    started), and it fails several seconds later inside `docker run`, where the
    error says nothing useful.
    """
    if shutil.which("docker") is None:
        return False
    return _run(["docker", "info"]).returncode == 0


def _container_state(name: str) -> Optional[str]:
    """The state of the container named ``name`` ("running", "exited", ...), or None.

    The filter narrows the listing; the name is then compared exactly, because
    `--filter name=` is a substring pattern -- a user's `partcad-freecad-test`
    must not be mistaken for the container PartCAD manages.
    """
    result = _run(
        [
            "docker",
            "ps",
            "--all",
            "--filter",
            "name=" + name,
            "--format",
            "{{.Names}}\t{{.State}}",
        ]
    )
    if result.returncode != 0:
        raise ExternalToolError("Failed to look for the '%s' container: %s" % (name, _message(result)))
    for line in (result.stdout or "").splitlines():
        fields = line.strip().split("\t")
        if len(fields) == 2 and fields[0] == name:
            return fields[1]
    return None


def _create_container(spec: Tool, image: str, root: str, x11_mounts: List[str], x11_env: Dict[str, str]) -> None:
    """Create the tool's container, mounting the workspace and the daemon socket.

    The container is created idle (it sleeps) and the application is started in
    it with `docker exec`, rather than being the container's own command. One
    container then serves every `pc open`: the first one does not have to be
    treated differently from the next, and closing the application's window does
    not throw away a container the user may have customised.
    """
    mounts = ["--volume", "%s:%s" % (root, root)]

    # The daemon's socket, so that a PartCAD running inside the container talks
    # to the same daemon this workspace already has, instead of starting a
    # second one against a directory only it can see. The directory is mounted
    # rather than the socket file: a restarted daemon creates a new socket, and
    # a bind mount of the old file would keep pointing at something that is gone.
    #
    # Created here if it does not exist yet, because the mounts are fixed when
    # the container is created and this container outlives the daemon several
    # times over. Waiting for a daemon that has not started would mean a
    # container that can never see the one that eventually does -- and the
    # directory is PartCAD's own, which the daemon would create the same way.
    socket_dir = _state_dir(root)
    with contextlib.suppress(OSError):
        os.makedirs(socket_dir, exist_ok=True)
    if os.path.isdir(socket_dir):
        mounts += ["--volume", "%s:%s" % (socket_dir, socket_dir)]

    command = [
        "docker",
        "run",
        "--detach",
        "--name",
        spec.container_name,
        "--workdir",
        root,
        *_env_args(x11_env),
        *mounts,
        *x11_mounts,
        # The image's own entrypoint is the application; it has to be replaced
        # for the container to stay up and wait for `docker exec`.
        "--entrypoint",
        "sh",
        image,
        "-c",
        "while true; do sleep 3600; done",
    ]
    result = _run(command, timeout=None)
    if result.returncode != 0:
        raise ExternalToolError(
            "Failed to create the '%s' container from %s: %s" % (spec.container_name, image, _message(result))
        )


def _start_container(name: str) -> None:
    result = _run(["docker", "start", name])
    if result.returncode != 0:
        raise ExternalToolError("Failed to start the '%s' container: %s" % (name, _message(result)))


def _check_container_mounts(spec: Tool, root: str) -> None:
    """Refuse an existing container that cannot see this workspace.

    A container outlives the workspace it was created for, and the mounts are
    fixed when it is created. Without this check the application starts, reports
    that the file does not exist, and the user has no way to know why.
    """
    result = _run(
        ["docker", "inspect", "--format", "{{range .Mounts}}{{println .Destination}}{{end}}", spec.container_name]
    )
    if result.returncode != 0:
        # Not fatal: an old Docker that formats this differently must not stop
        # a container that is very probably fine.
        return
    mounted = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    if not mounted:
        return
    if any(_is_within(root, destination) for destination in mounted):
        return
    raise ExternalToolError(
        "The '%s' container does not have this workspace (%s) mounted; it was created for a different one.\n"
        "Remove it and PartCAD will create one for this workspace: docker rm -f %s"
        % (spec.container_name, root, spec.container_name)
    )


def _container_binary(spec: Tool) -> str:
    """The application's executable inside the container, or an error naming why not."""
    for binary in spec.binaries:
        result = _run(["docker", "exec", spec.container_name, "sh", "-c", "command -v " + binary])
        if result.returncode == 0 and (result.stdout or "").strip():
            return (result.stdout or "").strip().splitlines()[0]
    raise ExternalToolError(
        "The '%s' container has no %s executable (looked for: %s).\n"
        "Remove it so that PartCAD recreates it from %s: docker rm -f %s"
        % (
            spec.container_name,
            spec.display_name,
            ", ".join(spec.binaries),
            spec.image,
            spec.container_name,
        )
    )


# ---------------------------------------------------------------------------
# Getting the window onto the user's screen
# ---------------------------------------------------------------------------

_LINUX_NO_DISPLAY = (
    "There is no X display to show {name} on (DISPLAY is not set).\n"
    "Run `pc open` from a graphical session, or set DISPLAY to the X server to use.\n"
    "Under Wayland, install XWayland so that X applications have a display."
)

_MACOS_NO_DISPLAY = (
    "Running {name} in a container needs an X server on macOS, and none was found.\n"
    "Install XQuartz (https://www.xquartz.org/ or `brew install --cask xquartz`), then:\n"
    "  1. start XQuartz and turn on Preferences > Security > 'Allow connections from network clients';\n"
    "  2. log out and back in, so XQuartz restarts with that setting;\n"
    "  3. run `xhost + 127.0.0.1` to let the container connect.\n"
    "Install {name} on this machine instead if you would rather not run an X server."
)

_WINDOWS_NO_DISPLAY = (
    "Running {name} in a container needs an X server on Windows, and none was found.\n"
    "Install one -- VcXsrv (https://sourceforge.net/projects/vcxsrv/), X410 or Xming -- start it with\n"
    "access control disabled ('Disable access control' in the VcXsrv wizard), then set DISPLAY, e.g.\n"
    "  set DISPLAY=host.docker.internal:0\n"
    "Install {name} on this machine instead if you would rather not run an X server."
)

_MACOS_ADVICE = "If no window appears, run `xhost + 127.0.0.1` in a terminal and check that XQuartz is running."
_WINDOWS_ADVICE = "If no window appears, check that the X server is running with access control disabled."
_LINUX_ADVICE = "If the application reports 'Authorization required', run `xhost +local:` to let the container connect."
_LINUX_TCP_ADVICE = (
    "The display is reached over TCP, so the container connects to it as host.docker.internal; "
    "run `xhost +` on the machine running the X server if it is refused."
)


def _x11_forwarding(spec: Tool) -> Tuple[Dict[str, str], List[str], str]:
    """How the container reaches the user's screen: (environment, mounts, advice).

    Raises with instructions when there is nothing to reach. That message is the
    reason this runs before the container is created: an unusable container that
    starts and shows nothing is worse than a command that says what to install.
    """
    system = platform.system()
    display = os.environ.get("DISPLAY", "").strip()

    if system == "Darwin":
        if not (display or _xquartz_installed()):
            raise ExternalToolError(_MACOS_NO_DISPLAY.format(name=spec.display_name))
        # Always over TCP: the container has no access to the launchd socket
        # macOS puts in DISPLAY, and host.docker.internal is how Docker Desktop
        # exposes the host to it.
        return {"DISPLAY": _host_display(display)}, [], _MACOS_ADVICE

    if system == "Windows":  # pragma: no cover - exercised only on Windows
        if not display:
            raise ExternalToolError(_WINDOWS_NO_DISPLAY.format(name=spec.display_name))
        return {"DISPLAY": _host_display(display)}, [], _WINDOWS_ADVICE

    if not display:
        raise ExternalToolError(_LINUX_NO_DISPLAY.format(name=spec.display_name))

    host = display.rsplit(":", 1)[0] if ":" in display else ""
    if host not in ("", "unix") and not host.startswith("/"):
        # A display reached over TCP -- an SSH-forwarded one, or an X server on
        # another machine. There is no socket to share, so the container is
        # given the address instead; `host-gateway` is what makes "the host"
        # resolvable from inside a container on Linux.
        return (
            {"DISPLAY": _host_display(display)},
            ["--add-host", "host.docker.internal:host-gateway"],
            _LINUX_TCP_ADVICE,
        )

    env = {"DISPLAY": display}
    mounts = []
    if os.path.isdir("/tmp/.X11-unix"):
        # The display is a socket on this machine, so it can simply be shared --
        # no TCP, no listening X server, nothing for the user to configure.
        mounts += ["--volume", "/tmp/.X11-unix:/tmp/.X11-unix:rw"]
    xauthority = os.environ.get("XAUTHORITY")
    if xauthority and os.path.isfile(xauthority):
        # Both the file and the variable naming it: an X client that cannot find
        # the cookie is refused by the server, and the container's idea of a home
        # directory is not the user's.
        mounts += ["--volume", "%s:%s:ro" % (xauthority, xauthority)]
        env["XAUTHORITY"] = xauthority
    return env, mounts, _LINUX_ADVICE


def _xquartz_installed() -> bool:
    """True when macOS has an X server installed, even if it is not running."""
    return any(
        os.path.exists(candidate)
        for candidate in ("/Applications/Utilities/XQuartz.app", "/opt/X11/bin/Xquartz", "/opt/X11/bin/xquartz")
    )


def _host_display(display: str) -> str:
    """The host's display, addressed the way a container has to address it.

    A local display is on the host, which a container on macOS or Windows
    reaches as `host.docker.internal`. Local covers more than ":0": macOS puts
    the path of XQuartz's launchd socket in DISPLAY, which names nothing at all
    outside this machine. Anything that does name a machine is passed through
    untouched.
    """
    screen = display.rsplit(":", 1)[-1] if ":" in display else "0"
    host = display.rsplit(":", 1)[0] if ":" in display else ""
    if host in ("", "localhost", "127.0.0.1", "unix") or host.startswith("/"):
        return "host.docker.internal:" + screen
    return display


# ---------------------------------------------------------------------------
# Running things
# ---------------------------------------------------------------------------


def _is_within(path: str, directory: str) -> bool:
    """True when ``path`` is ``directory`` or below it."""
    try:
        relative = os.path.relpath(os.path.realpath(path), os.path.realpath(directory))
    except ValueError:  # pragma: no cover - different drives on Windows
        return False
    if relative == os.curdir:
        return True
    return relative != os.pardir and not relative.startswith(os.pardir + os.sep)


def _message(result: subprocess.CompletedProcess) -> str:
    """The most useful line Docker printed, for a message a user has to act on."""
    for stream in (result.stderr, result.stdout):
        text = (stream or "").strip()
        if text:
            return text.splitlines()[-1]
    return ""


def _run(args: List[str], timeout: Optional[float] = DOCKER_TIMEOUT) -> subprocess.CompletedProcess:
    """Run a command and capture what it said; a timeout is a failed command."""
    try:
        return subprocess.run(
            args,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 1, "", "timed out after %s seconds" % timeout)
    except OSError as e:
        return subprocess.CompletedProcess(args, 1, "", str(e))


def _spawn(args: List[str]) -> None:
    """Start a GUI application and leave it running once this process exits.

    Detached on purpose: `pc open` is done the moment the window belongs to the
    user, and an editor's context menu must not stay busy for as long as the
    application is open.
    """
    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":  # pragma: no cover - exercised only on Windows
        kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(args, **kwargs)
    except OSError as e:
        raise ExternalToolError("Failed to run %s: %s" % (" ".join(args), e))
