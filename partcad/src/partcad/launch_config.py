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
would drop every comment in it.
"""

import json
import os
import re
from typing import Any, Optional

from . import logging as pc_logging

CONFIGURATION_NAME = "Render"

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


def _strip_json_comments(text: str) -> str:
    """Return `text` with `//` and `/* */` comments removed.

    `launch.json` is "JSON with comments", which `json` refuses to parse -- and
    Visual Studio Code puts three comment lines in the file it generates, so
    this is the common case rather than the exotic one. String literals are
    tracked so that a `//` inside a URL survives.
    """
    out: list[str] = []
    index = 0
    length = len(text)
    in_string = False
    while index < length:
        char = text[index]

        if in_string:
            out.append(char)
            if char == "\\" and index + 1 < length:
                out.append(text[index + 1])
                index += 2
                continue
            if char == '"':
                in_string = False
            index += 1
            continue

        if char == '"':
            in_string = True
            out.append(char)
            index += 1
            continue

        if char == "/" and index + 1 < length:
            if text[index + 1] == "/":
                while index < length and text[index] != "\n":
                    index += 1
                continue
            if text[index + 1] == "*":
                end = text.find("*/", index + 2)
                index = length if end == -1 else end + 2
                continue

        out.append(char)
        index += 1

    return "".join(out)


def _drop_trailing_commas(text: str) -> str:
    """Remove the commas that JSON forbids and editors leave behind."""
    return re.sub(r",(\s*[}\]])", r"\1", text)


def parse_launch_configuration(text: str) -> Any:
    """Parse the contents of a `launch.json`."""
    return json.loads(_drop_trailing_commas(_strip_json_comments(text)))


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


def render_configuration(package_dir: str, repository_root: str) -> dict:
    """The command itself.

    `cwd` matters when the package is not at the root of the repository, which
    is the normal shape of a monorepo: the command has to run where the package
    is, and `${workspaceFolder}` is where the repository is.
    """
    relative = os.path.relpath(os.path.abspath(package_dir), os.path.abspath(repository_root))
    workspace = "${workspaceFolder}"
    if relative not in (".", ""):
        workspace = workspace + "/" + relative.replace(os.sep, "/")

    return {
        "name": CONFIGURATION_NAME,
        "type": CONFIGURATION_TYPE,
        "request": "launch",
        "command": "pc render",
        "cwd": workspace,
    }


def _insert_configuration(text: str, configuration: dict) -> Optional[str]:
    """Return `text` with `configuration` added to its `configurations` array.

    Returns None when the array cannot be found, which means the file is not
    shaped like a launch configuration and is better left alone than guessed at.
    """
    match = re.search(r'"configurations"\s*:\s*\[', text)
    if match is None:
        return None

    unit = _indent_unit(text)
    line_start = text.rfind("\n", 0, match.start()) + 1
    outer = text[line_start : match.start()]
    if outer.strip():
        # The key is not alone on its line; there is nothing to copy the
        # indentation from, so fall back to one level.
        outer = unit
    element = outer + unit

    block = "\n".join(element + line for line in json.dumps(configuration, indent=unit).splitlines())

    end = match.end()
    remainder = text[end:].lstrip()
    if remainder.startswith("]"):
        # An empty array: the closing bracket has to move down a line.
        return text[:end] + "\n" + block + "\n" + outer + text[end:].lstrip()
    # Added first, so that it is also what the editor offers by default.
    return text[:end] + "\n" + block + "," + text[end:]


def add_render_configuration(package_dir: str = ".") -> bool:
    """Add the "Render" command to the launch configuration for `package_dir`.

    The file is written at the root of the git repository holding the package,
    because that is what an editor opens as its workspace; when the package is
    not in a repository, it goes next to the package itself.

    Returns True when the file was written. Anything that makes it unsafe to
    write -- the command is there already, the file cannot be parsed, it is not
    shaped like a launch configuration -- is reported and returns False. None of
    them is a reason for `pc init` to fail: the package is created either way.
    """
    root = find_repository_root(package_dir) or os.path.abspath(package_dir)
    path = os.path.join(root, LAUNCH_FILE)
    configuration = render_configuration(package_dir, root)

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
        if any(isinstance(item, dict) and item.get("name") == CONFIGURATION_NAME for item in configurations):
            pc_logging.debug("The '%s' command is already in %s" % (CONFIGURATION_NAME, path))
            return False

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

    pc_logging.info("Added the '%s' command to '%s'" % (CONFIGURATION_NAME, path))
    return True
