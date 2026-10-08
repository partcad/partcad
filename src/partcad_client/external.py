#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Opening an object in a third-party application, on the machine the client runs on.

This is a client's job by construction, and it is why the code sits here rather
than behind an RPC method. A daemon can be remote: "open this in FreeCAD" sent to
one would start a window on somebody else's desk, on a machine that may have no
display at all -- and the file named on the command line is the client's own,
found by a path that means nothing on the other side of the wire. So the opening
is done here, and the VS Code extension reaches this code by running `pc ide open`
rather than by reimplementing it in TypeScript.

**An application is an `open:` plugin.** Each entry of an `open:` section -- the
ones PartCAD ships in `//builtin/open`, and any a package declares -- says where
the application is installed on each operating system, what to run it as, an
optional ``container:`` to run it in where it is not installed (the same shape a
plugin's implementation declares), and an ordered list of the ``formats:`` it
opens. Nothing in it is code; what is code is here, once, for every application.

**The formats decide what the application is handed.** An object whose own
format is on the list is opened as it is. One that is not is converted to the
first format on the list PartCAD can write -- a CadQuery script into STEP for
FreeCAD, a STEP into STL for Blender -- and the application is handed that.
Conversion is CAD work, so it is not done here: the caller passes a
``transcode`` callback, and `pc ide open` implements it as the daemon's
`adhoc.convert`. The copy is written under the workspace's own state directory,
never beside the source.

**And `pc ide open` waits.** It returns when the application does, so that what
somebody did in it can be brought back: an object opened as it is was edited
where it lives; one that was converted is converted back into its own format and
written over its source -- when its source is a file PartCAD can write. A script,
an alias, an extrude has no file a STEP could be written back into, so the edited
copy is kept and its path reported instead. Nothing is written when nothing
changed.

Two ways to run an application, tried in this order:

* **Natively**, when the machine has it installed. Nothing is containerised, and
  the application sees the file at the path the user typed.
* **In a container**, when it is not, Docker is available, and the caller passed
  ``use_docker``. Started by `partcad_utils.containers`, like every container
  PartCAD starts -- named after the application, its image and how it is set
  up, labelled for `pc system prune`, and replaced rather than reused when it no
  longer matches. Its home directory is a volume of its own, so the preferences
  and add-ons somebody gave it survive the container being replaced. Files reach
  it by mount -- the workspace at the path it has here -- or, with
  ``useDockerRemote``, by upload: the file goes with the command and comes back
  when the application exits.

A containerised GUI needs an X server on the host, which is the one place where
this cannot paper over the difference between platforms. On Linux the display is
usually a socket that can simply be shared, cookie and all; on macOS and Windows
-- and on Linux over a forwarded display -- it is a TCP connection to an X server
the user has to install and allow. When it is missing they are told which one to
install and what to run, rather than given a container that silently never shows
a window.
"""

import contextlib
import functools
import glob
import hashlib
import os
import platform
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from partcad_utils import containers
from partcad_utils.container_image import image_name, image_tag
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

# How long to wait for a question to the container runtime. Generous enough for
# a busy daemon, short enough that a wedged one is reported rather than hanging
# an editor.
DOCKER_TIMEOUT = 60.0

# An application that returns sooner than this, having changed nothing, most
# likely handed the file to a copy of itself that was already running and
# exited -- which leaves nothing here to wait for. Said, rather than reported as
# "no changes", because the edits will happen and will not be brought back.
HANDOFF_SECONDS = 3.0

# Where an application's home directory is inside its container: a volume per
# application, so that what somebody configured outlives the container.
CONTAINER_HOME = "/partcad-home"


class ExternalToolError(Exception):
    """No way to open the file, with a message saying what would fix that."""


def _extension_of(path: str) -> str:
    """The extension of ``path``, lowercased and with its dot kept.

    With the dot, because that is how every extension a tool declares is written
    -- `ownFormats`, `imports` and `sceneExtensions` alike -- so a comparison
    needs no stripping at either end.
    """
    return os.path.splitext(path)[1].lower()


def _export_target(scene_type: str) -> str:
    """How ``scene_type`` has to be spelled for `pc export -t` to resolve it.

    A format PartCAD implements is asked for by name. One an engine's plugin
    implements is not PartCAD's to resolve, so the package that declares it has
    to be named -- and which of the two this is is exactly whether PartCAD has an
    extension for it.
    """
    if scene_type in object_types.SCENE_TYPE_EXTENSION:
        return scene_type
    return "<package>:" + scene_type


def _bare_type(object_type: Optional[str]) -> Optional[str]:
    """An object type without the package that declares it.

    'sim-mujoco:mjcf' and 'mjcf' are one format asked for in two places: the
    first is how an object in some other package declares it, the second is what
    the package implementing it calls it in its own `open:` entry. Comparing the
    part after the last ':' is what makes those the same answer.

    None stays None, so that two tools declaring no scene type at all do not
    come out equal.
    """
    if object_type is None:
        return None
    return object_type.rsplit(":", 1)[-1].lower()


def _format_name(value: str) -> str:
    """A format as a declaration spells it -- 'STEP', '.stl', 'kicad_pro' -- as one comparable name."""
    return str(value).strip().lower().lstrip(".")


@dataclass(frozen=True)
class Tool:
    """A third-party application PartCAD knows how to launch: one `open:` entry.

    Everything platform-specific about finding one is data, so that adding the
    second tool is a table entry rather than another copy of the logic below.
    """

    name: str
    display_name: str
    # The image the application's container is created from when the machine
    # has no local copy -- `container: {image: ...}` in a declaration, or the
    # older `image:`. Empty for an application whose declaration names none: a
    # package may know where a tool is installed without there being a
    # container to fall back to.
    image: str = ""
    # The interpreter PartCAD's service runs on inside that container. An image
    # whose `python3` is not on PATH says where its is.
    container_python: str = "python3"
    # What the application opens, most preferred first: PartCAD types ('step',
    # 'stl', 'mjcf') and the extensions of the application's own formats
    # ('blend', 'kicad_pro'). An object whose format is on the list is opened as
    # it is; one that is not is converted to the first entry PartCAD can write.
    # Empty means the application is handed whatever it is asked to open.
    formats: Tuple[str, ...] = ()
    # Executable names to look for, both on this machine's PATH and inside the
    # container. Ordered: the first one found wins.
    binaries: Tuple[str, ...] = ()
    # macOS application bundles, looked for under /Applications and ~/Applications.
    macos_apps: Tuple[str, ...] = ()
    # The executable inside the macOS bundle, relative to it, for an application
    # that is handed arguments rather than a document.
    macos_executable: Optional[str] = None
    # Windows install locations, as globs relative to the directories in
    # `windows_roots`, so a versioned directory name still matches.
    windows_globs: Tuple[str, ...] = ()
    flatpak_id: Optional[str] = None
    # Extra arguments the application needs before the file name, if any.
    args: Tuple[str, ...] = field(default_factory=tuple)
    # The same, for one executable in particular. Gazebo's world file is
    # `gz sim <world>` through the current command and a bare `gazebo <world>`
    # through the old one, and which of the two is on the machine decides.
    binary_args: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    # Extensions this application actually opens, when the file it is handed is
    # not one of them and one of these sits beside it. A PartCAD `kicad` part
    # *is* the STEP file KiCad's CLI writes out of the board; the board itself --
    # what somebody opening KiCad means -- is the project file next to it.
    companions: Tuple[str, ...] = ()
    # How the file reaches the application, when being the last argument is not
    # it, as templates: `{path}` is the file name. Blender imports anything but
    # its own `.blend` through a line of Python, and reads the name from after
    # `--` on its command line -- so the name is still an argument of its own,
    # which is what lets it be sent to a container on another machine.
    # `{path_repr}`, the name quoted inside another argument, still works where
    # the file is shared, and cannot be sent.
    file_args: Tuple[str, ...] = ()
    # The PartCAD *scene* type this application reads, and the extensions a file
    # of it is stored in -- from the older `sceneType`/`sceneExtensions`, which
    # are also how a format two engines store under one extension (MJCF and
    # SDFormat both in `.xml`) is told apart by its declared type.
    scene_type: Optional[str] = None
    scene_extensions: Tuple[str, ...] = ()
    # Which of the older format fields the declaration used. They still work --
    # a package published against an older PartCAD must not stop opening -- and
    # `pc ide open` says once that `formats:` is how to say it now.
    deprecated: Tuple[str, ...] = ()

    @property
    def role(self) -> str:
        """What its container is for, in the container's name: ``open-<tool>``."""
        return "open-" + self.name

    @property
    def format_set(self) -> frozenset:
        return frozenset(_format_name(f) for f in self.formats)

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

        The path itself for every application that takes a file name; see
        `file_args` for the one that does not. An application's own file is
        named that way too even when it declares templates: what those are for
        is the *import* of something that is not one, and a `.blend` is opened
        rather than imported.
        """
        if not self.file_args:
            return (path,)
        if _extension_of(path).lstrip(".") in self._own_extensions():
            return (path,)
        return tuple(template.replace("{path_repr}", repr(path)).replace("{path}", path) for template in self.file_args)

    def embeds_path(self) -> bool:
        """Whether the file name is quoted *inside* an argument, where only a shared file can be named."""
        return any("{path_repr}" in template for template in self.file_args)

    def _own_extensions(self) -> frozenset:
        """The formats on the list that are not PartCAD's: the application's own, opened rather than imported."""
        known = set(object_types.PART_TYPE_IS_MESH) | set(object_types.SCENE_TYPE_EXTENSION)
        own = {f for f in self.format_set if f not in known and f not in object_types.EXTENSION_ALIASES}
        # The mesh extensions an importer reads are not the application's own,
        # whatever PartCAD calls them: 'ply', 'fbx', 'glb' are imported.
        return frozenset(f for f in own if f not in _IMPORTED_EXTENSIONS)

    def formats_of(self, path: str, object_type: Optional[str] = None) -> List[str]:
        """Every name the format of ``path`` goes by, as this application's list would spell it.

        A declared type that names a *scene format* decides it alone and the
        extension is not consulted: two scene formats can share one -- a Gazebo
        world and a MuJoCo model are both '.xml' -- and the declaration is the
        only thing that tells them apart. Any other declared type, or none,
        defers to the file: its extension, the PartCAD type that extension (or
        the declaration) makes it, and this application's scene type where the
        extension is one it stores that in.
        """
        if object_type:
            bare = _bare_type(object_type)
            if ":" in object_type or bare in object_types.SCENE_TYPE_EXTENSION:
                return [bare]
        found = []
        extension = _extension_of(path).lstrip(".")
        if extension:
            found.append(extension)
            alias = object_types.EXTENSION_ALIASES.get(extension)
            if alias:
                found.append(alias)
        part = object_types.readable_type(path, object_type)
        if part:
            found.append(part)
        scene = object_types.readable_scene_type(path, object_type)
        if scene:
            found.append(scene)
        if self.scene_type and extension and "." + extension in self.scene_extensions:
            found.append(_bare_type(self.scene_type))
        return list(dict.fromkeys(_format_name(f) for f in found))

    def opens(self, path: str, object_type: Optional[str] = None) -> bool:
        """Whether ``path`` can be handed to this application as it is."""
        if not self.formats:
            return True
        return any(name in self.format_set for name in self.formats_of(path, object_type))

    def reads_scenes(self) -> bool:
        """Whether this application reads a description of an arrangement rather than geometry.

        Said by its `sceneType`, not guessed from its formats: KiCad's are all
        its own and it reads no scene.
        """
        return bool(self.scene_type)

    def conversion_target(self) -> Optional[str]:
        """The first format on the list PartCAD can write a part into, or None."""
        for name in self.formats:
            if _format_name(name) in object_types.WRITABLE_PART_TYPES:
                return _format_name(name)
        return None

    def file_for(self, path: str) -> str:
        """The file this application is really given, from the one it was handed.

        Unchanged unless the tool declares `companions` and the path is not one
        of them: then the first companion that exists beside it wins.
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


# Mesh extensions applications import that PartCAD does not write: they count as
# formats the application reads, never as its own project files.
_IMPORTED_EXTENSIONS = frozenset({"ply", "fbx", "x3d", "glb", "dae", "abc", "usd", "usdz"})


# Where the built-in declarations live inside the wheel. Found without importing
# `partcad`: this module is a client's and has to stay cheap to import, and the
# file is data -- the same reason `object_types` holds a copy of PartCAD's tables
# rather than reaching for them.
BUILTIN_OPEN_PACKAGE = ("partcad", "builtin", "open", "partcad.yaml")

# What a declaration calls each field of `Tool`. Spelled camelCase in YAML, like
# every other declaration PartCAD reads, and snake_case here.
DECLARATION_FIELDS = {
    "displayName": "display_name",
    "formats": "formats",
    "binaries": "binaries",
    "args": "args",
    "binaryArgs": "binary_args",
    "macosApps": "macos_apps",
    "macosExecutable": "macos_executable",
    "windowsGlobs": "windows_globs",
    "flatpakId": "flatpak_id",
    "companions": "companions",
    "fileArgs": "file_args",
    "sceneType": "scene_type",
    "sceneExtensions": "scene_extensions",
}

# The fields that are a sequence, so a declaration's list becomes the tuple the
# frozen dataclass wants.
_TUPLE_FIELDS = frozenset(
    {"formats", "binaries", "args", "macos_apps", "windows_globs", "companions", "file_args", "scene_extensions"}
)

# The fields a declaration used to say what an application opens with, before
# `formats:`. Read into `formats` when a declaration names no `formats` of its
# own, in an order that keeps what each meant: an application's own files first,
# then the format a solid was converted to, then the mesh formats it imports,
# then the scene type it reads. `sceneType` is not deprecated -- it is still what
# says an application reads scenes -- the other three are.
LEGACY_FORMAT_FIELDS = ("ownFormats", "meshVia", "imports", "sceneType")
DEPRECATED_FIELDS = ("ownFormats", "meshVia", "imports")


def _image_of(value: str) -> str:
    """An image reference as a declaration wrote it, pinned to this release where it says so.

    `{version}` pins an image PartCAD publishes to this release without the
    number being written down twice. Through `image_tag()`, not the bare
    version: a CI run that rebuilt the images has to reach *those*. And through
    `image_name()` for the owner, which is the same redirection one segment to
    the left; it only ever rewrites images in PartCAD's own namespace, so a
    tool a user declared keeps the image it named.
    """
    return image_name(str(value).replace("{version}", image_tag(__version__)))


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
        values[field_name] = value

    # The container, the way a plugin's implementation declares one: a mapping
    # with an image, or the image alone. `image:` at the top is how an entry
    # said it before there was a `container:`.
    container = config.get("container")
    if isinstance(container, str):
        container = {"image": container}
    if isinstance(container, dict) and container.get("image"):
        values["image"] = _image_of(container["image"])
        if container.get("python"):
            values["container_python"] = str(container["python"])
    elif config.get("image"):
        values["image"] = _image_of(config["image"])

    if "formats" not in values:
        legacy = []
        used = []
        for key in LEGACY_FORMAT_FIELDS:
            value = config.get(key)
            if not value:
                continue
            used.append(key)
            legacy += list(value) if isinstance(value, (list, tuple)) else [value]
        if legacy:
            values["formats"] = tuple(dict.fromkeys(_format_name(v) for v in legacy))
            values["deprecated"] = tuple(key for key in used if key in DEPRECATED_FIELDS)
    return Tool(**values)


def tools_from_section(section: dict) -> Dict[str, Tool]:
    """Every entry of one `open:` section, as tools."""
    if not isinstance(section, dict):
        return {}
    return {name: tool_from_declaration(name, config) for name, config in section.items() if isinstance(config, dict)}


def _builtin_declarations() -> dict:
    """The `open:` section of the package that ships inside `partcad`.

    Read off disk rather than through a context, because `pc ide open` has none and
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
    running process, and `pc ide open` asks for it on a path where an editor's
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


# What `pc ide open` opens a file in when the user names no application. A string
# rather than a reference to one of the entries, because the entries are data
# now and this is the one of them PartCAD treats as special.
DEFAULT_TOOL = "freecad"

# The tools `pc ide open --with` accepts. Each is a declaration, not a branch
# anywhere below. Replaced wholesale by `use_tools()` when a caller has asked
# the daemon what the workspace's packages declare.
TOOLS: Dict[str, Tool] = merge_tools()


def use_tools(declared: Optional[dict]) -> None:
    """Add the applications a workspace's packages declare to this process.

    Called by `pc ide open` once, before it looks a tool up, with whatever the
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
    """What was opened, how, and what became of what was done in it."""

    tool: str
    # "native" or "docker": which of the two routes below actually ran.
    method: str
    path: str
    command: List[str]
    detail: str
    # The file the caller named, when the application was given another one --
    # the board beside a KiCad part's STEP, the copy converted out of a solid.
    source: Optional[str] = None
    # Whether the file the application was given is different now.
    changed: bool = False
    # Where the edit went, when it went where the object lives: the source
    # itself, edited in place or converted back into its own format.
    written_back: Optional[str] = None
    # Where the edit is, when it could not go there: a converted copy of an
    # object whose source is a script, an alias, an extrude -- nothing a STEP
    # could be written back into.
    edited: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "tool": self.tool,
            "method": self.method,
            "path": self.path,
            "source": self.source,
            "command": list(self.command),
            "detail": self.detail,
            "changed": self.changed,
            "writtenBack": self.written_back,
            "edited": self.edited,
        }


def _digest(path: str) -> Optional[str]:
    """What a file holds, as a digest -- None when it is not there."""
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def _tree_digest(directory: str) -> Optional[str]:
    """What a directory holds, as one digest: names and contents, nothing about times."""
    if not os.path.isdir(directory):
        return None
    digest = hashlib.sha256()
    for top, dirs, files in os.walk(directory):
        dirs[:] = sorted(d for d in dirs if d not in (".git", "__pycache__"))
        for name in sorted(files):
            path = os.path.join(top, name)
            digest.update(os.path.relpath(path, directory).encode("utf-8"))
            digest.update((_digest(path) or "").encode("utf-8"))
    return digest.hexdigest()


def open_file(
    path: str,
    tool: str = DEFAULT_TOOL,
    use_docker: bool = False,
    image: Optional[str] = None,
    log: Optional[Callable[[str], None]] = None,
    object_type: Optional[str] = None,
    transcode: Optional[Callable[..., None]] = None,
    mode: Optional[str] = None,
) -> OpenResult:
    """Open ``path`` in ``tool``, wait for it to close, and bring back what was done in it.

    ``use_docker`` is the caller's permission to fall back to a container, not a
    demand for one: a machine with the application installed uses it either way.

    ``object_type`` is the PartCAD type the object was declared with, when the
    caller knows it -- the VS Code tree does, and a file name does not always
    say (a '.py' is three different script types).

    ``transcode`` is how a file this application cannot open becomes one it can,
    and how an edit to that copy goes back into the object's own format. Called
    as ``transcode(source, source_type, target, target_type, kind)`` -- ``kind``
    is "part" or "scene" -- and expected to leave ``target`` on disk. It is CAD
    work, so it belongs to the daemon; a caller that passes none can still open
    anything the application reads as it is.

    ``mode`` is the transfer mode for a container (see
    `partcad_utils.containers`); the configuration's when it is None.
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
    kind = "scene" if spec.reads_scenes() else "part"
    target_type = None
    opened = resolved
    if not spec.opens(resolved, object_type):
        if kind == "scene":
            opened, target_type = _transcode_scene(spec, resolved, root, object_type, transcode, say)
        else:
            opened, target_type = _transcode(spec, resolved, root, object_type, transcode, say)

    # The whole directory where the application opens a project rather than a
    # file: KiCad saves the board beside the project it was handed.
    watched = os.path.dirname(opened) if spec.companions else None
    before = _tree_digest(watched) if watched else _digest(opened)

    native = native_command(spec)
    if native is not None:
        command = list(native) + list(spec.launch_args(native[-1])) + list(spec.file_arguments(opened))
        say("Opening %s in %s. Close %s to continue." % (opened, spec.display_name, spec.display_name))
        started = time.monotonic()
        _launch(command)
        elapsed = time.monotonic() - started
        method, detail = "native", "%s is installed on this machine." % spec.display_name
    else:
        if not use_docker:
            raise ExternalToolError(
                "%s was not found on this machine.\n"
                "Install it, or let PartCAD run it in a container: pass --use-docker to `pc ide open` "
                "(the 'partcad.open.useDocker' setting in the VS Code extension)." % spec.display_name
            )
        started = time.monotonic()
        command, detail = _open_in_container(spec, opened, root, image, say, mode)
        elapsed = time.monotonic() - started
        method = "docker"

    after = _tree_digest(watched) if watched else _digest(opened)
    result = OpenResult(
        tool=spec.name,
        method=method,
        path=opened,
        source=None if opened == named else named,
        command=command,
        detail=detail,
        changed=after != before,
    )
    if not result.changed:
        if method == "native" and elapsed < HANDOFF_SECONDS:
            result.detail += (
                "\n%s returned at once. If it handed the file to a copy of itself that was already "
                "running, close that copy too -- PartCAD cannot see edits made there." % spec.display_name
            )
        return result

    if target_type is None:
        # Opened as it is: the edit is already where the object lives.
        result.written_back = watched or opened
        return result
    _bring_back(spec, result, resolved, opened, target_type, object_type, kind, transcode, say)
    return result


def _bring_back(spec, result, source, edited, edited_type, object_type, kind, transcode, say) -> None:
    """Convert an edited copy back into the object's own format, over its source -- where there is one."""
    original_type = object_types.readable_type(source, object_type) if kind == "part" else None
    if kind != "part" or original_type not in object_types.WRITABLE_PART_TYPES or transcode is None:
        # A script, an alias, an extrude: nothing a converted file can be
        # written back into. The edit is kept where it was made and said so.
        result.edited = edited
        return
    say("Writing your changes back into %s..." % source)
    try:
        transcode(edited, edited_type, source, original_type, kind)
    except Exception as e:
        result.edited = edited
        result.detail += "\nYour changes are in %s; writing them back into %s failed: %s" % (edited, source, e)
        return
    result.written_back = source


# ---------------------------------------------------------------------------
# Making something the application can read out of what it cannot
# ---------------------------------------------------------------------------


def transcode_path(root: str, source: str, output_type: str) -> str:
    """Where the converted copy of ``source`` goes.

    Under the workspace's own directory on this machine -- the one that holds
    its daemon socket -- rather than beside the file, so nothing PartCAD
    generates turns up in `git status`, and so that it is inside what a
    container is given.

    The name carries a digest of the source path, so two parts called `cube` in
    different packages do not overwrite each other's copy, and is otherwise
    stable, so opening the same part twice reuses the same file.
    """
    digest = hashlib.sha256(os.path.realpath(source).encode("utf-8")).hexdigest()[:16]
    stem = os.path.splitext(os.path.basename(source))[0]
    return os.path.join(_state_dir(root), "open", "%s-%s.%s" % (stem, digest, output_type))


def _formats_named(spec: Tool) -> str:
    return ", ".join(f.upper() for f in spec.formats)


def _transcode(
    spec: Tool,
    source: str,
    root: str,
    object_type: Optional[str],
    transcode: Optional[Callable[..., None]],
    say: Callable[[str], None],
) -> Tuple[str, str]:
    """Convert ``source`` to the first format ``spec`` opens that PartCAD writes: (file, its type)."""
    source_type = object_types.readable_type(source, object_type)
    reason = object_types.PACKAGE_ONLY_TYPES.get((source_type or "").lower())
    if reason is not None:
        raise ExternalToolError(
            "%s cannot open %s: %s, so it only means anything inside a package and there is "
            "nothing here to convert.\n"
            "Export the object to a format %s opens first, and open that: pc export -t %s -O <file> <object>"
            % (spec.display_name, source, reason, spec.display_name, spec.conversion_target() or "<type>")
        )
    target = spec.conversion_target()
    if target is None:
        raise ExternalToolError(
            "%s opens %s, and %s is none of them -- nor anything PartCAD can convert into one of them."
            % (spec.display_name, _formats_named(spec), source)
        )
    if source_type is None:
        candidates = object_types.types_of_extension(os.path.splitext(source)[1])
        raise ExternalToolError(
            "%s opens %s, and PartCAD cannot tell from its name what %s holds%s.\n"
            "Say so with --type ('pc ide open --type ...'); the VS Code extension passes the "
            "declared type of the object you clicked."
            % (
                spec.display_name,
                _formats_named(spec),
                source,
                (" (it could be: %s)" % ", ".join(candidates)) if candidates else "",
            )
        )
    if transcode is None:
        raise ExternalToolError(
            "%s opens %s, and %s is not one. Converting it needs the PartCAD daemon; "
            "run `pc ide open` rather than calling this directly." % (spec.display_name, _formats_named(spec), source)
        )
    extension = object_types.PART_TYPE_EXTENSION.get(target, target)
    return _produce(spec, source, source_type, root, target, extension, "part", transcode, say), target


def _transcode_scene(
    spec: Tool,
    source: str,
    root: str,
    object_type: Optional[str],
    transcode: Optional[Callable[..., None]],
    say: Callable[[str], None],
) -> Tuple[str, str]:
    """Convert ``source`` into the scene description ``spec`` reads: (file, its type).

    The counterpart of `_transcode` for an application that reads an arrangement
    rather than geometry, and it refuses far more often, for a reason that is
    structural rather than incidental: the format such an application reads
    belongs to that application's engine, and PartCAD does not implement it.
    `mjcf` is `partcad/partcad-sim-mujoco`'s and `world` is
    `partcad/partcad-sim-gazebo`'s -- the same packages the `open:` entries for
    MuJoCo and Gazebo come from -- so writing one means running that package's
    exporter, which means a package that imports it. A file handed to `pc ide open`
    has no package around it at all.

    So this converts only between formats PartCAD itself has, refuses the rest
    with the export command that does work, and is in practice a refusal. What
    it must never do is hand the application a file it cannot read and let it
    say something of its own.
    """
    source_type = object_types.readable_scene_type(source, object_type)
    reason = object_types.PACKAGE_ONLY_TYPES.get(source_type or "")
    if reason is not None:
        raise ExternalToolError(
            "%s cannot open %s: %s, so it only means anything inside a package and there is "
            "nothing here to convert.\n"
            "Export the scene from its package instead, and open that: pc export -S -t %s -O <dir> <scene>"
            % (spec.display_name, source, reason, _export_target(spec.scene_type))
        )
    # The tool's own format, as PartCAD knows it. Absent for every engine format,
    # which is the ordinary case and the reason for the message below.
    extension = object_types.SCENE_TYPE_EXTENSION.get(spec.scene_type)
    if extension is None:
        raise ExternalToolError(
            "%s reads %s, and %s is not one.\n"
            "PartCAD cannot write %s here: the package that declares %s is what implements it, and a "
            "file opened on its own has no package to reach that from.\n"
            "Export the scene from a package that imports it, and open the result:\n"
            "  pc export -S -t %s -O <dir> <scene>\n"
            "If %s already is %s, say so with --type ('pc ide open --type <package>:%s ...'); the VS Code "
            "extension passes the declared type of the object you clicked."
            % (
                spec.display_name,
                spec.scene_type.upper(),
                source,
                spec.scene_type.upper(),
                spec.scene_type,
                _export_target(spec.scene_type),
                source,
                spec.scene_type.upper(),
                spec.scene_type,
            )
        )
    if source_type is None:
        raise ExternalToolError(
            "%s reads %s, and PartCAD cannot tell what %s holds -- it is not a scene file it knows "
            "(it reads: %s).\n"
            "If it is one, say so with --type ('pc ide open --type ...'); the VS Code extension passes the "
            "declared type of the object you clicked."
            % (
                spec.display_name,
                spec.scene_type.upper(),
                source,
                ", ".join(sorted(object_types.SCENE_TYPE_EXTENSION)),
            )
        )
    if transcode is None:
        raise ExternalToolError(
            "%s reads %s, and %s is not one. Converting it needs the PartCAD daemon; "
            "run `pc ide open` rather than calling this directly."
            % (spec.display_name, spec.scene_type.upper(), source)
        )

    return (
        _produce(spec, source, source_type, root, spec.scene_type, extension, "scene", transcode, say),
        spec.scene_type,
    )


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
                    # all, silently, from the second `pc ide open` onwards.
                    executable = os.path.join(bundle, spec.macos_executable)
                    if os.path.isfile(executable):
                        return [executable]
                    continue
                # Through `open`, not the executable inside the bundle: it is
                # how macOS launches an application. '-W' waits until it quits,
                # which is what lets an edit be brought back, and '-n' makes it
                # a copy of its own -- waiting on one that was already running
                # would wait for that, not for this file.
                return ["open", "-W", "-n", "-a", bundle]
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


def _docker_available() -> bool:
    """True when a container runtime answers -- and runs Linux containers, which every image here is."""
    try:
        import docker

        client = docker.from_env(timeout=DOCKER_TIMEOUT)
        client.ping()
        return str(client.info().get("OSType", "")).lower() in ("", "linux")
    except Exception:
        return False


def _host_user() -> Optional[str]:
    """This user, for a container on Linux: what it saves into the workspace stays this user's to edit."""
    if platform.system() == "Linux" and hasattr(os, "getuid"):
        return "%d:%d" % (os.getuid(), os.getgid())
    return None


def _home_volume(spec: Tool) -> str:
    """The volume an application's home directory is kept in, so its settings outlive its container."""
    return "partcad-open-%s-home" % "".join(c if c.isalnum() or c in "_.-" else "-" for c in spec.name)


def _shared_directories(root: str, path: str) -> List[str]:
    """What a container in 'mount' mode is given: the workspace, its state directory, and wherever the file is."""
    wanted = [root, _state_dir(root)]
    directory = os.path.dirname(path)
    if not any(_is_within(directory, d) for d in wanted):
        wanted.append(directory)
    kept = []
    for directory in sorted(dict.fromkeys(wanted), key=len):
        if not any(_is_within(directory, outer) for outer in kept):
            kept.append(directory)
    return kept


def _open_in_container(
    spec: Tool,
    path: str,
    root: str,
    image: Optional[str],
    say: Callable[[str], None],
    mode: Optional[str] = None,
) -> Tuple[List[str], str]:
    """Run ``spec`` on ``path`` in its container, until it is closed: (command, what to tell the user).

    ``root`` is the workspace to mount, worked out by the caller from the file
    it was asked about rather than from ``path``: the two differ when ``path``
    is a copy PartCAD converted, which lives under that workspace's state
    directory and is not in a workspace of its own.
    """
    if not _docker_available():
        raise ExternalToolError(
            "%s is not installed on this machine and Docker is not available to run it in a container.\n"
            "Install %s, or install Docker and make sure `docker info` succeeds."
            % (spec.display_name, spec.display_name)
        )

    # Worked out before anything is started: a container that cannot show a
    # window is not worth starting, and the message is the point of the check.
    env, local_binds, extra_hosts, advice = _x11_forwarding(spec)
    display = env["DISPLAY"]

    reference = image or spec.image
    if not reference:
        raise ExternalToolError(
            "%s is not installed here and declares no container image, so there is nothing to run it in.\n"
            "Install it, or name an image with --docker-image." % spec.display_name
        )

    mode = mode or containers.transfer_mode()
    if mode == containers.UPLOAD and spec.embeds_path():
        raise ExternalToolError(
            "%s's declaration names the file inside another argument ('{path_repr}'), and with "
            "'useDockerRemote' the file is sent to the container rather than shared with it -- so that "
            "name would be one the container does not have. Its 'fileArgs' have to name the file as an "
            "argument of its own ('{path}')." % spec.display_name
        )
    mounts = {}
    user = None
    if mode == containers.MOUNT:
        # The workspace's state directory, made now if it is not there yet: it
        # holds the daemon's socket, so that a PartCAD inside the container talks
        # to this workspace's daemon -- and the mounts are fixed when the
        # container is created, which may be long before that daemon starts.
        with contextlib.suppress(OSError):
            os.makedirs(_state_dir(root), exist_ok=True)
        # The state directory is there for the daemon's socket, which a PartCAD
        # inside the application could use and nothing needs -- unless the file
        # opened is a converted copy, which lives in it.
        state = _state_dir(root)
        optional = () if _is_within(path, state) else (state,)
        mounts, local_binds = _binds(spec, reference, _shared_directories(root, path), local_binds, optional)
        user = _host_user()

    endpoint_spec = containers.ContainerSpec(
        role=spec.role,
        image=reference,
        mode=mode,
        mounts=mounts,
        volumes={_home_volume(spec): {"bind": CONTAINER_HOME, "mode": "rw"}},
        environment={"HOME": CONTAINER_HOME},
        allowed_commands={binary: None for binary in spec.binaries},
        user=user,
        service_python=spec.container_python,
        local_binds=local_binds,
        extra_hosts=extra_hosts,
    )
    say("Starting the container for %s (%s)..." % (spec.display_name, reference))
    try:
        endpoint = containers.acquire(endpoint_spec)
    except containers.ContainerUnavailable as e:
        raise ExternalToolError(str(e))

    binary = _container_binary(spec, endpoint, reference)
    command = [binary, *spec.launch_args(binary), *spec.file_arguments(path)]
    transfers = {}
    if mode == containers.UPLOAD:
        # The file goes with the command and comes back when the application
        # closes. A project application saves beside what it opened, so its
        # whole directory travels both ways.
        if spec.companions:
            directory = os.path.dirname(path)
            transfers = {"input_dirs": [directory], "output_dirs": [directory]}
        else:
            transfers = {"input_files": [path], "output_files": [path]}

    say(
        "Opening %s in %s (container '%s', DISPLAY=%s). Close %s to continue."
        % (path, spec.display_name, endpoint.name, display, spec.display_name)
    )
    # The display travels with the command rather than being fixed when the
    # container was made: the container outlives the session, and the display
    # the user is on now is the one the window has to come out on.
    code, _stdout, stderr = endpoint.run(command, cwd=os.path.dirname(path), env=env, timeout=None, **transfers)
    if code != 0 and ("refused the command" in stderr or "returned no response" in stderr):
        raise ExternalToolError(
            "Failed to run %s in the '%s' container: %s" % (spec.display_name, endpoint.name, stderr)
        )

    detail = "%s ran in the '%s' container, displaying on %s." % (spec.display_name, endpoint.name, display)
    if advice:
        detail += "\n" + advice
    return command, detail


def _mount_sources(reference: str, python: str):
    """Where the Docker daemon has this machine's directories: None, (here, there) pairs, or False.

    See `partcad_utils.daemon_mounts.mount_sources`, which this asks with the
    application's own image -- the one image certain to be here, since it is
    about to be run. Kept to one function so that what it answers is what a
    test replaces.
    """
    import docker

    from partcad_utils import daemon_mounts

    client = docker.from_env()
    try:
        resolved, _ = containers.resolve_image(client, reference)
    except containers.ContainerUnavailable as e:
        raise ExternalToolError(str(e))
    return daemon_mounts.mount_sources(client, resolved, python)


def _binds(spec: Tool, reference: str, wanted: List[str], local_binds: dict, optional=()) -> Tuple[dict, dict]:
    """The binds for ``wanted`` and for the display, as the daemon can make them: (mounts, local binds).

    On an ordinary host every path is bound as it is. In a dev container holding
    the host's Docker socket -- this repository's own -- the daemon resolves a
    bind against the *host's* filesystem, where this container's workspace and
    temporary directory are somewhere else entirely; binding them as they are
    gave the application an empty directory of the same name, owned by root,
    and the file it was told to open was not there. So each is bound from where
    the daemon keeps it, at the path it has here -- the sandbox's rule, from the
    same code (`partcad_utils.daemon_mounts`). The display's socket and cookie
    are translated the same way when this container has them from the host, and
    left as they are when it does not, since then they are the host's own.

    A directory in ``optional`` that the daemon does not have is left out
    rather than refused.
    """
    from partcad_utils import daemon_mounts, docker_mount

    sources = _mount_sources(reference, spec.container_python or "python3")
    if sources is None:
        return {d: {"bind": d, "mode": "rw"} for d in wanted}, local_binds
    if sources is False:
        raise ExternalToolError(
            "The Docker daemon cannot see this machine's files, so %s's container cannot be given %s by "
            "mounting it -- which is what a Docker daemon on another machine, or behind DOCKER_HOST, looks "
            "like. Set 'useDockerRemote: true' (PC_USE_DOCKER_REMOTE=true) so that PartCAD sends the file "
            "to the container and brings it back instead." % (spec.display_name, ", ".join(wanted))
        )
    missing = daemon_mounts.unbacked(wanted, sources)
    wanted = [d for d in wanted if d not in missing or not any(_is_within(d, o) for o in optional)]
    missing = [d for d in missing if d in wanted]
    if missing:
        raise ExternalToolError(
            "The Docker daemon here does not share this filesystem, and binds from where it keeps this "
            "container's mounts -- but %s %s on none of them. Mount %s into this container, name where the "
            "daemon has %s in PC_DOCKER_MOUNT_SOURCES (here=there;...), or set 'useDockerRemote: true' so "
            "that PartCAD sends the file instead."
            % (
                ", ".join(missing),
                "is" if len(missing) == 1 else "are",
                "it" if len(missing) == 1 else "them",
                "it" if len(missing) == 1 else "them",
            )
        )
    translated = {docker_mount.backed_by(source, sources) or source: bind for source, bind in local_binds.items()}
    return docker_mount.mounts(wanted, sources=sources), translated


def _container_binary(spec: Tool, endpoint, image: str) -> str:
    """Which of the application's names its container has, or an error naming why not.

    Asked of the service in the container rather than with `docker exec`: on a
    daemon somewhere else there is nothing to exec through but the service.
    """
    found = endpoint.which(spec.binaries)
    for binary in spec.binaries:
        if found.get(binary):
            return binary
    raise ExternalToolError(
        "The container for %s, from %s, has no %s executable on its PATH (looked for: %s).\n"
        "Name an image that has one with --docker-image."
        % (spec.display_name, image, spec.display_name, ", ".join(spec.binaries))
    )


def _state_dir(root: str) -> str:
    """The workspace's own directory on this machine, holding its daemon socket.

    Derived from `socket_path` rather than named again, because this is the
    directory `_open_in_container` mounts: a converted mesh is written into it
    (see `transcode_path`) precisely so that it arrives inside the container,
    and two ways of spelling one directory is how that would quietly stop being
    true.
    """
    return os.path.dirname(socket_path(root))


def _workspace_for(path: str) -> str:
    """The workspace to mount into the container so that ``path`` is inside it.

    The one this command runs in, when it holds the file: that is the workspace
    whose daemon socket is worth mounting beside it, and the one the caller
    means -- an editor runs `pc ide open` in the window's workspace folder. A file
    somewhere else gets its own workspace mounted instead, which still contains
    it; there is simply no daemon of this workspace's to offer it.
    """
    root = determine_root_path()
    # Only where there is a workspace: with no 'partcad.yaml' the root found is
    # just where the command was run, and run from '/' or '~' that bound the
    # whole filesystem, or the whole home directory, into the application's
    # container to open one file.
    if _is_within(path, root) and os.path.isfile(os.path.join(root, "partcad.yaml")):
        return root
    return determine_root_path(os.path.dirname(path))


# ---------------------------------------------------------------------------
# Getting the window onto the user's screen
# ---------------------------------------------------------------------------

_LINUX_NO_DISPLAY = (
    "There is no X display to show {name} on (DISPLAY is not set).\n"
    "Run `pc ide open` from a graphical session, or set DISPLAY to the X server to use.\n"
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


def _x11_forwarding(spec: Tool) -> Tuple[Dict[str, str], Dict[str, Dict[str, str]], Dict[str, str], str]:
    """How the container reaches the user's screen: (environment, binds, extra hosts, advice).

    The binds are the X server's socket and cookie: this machine's plumbing
    rather than its files, so they are given in either transfer mode -- and
    dropped by `containers.acquire` when the daemon is another machine.

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
        return {"DISPLAY": _host_display(display)}, {}, {}, _MACOS_ADVICE

    if system == "Windows":  # pragma: no cover - exercised only on Windows
        if not display:
            raise ExternalToolError(_WINDOWS_NO_DISPLAY.format(name=spec.display_name))
        return {"DISPLAY": _host_display(display)}, {}, {}, _WINDOWS_ADVICE

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
            {},
            {"host.docker.internal": "host-gateway"},
            _LINUX_TCP_ADVICE,
        )

    env = {"DISPLAY": display}
    binds = {}
    if os.path.isdir("/tmp/.X11-unix"):
        # The display is a socket on this machine, so it can simply be shared --
        # no TCP, no listening X server, nothing for the user to configure.
        binds["/tmp/.X11-unix"] = {"bind": "/tmp/.X11-unix", "mode": "rw"}
    xauthority = os.environ.get("XAUTHORITY")
    if xauthority and os.path.isfile(xauthority):
        # Both the file and the variable naming it: an X client that cannot find
        # the cookie is refused by the server, and the container's idea of a home
        # directory is not the user's.
        binds[xauthority] = {"bind": xauthority, "mode": "ro"}
        env["XAUTHORITY"] = xauthority
    return env, binds, {}, _LINUX_ADVICE


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


def _launch(args: List[str]) -> int:
    """Run a GUI application here and wait for it to close; its exit code.

    In a session of its own, so that it is not this process's to take down:
    stopping `pc ide open` -- Ctrl-C at a terminal, Cancel in an editor -- stops the
    waiting, and must never close somebody's application on unsaved work.
    """
    kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":  # pragma: no cover - exercised only on Windows
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    try:
        process = subprocess.Popen(args, **kwargs)
    except OSError as e:
        raise ExternalToolError("Failed to run %s: %s" % (" ".join(args), e))
    try:
        return process.wait()
    except KeyboardInterrupt:
        raise ExternalToolError(
            "Stopped waiting. The application is still open; what is done in it from now on will not be "
            "brought back into the package."
        )
