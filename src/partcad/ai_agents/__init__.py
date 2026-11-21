#
# PartCAD, 2026
#
# Author: PartCAD (support@partcad.org)
# Created: 2026-09-08
#
# Licensed under Apache License, Version 2.0.
#

"""The AI agent skills PartCAD ships, and where `pc init` puts them.

The skills live at the top of the repository, in `ai-agents/`, where a visitor
finds them and where the Claude plugin is published from. `skills` and
`plugin.json` in *this* directory are symlinks into it, and they are what puts
the library in the wheel -- because the wheel is what a user of PartCAD has.
`pc init` creates a package and then installs the skills beside it, so the agent
already open in the editor knows how to drive PartCAD without anyone first
finding a repository, a marketplace or an install command.

Nothing is a second copy, in either direction. `setuptools` resolves a symlink
that is a path component and stores what it finds as an ordinary file, so the
wheel, the sdist and the frozen bundle all carry real files; `pyproject.toml`
says which patterns, and a test fails if a file in the library matches none of
them. What the plugin ships and what the wheel ships cannot drift, because they
are the same files.

The agents are not all given the same thing:

  * **Claude Code** gets the *plugin*, written into `.claude/skills/pc/` as a
    manifest plus the skills under it. A directory there holding a
    `.claude-plugin/plugin.json` is loaded as a plugin, which is what puts every
    skill in one namespace: `/pc:init`, not `/init`. The name comes from the
    manifest, so it is the same `pc` a marketplace install produces, and a
    project that has both does not end up with two spellings of one skill.

  * **Cursor** has no plugin to namespace anything, so a skill is whatever its
    directory is called. `init`, `gen`, `render`, `search`, `export` -- shipped
    as they are, PartCAD would be claiming five of the most generic names in a
    user's `.cursor/skills`. They are installed prefixed instead, as `pc-init`
    and its siblings, and the `pc:<skill>` cross-references in the text are
    rewritten to match: a skill that tells the agent to run `/pc:setup` in an
    editor where that resolves to nothing is worse than one that says nothing.

  * **Every other agent** -- GitHub Copilot, Codex, Gemini CLI, Zed, OpenCode,
    Devin Desktop, Kiro -- gets what Cursor gets, in the directory it reads.
    Six of them read the same one, `.agents/skills`, and share one copy there.

Beside the skills, `pc init` writes the MCP server into each agent's project
configuration, and a PartCAD section into the repository's `AGENTS.md` (see the
end of this module). The text of a skill -- its renaming, its stamp -- is
`partcad_utils.agent_skills`, because `pc mcp` serves the same skills without
importing this package.

No destination is written through a symlink. `.claude/skills/pc` is a
symlink in PartCAD's own repository -- to `ai-agents/claude`, so that a session
opened here loads the plugin from the working tree -- and following it would
have `pc init` overwrite the source tree with a copy of itself.
"""

import json
import os
import re
import shutil
from dataclasses import dataclass
from typing import Optional

from partcad_utils import agent_skills

from .. import __version__
from .. import logging as pc_logging
from ..launch_config import find_repository_root

# Read out of this package rather than out of the repository, because in every
# install except a checkout there is no repository: `pyproject.toml` lists these
# two under `[tool.setuptools.package-data]`, and
# `dev-tools/pyinstaller/partcad.spec` lists them again for the frozen bundle,
# which does not read `package-data`. In a checkout they are the symlinks, which
# resolve to the same files.
_HERE = os.path.dirname(os.path.abspath(__file__))

SKILLS_DIR = os.path.join(_HERE, "skills")

# The Claude plugin manifest. Flat here, and written into a `.claude-plugin/`
# directory at install time, so that the wheel carries no dot-directory: in the
# repository it is `ai-agents/claude/.claude-plugin/plugin.json`, which is where
# `dev-tools/bumpversion.toml` moves its version with every other version.
CLAUDE_PLUGIN_MANIFEST = os.path.join(_HERE, "plugin.json")

# Where each editor looks. Relative to the repository the package was created
# in, which is what an editor opens as its workspace -- the same root
# `add_render_configuration` writes `.vscode/launch.json` into.
CLAUDE_SKILLS_DIR = os.path.join(".claude", "skills")
CURSOR_SKILLS_DIR = os.path.join(".cursor", "skills")

# The project instructions most agents read, and the file Claude Code reads
# instead of it where there is one (see "AGENTS.md" below).
AGENTS_MD = "AGENTS.md"
CLAUDE_MD_NAME = "CLAUDE.md"

# The manifest directory Claude Code identifies a plugin by.
CLAUDE_PLUGIN_DIR = ".claude-plugin"

# What a skill of ours is called by every agent but Claude Code, and what the
# plugin calls it. The prefix is the plugin's name because they are the same
# skill: `/pc:init` in Claude Code is `pc-init` in Cursor, in GitHub Copilot and
# the rest, and the `pc-init` prompt of `pc mcp`. The name is historical; the
# value is `partcad_utils.agent_skills.PREFIX`, which `pc mcp` reads too.
CURSOR_PREFIX = agent_skills.PREFIX

# The front matter key the prefixed copies are stamped with, under `metadata:`.
# Two things depend on it and neither has another way to know:
#
#   * staleness -- the skills a user has are the ones the PartCAD that wrote
#     them shipped, and nothing else in a `.cursor/skills` directory (or any
#     other agent's) says which
#     PartCAD that was. The Claude side has `plugin.json` for this.
#   * ownership -- a `pc-` directory carrying this stamp is one PartCAD wrote,
#     so it is one PartCAD may remove when the skill behind it is retired. A
#     `pc-something` a user wrote themselves has no stamp and is never touched.
#
# The value is `partcad.__version__`, read here, at install time. It is
# deliberately *not* a literal in this file: a literal would be one more entry
# in `dev-tools/bumpversion.toml` and one more thing to forget on a release --
# which is exactly how the Claude plugin manifest sat at 0.1.0 for twenty-three
# releases (see the note at the top of that file). `__version__` is already
# bumped, `tests/partcad_cli/unit/test_versions.py` already fails if it stops
# moving, and reading it costs nothing. Do not replace this with a constant.
STAMP_KEY = agent_skills.STAMP_KEY
STAMP_SECTION = agent_skills.STAMP_SECTION


def plugin_manifest() -> dict:
    """The Claude plugin manifest, as shipped."""
    with open(CLAUDE_PLUGIN_MANIFEST, "r", encoding="utf-8") as f:
        return json.load(f)


def plugin_name() -> str:
    """The name Claude Code loads the plugin under, and the `/<name>:` prefix."""
    return plugin_manifest()["name"]


def available_skills() -> list[str]:
    """Every skill in the wheel, by directory name -- which is also its name."""
    if not os.path.isdir(SKILLS_DIR):
        return []
    return sorted(name for name in os.listdir(SKILLS_DIR) if os.path.isfile(os.path.join(SKILLS_DIR, name, "SKILL.md")))


# The text of a skill -- its front matter, its stamp, its name once it has left
# the plugin namespace -- is `partcad_utils.agent_skills`'s, because `pc mcp`
# reads the same skills without importing `partcad`. These are its names here,
# where everything else that installs a skill already looks for them.
front_matter_bounds = agent_skills.front_matter_bounds
stamped_version = agent_skills.stamped_version
rename_skill = agent_skills.rename_skill


def _writable_destination(path: str, what: str) -> bool:
    """Whether `path` is ours to write, reporting why when it is not.

    A symlink is never followed. PartCAD's own repository has
    `.claude/skills/pc -> ../../ai-agents/claude`, so `pc init` run in a
    checkout would otherwise replace the working tree's plugin with a copy of
    the installed one -- and any user who symlinked one of these at a shared
    directory means it to stay a symlink.
    """
    if os.path.islink(path):
        pc_logging.warning("Not installing %s: '%s' is a symbolic link" % (what, path))
        return False
    if os.path.exists(path) and not os.path.isdir(path):
        pc_logging.warning("Not installing %s: '%s' is not a directory" % (what, path))
        return False
    return True


def _ours_to_retire(directory: str) -> Optional[str]:
    """The name of a Cursor skill PartCAD may remove, or None to leave it alone.

    Ours is a `pc-` directory carrying the stamp: `pc init` wrote it, so `pc
    init` may retire it when the skill behind it is gone. Anything else in that
    directory belongs to somebody else -- a `pc-` skill an author wrote by hand,
    or one an older PartCAD installed before it stamped anything -- and a
    retired skill lingering there is a much smaller harm than deleting a file
    PartCAD did not write.
    """
    name = os.path.basename(directory)
    if not name.startswith(CURSOR_PREFIX):
        return None

    try:
        with open(os.path.join(directory, "SKILL.md"), "r", encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError):
        return None

    if stamped_version(text) is None:
        pc_logging.debug("Leaving '%s' in place: PartCAD does not ship it and did not write it" % directory)
        return None
    return name


def _retire(parent: str, keep: list[str], owned) -> list[str]:
    """Remove the skills under `parent` that PartCAD no longer ships.

    A skill retired upstream keeps being offered to the agent otherwise, and an
    agent that follows it drives a CLI that no longer works that way -- which is
    worse than having no skill at all, because it looks like a working one. That
    is what makes this a removal rather than a warning.

    `owned` decides what may go: the whole plugin directory is PartCAD's, so
    there it is every name; under `.cursor/skills` it is the stamped ones.
    Returns the names removed, for the caller to report.
    """
    if not os.path.isdir(parent):
        return []

    retired = []
    for name in sorted(os.listdir(parent)):
        directory = os.path.join(parent, name)
        if name in keep or os.path.islink(directory) or not os.path.isdir(directory):
            continue
        if owned(directory) is None:
            continue
        try:
            shutil.rmtree(directory)
        except OSError as e:
            pc_logging.warning("Failed to remove the retired skill '%s': %s" % (directory, e))
            continue
        retired.append(name)
    return retired


def install_claude_plugin(root: str) -> bool:
    """Install the skills into `root` as the Claude Code plugin.

    Written as `.claude/skills/<plugin>/`, holding the manifest and a copy of
    every skill. Returns True when the plugin was written.
    """
    name = plugin_name()
    destination = os.path.join(root, CLAUDE_SKILLS_DIR, name)
    if not _writable_destination(destination, "the Claude plugin"):
        return False

    skills = available_skills()
    if not skills:
        pc_logging.warning("Not installing the Claude plugin: no skills are installed with PartCAD")
        return False

    try:
        os.makedirs(os.path.join(destination, CLAUDE_PLUGIN_DIR), exist_ok=True)
        shutil.copyfile(CLAUDE_PLUGIN_MANIFEST, os.path.join(destination, CLAUDE_PLUGIN_DIR, "plugin.json"))
        for skill in skills:
            # Copied whole: a skill is a directory, and the ones that grow a
            # `references/` or a script beside the `SKILL.md` have to keep them.
            target = os.path.join(destination, "skills", skill)
            shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(os.path.join(SKILLS_DIR, skill), target)
    except OSError as e:
        pc_logging.warning("Failed to install the Claude plugin into '%s': %s" % (destination, e))
        return False

    retired = _retire(os.path.join(destination, "skills"), skills, lambda directory: directory)
    pc_logging.info("Installed the '%s' plugin (%d skills) into '%s'" % (name, len(skills), destination))
    if retired:
        pc_logging.info("Removed %d skill(s) PartCAD no longer ships: %s" % (len(retired), ", ".join(retired)))
    return True


def install_prefixed_skills(root: str, skills_dir: str, title: str) -> bool:
    """Install the skills into `root/skills_dir` for an agent with no plugin namespace, prefixed and renamed.

    One directory per skill, named `pc-<skill>` and stamped (see
    `agent_skills.rename_skill`). This is what every agent but Claude Code gets:
    they read the same `SKILL.md` folders, and differ only in where they look.
    Returns True when at least one skill was written.
    """
    destination = os.path.join(root, skills_dir)
    if not _writable_destination(destination, "the %s skills" % title):
        return False

    skills = available_skills()
    if not skills:
        pc_logging.warning("Not installing the %s skills: no skills are installed with PartCAD" % title)
        return False

    installed = 0
    for skill in skills:
        name = CURSOR_PREFIX + skill
        target = os.path.join(destination, name)
        if os.path.islink(target):
            pc_logging.warning("Not installing '%s': '%s' is a symbolic link" % (name, target))
            continue
        try:
            source = os.path.join(SKILLS_DIR, skill)
            shutil.rmtree(target, ignore_errors=True)
            # The whole directory, then the one file that has to be rewritten --
            # so anything a skill carries beside its `SKILL.md` comes along.
            shutil.copytree(source, target)
            with open(os.path.join(source, "SKILL.md"), "r", encoding="utf-8") as f:
                text = f.read()
            with open(os.path.join(target, "SKILL.md"), "w", encoding="utf-8", newline="\n") as f:
                f.write(rename_skill(text, name, skills, __version__))
        except OSError as e:
            pc_logging.warning("Failed to install '%s' into '%s': %s" % (name, target, e))
            continue
        installed += 1

    if not installed:
        return False

    retired = _retire(destination, [CURSOR_PREFIX + skill for skill in skills], _ours_to_retire)
    pc_logging.info("Installed %d skills into '%s' as '%s*'" % (installed, destination, CURSOR_PREFIX))
    if retired:
        pc_logging.info("Removed %d skill(s) PartCAD no longer ships: %s" % (len(retired), ", ".join(retired)))
    return True


def install_cursor_skills(root: str) -> bool:
    """Install the skills into `root` for Cursor: `.cursor/skills/pc-<skill>`."""
    return install_prefixed_skills(root, CURSOR_SKILLS_DIR, "Cursor")


# Where the agents that have converged on one directory for a project's skills
# look: GitHub Copilot, Codex, Gemini CLI, Zed, OpenCode and Devin Desktop
# (Windsurf) all read `.agents/skills`. One copy there serves all of them, so it
# is written once however many of them are asked for. Kiro reads only its own.
AGENTS_SKILLS_DIR = os.path.join(".agents", "skills")
KIRO_SKILLS_DIR = os.path.join(".kiro", "skills")


def install_shared_skills(root: str) -> bool:
    """Install the skills into `root` for every agent reading `.agents/skills`: `.agents/skills/pc-<skill>`."""
    return install_prefixed_skills(root, AGENTS_SKILLS_DIR, "'.agents/skills'")


def install_kiro_skills(root: str) -> bool:
    """Install the skills into `root` for Kiro: `.kiro/skills/pc-<skill>`."""
    return install_prefixed_skills(root, KIRO_SKILLS_DIR, "Kiro")


# Each place skills are written, keyed by what installs them, with the directory
# it writes (for `AGENTS.md`, which says where they are, and for `pc
# healthcheck`, which looks there).
SKILL_TARGETS = {
    "claude": (CLAUDE_SKILLS_DIR, install_claude_plugin),
    "cursor": (CURSOR_SKILLS_DIR, install_cursor_skills),
    "shared": (AGENTS_SKILLS_DIR, install_shared_skills),
    "kiro": (KIRO_SKILLS_DIR, install_kiro_skills),
}


@dataclass(frozen=True)
class Agent:
    """A coding agent `pc init` installs for.

    `skills` is the `SKILL_TARGETS` entry it reads. `markers` are paths at the
    root of a repository that say the agent is used there, and `default` says
    whether it is installed for when nobody names the agents: the ones that are
    are the two with an install base PartCAD has had since the start, plus the
    shared directory, which costs one copy and serves six agents; every other is
    installed for where its marker is found, or when asked for by name -- a
    `pc init` that wrote a `.kiro`, a `.zed` and a `.codex` into every new
    repository would be littering it for agents its author does not use.
    """

    title: str
    skills: str
    markers: tuple = ()
    default: bool = False


# Every agent this knows how to install for. The skills themselves are
# vendor-neutral `SKILL.md` folders, so an agent is added here by saying where
# it reads them (and, in `MCP_CONFIGS`, its servers) -- not by writing a second
# copy of the library.
AGENT_SPECS = {
    "claude": Agent("Claude Code", "claude", (".claude", CLAUDE_MD_NAME, ".mcp.json"), default=True),
    "cursor": Agent("Cursor", "cursor", (".cursor", ".cursorrules"), default=True),
    "copilot": Agent(
        "GitHub Copilot", "shared", (os.path.join(".github", "copilot-instructions.md"), ".agents"), default=True
    ),
    "codex": Agent("Codex", "shared", (".codex",)),
    "gemini": Agent("Gemini CLI", "shared", (".gemini", "GEMINI.md")),
    "zed": Agent("Zed", "shared", (".zed",)),
    "opencode": Agent("OpenCode", "shared", (".opencode", "opencode.json", "opencode.jsonc")),
    "devin": Agent("Devin Desktop (Windsurf)", "shared", (".devin", ".windsurf", ".windsurfrules")),
    "kiro": Agent("Kiro", "kiro", (".kiro",)),
}

# Other names an agent is known by. Windsurf became Devin Desktop in 2026, and
# whoever has used it longest still calls it Windsurf.
AGENT_ALIASES = {"windsurf": "devin"}

# What installing for each agent means, by name: kept as a mapping of callables
# because that is what it has always been, and what tests stub.
AGENTS = {name: SKILL_TARGETS[spec.skills][1] for name, spec in AGENT_SPECS.items()}


def default_agents(root: str) -> list[str]:
    """The agents `pc init` installs for when none are named: the defaults, and whichever are used in `root`."""
    return [
        name
        for name, spec in AGENT_SPECS.items()
        if spec.default or any(os.path.lexists(os.path.join(root, marker)) for marker in spec.markers)
    ]


# The MCP server, `pc mcp`, under the one name PartCAD writes into an agent's
# configuration. The entry under that name is PartCAD's and is rewritten every
# time; every other server in the file is somebody else's and is left alone.
MCP_SERVER_NAME = "partcad"


@dataclass(frozen=True)
class McpConfig:
    """Where an agent reads a project's MCP servers from, and how.

    `project` is how the file spells "the project's directory", which the
    server's `-p` is written relative to, because the directory an agent starts
    it in is not one every agent promises -- and in a repository whose package
    is in a subdirectory, it would not be the package anyway. Claude Code sets no
    `CLAUDE_PROJECT_DIR` of its own when it reads a project's `.mcp.json`, so the
    variable has a default there; Cursor resolves `${workspaceFolder}` itself.
    The others document no such variable, and start a project's servers in the
    project: there the path is relative, and `None` says so.
    """

    path: str
    key: str = "mcpServers"
    project: Optional[str] = None
    extra: tuple = ()
    toml: bool = False


MCP_CONFIGS = {
    "claude": McpConfig(".mcp.json", project="${CLAUDE_PROJECT_DIR:-.}", extra=(("type", "stdio"),)),
    "cursor": McpConfig(os.path.join(".cursor", "mcp.json"), project="${workspaceFolder}"),
    "codex": McpConfig(os.path.join(".codex", "config.toml"), key="mcp_servers", toml=True),
    "gemini": McpConfig(os.path.join(".gemini", "settings.json")),
    "zed": McpConfig(os.path.join(".zed", "settings.json"), key="context_servers"),
    "kiro": McpConfig(os.path.join(".kiro", "settings", "mcp.json")),
    "devin": McpConfig(os.path.join(".devin", "mcp_config.json")),
}

# The agents that are given no MCP configuration, and why: an agent added to
# `AGENT_SPECS` has to be in one of these two or a test fails, so that none of
# them silently gets the skills and no server.
MCP_NOT_WRITTEN = {
    # The PartCAD extension registers the server with the editor for every
    # workspace holding a `partcad.yaml` (`ide/vscode/src/common/mcp.ts`), with
    # the `pc` it resolved; a `.vscode/mcp.json` beside it would be a second
    # server under the same name. The Copilot cloud agent reads its servers from
    # the repository's settings on GitHub, not from a file.
    "copilot": "the PartCAD extension registers it with VS Code; see 'Visual Studio Code' in the MCP documentation",
    # Its configuration file has changed shape (`mcp` holding servers, then
    # `mcp.servers`), and a file merged into in the wrong shape is a broken one.
    "opencode": "its configuration format is in flux; see 'OpenCode' in the MCP documentation",
}


def mcp_server_entry(agent: str, root: str, package_dir: str) -> dict:
    """The configuration entry that starts `pc mcp` for the package in `package_dir`.

    `pc`, not an absolute path to it: the file is committed with the package and
    read on every machine that checks it out, where PartCAD is wherever that
    machine installed it.
    """
    config = MCP_CONFIGS[agent]
    relative = os.path.relpath(os.path.abspath(package_dir), os.path.abspath(root)).replace(os.sep, "/")
    if config.project is None:
        path = relative
    else:
        path = config.project if relative == os.curdir else config.project + "/" + relative
    # Claude Code reads an entry with no "type" as stdio, and says so in its
    # documentation by always writing it out; the others have no such field.
    return {**dict(config.extra), "command": "pc", "args": ["-p", path, "mcp"]}


def install_mcp_config(agent: str, root: str, package_dir: str) -> bool:
    """Add (or update) the `pc mcp` entry in `agent`'s project configuration under `root`.

    The file is merged into, never replaced: it is a list of servers, and the
    others in it belong to whoever put them there. A file that cannot be merged
    into -- not JSON (or TOML), or JSON with comments, or one without a mapping
    of servers -- is left as it is, with a warning, because rewriting it would
    lose whatever it holds; and so is a symbolic link, for the reason
    `_writable_destination` gives.
    """
    config = MCP_CONFIGS[agent]
    path = os.path.join(root, config.path)
    if os.path.islink(path):
        pc_logging.warning("Not adding the MCP server: '%s' is a symbolic link" % path)
        return False
    entry = mcp_server_entry(agent, root, package_dir)
    if config.toml:
        return _install_toml_server(path, config.key, entry)

    def add(document: dict) -> Optional[str]:
        if not isinstance(document.get(config.key, {}), dict):
            return "it has no '%s' object to add to" % config.key
        servers = document.setdefault(config.key, {})
        if servers.get(MCP_SERVER_NAME) == entry:
            return ""
        servers[MCP_SERVER_NAME] = entry
        return None

    return _merge_json(path, add, "the PartCAD MCP server ('%s')" % MCP_SERVER_NAME)


def _merge_json(path: str, change, what: str) -> bool:
    """Apply `change` to the JSON object in `path` (an empty one when it does not exist) and write it back.

    `change` returns None when it changed the document, "" when there was
    nothing to change, and a reason when it refuses to. True when `what` is in
    place afterwards.
    """
    document = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                document = json.load(f)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            pc_logging.warning("Not adding %s to '%s', which is not readable JSON: %s" % (what, path, e))
            return False
        if not isinstance(document, dict):
            pc_logging.warning("Not adding %s to '%s': it is not a JSON object" % (what, path))
            return False

    refused = change(document)
    if refused == "":
        pc_logging.debug("'%s' already has %s" % (path, what))
        return True
    if refused is not None:
        pc_logging.warning("Not adding %s to '%s': %s" % (what, path, refused))
        return False
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(document, f, indent=2)
            f.write("\n")
    except OSError as e:
        pc_logging.warning("Failed to add %s to '%s': %s" % (what, path, e))
        return False
    pc_logging.info("Added %s to '%s'" % (what, path))
    return True


# A table header in a TOML file, with its dotted name.
_TOML_HEADER = re.compile(r"^[ \t]*\[(?!\[)(?P<name>[^\]]+)\][ \t]*(?:#.*)?$", re.MULTILINE)


def _toml_key_path(header: str) -> list[str]:
    """The keys of a dotted TOML table name, unquoted: `mcp_servers."partcad"` is `['mcp_servers', 'partcad']`."""
    return [part.strip().strip('"').strip("'") for part in re.findall(r'"[^"]*"|\'[^\']*\'|[^.]+', header)]


def _toml_loads(text: str):
    """Parse TOML with whichever parser this Python has, or None when it has none (3.10, without `tomli`)."""
    try:
        import tomllib  # pylint: disable=import-outside-toplevel
    except ImportError:  # pragma: no cover - Python 3.10
        try:
            import tomli as tomllib  # pylint: disable=import-outside-toplevel
        except ImportError:
            return None
    return tomllib.loads(text)


def _install_toml_server(path: str, key: str, entry: dict) -> bool:
    """Add (or update) `[<key>.partcad]` in the TOML file at `path` -- Codex's `.codex/config.toml`.

    Edited as text, the way `launch_config` edits `launch.json`: a parse and
    re-dump would drop every comment in the file, and there is no TOML writer
    among PartCAD's dependencies. The table PartCAD owns -- and any sub-table of
    it, such as an `env` -- is replaced whole; everything else is kept byte for
    byte. Where a parser is at hand the result is parsed before it is written,
    and a file this would break is left as it was.
    """
    what = "the PartCAD MCP server ('%s')" % MCP_SERVER_NAME
    text = ""
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError) as e:
            pc_logging.warning("Not adding %s to '%s', which cannot be read: %s" % (what, path, e))
            return False

    table = "[%s.%s]\ncommand = %s\nargs = [%s]\n" % (
        key,
        MCP_SERVER_NAME,
        json.dumps(entry["command"]),
        ", ".join(json.dumps(arg) for arg in entry["args"]),
    )

    ours = [key, MCP_SERVER_NAME]
    headers = list(_TOML_HEADER.finditer(text))
    start = end = None
    for index, header in enumerate(headers):
        if _toml_key_path(header.group("name"))[:2] != ours:
            continue
        if start is None:
            start = header.start()
        # To the next table that is not ours, or to the end of the file.
        following = next((h for h in headers[index + 1 :] if _toml_key_path(h.group("name"))[:2] != ours), None)
        end = following.start() if following else len(text)
    if start is not None:
        tail = text[end:]
        updated = text[:start] + table + ("\n" + tail if tail else "")
    else:
        updated = (text.rstrip("\n") + "\n\n" if text.strip() else "") + table

    if updated == text:
        pc_logging.debug("'%s' already has %s" % (path, what))
        return True
    try:
        parsed = _toml_loads(updated)
    except Exception as e:  # pylint: disable=broad-except
        pc_logging.warning("Not adding %s to '%s': the file would not be valid TOML (%s)" % (what, path, e))
        return False
    if parsed is not None and parsed.get(key, {}).get(MCP_SERVER_NAME) != entry:
        # A server of that name written some other way -- inline, under
        # `[mcp_servers]` -- which this edit cannot see to replace.
        pc_logging.warning(
            "Not adding %s to '%s': it declares '%s' in a form this cannot edit" % (what, path, MCP_SERVER_NAME)
        )
        return False
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(updated)
    except OSError as e:
        pc_logging.warning("Failed to add %s to '%s': %s" % (what, path, e))
        return False
    pc_logging.info("Added %s to '%s'" % (what, path))
    return True


# Gemini CLI reads `GEMINI.md` and nothing else unless its settings say
# otherwise: `context.fileName` names the files it reads instead. PartCAD adds
# `AGENTS.md` to that list in the project's `.gemini/settings.json`, keeping
# `GEMINI.md` and whatever else is there.
GEMINI_SETTINGS = os.path.join(".gemini", "settings.json")


def install_gemini_context(root: str) -> bool:
    """Make Gemini CLI read `AGENTS.md` in `root`, beside the files it already reads."""

    def add(document: dict) -> Optional[str]:
        context = document.get("context", {})
        if not isinstance(context, dict):
            return "its 'context' is not an object"
        names = context.get("fileName", ["GEMINI.md"])
        names = [names] if isinstance(names, str) else names
        if not isinstance(names, list):
            return "its 'context.fileName' is neither a name nor a list of them"
        if AGENTS_MD in names:
            return ""
        document["context"] = {**context, "fileName": [AGENTS_MD, *names]}
        return None

    return _merge_json(os.path.join(root, GEMINI_SETTINGS), add, "%s, as a context file" % AGENTS_MD)


def resolve_agents(names) -> tuple[list[str], list[str]]:
    """The agents `names` mean, aliases resolved and duplicates dropped, and the names that mean none."""
    resolved, unknown = [], []
    for name in names:
        agent = AGENT_ALIASES.get(name, name)
        if agent not in AGENT_SPECS:
            unknown.append(name)
        elif agent not in resolved:
            resolved.append(agent)
    return resolved, unknown


def install_agent_skills(package_dir: str = ".", agents=None, mcp: bool = True, instructions: bool = True) -> bool:
    """Install the skills for `agents`, beside the package in `package_dir`.

    The files go to the root of the git repository holding the package, because
    that is what an editor opens as its workspace; when the package is not in a
    repository, they go next to the package itself. This is the same root
    `add_render_configuration` writes into, and for the same reason.

    `agents` is the names to install for, defaulting to `default_agents`. An
    unknown name is an error rather than a no-op: a typo that silently installs
    nothing looks exactly like an agent PartCAD does not support yet. Agents that
    read one directory share one copy of the skills in it.

    `mcp` also adds the MCP server, `pc mcp`, to each agent's project
    configuration (see `install_mcp_config`): the skills say how to drive
    PartCAD, and the server is what an agent drives it through without a shell.
    `instructions` writes PartCAD's section of `AGENTS.md` (`install_instructions`).

    Returns True when anything was installed. Nothing here is a reason for
    `pc init` to fail -- the package is created either way -- so every failure
    is reported and returns False.
    """
    root = find_repository_root(package_dir) or os.path.abspath(package_dir)
    if agents is None:
        agents = default_agents(root)
    agents, unknown = resolve_agents(agents)
    if unknown:
        known = sorted([*AGENT_SPECS, *AGENT_ALIASES])
        pc_logging.error("Unknown agent(s): %s. Known: %s" % (", ".join(sorted(unknown)), ", ".join(known)))
        return False

    # Every one of them runs: a refusal for one agent is not a reason to skip
    # the next, so this must not short-circuit the way `and`/`or` would. Each
    # place is written once, however many of the agents read it.
    targets = []
    for agent in agents:
        if AGENT_SPECS[agent].skills not in targets:
            targets.append(AGENT_SPECS[agent].skills)
    installed = [SKILL_TARGETS[target][1](root) for target in targets]
    if mcp:
        installed += [install_mcp_config(agent, root, package_dir) for agent in agents if agent in MCP_CONFIGS]
    if instructions:
        installed.append(install_instructions(root, package_dir))
        if "gemini" in agents:
            installed.append(install_gemini_context(root))
    return any(installed)


# --- AGENTS.md -----------------------------------------------------------------
#
# The project instructions nearly every coding agent reads before it does
# anything: `AGENTS.md` at the root of the repository. The skills say how to do
# a kind of work, but an agent has to know they exist, and that this repository
# is a PartCAD package at all, before it would think to look -- and an agent
# that has neither skills nor MCP still reads this file. So PartCAD writes a
# section of it: what the package is, how to run `pc` so its output can be read,
# how to check a change, and which skills there are.
#
# The file is the user's. PartCAD owns the text between its two markers and
# nothing else: a re-run replaces that section, and every line outside it --
# the rest of the user's instructions -- is left exactly as it was. The begin
# marker carries the version that wrote it, which is what `pc healthcheck` reads,
# for the same reason the Cursor copies carry a stamp.

CLAUDE_MD = CLAUDE_MD_NAME

_SECTION_BEGIN = "<!-- BEGIN partcad %s: written by 'pc init --skills-only', which replaces this section -->"
_SECTION_BEGIN_RE = re.compile(r"^<!-- BEGIN partcad (?P<version>\S+?):? .*-->[ \t]*$", re.MULTILINE)
_SECTION_END = "<!-- END partcad -->"
_SECTION_END_RE = re.compile(r"^<!-- END partcad -->[ \t]*$", re.MULTILINE)

# How Claude Code is pointed at `AGENTS.md`: it reads `CLAUDE.md`, and a line of
# that file that is `@<path>` imports another. One line rather than a copy of the
# section, so there is one text and nothing to fall out of step.
CLAUDE_IMPORT = "@" + AGENTS_MD


def instructions_version(text: str) -> Optional[str]:
    """The PartCAD version that wrote the section in this `AGENTS.md`, or None if it has none."""
    found = _SECTION_BEGIN_RE.search(text)
    return found.group("version") if found else None


def instructions_section(root: str, package_dir: str) -> str:
    """PartCAD's section of `AGENTS.md` in `root`, for the package in `package_dir` and the skills installed there."""
    relative = os.path.relpath(os.path.abspath(package_dir), os.path.abspath(root)).replace(os.sep, "/")
    at_root = relative == os.curdir
    package = "`partcad.yaml`" if at_root else "`%s/partcad.yaml`" % relative
    pc = "pc --no-ansi" if at_root else "pc --no-ansi -p %s" % relative

    lines = [
        _SECTION_BEGIN % __version__,
        "## PartCAD",
        "",
        "This repository holds a [PartCAD](https://partcad.org) package: %s declares its parts, sketches," % package,
        "assemblies, scenes and interfaces, each made by a script (build123d, CadQuery, OpenSCAD, ...) or read from a",
        "file (STEP, STL, ...), and the packages it imports. Objects are named `//package/path:name`.",
        "",
        "- Drive PartCAD with its command line tool, `pc`, or with its MCP server, `pc mcp`, where it is configured.",
        "  Run `pc` as `%s <command>` and capture both streams (`2>&1`): without `--no-ansi` it draws" % pc,
        "  progress bars whose control characters corrupt captured output. `pc <command> --help` says the rest.",
        "- To create or change an object, edit `partcad.yaml` and the object's script with your own file tools.",
        "- Check every change. `pc qual test <object>` builds an object and holds it to its declared requirements,",
        "  but it cannot say whether the shape is the one that was asked for: render it from more than one angle",
        "  (`pc render -t png --view iso <object>`, then `front`, `top`, `right`) and look at the pictures.",
        "- Before generating, validating, rendering, exporting or converting, read PartCAD's skill for that kind of",
        "  work and follow it. `pc mcp` serves every one of them, as its `pc-<skill>` prompts and through its",
        "  `skill` tool; `/pc:<skill>` and `pc-<skill>` name the same skill.%s" % _where_the_skills_are(root),
        "",
    ]
    skills = available_skills()
    for skill in skills:
        try:
            meta = agent_skills.front_matter(agent_skills.read_skill(skill, SKILLS_DIR))
        except (OSError, UnicodeDecodeError):
            continue
        description = agent_skills.rename_references(agent_skills.summary(meta.get("description")), skills)
        lines.append("  - `%s%s`: %s" % (agent_skills.PREFIX, skill, description))
    lines += ["", _SECTION_END]
    return "\n".join(lines) + "\n"


def _where_the_skills_are(root: str) -> str:
    """Where in `root` the skills are installed, as the rest of the `AGENTS.md` line that introduces them.

    Read off the repository rather than off the agents this run installed for:
    the section is rewritten by every run, and a run for one agent must not drop
    the directories an earlier run wrote for another. Each directory is listed
    with every agent that reads it, which for `.agents/skills` is most of them.
    """
    places = []
    for target, (directory, _) in SKILL_TARGETS.items():
        if target == "claude":
            directory = os.path.join(directory, plugin_name(), "skills")
        path = os.path.join(root, directory)
        if not os.path.isdir(path) or not any(
            name.startswith(CURSOR_PREFIX) or target == "claude" for name in os.listdir(path)
        ):
            continue
        titles = [spec.title for spec in AGENT_SPECS.values() if spec.skills == target]
        places.append("\n  - in `%s/`, for %s" % (directory.replace(os.sep, "/"), ", ".join(titles)))
    if not places:
        return " They are:"
    return " They are installed%s\n\n  and they are:" % "".join(places)


def _replace_section(text: str, section: str) -> str:
    """`text` with PartCAD's section replaced by `section`, or with `section` appended where it has none."""
    begin = _SECTION_BEGIN_RE.search(text)
    end = _SECTION_END_RE.search(text, begin.end()) if begin else None
    if begin is not None and end is not None:
        tail = text[end.end() :]
        return text[: begin.start()] + section.rstrip("\n") + (tail if tail else "\n")
    if not text.strip():
        return section
    return text.rstrip("\n") + "\n\n" + section


def install_instructions(root: str, package_dir: str) -> bool:
    """Write PartCAD's section of `AGENTS.md` under `root`, and point Claude Code's `CLAUDE.md` at it.

    Returns True when the section is in place. A symbolic link is refused, as
    every destination here is: a linked `AGENTS.md` is a file shared with
    something else, which is not this repository's to write into.
    """
    path = os.path.join(root, AGENTS_MD)
    if os.path.islink(path):
        pc_logging.warning("Not writing the PartCAD section: '%s' is a symbolic link" % path)
        return False

    text = ""
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError) as e:
            pc_logging.warning("Not writing the PartCAD section into '%s', which cannot be read: %s" % (path, e))
            return False

    updated = _replace_section(text, instructions_section(root, package_dir))
    if updated != text:
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(updated)
        except OSError as e:
            pc_logging.warning("Failed to write the PartCAD section into '%s': %s" % (path, e))
            return False
        pc_logging.info("Wrote the PartCAD section of '%s'" % path)

    # Whoever has a `CLAUDE.md` uses Claude Code, whatever this run was asked to install for.
    _import_into_claude_md(root)
    return True


def _import_into_claude_md(root: str) -> None:
    """Make Claude Code read `AGENTS.md` where a `CLAUDE.md` would stop it.

    Claude Code reads `AGENTS.md` on its own only where there is no `CLAUDE.md`;
    where there is one, it reads that alone, and a line `@AGENTS.md` in it is the
    documented way to bring `AGENTS.md` in. So a missing `CLAUDE.md` is left
    missing, one that is a link (to `AGENTS.md`, as PartCAD's own is) or already
    imports it is left alone, and any other gets that one line appended.
    """
    path = os.path.join(root, CLAUDE_MD)
    if os.path.islink(path) or not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as e:
        pc_logging.warning("Not pointing '%s' at %s: %s" % (path, AGENTS_MD, e))
        return
    if re.search(r"^@(\./)?%s[ \t]*$" % re.escape(AGENTS_MD), text, re.MULTILINE):
        return
    updated = (text.rstrip("\n") + "\n\n" if text.strip() else "") + CLAUDE_IMPORT + "\n"
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(updated)
    except OSError as e:
        pc_logging.warning("Failed to point '%s' at %s: %s" % (path, AGENTS_MD, e))
        return
    pc_logging.info("Pointed '%s' at %s" % (path, AGENTS_MD))
