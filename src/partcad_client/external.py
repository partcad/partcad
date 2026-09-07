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
import functools
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
    "builtin_tools",
    "merge_tools",
    "open_file",
    "tool_from_declaration",
    "tool_names",
    "tools_from_section",
    "transcode_path",
    "use_tools",
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
    # Empty for an application whose declaration names none: a package may know
    # where a tool is installed without there being a container to fall back to,
    # and `--use-docker` says so rather than trying to create one from nothing.
    image: str = ""
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
    # with the rest of them -- in its declaration, as templates: `{path}` is
    # substituted with the file name and `{path_repr}` with it quoted as a
    # Python string, for a template that embeds the name in code.
    #
    # Templates rather than a callable because this table is read out of
    # `open:` declarations now, and a package that teaches PartCAD an
    # application cannot ship a Python function into a frozen client.
    file_args: Tuple[str, ...] = ()
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
        all of them but Blender; see `file_args`. An application's own file is
        named that way too even when it declares templates: what those are for
        is the *import* of something that is not one, and a `.blend` is opened
        rather than imported.
        """
        if not self.file_args:
            return (path,)
        if os.path.splitext(path)[1].lower() in self.own_formats:
            return (path,)
        return tuple(template.replace("{path_repr}", repr(path)).replace("{path}", path) for template in self.file_args)

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


# Where the built-in declarations live inside the wheel. Found without importing
# `partcad`: this module is a client's and has to stay cheap to import, and the
# file is data -- the same reason `object_types` holds a copy of PartCAD's tables
# rather than reaching for them.
BUILTIN_OPEN_PACKAGE = ("partcad", "builtin", "open", "partcad.yaml")

# What a declaration calls each field of `Tool`. Spelled camelCase in YAML, like
# every other declaration PartCAD reads, and snake_case here.
DECLARATION_FIELDS = {
    "displayName": "display_name",
    "image": "image",
    "binaries": "binaries",
    "args": "args",
    "binaryArgs": "binary_args",
    "macosApps": "macos_apps",
    "macosExecutable": "macos_executable",
    "windowsGlobs": "windows_globs",
    "flatpakId": "flatpak_id",
    "companions": "companions",
    "fileArgs": "file_args",
    "ownFormats": "own_formats",
    "imports": "imports",
    "meshVia": "mesh_via",
    "sceneType": "scene_type",
}

# The fields that are a sequence, so a declaration's list becomes the tuple the
# frozen dataclass wants.
_TUPLE_FIELDS = frozenset(
    {"binaries", "args", "macos_apps", "windows_globs", "companions", "file_args", "own_formats", "imports"}
)


def tool_from_declaration(name: str, config: dict) -> Tool:
    """One `open:` entry as a `Tool`.

    Unknown keys are ignored rather than refused. A declaration is read by
    whatever PartCAD the user has installed, and a tool declared by a package
    that knows about a field this release does not should still launch.
    """
    values = {"name": name, "display_name": name}
    for declared, field_name in DECLARATION_FIELDS.items():
        if declared not in config or config[declared] is None:
            continue
        value = config[declared]
        if field_name in _TUPLE_FIELDS:
            value = tuple(value) if isinstance(value, (list, tuple)) else (value,)
        elif field_name == "binary_args":
            value = {key: tuple(args) for key, args in (value or {}).items()}
        elif field_name == "image":
            # `{version}` pins an image PartCAD publishes to this release
            # without the number being written down twice.
            value = str(value).replace("{version}", __version__)
        values[field_name] = value
    return Tool(**values)


def tools_from_section(section: dict) -> Dict[str, Tool]:
    """Every entry of one `open:` section, as tools."""
    if not isinstance(section, dict):
        return {}
    return {name: tool_from_declaration(name, config) for name, config in section.items() if isinstance(config, dict)}


def _builtin_declarations() -> dict:
    """The `open:` section of the package that ships inside `partcad`.

    Read off disk rather than through a context, because `pc open` has none and
    is not going to acquire one: it is handed a path, the file is already there,
    and needing the package graph to answer "where is FreeCAD" would make the
    command depend on a workspace it has nothing to do with. A tool a *package*
    declares is the case that does need the graph, and that one is answered by
    the daemon -- see `merge_tools()`.
    """
    import importlib.util

    spec = importlib.util.find_spec("partcad")
    if spec is None or not spec.submodule_search_locations:
        return {}
    root = os.path.dirname(list(spec.submodule_search_locations)[0])
    path = os.path.join(root, *BUILTIN_OPEN_PACKAGE)
    if not os.path.isfile(path):
        return {}
    import yaml

    with open(path, encoding="utf-8") as f:
        return (yaml.safe_load(f) or {}).get("open") or {}


@functools.lru_cache(maxsize=1)
def builtin_tools() -> Dict[str, Tool]:
    """The applications PartCAD itself declares.

    Cached: the file is inside the installation and cannot change under a
    running process, and `pc open` asks for it on a path where an editor's
    context menu is waiting.
    """
    return tools_from_section(_builtin_declarations())


def merge_tools(declared: Optional[dict] = None) -> Dict[str, Tool]:
    """The built-in applications, plus whatever a workspace's packages declare.

    `declared` is an `open:` section the caller obtained from somewhere that has
    the package graph -- in practice the daemon, which is the only side that
    does. A package's entry wins over a built-in of the same name, which is what
    lets the plugin for an engine own the tool for it once it is published.
    """
    tools = dict(builtin_tools())
    tools.update(tools_from_section(declared or {}))
    return tools


# What `pc open` opens a file in when the user names no application. A string
# rather than a reference to one of the entries, because the entries are data
# now and this is the one of them PartCAD treats as special.
DEFAULT_TOOL = "freecad"

# The tools `pc open --with` accepts. Each is a declaration, not a branch
# anywhere below. Replaced wholesale by `use_tools()` when a caller has asked
# the daemon what the workspace's packages declare.
TOOLS: Dict[str, Tool] = merge_tools()


def use_tools(declared: Optional[dict]) -> None:
    """Add the applications a workspace's packages declare to this process.

    Called by `pc open` once, before it looks a tool up, with whatever the
    daemon reported. A no-op when nothing was declared or the daemon could not
    be reached, which is what keeps the command working with no daemon at all --
    for every tool PartCAD itself ships, which is the common case.
    """
    if not declared:
        return
    TOOLS.clear()
    TOOLS.update(merge_tools(declared))


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
    tool: str = DEFAULT_TOOL,
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

    if not (image or spec.image):
        raise ExternalToolError(
            "%s is not installed here and declares no container image, so there is nothing to run it in.\n"
            "Install it, or name an image with --docker-image." % spec.display_name
        )

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
