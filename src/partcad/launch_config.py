#
# PartCAD, 2026
#
# Author: PartCAD (support@partcad.org)
# Created: 2026-08-19
#
# Licensed under Apache License, Version 2.0.
#

"""
The "Render" command PartCAD puts in an editor's "Run and Debug" view.

`pc init` creates a package; this puts a button next to it. Visual Studio Code,
VSCodium and the PartCAD IDE all list the entries of `.vscode/launch.json` in
"Run and Debug", so that file, in the repository holding the new package, is
where a command a user is meant to press a button for has to be.

The file belongs to the user, not to PartCAD: it may already exist, hold other
commands, and be full of comments explaining them. So the command is inserted
into the text rather than the file being rewritten from a parsed copy, which
would drop every comment in it. Which is why finding the one array to add to is
most of the work here: `"configurations"` also appears inside every compound
launch, and inside any commented-out block that mentions one. PartCAD's own
`launch.json` has both, and each of them was picked over the real array before
this file learned to tell them apart.
"""

import json
import os
import re
from typing import Any, Optional

from partcad_utils import jsonc
from partcad_utils.jsonc import blank_json_comments
from partcad_utils.workspace import determine_root_path

from . import logging as pc_logging

CONFIGURATION_NAME = "Render"

# What it runs, in the package's directory.
RENDER_COMMAND = "pc render"

# The folder holding the `launch.json`, as the editor spells it.
WORKSPACE_FOLDER = "${workspaceFolder}"

# `node-terminal` is the one launch type in a stock Visual Studio Code that runs
# a command rather than a program under a debugger: it comes from the JavaScript
# debugger, which is built in everywhere, and it opens a terminal and runs
# `command` in it. Nothing about it is specific to JavaScript, and it is what
# makes this work with no extension installed at all -- including in an editor
# where PartCAD is a set of command line tools and nothing more.
CONFIGURATION_TYPE = "node-terminal"

LAUNCH_FILE = os.path.join(".vscode", "launch.json")

# The `launch.json` version, not PartCAD's: the schema of the file.
LAUNCH_VERSION = "0.2.0"


def parse_launch_configuration(text: str) -> Any:
    """Parse the contents of a `launch.json`: JSON with comments and trailing commas."""
    return jsonc.loads(text)


def find_repository_root(path: str) -> Optional[str]:
    """The root of the git repository holding `path`, or None if there is none.

    `.git` is looked for as a name rather than as a directory: in a worktree and
    in a submodule it is a file pointing elsewhere, and those are repositories
    too.
    """
    current = os.path.abspath(path)
    while True:
        if os.path.exists(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def editor_folder(path: str) -> str:
    """The folder an editor is expected to open for the package at `path`.

    Three directories are involved in what `pc init` writes for an editor, and
    they need not be one: the folder the editor or agent opens (what
    `${workspaceFolder}` is, and where its files are read from), the root of the
    git repository, and the PartCAD root the package belongs to (see
    `partcad_utils.workspace.determine_root_path`). Only the first is where the
    files go, and it cannot be known here -- an editor can open the repository, a
    folder of repositories above it, or a folder inside it -- so this is the
    default for it, and `pc init --editor-folder` says otherwise.

    The default is the repository's root, which is what an editor is usually
    opened on; outside a repository, the PartCAD root, which is the top of what
    the package belongs to. Never the package's own directory when that is below
    its root: a subpackage is not something an editor is opened on.
    """
    return find_repository_root(path) or determine_root_path(path)


# For `add_render_configuration`, whose argument of the same name is the folder
# itself.
editor_folder_of = editor_folder


def _is_inside(path: str, folder: str) -> bool:
    try:
        return os.path.commonpath([os.path.abspath(path), os.path.abspath(folder)]) == os.path.abspath(folder)
    except ValueError:  # on two Windows drives
        return False


def _spelled_like(package_dir: str, folder: str) -> Optional[str]:
    """`folder`, spelled through the same symbolic links as `package_dir`, if the package is inside it at all.

    The editor names the folder it has open the way it was opened, and a
    process's working directory is the resolved one: on macOS `/tmp` is
    `/private/tmp`, and a folder opened through a link to another disk is that
    disk. Both name one directory, but every path written for the editor is
    `package_dir` relative to the folder, which only comes out right when the
    two are spelled alike -- so this returns the ancestor of `package_dir` that
    *is* `folder`, rather than `folder` as it was given.
    """
    real_package, real_folder = os.path.realpath(package_dir), os.path.realpath(folder)
    if not _is_inside(real_package, real_folder):
        return None
    candidate = os.path.abspath(package_dir)
    relative = os.path.relpath(real_package, real_folder)
    if relative != os.curdir:
        for _ in relative.split(os.sep):
            candidate = os.path.dirname(candidate)
    try:
        return candidate if os.path.samefile(candidate, folder) else None
    except OSError:
        return None


def choose_editor_folder(package_dir: str, explicit: Optional[str] = None, advertised: Optional[str] = None) -> str:
    """The folder `pc init` writes the editor's files into, for the package in `package_dir`.

    In order:

    * `explicit`, `pc init --editor-folder`: a person said so;
    * `advertised`, the folder the editor has open, as the PartCAD extension
      tells the terminals of each workspace folder and the `pc init` its "Init
      package" runs (`PARTCAD_WORKSPACE_FOLDER`, see
      `partcad_utils.agent_config.WORKSPACE_FOLDER_ENV`) -- but only when the
      package is inside it. A terminal keeps the folder it was opened in, wherever it `cd`s
      to afterwards, and files written into a folder that does not hold the
      package would name it with a path climbing out of the editor's workspace;
    * `editor_folder`, the git repository's root, or the PartCAD root outside one.

    Read by the caller, never here: the daemon is shared by every client of a
    workspace, and an environment it inherited from whoever started it says
    nothing about the editor asking now.
    """
    if explicit:
        return os.path.abspath(explicit)
    if advertised:
        if os.path.isdir(advertised):
            if _is_inside(package_dir, advertised):
                return os.path.abspath(advertised)
            same = _spelled_like(package_dir, advertised)
            if same:
                return same
        pc_logging.info(
            "Not writing the editor's files into '%s', the folder the editor has open: '%s' is not inside it"
            % (advertised, os.path.abspath(package_dir))
        )
    return editor_folder(package_dir)


def relative_to(path: str, folder: str) -> str:
    """`path` relative to `folder`, with `/` separators, or "." for the folder itself.

    What goes after `${workspaceFolder}` in a file an editor reads on every
    machine that checks it out, so never an absolute path. Raises ValueError
    where there is none: on Windows, for two different drives.
    """
    relative = os.path.relpath(os.path.abspath(path), os.path.abspath(folder))
    return "." if relative in (os.curdir, "") else relative.replace(os.sep, "/")


def _indent_unit(text: str) -> str:
    """One level of indentation, as the file in hand writes it."""
    for line in text.splitlines():
        stripped = line.lstrip()
        if not stripped or stripped.startswith("//"):
            continue
        indent = line[: len(line) - len(stripped)]
        if indent:
            return "\t" if indent.startswith("\t") else indent
    return "  "


def render_configuration(package_dir: str, folder: str, name: str = CONFIGURATION_NAME) -> dict:
    """The command itself, for the package in `package_dir`, in the launch configuration of `folder`.

    `cwd` matters when the package is not the folder the editor opened, which is
    the normal shape of a monorepo: the command has to run where the package is,
    and `${workspaceFolder}` is the folder holding this `launch.json` -- in a
    multi-root workspace too.
    """
    relative = relative_to(package_dir, folder)
    workspace = WORKSPACE_FOLDER if relative == "." else WORKSPACE_FOLDER + "/" + relative

    return {
        "name": name,
        "type": CONFIGURATION_TYPE,
        "request": "launch",
        "command": RENDER_COMMAND,
        "cwd": workspace,
    }


def _is_render_for(item: Any, cwd: str) -> bool:
    """Whether `item` is the "Render" command of the package `cwd` runs in.

    Recognised by what it runs and where rather than by its name, because there
    is one per package: a second package in the same folder gets a command of
    its own beside the first rather than finding the name taken and getting
    none. What it runs is `pc render`, options and all; a launch merely named
    "Render ..." that runs something else is somebody else's. A command with no
    `cwd` runs in `${workspaceFolder}`.
    """
    if not isinstance(item, dict):
        return False
    command = item.get("command")
    if not isinstance(command, str) or command.split()[:2] != RENDER_COMMAND.split():
        return False
    return str(item.get("cwd") or WORKSPACE_FOLDER).rstrip("/") == cwd


def configuration_name(package_dir: str, folder: str, taken) -> str:
    """The command's name: "Render", or "Render (<package>)" when another package's command has that one."""
    if CONFIGURATION_NAME not in taken:
        return CONFIGURATION_NAME
    relative = relative_to(package_dir, folder)
    label = relative if relative != "." else os.path.basename(os.path.abspath(package_dir))
    base = "%s (%s)" % (CONFIGURATION_NAME, label)
    name, number = base, 2
    while name in taken:
        name = "%s %d" % (base, number)
        number += 1
    return name


CONFIGURATIONS_KEY = '"configurations"'


def _find_configurations_array(blanked: str) -> Optional[tuple]:
    """Locate the top-level `configurations` array in a comment-blanked file.

    Returns `(offset of the key, offset just past its opening bracket)`, or None
    when the file has no such array.

    Only the root object's key counts. A compound launch has a `configurations`
    of its own, listing the names of other launches rather than commands, and
    adding a command to that array produces a file that no longer describes what
    its author wrote -- so the nesting depth is tracked rather than the first
    match being taken.
    """
    depth = 0
    index = 0
    length = len(blanked)
    while index < length:
        char = blanked[index]

        if char == '"':
            start = index
            index += 1
            while index < length:
                if blanked[index] == "\\":
                    index += 2
                    continue
                if blanked[index] == '"':
                    break
                index += 1
            index += 1  # past the closing quote

            if depth == 1 and blanked[start:index] == CONFIGURATIONS_KEY:
                opening = re.compile(r"\s*:\s*\[").match(blanked, index)
                if opening:
                    return start, opening.end()
            continue

        if char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
        index += 1

    return None


def _insert_configuration(text: str, configuration: dict) -> Optional[str]:
    """Return `text` with `configuration` added to its `configurations` array.

    Returns None when the array cannot be found, which means the file is not
    shaped like a launch configuration and is better left alone than guessed at.
    """
    # Searched in the blanked copy and applied to the original: they are the
    # same length, so a position in one is a position in the other.
    blanked = blank_json_comments(text)
    found = _find_configurations_array(blanked)
    if found is None:
        return None
    key_start, end = found

    unit = _indent_unit(text)
    line_start = text.rfind("\n", 0, key_start) + 1
    outer = text[line_start:key_start]
    if outer.strip():
        # The key is not alone on its line; there is nothing to copy the
        # indentation from, so fall back to one level.
        outer = unit
    element = outer + unit

    block = "\n".join(element + line for line in json.dumps(configuration, indent=unit).splitlines())

    if blanked[end:].lstrip().startswith("]"):
        # An empty array: the closing bracket has to move down a line. Whatever
        # whitespace and comments were between the brackets go with it.
        return text[:end] + "\n" + block + "\n" + outer + text[end:].lstrip()
    # Added first, so that it is also what the editor offers by default.
    return text[:end] + "\n" + block + "," + text[end:]


def add_render_configuration(package_dir: str = ".", editor_folder: Optional[str] = None) -> bool:
    """Add the "Render" command for `package_dir` to the launch configuration of `editor_folder`.

    An editor reads `.vscode/launch.json` from the folder it opened, so that is
    where it goes. Left out, that folder is the root of the git repository
    holding the package, or its PartCAD root outside one (see `editor_folder`).

    Returns True when the file was written. Anything that makes it unsafe to
    write -- the command is there already, the file cannot be parsed, it is not
    shaped like a launch configuration -- is reported and returns False. None of
    them is a reason for `pc init` to fail: the package is created either way.
    """
    folder = os.path.abspath(editor_folder) if editor_folder else editor_folder_of(package_dir)
    path = os.path.join(folder, LAUNCH_FILE)
    try:
        configuration = render_configuration(package_dir, folder)
    except ValueError:
        # `relpath` across two Windows drives: there is no relative path to
        # write, and an absolute one would be this machine's in a shared file.
        pc_logging.warning(
            "Not adding the '%s' command: '%s' and '%s' are on different drives, so the one cannot be named from "
            "the other" % (CONFIGURATION_NAME, os.path.abspath(package_dir), folder)
        )
        return False

    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            existing = parse_launch_configuration(text)
        except (OSError, ValueError, UnicodeDecodeError) as e:
            pc_logging.warning("Not adding the '%s' command: %s cannot be read: %s" % (CONFIGURATION_NAME, path, e))
            return False

        if not isinstance(existing, dict):
            pc_logging.warning(
                "Not adding the '%s' command: %s is not a launch configuration" % (CONFIGURATION_NAME, path)
            )
            return False

        configurations = existing.get("configurations") or []
        if not isinstance(configurations, list):
            configurations = []
        if any(_is_render_for(item, configuration["cwd"]) for item in configurations):
            pc_logging.debug("The '%s' command for '%s' is already in %s" % (CONFIGURATION_NAME, package_dir, path))
            return False
        taken = {item.get("name") for item in configurations if isinstance(item, dict)}
        configuration["name"] = configuration_name(package_dir, folder, taken)

        updated = _insert_configuration(text, configuration)
        if updated is None:
            pc_logging.warning(
                "Not adding the '%s' command: %s has no 'configurations' to add it to" % (CONFIGURATION_NAME, path)
            )
            return False
    else:
        updated = json.dumps({"version": LAUNCH_VERSION, "configurations": [configuration]}, indent=2) + "\n"

    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(updated)
    except OSError as e:
        pc_logging.warning("Failed to add the '%s' command to %s: %s" % (CONFIGURATION_NAME, path, e))
        return False

    pc_logging.info("Added the '%s' command to '%s'" % (configuration["name"], path))
    return True
