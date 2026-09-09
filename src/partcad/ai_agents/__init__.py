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

Two consumers, and they are not given the same thing:

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

Neither destination is written through a symlink. `.claude/skills/pc` is a
symlink in PartCAD's own repository -- to `ai-agents/claude`, so that a session
opened here loads the plugin from the working tree -- and following it would
have `pc init` overwrite the source tree with a copy of itself.
"""

import json
import os
import re
import shutil
from typing import Optional

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

# The manifest directory Claude Code identifies a plugin by.
CLAUDE_PLUGIN_DIR = ".claude-plugin"

# What a Cursor skill of ours is called, and what the plugin calls it. The
# prefix is the plugin's name because they are the same skill: `/pc:init` in
# Claude Code is `pc-init` in Cursor.
CURSOR_PREFIX = "pc-"


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


def _front_matter_bounds(text: str) -> Optional[tuple[int, int]]:
    """The offsets of the YAML front matter body, or None if there is none.

    Front matter is the block between the first two `---` lines, and it has to
    start at the very beginning of the file -- a `---` further down is a
    horizontal rule.
    """
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    return 4, end + 1


def rename_skill(text: str, name: str, skills: list[str]) -> str:
    """Return `text` as the skill `name`, for an agent with no plugin namespace.

    Two things change, and only these two. The `name` in the front matter, which
    has to match the directory the skill is installed in or it answers to a
    command nobody typed. And every `pc:<skill>` in the text -- `/pc:setup` in
    prose, `# pc:init` as a title -- which names a skill through the plugin
    namespace that does not exist here.

    `skills` is what makes the second one safe: only the names actually shipped
    are rewritten, so a `pc:` that is something else, and the `pc render` and
    `pc adhoc convert` command lines that fill these files, are left alone.
    """
    bounds = _front_matter_bounds(text)
    if bounds is not None:
        start, end = bounds
        front_matter = re.sub(
            r"^name:[ \t]*\S.*$",
            "name: %s" % name,
            text[start:end],
            count=1,
            flags=re.MULTILINE,
        )
        text = text[:start] + front_matter + text[end:]

    if skills:
        text = re.sub(
            r"\bpc:(%s)\b" % "|".join(re.escape(skill) for skill in sorted(skills, key=len, reverse=True)),
            lambda match: CURSOR_PREFIX + match.group(1),
            text,
        )

    return text


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

    pc_logging.info("Installed the '%s' plugin (%d skills) into '%s'" % (name, len(skills), destination))
    return True


def install_cursor_skills(root: str) -> bool:
    """Install the skills into `root` for Cursor, prefixed and renamed.

    One directory per skill under `.cursor/skills`, named `pc-<skill>`. Returns
    True when at least one skill was written.
    """
    destination = os.path.join(root, CURSOR_SKILLS_DIR)
    if not _writable_destination(destination, "the Cursor skills"):
        return False

    skills = available_skills()
    if not skills:
        pc_logging.warning("Not installing the Cursor skills: no skills are installed with PartCAD")
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
                f.write(rename_skill(text, name, skills))
        except OSError as e:
            pc_logging.warning("Failed to install '%s' into '%s': %s" % (name, target, e))
            continue
        installed += 1

    if not installed:
        return False

    pc_logging.info("Installed %d skills into '%s' as '%s*'" % (installed, destination, CURSOR_PREFIX))
    return True


def install_agent_skills(package_dir: str = ".") -> bool:
    """Install the skills for every agent, beside the package in `package_dir`.

    The files go to the root of the git repository holding the package, because
    that is what an editor opens as its workspace; when the package is not in a
    repository, they go next to the package itself. This is the same root
    `add_render_configuration` writes into, and for the same reason.

    Returns True when anything was installed. Nothing here is a reason for
    `pc init` to fail -- the package is created either way -- so every failure
    is reported and returns False.
    """
    root = find_repository_root(package_dir) or os.path.abspath(package_dir)
    # `or` short-circuits, and both of these have to run.
    claude = install_claude_plugin(root)
    cursor = install_cursor_skills(root)
    return claude or cursor
