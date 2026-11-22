#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""How an agent's MCP configuration names the PartCAD root it serves, and which folder that is.

`pc init` writes the PartCAD MCP server into the project configuration of the
folder an editor or agent opens, and `pc mcp` is what that entry starts. The two
have to agree on what the path in it is relative to, which is why the rule is
here and not on either side: a copy each is a copy that can disagree, and a
disagreement is a server serving the wrong package.

The path cannot be relative to the directory the server is started in, because
that is not the folder holding the file for every agent:

* Claude Code looks for `.mcp.json` in the directory it was started in *and in
  every directory above it*, and starts the server in the directory it was
  started in. So an entry at the root of a repository is read by a Claude Code
  started in `packages/robot/` too, and a `-p packages/robot` there means
  `packages/robot/packages/robot`. It sets `CLAUDE_PROJECT_DIR` only in the
  server's environment, not while it expands the file, and to the directory it
  was started in -- so no variable names the folder holding the file.
* Visual Studio Code reads a `.mcp.json` at the root of each workspace folder,
  expands environment variables in it and nothing else, and starts the server
  in that folder.
* The other agents whose configuration has no variable for the folder (Codex,
  Gemini CLI, Zed, Kiro, Devin Desktop, OpenCode) start a project's servers in
  the project. `--root` costs them nothing, and an agent that reads the
  configuration of the folders above the one it was started in, the way Claude
  Code does, starts the server below that folder too.

So such an entry says `pc mcp --root <path> --from <file>`: the path is relative
to the folder holding the file the entry is in, and `--from` names that file,
relative to its folder (`.mcp.json`, `.codex/config.toml`, ...). The server
finds the folder by looking for it: from the directory it was started in,
upwards, the first folder whose `<file>` has an entry naming the same `--root`
is the one that started it. Naming the file is what makes that the entry that
started it rather than another agent's naming the same path in a folder between
the two. An entry without `--from` (written by hand) is looked for in every
file in `CONFIG_FILES`. Where there is none, the server was not started by such
an entry -- or was started in the PartCAD image with the wrong folder mounted --
and it refuses rather than serve a directory it guessed.

Cursor needs none of this: `${workspaceFolder}` in its `.cursor/mcp.json` is the
folder holding that file, which is exactly the anchor, so its entry names the
root with `-p` as an absolute path.
"""

import json
import os
import re
from typing import Optional

from . import jsonc

# The options of `pc mcp` that name the root relative to that file's folder,
# and the file.
ROOT_OPTION = "--root"
SOURCE_OPTION = "--from"

# Every file an entry naming its root with `--root` can be in, relative to the
# folder holding it, with `/` separators: the agents in
# `partcad.ai_agents.MCP_CONFIGS` whose configuration has no spelling of that
# folder. A test holds the two lists together, so that an agent added there is
# one whose server can find its root.
CONFIG_FILES = (
    ".mcp.json",
    ".codex/config.toml",
    ".gemini/settings.json",
    ".zed/settings.json",
    ".kiro/settings/mcp.json",
    ".devin/mcp_config.json",
    "opencode.json",
    "opencode.jsonc",
    ".opencode/opencode.json",
    ".opencode/opencode.jsonc",
)

# The variable the PartCAD editor extension sets on the terminals of each
# workspace folder it has open, to the folder's path: the folder an editor
# opened, which `pc init` cannot otherwise know. Kept in step with
# `WORKSPACE_FOLDER_ENV` in `ide/vscode/src/common/workspaceFolderEnv.ts`.
WORKSPACE_FOLDER_ENV = "PARTCAD_WORKSPACE_FOLDER"


def _argument(args, option: str) -> Optional[str]:
    if not isinstance(args, list):
        return None
    for index, arg in enumerate(args[:-1]):
        if arg == option and isinstance(args[index + 1], str):
            return args[index + 1]
    return None


def root_argument(args) -> Optional[str]:
    """The value of `--root` in a command's arguments, or None if it has none."""
    return _argument(args, ROOT_OPTION)


def source_argument(args) -> Optional[str]:
    """The value of `--from` in a command's arguments, or None if it has none."""
    return _argument(args, SOURCE_OPTION)


def _names(value, root: str) -> bool:
    """Whether any list in the parsed configuration `value` says `--root <root>`.

    Looked for in every list rather than under each agent's key for its servers,
    because those differ (`mcpServers`, `context_servers`, `mcp.servers`,
    `mcp_servers`) and so do the entries (a `command` and its `args`, or one
    command array): a list holding `--root` and then this path is a command
    starting `pc mcp` for it, whichever agent's file it is in.
    """
    if isinstance(value, dict):
        return any(_names(item, root) for item in value.values())
    if isinstance(value, list):
        return root_argument(value) == root or any(_names(item, root) for item in value)
    return False


def _load(path: str):
    """The configuration at `path`, parsed, or None when it cannot be read."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError):
        return None
    if not path.endswith(".toml"):
        # With comments and trailing commas: Zed's settings, say, which a
        # person edits by hand, and `pc init` leaves alone when they are.
        try:
            return jsonc.loads(text)
        except ValueError:
            return None
    try:
        import tomllib  # pylint: disable=import-outside-toplevel
    except ImportError:  # pragma: no cover - Python 3.10
        try:
            import tomli as tomllib  # pylint: disable=import-outside-toplevel
        except ImportError:
            # No parser (Python 3.10 without `tomli`): the arrays `pc init`
            # writes are JSON arrays on one line, so those are read as JSON.
            arrays = []
            for found in re.findall(r"^[ \t]*args[ \t]*=[ \t]*(\[.*\])[ \t]*$", text, re.MULTILINE):
                try:
                    arrays.append(json.loads(found))
                except ValueError:
                    continue
            return arrays
    try:
        return tomllib.loads(text)
    except Exception:  # pylint: disable=broad-except
        return None


def _names_root(folder: str, root: str, source: Optional[str]) -> bool:
    """Whether a configuration in `folder` -- `source`, or any of `CONFIG_FILES` -- has an entry for `<root>`."""
    names = [source] if source else CONFIG_FILES
    return any(_names(_load(os.path.join(folder, *name.split("/"))), root) for name in names)


def config_folder(start: str, root: str, source: Optional[str] = None) -> Optional[str]:
    """The folder of the configuration whose entry started `pc mcp --root <root> [--from <source>]`, or None.

    Looked for from `start` -- the directory the server was started in --
    upwards, nearest first, which is the order Claude Code reads them in.
    """
    current = os.path.abspath(start)
    while True:
        if _names_root(current, root, source):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def resolve_root(start: str, root: str, source: Optional[str] = None) -> Optional[str]:
    """The directory `pc mcp --root <root>`, started in `start`, serves; None when nothing names it.

    Relative to the folder of the configuration that names it. When no
    configuration at or above `start` does, the server was started somewhere
    that file is not -- the PartCAD image given the wrong folder to mount, say
    -- and any directory chosen for it would be a guess; `-p` is how a person
    names a directory by hand.
    """
    if os.path.isabs(root):
        return os.path.normpath(root)
    folder = config_folder(start, root, source)
    return None if folder is None else os.path.normpath(os.path.join(folder, root))
