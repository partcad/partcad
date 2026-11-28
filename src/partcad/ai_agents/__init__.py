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

import hashlib
import json
import os
import re
import shutil
import textwrap
from dataclasses import dataclass
from typing import Optional

from partcad_utils import agent_config, agent_skills, app_image
from partcad_utils.pcignore import PACKAGE_FILE
from partcad_utils.workspace import determine_root_path

from .. import __version__
from .. import logging as pc_logging
from ..launch_config import editor_folder as default_editor_folder
from ..launch_config import relative_to

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


# The MCP server, `pc mcp`, in each agent's project configuration -- one entry per
# PartCAD root, because one `pc mcp` serves one root (one daemon, and one set of
# files the agent may use), and a repository can hold several. Three
# directories decide what an entry says, and none of them has to be another: the
# folder the editor or agent opens, where its configuration is and what
# `${workspaceFolder}` is (`partcad.launch_config.choose_editor_folder`); the git
# repository's root, which is only the default for it; and the PartCAD root the
# entry serves (`partcad_utils.workspace.determine_root_path`, which stops at a
# `.pcignore`).
#
# An entry is recognised by the root it serves rather than by its name, so
# running `pc init` again -- for that package, or for another package of the same
# root -- updates it where it is, and an entry an older release wrote is that
# entry. Its name is `partcad` when that is free, the one root most repositories
# have, wherever it is, and `partcad-<path>` otherwise (`server_name`). A name,
# once written, is never changed: an agent keys approvals and permission rules
# by it. Every other server in the file is somebody else's and is left alone.
MCP_SERVER_NAME = "partcad"

# Long enough for any path worth reading, short enough for every agent's limit
# on a server's name and a tool's together: Cursor's is 60 characters, and the
# longest tool `pc mcp` has is 13.
MAX_SERVER_NAME = 32


@dataclass(frozen=True)
class McpConfig:
    """Where an agent reads a project's MCP servers from, and how.

    `project` is how the file spells "the folder holding this file", which the
    server's `-p` is written relative to: Cursor resolves `${workspaceFolder}` to
    exactly that. Where it is None the agent has no such spelling, and the entry
    says `pc mcp --root <path>` instead, relative to the folder holding the file,
    which the server finds for itself (`partcad_utils.agent_config`). That is
    every other agent: Claude Code expands no variable of its own in
    `.mcp.json` (its `CLAUDE_PROJECT_DIR` is only in the server's environment),
    reads that file in the folders above the one it was started in, and starts
    the server in the one it was started in; the others start it in the project.
    """

    path: str
    # The key holding the servers, or the path of keys to it.
    key: object = "mcpServers"
    project: Optional[str] = None
    extra: tuple = ()
    toml: bool = False
    # The command as one array (`["pc", "-p", ..., "mcp"]`) rather than a
    # `command` and its `args`.
    command_array: bool = False
    # Other files the agent reads the same configuration from: the first of
    # them that exists is written instead of `path`, so that a repository using
    # one is not given a second.
    alternatives: tuple = ()
    # What a file created from nothing starts with, before the servers.
    preamble: tuple = ()
    # Where an older form of the configuration held the servers, by key path:
    # PartCAD's entry there is removed when it is written where they are now.
    legacy_key: tuple = ()

    def keys(self) -> tuple:
        return (self.key,) if isinstance(self.key, str) else tuple(self.key)

    def file(self, root: str) -> str:
        """The file to write under `root`: an existing alternative, or `path`."""
        for candidate in (self.path, *self.alternatives):
            if os.path.lexists(os.path.join(root, candidate)):
                return os.path.join(root, candidate)
        return os.path.join(root, self.path)


MCP_CONFIGS = {
    "claude": McpConfig(".mcp.json", extra=(("type", "stdio"),)),
    "cursor": McpConfig(os.path.join(".cursor", "mcp.json"), project="${workspaceFolder}"),
    "codex": McpConfig(os.path.join(".codex", "config.toml"), key="mcp_servers", toml=True),
    "gemini": McpConfig(os.path.join(".gemini", "settings.json")),
    "zed": McpConfig(os.path.join(".zed", "settings.json"), key="context_servers"),
    "kiro": McpConfig(os.path.join(".kiro", "settings", "mcp.json")),
    "devin": McpConfig(os.path.join(".devin", "mcp_config.json")),
    # OpenCode 2 nests servers under `mcp.servers` and describes one as a
    # `type` and a `command` array (`Mcp.LocalConfigEncoded` in
    # https://opencode.ai/config.json). The servers OpenCode 1 kept directly
    # under `mcp` still load, migrated, but that form is deprecated -- so an
    # entry of PartCAD's left there by hand is moved rather than duplicated.
    # A relative package is relative to the workspace, which is where OpenCode
    # starts a server unless told otherwise.
    "opencode": McpConfig(
        "opencode.json",
        key=("mcp", "servers"),
        extra=(("type", "local"),),
        command_array=True,
        alternatives=(
            "opencode.jsonc",
            os.path.join(".opencode", "opencode.json"),
            os.path.join(".opencode", "opencode.jsonc"),
        ),
        preamble=(("$schema", "https://opencode.ai/config.json"),),
        legacy_key=("mcp",),
    ),
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
}

# What the PartCAD image is given to mount, where the server runs in it: the
# folder holding the configuration, at the path it has on the host -- the whole
# folder rather than the root alone, because it holds the repository the
# revision tools read -- which Docker needs as an absolute path. Cursor's
# variable is that folder. Claude Code has none, so it is the directory Claude
# Code was started in, from its environment: right when that is the folder
# holding `.mcp.json`, and `pc mcp --root` inside the container refuses, saying
# where to start it, when it is not. Only these two: the other agents document no
# variable for it at all, which a mount cannot do without -- `install_mcp_config`
# says so for each of them rather than write an entry that cannot start.
MCP_DOCKER_PROJECT = {
    "claude": "${PWD}",
    "cursor": "${workspaceFolder}",
}

# The two ways an agent's configuration can start the server: the `pc` this
# machine has installed, or the PartCAD image (`partcad_utils.app_image`).
MCP_VIA_PC = "pc"
MCP_VIA_DOCKER = "docker"
MCP_VIA = (MCP_VIA_PC, MCP_VIA_DOCKER)


def default_mcp_via() -> str:
    """`docker` where `pc init` runs in the PartCAD image, whose user has no `pc` outside it; `pc` elsewhere."""
    return MCP_VIA_DOCKER if app_image.running_in_image() else MCP_VIA_PC


def _join(base: str, relative: str) -> str:
    return base if relative == "." else base + "/" + relative


def mcp_server_entry(agent: str, folder: str, root: str, via: str = MCP_VIA_PC) -> dict:
    """The entry, in `agent`'s configuration held by `folder`, that starts `pc mcp` for the PartCAD root `root`.

    The root is named relative to `folder`, never as an absolute path: the file
    is committed with the package and read on every machine that checks it out.
    For the same reason the command is `pc`, not an absolute path to it --
    PartCAD is wherever each machine installed it.

    With ``via`` set to `docker`, `docker run ... ghcr.io/partcad/partcad`
    instead, for the same reason one level up: what every machine is then asked
    for is Docker, and the image comes along. The image is named without a tag,
    so like `pc` it is whatever that machine last pulled. No Docker socket is
    passed: that hands the container the host's Docker, and is for a person to
    add knowingly (see "Docker" in the installation documentation).
    """
    if via not in MCP_VIA:
        raise ValueError("unknown way to start the MCP server: %r (expected one of %s)" % (via, ", ".join(MCP_VIA)))
    if via == MCP_VIA_DOCKER and agent not in MCP_DOCKER_PROJECT:
        raise ValueError("%s's configuration cannot name the absolute directory Docker has to mount" % agent)
    config = MCP_CONFIGS[agent]
    relative = relative_to(root, folder)
    if config.project is None:
        # And which file the entry is in, so that the server reads that one:
        # another agent's file between it and the folder could name the same path.
        source = relative_to(config.file(folder), folder)
        server = ["mcp", agent_config.ROOT_OPTION, relative, agent_config.SOURCE_OPTION, source]
    else:
        server = ["-p", _join(config.project, relative), "mcp"]
    if via == MCP_VIA_DOCKER:
        command = ["docker", *app_image.docker_run_args(MCP_DOCKER_PROJECT[agent], *server)]
    else:
        command = ["pc", *server]
    # Claude Code reads an entry with no "type" as stdio, and says so in its
    # documentation by always writing it out; OpenCode requires one, "local";
    # the others have no such field.
    if config.command_array:
        return {**dict(config.extra), "command": command}
    return {**dict(config.extra), "command": command[0], "args": command[1:]}


# Every spelling of "the folder holding this file" PartCAD has written into an
# entry, in this release or an earlier one: how the root an older entry serves is
# read back out of it.
PROJECT_SPELLINGS = ("${CLAUDE_PROJECT_DIR:-.}", "${CLAUDE_PROJECT_DIR}", "${PWD}", "${workspaceFolder}")

# The global option of `pc` that names a package, as PartCAD's entries use it.
PATH_OPTIONS = ("-p", "--path")

# An image of PartCAD's, by its name: `ghcr.io/partcad/partcad`, `mcp/partcad`
# (Docker's MCP Catalog), a fork's `ghcr.io/someone/partcad`, any of them tagged
# or pinned -- and not a host path that happens to end in `partcad`, which starts
# with a `/`.
_PARTCAD_IMAGE = re.compile(
    r"(?:[a-z0-9._-]+(?::[0-9]+)?/)*partcad(?::[\w][\w.-]{0,127})?(?:@sha256:[0-9a-f]{64})?", re.IGNORECASE
)

# The options of `docker run` whose value could look like an image name.
_DOCKER_VALUE_OPTIONS = ("--name", "--hostname", "-h", "--network", "--net", "--label", "-l", "--user", "-u")


def _command_line(entry) -> Optional[list]:
    """An entry's command and its arguments as one list, in either shape the configurations use."""
    if not isinstance(entry, dict):
        return None
    command, args = entry.get("command"), entry.get("args", [])
    if isinstance(command, list):
        line = command
    elif isinstance(args, list):
        line = [command, *args]
    else:
        return None
    return line if line and all(isinstance(arg, str) for arg in line) else None


def _partcad_arguments(line: list) -> Optional[list]:
    """The arguments PartCAD is given by the command `line`, or None when it does not start PartCAD.

    `pc` or `partcad`, by any path; `uvx` or `pipx run` of the `partcad`
    package; `docker run` (or `podman run`) of a PartCAD image. Anything else is
    somebody else's server, whatever it is called and whatever it is given.
    """
    program = os.path.basename(line[0].replace("\\", "/")).lower()
    if program.endswith(".exe"):
        program = program[: -len(".exe")]
    rest = line[1:]
    if program in ("pc", "partcad"):
        return rest
    if program in ("uvx", "pipx"):
        found = [index for index, arg in enumerate(rest) if re.fullmatch(r"partcad(?:[=@<>~!].*)?", arg)]
        return rest[found[0] + 1 :] if found else None
    if program in ("docker", "podman"):
        for index, arg in enumerate(rest):
            if _PARTCAD_IMAGE.fullmatch(arg) and (index == 0 or rest[index - 1] not in _DOCKER_VALUE_OPTIONS):
                return rest[index + 1 :]
    return None


def served_directory(entry, folder: str) -> Optional[str]:
    """The directory an entry in the configuration held by `folder` has `pc mcp` serve, or None.

    Read the way PartCAD has written entries -- `pc mcp --root <path>` and
    `pc -p <folder>/<path> mcp`, with any of `PROJECT_SPELLINGS` for the folder,
    or the path alone -- run directly or in the image, and a path written out by
    hand. An entry with no path at all serves the directory it is started in,
    which for these agents is `folder`. An entry that does not start PartCAD, or
    names its directory some other way, is not something PartCAD wrote, and None
    leaves it alone.
    """
    line = _command_line(entry)
    arguments = _partcad_arguments(line) if line else None
    if arguments is None or "mcp" not in arguments:
        return None

    root = agent_config.root_argument(arguments)
    if root is not None:
        return os.path.normpath(os.path.join(folder, root))

    mcp = len(arguments) - 1 - arguments[::-1].index("mcp")
    if mcp >= 2 and arguments[mcp - 2] in PATH_OPTIONS:
        value = arguments[mcp - 1]
        for spelling in PROJECT_SPELLINGS:
            if value == spelling or value.startswith(spelling + "/"):
                return _package_directory(os.path.join(folder, value[len(spelling) :].lstrip("/")))
        if "${" in value:
            return None
        return _package_directory(os.path.join(folder, value))
    if any(arg in PATH_OPTIONS for arg in arguments[:mcp]):
        return None
    return os.path.normpath(folder)


def _package_directory(path: str) -> str:
    """The directory `pc -p <path>` loads: `-p` names a package's directory or its `partcad.yaml`."""
    path = os.path.normpath(path)
    return os.path.dirname(path) if os.path.basename(path).lower().endswith((".yaml", ".yml")) else path


def is_partcad_name(name) -> bool:
    """Whether `name` is one PartCAD gives its entries."""
    return isinstance(name, str) and (name == MCP_SERVER_NAME or name.startswith(MCP_SERVER_NAME + "-"))


def _same(a: str, b: str) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def server_name(root: str, folder: str, taken) -> str:
    """The name for a new entry serving `root`, one not in `taken`.

    `partcad` if it is free. Otherwise `partcad-` and the root's path relative
    to `folder` -- `partcad-packages-robot` -- in the characters every agent
    accepts in a name (Claude Code's are letters, digits, `-` and `_`), cut
    short with a hash of the path when it would be too long to read.
    """
    if MCP_SERVER_NAME not in taken:
        return MCP_SERVER_NAME
    relative = relative_to(root, folder)
    words = relative if relative != "." else os.path.basename(os.path.abspath(root))
    slug = re.sub(r"[^A-Za-z0-9_]+", "-", words).strip("-_") or "root"
    base = "%s-%s" % (MCP_SERVER_NAME, slug)
    if len(base) > MAX_SERVER_NAME:
        digest = hashlib.sha1(relative.encode("utf-8")).hexdigest()[:6]
        base = "%s-%s" % (base[: MAX_SERVER_NAME - len(digest) - 1].rstrip("-_"), digest)
    name, number = base, 2
    while name in taken:
        name = "%s-%d" % (base, number)
        number += 1
    return name


def _claimed(servers: dict, folder: str, root: str) -> tuple:
    """PartCAD's entries in `servers` that serve `root`, and those that serve a directory that is gone."""
    mine, gone = [], []
    for name, existing in servers.items():
        if not is_partcad_name(name):
            continue
        directory = served_directory(existing, folder)
        if directory is None:
            continue
        if not os.path.isdir(directory):
            gone.append(name)
        elif _same(determine_root_path(directory), root):
            mine.append(name)
    return mine, gone


def _plan(servers: dict, folder: str, root: str, keep: Optional[str] = None) -> tuple:
    """The name for the entry serving `root` among `servers`, and the names of PartCAD's entries to remove.

    The entry already serving the root keeps its name; where there is none,
    `keep` -- the name it had in an older form of the file -- if it is free.
    Another entry serving the root is a duplicate, and one serving a directory
    that is gone can only fail to start; both go. The name chosen is never one
    of them: an entry under it is replaced, not removed.
    """
    mine, gone = _claimed(servers, folder, root)
    removed = mine[1:] + gone
    if mine:
        name = mine[0]
    elif keep and keep not in set(servers) - set(gone):
        name = keep
    else:
        name = server_name(root, folder, set(servers) - set(removed))
    return name, [old for old in removed if old != name]


# Directories never looked into for PartCAD roots: hidden ones (`.git`, a
# virtual environment, an editor's settings) are skipped by their dot.
_NOT_SEARCHED = ("node_modules", "__pycache__")


def partcad_roots(directory: str) -> list:
    """The PartCAD roots to give entries to, for `pc init` run on `directory`.

    The root of the package `directory` is in, when it is in one. Otherwise --
    `pc init --skills-only` run at the top of a repository whose packages are in
    subfolders -- every root below it, and `directory` itself when there are
    none, because a server started where there is no package yet still starts
    and says so. A root's own subfolders are not looked into: what is below it
    is its subpackages, or folders it set apart with a `.pcignore`, whose
    packages get an entry when `pc init` is run on them.
    """
    directory = os.path.abspath(directory)
    root = determine_root_path(directory)
    if os.path.isfile(os.path.join(root, PACKAGE_FILE)):
        return [root]

    found = []
    for current, subdirectories, files in os.walk(directory):
        if current != directory and PACKAGE_FILE in files:
            found.append(current)
            subdirectories[:] = []
            continue
        subdirectories[:] = sorted(
            name for name in subdirectories if not name.startswith(".") and name not in _NOT_SEARCHED
        )
    return sorted(found) or [directory]


def install_mcp_config(agent: str, folder: str, served: str, via: str = MCP_VIA_PC) -> bool:
    """Add (or update) the entry for the PartCAD root of `served` in `agent`'s project configuration in `folder`.

    `served` is any directory of the root -- a package, a subpackage, the root
    itself; it is the root that gets the entry (see `_plan` for which entry,
    under which name). The file is merged into, never replaced: it is a list of
    servers, and the others in it belong to whoever put them there. A file that
    cannot be merged into -- not JSON (or TOML), or JSON with comments, or one
    without a mapping of servers -- is left as it is, with a warning, because
    rewriting it would lose whatever it holds; and so is a symbolic link, for
    the reason `_writable_destination` gives.
    """
    config = MCP_CONFIGS[agent]
    if via == MCP_VIA_DOCKER and agent not in MCP_DOCKER_PROJECT:
        # Docker needs the folder as an absolute path to mount, and this
        # agent's configuration has no way to spell one. Said rather than
        # written as something that cannot start.
        pc_logging.warning(
            "Not adding the PartCAD MCP server for %s as 'docker run': its configuration cannot name the "
            "project's directory, which Docker has to mount. Add it by hand (see 'Docker' in the installation "
            "documentation), or run 'pc init --mcp-via pc' where PartCAD is installed" % AGENT_SPECS[agent].title
        )
        return False
    path = config.file(folder)
    if os.path.islink(path):
        pc_logging.warning("Not adding the MCP server: '%s' is a symbolic link" % path)
        return False

    root = determine_root_path(served)
    relative = relative_to(root, folder)
    if via == MCP_VIA_DOCKER and relative.split("/")[0] == "..":
        pc_logging.warning(
            "The PartCAD root '%s' is outside '%s', which is all the PartCAD image is given: the server '%s' starts "
            "will not reach it. Run 'pc init --editor-folder' on a folder holding both" % (root, folder, path)
        )
    what = "the PartCAD MCP server for '%s'" % relative
    entry = mcp_server_entry(agent, folder, root, via)
    if config.toml:
        return _install_toml_server(path, config.key, entry, lambda servers: _plan(servers, folder, root), what)

    def add(document: dict) -> Optional[str]:
        if not document:
            document.update(dict(config.preamble))
        servers = document
        for key in config.keys():
            if not isinstance(servers.get(key, {}), dict):
                return "its '%s' is not an object to add to" % ".".join(config.keys())
            servers = servers.setdefault(key, {})
        # Where an older form of the configuration kept them (OpenCode 1's
        # `mcp`): PartCAD's entries there for this root, or for a folder that
        # is gone, are what this one replaces -- under the name it had there.
        legacy = document
        for key in config.legacy_key:
            legacy = legacy.get(key) if isinstance(legacy, dict) else None
        moved, before = [], None
        if config.legacy_key and isinstance(legacy, dict) and legacy is not servers:
            mine, gone = _claimed(legacy, folder, root)
            moved, before = mine + gone, (mine[0] if mine else None)
        name, removed = _plan(servers, folder, root, keep=before)
        for old in removed:
            del servers[old]
        for old in moved:
            del legacy[old]
        if servers.get(name) == entry and not removed and not moved:
            return ""
        servers[name] = entry
        return None

    return _merge_json(path, add, what)


def _merge_json(path: str, change, what: str) -> bool:
    """Apply `change` to the JSON object in `path` (an empty one when it does not exist) and write it back.

    `change` returns None when it changed the document, "" when there was
    nothing to change, and a reason when it refuses to. True when `what` is in
    place afterwards.
    """
    # Every caller, not only the MCP entry's: a linked settings file is one
    # shared with something else (see `_writable_destination`).
    if os.path.islink(path):
        pc_logging.warning("Not adding %s: '%s' is a symbolic link" % (what, path))
        return False
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
# A table header in a TOML file, `[name]` or an array-of-tables `[[name]]`,
# with its dotted name: each one ends the table before it.
_TOML_HEADER = re.compile(r"^[ \t]*\[\[?(?P<name>[^\[\]]+)\]\]?[ \t]*(?:#.*)?$", re.MULTILINE)


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


def _others(document: dict, key: str, names) -> dict:
    """`document` without the servers `names`: everything an edit of PartCAD's tables must leave as it was."""
    others = dict(document)
    servers = {name: value for name, value in dict(others.get(key) or {}).items() if name not in names}
    if servers:
        others[key] = servers
    else:
        others.pop(key, None)
    return others


def _toml_servers(text: str, key: str, parsed) -> dict:
    """The servers under `[<key>.<name>]` in the TOML `text`, by name.

    From the parsed document where there is a parser. Without one (Python 3.10
    without `tomli`), read off the tables the way `pc init` writes them -- a
    `command` and an `args` that are JSON on one line each -- which is all it
    needs to know to recognise its own; a table it cannot read that way is
    taken as somebody else's.
    """
    if parsed is not None:
        servers = parsed.get(key)
        return dict(servers) if isinstance(servers, dict) else {}
    servers = {}
    headers = list(_TOML_HEADER.finditer(text))
    for header, following in zip(headers, headers[1:] + [None]):
        path = _toml_key_path(header.group("name"))
        if len(path) != 2 or path[0] != key:
            continue
        body = text[header.end() : following.start() if following else len(text)]
        entry = {}
        for field in ("command", "args"):
            found = re.search(r"^[ \t]*%s[ \t]*=[ \t]*(.+?)[ \t]*$" % field, body, re.MULTILINE)
            try:
                entry[field] = json.loads(found.group(1)) if found else None
            except ValueError:
                entry[field] = None
        servers[path[1]] = entry
    return servers


def _install_toml_server(path: str, key: str, entry: dict, plan, what: str) -> bool:
    """Add (or update) PartCAD's `[<key>.<name>]` in the TOML file at `path` -- Codex's `.codex/config.toml`.

    `plan` is given the servers already there and says which name the entry
    goes under and which of PartCAD's tables go (see `_plan`).

    Edited as text, the way `launch_config` edits `launch.json`: a parse and
    re-dump would drop every comment in the file, and there is no TOML writer
    among PartCAD's dependencies. The tables PartCAD owns -- and any sub-table
    of them, such as an `env` -- are replaced or dropped whole; everything else
    is kept byte for byte. Where a parser is at hand the result is parsed before
    it is written, and a file this would break is left as it was.
    """
    text = ""
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError) as e:
            pc_logging.warning("Not adding %s to '%s', which cannot be read: %s" % (what, path, e))
            return False

    try:
        before = _toml_loads(text) if text.strip() else {}
    except Exception as e:  # pylint: disable=broad-except
        pc_logging.warning("Not adding %s to '%s', which is not valid TOML: %s" % (what, path, e))
        return False
    name, removed = plan(_toml_servers(text, key, before))
    table = "[%s.%s]\ncommand = %s\nargs = [%s]\n" % (
        key,
        name,
        json.dumps(entry["command"]),
        ", ".join(json.dumps(arg) for arg in entry["args"]),
    )

    # The file as the spans its headers start, each running to the next
    # header. PartCAD's are its tables and their sub-tables, wherever they are:
    # TOML lets `[mcp_servers.partcad.env]` come after somebody else's table,
    # so each span is replaced or dropped on its own and what lies between
    # them is kept.
    ours = [key, name]
    gone = [[key, old] for old in removed]
    headers = list(_TOML_HEADER.finditer(text))
    starts = [header.start() for header in headers]
    spans = list(zip(starts, starts[1:] + [len(text)]))
    pieces = [text[: starts[0]] if starts else text]
    replaced = False
    for header, (start, end) in zip(headers, spans):
        table_path = _toml_key_path(header.group("name"))[:2]
        if table_path in gone:
            continue
        if table_path != ours:
            pieces.append(text[start:end])
        elif not replaced:
            pieces.append(table + ("\n" if end < len(text) else ""))
            replaced = True
    if replaced:
        updated = "".join(pieces)
        if headers and _toml_key_path(headers[-1].group("name"))[:2] in gone:
            # The table that ended the file was dropped, and the one before it
            # kept the blank line that used to separate them.
            updated = updated.rstrip("\n") + "\n"
    else:
        kept = "".join(pieces)
        updated = (kept.rstrip("\n") + "\n\n" if kept.strip() else "") + table

    if updated == text:
        pc_logging.debug("'%s' already has %s" % (path, what))
        return True
    # The text edit finds tables by their header lines, and a header-shaped
    # line can also be text inside a multi-line string. So what the edit did is
    # checked by what it means: parsed before and after, the file has to be the
    # same everywhere but PartCAD's own tables, or it is left as it was. Without
    # a parser (Python 3.10 with no `tomli`) that cannot be checked, and a file
    # holding a multi-line string is left alone rather than edited unchecked.
    try:
        parsed = _toml_loads(updated)
    except Exception as e:  # pylint: disable=broad-except
        pc_logging.warning("Not adding %s to '%s': the file would not be valid TOML (%s)" % (what, path, e))
        return False
    if parsed is None and ('"""' in text or "'''" in text):
        pc_logging.warning(
            "Not adding %s to '%s': it holds a multi-line string, and there is no TOML parser here to check the edit"
            % (what, path)
        )
        return False
    touched = [name, *removed]
    if parsed is not None and _others(before, key, touched) != _others(parsed, key, touched):
        pc_logging.warning(
            "Not adding %s to '%s': editing it would change more than PartCAD's own tables; add it by hand"
            % (what, path)
        )
        return False
    if parsed is not None and (
        parsed.get(key, {}).get(name) != entry or any(old in parsed.get(key, {}) for old in removed)
    ):
        # A server of that name written some other way -- inline, under
        # `[mcp_servers]` -- which this edit cannot see to replace.
        pc_logging.warning("Not adding %s to '%s': it declares '%s' in a form this cannot edit" % (what, path, name))
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


def install_agent_skills(
    package_dir: str = ".",
    agents=None,
    mcp: bool = True,
    instructions: bool = True,
    mcp_via: Optional[str] = None,
    editor_folder: Optional[str] = None,
) -> bool:
    """Install the skills for `agents`, for the package in `package_dir`.

    The files go into `editor_folder`, the folder the editor or agent opens,
    because that is the only place any of them reads them from. Left out, it is
    the root of the git repository holding the package, or its PartCAD root
    outside one (`partcad.launch_config.editor_folder`): the same folder
    `add_render_configuration` writes into, for the same reason. `pc init`
    decides it with `partcad.launch_config.choose_editor_folder`.

    `agents` is the names to install for, defaulting to `default_agents`. An
    unknown name is an error rather than a no-op: a typo that silently installs
    nothing looks exactly like an agent PartCAD does not support yet. Agents that
    read one directory share one copy of the skills in it.

    `mcp` also adds the MCP server, `pc mcp`, to each agent's project
    configuration (see `install_mcp_config`): the skills say how to drive
    PartCAD, and the server is what an agent drives it through without a shell.
    The entry is for the PartCAD root of the package, beside any other root's;
    where `package_dir` is in no package, one for every root below it.
    `instructions` writes PartCAD's section of `AGENTS.md` (`install_instructions`).
    `mcp_via` is how that entry starts it, `pc` or `docker` (see
    `mcp_server_entry`); left out, `docker` inside the PartCAD image and `pc`
    everywhere else.

    Returns True when anything was installed. Nothing here is a reason for
    `pc init` to fail -- the package is created either way -- so every failure
    is reported and returns False.
    """
    folder = os.path.abspath(editor_folder) if editor_folder else default_editor_folder(package_dir)
    if agents is None:
        agents = default_agents(folder)
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
    installed = [SKILL_TARGETS[target][1](folder) for target in targets]

    try:
        relative_to(package_dir, folder)
    except ValueError:
        # Two Windows drives: there is no relative path from the one to the
        # other, and an absolute one would be this machine's in a shared file.
        pc_logging.warning(
            "Not adding the MCP server or the instructions to '%s': '%s' is on another drive, so they could not "
            "name it" % (folder, os.path.abspath(package_dir))
        )
        return any(installed)
    if mcp:
        via = mcp_via or default_mcp_via()
        roots = partcad_roots(package_dir)
        installed += [
            install_mcp_config(agent, folder, root, via) for agent in agents if agent in MCP_CONFIGS for root in roots
        ]
    if instructions:
        installed.append(install_instructions(folder, package_dir))
        if "gemini" in agents:
            installed.append(install_gemini_context(folder))
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

# The begin marker says which PartCAD wrote the section and which package it is
# about, relative to the repository root: a repair (`pc healthcheck --fix`) has
# to write it for the same package, from wherever it is run.
_SECTION_BEGIN = (
    "<!-- BEGIN partcad %s package=\"%s\": written by 'pc init --skills-only', which replaces this section -->"
)
_SECTION_BEGIN_RE = re.compile(
    r'^<!-- BEGIN partcad (?P<version>[^\s:]+)(?: package="(?P<package>[^"]*)")?:? .*-->[ \t]*$', re.MULTILINE
)
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


def instructions_package(text: str) -> Optional[str]:
    """The package the section in this `AGENTS.md` is about, relative to the repository root ('.' for the root).

    None where there is no section, or one whose marker does not say.
    """
    found = _SECTION_BEGIN_RE.search(text)
    return found.group("package") if found else None


def instructions_section(root: str, package_dir: str) -> str:
    """PartCAD's section of `AGENTS.md` in `root`, for the package in `package_dir` and the skills installed there."""
    relative = os.path.relpath(os.path.abspath(package_dir), os.path.abspath(root)).replace(os.sep, "/")
    at_root = relative == os.curdir
    package = "`partcad.yaml`" if at_root else "`%s/partcad.yaml`" % relative
    pc = "pc --no-ansi" if at_root else "pc --no-ansi -p %s" % relative

    lines = [
        _SECTION_BEGIN % (__version__, relative),
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
        *_bullet(agent_skills.issues_instruction()),
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


def _bullet(text: str) -> list:
    return textwrap.wrap(text, width=112, initial_indent="- ", subsequent_indent="  ", break_on_hyphens=False)


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
