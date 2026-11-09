#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The throwaway package an ad-hoc command works inside.

`pc adhoc convert` and `pc adhoc render` both operate on a file that belongs to
no package: PartCAD writes a `partcad.yaml` in a temporary directory declaring
that one file as its only object, builds a context around it, produces one
output file, and deletes the directory again.

Everything specific to a verb lives in `convert.py` and `render.py`; what is
here is the part they share, so that a change to how the throwaway package is
built cannot mean one thing for a conversion and another for a projection.
"""

import asyncio
import json
import re
import shutil
import stat
import tempfile
from pathlib import Path

from .. import consts
from .. import logging as pc_logging
from .. import output
from ..context import Context


class AdhocUsageError(ValueError):
    """A request an ad-hoc command cannot carry out as asked: nothing was attempted.

    Raised past the "Failed to ..." wrapping below, so that it reaches the
    caller as the usage error it is rather than as a failed render.
    """


# What a shape of each kind is called inside the throwaway package, and which
# section of its 'partcad.yaml' declares it. The names are not arbitrary: they
# are what the object is called, so they reach the user in an error message and
# in whatever an implementation writes an object's name into (a drawing's title
# block). A file nobody named is named after the input instead (see
# 'default_output_name').
KINDS = {
    "part": ("parts", "input_part"),
    "sketch": ("sketches", "input_sketch"),
    # A scene is the third thing a file can hold: an arrangement of objects
    # rather than one shape. Only a self-contained scene format could reach here
    # -- one that names its meshes by path, so that a throwaway package around it
    # is enough -- and PartCAD implements none: an '.assy' names the parts of a
    # package and is refused below, and an engine's own format is implemented by
    # that engine's plugin package, which a throwaway package cannot reach.
    "scene": ("scenes", "input_scene"),
}

# How the object of each kind is fetched out of the throwaway package.
GETTERS = {
    "part": "get_part",
    "sketch": "get_sketch",
    "scene": "get_scene",
}


# A value written on the command line is declared with the type it is written
# in, the way YAML would read it, since nothing else says what it is: 'true' and
# 'false' are flags, '10' a whole number, '2.5' and '1e3' numbers, and anything
# else text.
_WHOLE = re.compile(r"[-+]?\d+\Z")
_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?\Z")


def declare_parameter(text) -> dict:
    """The declaration of a parameter the value 'text' is all anyone said about: its type, and it as the default.

    A list -- which a client sending a mapping rather than '<name>=<value>' text
    can send -- is an array of what it holds.
    """
    if isinstance(text, (list, tuple)):
        return {"type": "array", "default": [declare_parameter(item)["default"] for item in text]}
    value = str(text)
    bare = value.strip()
    if bare.lower() in ("true", "false"):
        return {"type": "bool", "default": bare.lower() == "true"}
    if _WHOLE.match(bare):
        return {"type": "int", "default": int(bare)}
    if _NUMBER.match(bare):
        return {"type": "float", "default": float(bare)}
    return {"type": "string", "default": value}


# The package the public index is imported as: the same declaration 'pc init'
# writes into a new package (see 'template/init-public.yaml'), so that an
# ad-hoc render reads the index the way a package does -- including its
# 'devel' from a checkout of PartCAD, which the git importer decides by this
# URL (see 'consts.DEVEL_INDEX_REPO_PATHS').
PUBLIC_INDEX = "pub"
PUBLIC_INDEX_DEPENDENCY = {
    "type": "git",
    "url": "https://github.com/%s.git" % consts.DEVEL_INDEX_REPO_PATHS[0],
    "track": "main",
}

# The name a package directory named with '-e' is imported under.
OPTIONS_DEPENDENCY = "options"

# What every refusal of an '-e' ends with: the two things that can be named.
_NAME_ONE = "name a package in the public index ('//pub/...') or the directory of a package"


def _is(path: Path, kind) -> bool:
    """Whether 'path' is there and is of 'kind' ('stat.S_ISDIR', 'stat.S_ISREG'); any other answer is raised.

    'Path.stat' and not 'Path.is_dir' or 'Path.is_file', because only the first
    says the same thing on every Python this runs on: from 3.14 those two answer
    False for any error at all, so a directory the user may not read, or a share
    that dropped the connection, would read as "there is nothing there" and be
    refused without its reason - which up to 3.13 they raise. Asked this way,
    nothing being there is the one answer that is not an error, on every
    version: 'FileNotFoundError' (a missing host or share on Windows included,
    which Python maps to it) or 'NotADirectoryError' (a file where a directory
    on the way should be).
    """
    try:
        found = path.stat()
    except (FileNotFoundError, NotADirectoryError):
        return False
    return kind(found.st_mode)


def options_dependency(options_package):
    """What the throwaway package imports to read file types from 'options_package', and its name there.

    Returns ((dependency name, declaration), package name), or (None, None) for
    no package. A package in the public index is imported through the index; a
    directory on this machine that holds a 'partcad.yaml' is imported as it is.
    Anything else names nothing an ad-hoc render can reach -- there is no
    workspace around it whose packages a name could mean.

    Which of the two 'options_package' is, is decided by how it is spelled and
    by nothing else: a name starting with '//' is a package, as everywhere in
    PartCAD (and as the CLI already sends it: as written, where a directory is
    sent absolute), and it is never looked for on disk. The same text is a path
    too, on every system, and looking for it is not a question about packages:
    POSIX leaves a leading '//' to the implementation, and Linux and macOS read
    '//srv/pkg' as the directory '/srv/pkg'; on Windows '//elsewhere/render' is
    the share 'render' of a server called 'elsewhere', so looking is a trip to
    the network -- which can take an SMB timeout, can fail with an error nobody
    asked about (WinError 64 has), or can find a share by that name and import
    whatever is in it. So a package outside the public index is refused, here,
    without any of that.

    A directory is named by its path, then, and a network share on Windows with
    the backslashes Windows writes it with ('\\\\server\\share\\pkg', which is
    also what 'os.path.abspath' makes of a relative path in a working directory
    on a share). The forward-slash spelling of the same share is a package
    name. A directory that cannot be looked at -- one the user may not read, a
    share that drops the connection -- is refused for that reason, which is
    given, rather than failing the render with a traceback.
    """
    if not options_package:
        return None, None
    if options_package.startswith(consts.ROOT):
        if options_package == "//" + PUBLIC_INDEX or options_package.startswith("//%s/" % PUBLIC_INDEX):
            return (PUBLIC_INDEX, PUBLIC_INDEX_DEPENDENCY), options_package
        raise AdhocUsageError(
            "Cannot read file types from '%s' ad-hoc: a name starting with '//' is a package, and an ad-hoc render "
            "has no workspace around it to find one outside the public index in; %s, by its path without the '//' "
            "(a network share on Windows as '\\\\server\\share\\...')" % (options_package, _NAME_ONE)
        )
    directory = Path(options_package)
    try:
        found = _is(directory, stat.S_ISDIR) and _is(directory / consts.DEFAULT_PACKAGE_CONFIG, stat.S_ISREG)
        resolved = str(directory.resolve()) if found else None
    except (OSError, RuntimeError) as e:
        # 'RuntimeError' is how 'Path.resolve' says "symlink loop" up to Python
        # 3.12. A loop there would have stopped 'stat' first, unless one was
        # made between the two -- which is still no reason for a traceback.
        raise AdhocUsageError(
            "Cannot read file types from '%s' ad-hoc: it could not be looked at (%s); %s"
            % (options_package, e, _NAME_ONE)
        ) from e
    if found:
        return (OPTIONS_DEPENDENCY, {"type": "local", "path": resolved}), "//" + OPTIONS_DEPENDENCY
    raise AdhocUsageError("Cannot read file types from '%s' ad-hoc: %s" % (options_package, _NAME_ONE))


def generate_partcad_config(
    temp_dir: Path,
    input_type: str,
    temp_input_path: Path,
    kind: str = "part",
    parameters: dict = None,
    dependencies: dict = None,
) -> None:
    """
    Generate a temporary partcad.yaml configuration for processing.

    Args:
        temp_dir (Path): Temporary directory path.
        input_type (str): Input file format type.
        temp_input_path (Path): Path to the copied input file.
        kind (str): "part", "sketch" or "scene" (default is "part")
        parameters (dict): Parameter values of the input, by name, each
            declared with the type it is written in (see 'declare_parameter').
        dependencies (dict): Packages to import, by name: what '-e' reads its
            file type from.
    """
    section, name = KINDS[kind]

    # Doubling is how an apostrophe is escaped inside a YAML single-quoted
    # scalar. The path is the user's own -- '/home/me/part's.step' is a valid
    # file name -- and without this it closes the scalar early and the
    # throwaway package fails to parse before the input is ever read.
    quoted_path = str(temp_input_path).replace("'", "''")

    lines = []
    if dependencies:
        # JSON is YAML, and it quotes what it holds: a path or a URL is written
        # the way it is, whatever it has in it.
        lines.append("dependencies:")
        lines.extend("  %s: %s" % (key, json.dumps(value)) for key, value in dependencies.items())
    lines.extend(["%s:" % section, "  %s:" % name, "    type: %s" % input_type, "    path: '%s'" % quoted_path])
    if parameters:
        lines.append("    parameters:")
        lines.extend(
            "      %s: %s" % (json.dumps(key), json.dumps(declare_parameter(value)))
            for key, value in parameters.items()
        )
    config_path = temp_dir / "partcad.yaml"
    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# Formats that describe an assembly rather than a single shape. An ad-hoc
# operation is a file-in, file-out one with a throwaway package around it; these
# need a real one. A URDF resolves its meshes against the package that holds them
# and produces a part per link, and an ASSY is nothing but references to parts of
# a package - neither means anything on its own.
PACKAGE_ONLY_TYPES = {
    "urdf": "a URDF names the meshes of its links and becomes a part per link",
    "assy": "an ASSY file is a set of references to the parts of a package",
}


def reject_package_only(input_type: str, output_type: str = None, verb: str = "convert", advice: str = None) -> None:
    """Refuse the formats that only mean something inside a package.

    'verb' and 'advice' are what the caller is doing and what it should do
    instead; the rest of the message is the same either way, because the reason
    is the same either way.
    """
    if advice is None:
        advice = "Use 'pc convert assembly' in a package instead."
    for role, part_type in (("from", input_type), ("to", output_type)):
        reason = PACKAGE_ONLY_TYPES.get((part_type or "").lower())
        if reason is not None:
            raise ValueError(
                "Cannot %s %s '%s' ad-hoc: %s, so it only means anything inside a package. %s"
                % (verb, role, part_type, reason, advice)
            )


def default_output_name(input_path, parameters: dict = None, extension: str = "") -> str:
    """The file an ad-hoc output is written to when none is named: the input's, with its values and new extension.

    The values go into the name the way 'pc render' writes them into an
    object's ('bracket_depth_10.svg', see 'output.values_in_file_name'), so
    that renders of several values of one script sit side by side.
    """
    return Path(input_path).stem + output.values_in_file_name(parameters) + extension


def deliver(staging: Path, destination: Path, object_name: str, input_path, parameters: dict = None):
    """Move what an output wrote into 'staging' to 'destination', and return the path of the file it was for.

    That file is the one named after the object at the top of 'staging' -- which
    is what an implementation writes when it is handed a directory -- and it is
    renamed after the input (see 'default_output_name'). Anything written beside
    it -- the meshes a URDF refers to, the pictures a document shows -- moves
    too, under the name and the relative path it was written with, since that
    is what the file refers to it by. Returns None when nothing was written.
    """
    written = sorted(path for path in staging.rglob("*") if path.is_file())
    if not written:
        return None
    named = [path for path in written if path.parent == staging and path.name.startswith(object_name + ".")]
    primary = max(named or written, key=lambda path: path.stat().st_mtime)
    if primary.name.startswith(object_name + "."):
        extension = primary.name[len(object_name) :]
    else:
        extension = primary.suffix
    target = destination / default_output_name(input_path, parameters, extension)
    for path in written:
        moved = target if path == primary else destination / path.relative_to(staging)
        moved.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(moved))
    return str(target)


def write_output_file(
    input_filename: str,
    input_type: str,
    output_filename: str,
    output_type: str,
    kind: str = "part",
    verb: str = "Convert",
    parameters: dict = None,
    options_package: str = None,
    output_dir: str = None,
    **options,
) -> str:
    """Produce one output file from a CAD file that belongs to no package.

    Args:
        input_filename: Path to the input file.
        input_type: Format of the input file.
        output_filename: Path to write, or None to write it into 'output_dir'
            (the input's directory by default) under 'default_output_name'.
        output_type: The file type to write - a part or sketch format for a
            conversion, a 2D projection for a render.
        kind: "part", "sketch" or "scene", which decides how the input is
            declared and which section of the throwaway package declares it.
        verb: What is being done, for the progress label and the error message.
        parameters: Parameter values of the input, by name (see
            'generate_partcad_config').
        options_package: A package to read the file type from: one in the
            public index, or a package directory (see 'options_dependency').
        output_dir: Where the file goes when 'output_filename' is None.
        options: Export parameters handed to the implementation, overriding what
            it would otherwise default to. This is where a render's viewport
            arrives, and its 'reproducible'; a conversion passes none.

    Returns:
        The path written.

    Raises:
        AdhocUsageError: the request names something an ad-hoc command cannot
            reach, or a file type nothing it can reach writes.
        RuntimeError: the input could not be loaded, or the output not written.
            The cause is in the message and not only in '__cause__', because
            this is what the CLI prints.
    """
    _, object_name = KINDS[kind]
    input_path = Path(input_filename).resolve()
    dependency, options_name = options_dependency(options_package)
    if output_filename is None:
        destination = Path(output_dir).resolve() if output_dir else input_path.parent
    else:
        destination = Path(output_filename).resolve().parent

    # An ordinary temporary directory. It is the context root, so a container
    # sandbox has to mount it -- and it does: the temporary directory is one of
    # the fixed mounts, precisely so that nothing here has to be careful about
    # where it puts things.
    temp_dir = Path(tempfile.mkdtemp())

    try:
        generate_partcad_config(
            temp_dir,
            input_type,
            input_path,
            kind=kind,
            parameters=parameters,
            dependencies=dict([dependency]) if dependency else None,
        )

        ctx = Context(root_path=temp_dir, search_root=False)
        # The generated package points at the user's file wherever it is, so
        # neither the input nor the output is under the context root. A sandbox
        # that runs on the host does not care; one that runs in a container sees
        # only what is mounted, and without this it reports that it cannot read
        # a file the user can see perfectly well.
        #
        # The directories rather than the files: an OpenSCAD or a CadQuery input
        # may include a sibling, and the output's directory has to be writable
        # for the export to land in it.
        #
        # Both, and both writable. Mounting the input read-only was tried and
        # taken back out: it is one more way two containers of one image can
        # differ, on a mount contract that is a stopgap rather than the
        # isolation boundary -- the container is that. Either directory is
        # usually under the home directory anyway, in which case naming it costs
        # no mount at all.
        ctx.sandbox_paths = [
            str(destination),
            str(input_path.parent),
        ]
        # A package directory named with '-e' is read the same way: its
        # implementation script runs in the sandbox, wherever the user keeps it.
        if dependency is not None and dependency[1].get("type") == "local":
            ctx.sandbox_paths.append(dependency[1]["path"])
        with pc_logging.Process(verb, "adhoc" if kind == "part" else "adhoc-" + kind):
            project = ctx.get_project("//")
            # Before the input is built, which can take minutes: whether the file
            # type can be written at all needs nothing but the packages.
            options_project = None
            if options_name is not None:
                options_project = ctx.get_project(options_name)
                if options_project is None:
                    raise AdhocUsageError("The package %s could not be read" % options_package)
                declared = set()
                for section in output.SECTIONS:
                    declared.update(output.format_names(options_project.config_obj.get(section)))
                if output_type not in declared and output_type not in output.all_formats(ctx):
                    # What is wrong first, and the path after it: an error box
                    # wraps a long line, and the path is as long as it is.
                    raise AdhocUsageError(
                        "No '%s' file type is declared by %s. It declares: %s"
                        % (output_type, options_package, ", ".join(sorted(declared)) or "none")
                    )

            # Looked up by name and fetched one at a time: a dictionary of bound
            # methods would reach for all three, and a caller with a project that
            # only answers the kind it is being asked about - which is every test
            # that stubs one - would fail on the two it is not.
            obj = getattr(project, GETTERS[kind])(object_name)
            if not obj:
                raise RuntimeError(f"Failed to load the input {kind}: no {kind} returned")

            shape = asyncio.run(obj.get_wrapped(ctx))
            # Errors first: when the factory failed - a missing module, a
            # sandbox that would not install - that is the reason there is no
            # shape, and it is the one worth reporting. "No shape returned" is
            # what is left to say when nothing was recorded.
            if obj.errors:
                raise RuntimeError(f"Failed to load the input {kind}: {obj.errors}")
            if not shape:
                raise RuntimeError(f"Failed to load the input {kind}: no shape returned")

            if kind == "part":
                pc_logging.info(f"Loaded input part: {input_path}")
                pc_logging.info(f"Shape: {type(shape)}")
            else:
                pc_logging.debug(f"Loaded input {kind}: {input_path}")

            # Without a file name the implementation names the file, in a
            # directory of its own inside the throwaway package, and it is moved
            # to where it belongs under the input's name -- which is how a file
            # type whose extension only its own declaration knows still lands
            # under 'default_output_name'.
            staging = temp_dir / "output" if output_filename is None else None
            if staging is not None:
                staging.mkdir()
            obj.render(
                ctx=ctx,
                format_name=output_type,
                project=project,
                filepath=output_filename,
                output_dir=str(staging) if staging is not None else None,
                options_package=options_name,
                options_project=options_project,
                **options,
            )
            if staging is None:
                return str(Path(output_filename))
            delivered = deliver(staging, destination, object_name, input_path, parameters)
            if delivered is None:
                raise RuntimeError("no %s file was written; the log says why" % output_type)
            return delivered

    except AdhocUsageError:
        raise
    except Exception as e:
        subject = "" if kind == "part" else " " + kind
        raise RuntimeError(f"Failed to {verb.lower()}{subject}: {e}") from e
    finally:
        shutil.rmtree(temp_dir)
