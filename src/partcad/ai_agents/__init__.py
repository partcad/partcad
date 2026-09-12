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

# The manifest directory Claude Code identifies a plugin by.
CLAUDE_PLUGIN_DIR = ".claude-plugin"

# What a Cursor skill of ours is called, and what the plugin calls it. The
# prefix is the plugin's name because they are the same skill: `/pc:init` in
# Claude Code is `pc-init` in Cursor.
CURSOR_PREFIX = "pc-"

# The front matter key the Cursor copies are stamped with, under `metadata:`.
# Two things depend on it and neither has another way to know:
#
#   * staleness -- the skills a user has are the ones the PartCAD that wrote
#     them shipped, and nothing else in a `.cursor/skills` directory says which
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
STAMP_KEY = "partcad"
STAMP_SECTION = "metadata"


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


def _stamp(front_matter: str, version: str) -> str:
    """Return `front_matter` carrying `metadata.partcad: <version>`.

    Inserted as text rather than by parsing and re-dumping the YAML: a round
    trip through a parser reflows the long `description:` line every skill has
    and reorders the keys, so every install would rewrite files it did not
    change. An existing `metadata:` block is added to rather than replaced --
    the skills in this repository have none, but an author's may.
    """
    line = "%s: %s" % (STAMP_KEY, version)

    section = re.search(r"^%s:[ \t]*$" % re.escape(STAMP_SECTION), front_matter, re.MULTILINE)
    if section is None:
        separator = "" if front_matter.endswith("\n") else "\n"
        return front_matter + separator + "%s:\n  %s\n" % (STAMP_SECTION, line)

    body = front_matter[section.end() :]
    # The indentation the block already uses, so that this belongs to it.
    nested = re.match(r"\n([ \t]+)\S", body)
    indent = nested.group(1) if nested else "  "

    existing = re.search(r"^%s%s:[ \t]*.*$" % (re.escape(indent), re.escape(STAMP_KEY)), body, re.MULTILINE)
    if existing is not None:
        start = section.end() + existing.start()
        end = section.end() + existing.end()
        return front_matter[:start] + indent + line + front_matter[end:]

    return front_matter[: section.end()] + "\n" + indent + line + front_matter[section.end() :]


def stamped_version(text: str) -> Optional[str]:
    """The PartCAD version that wrote this skill, or None if nothing did.

    None is the answer for a skill a user wrote themselves *and* for one an
    older PartCAD installed before it stamped anything. Both are left alone by
    everything that reads this, which is the safe direction: the cost is a
    retired skill lingering for somebody who has not reinstalled since, and the
    alternative is deleting a file PartCAD may not have written.
    """
    bounds = _front_matter_bounds(text)
    if bounds is None:
        return None
    start, end = bounds
    found = re.search(
        r"^[ \t]+%s:[ \t]*(?P<version>\S+)[ \t]*$" % re.escape(STAMP_KEY),
        text[start:end],
        re.MULTILINE,
    )
    return found.group("version") if found else None


def rename_skill(text: str, name: str, skills: list[str], version: Optional[str] = None) -> str:
    """Return `text` as the skill `name`, for an agent with no plugin namespace.

    Three things change, and only these three. The `name` in the front matter,
    which has to match the directory the skill is installed in or it answers to
    a command nobody typed. Every `pc:<skill>` in the text -- `/pc:setup` in
    prose, `# pc:init` as a title -- which names a skill through the plugin
    namespace that does not exist here. And the stamp, which says which PartCAD
    wrote the file and marks it as PartCAD's to replace or retire.

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
        if version is not None:
            front_matter = _stamp(front_matter, version)
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


# Every agent this knows how to install for, and what installing means for it.
# The skills themselves are vendor-neutral `SKILL.md` folders, so an agent is
# added here by teaching this one function where its directory is and whether it
# has a namespace of its own -- not by writing a second copy of the library.
AGENTS = {
    "claude": install_claude_plugin,
    "cursor": install_cursor_skills,
}


def install_agent_skills(package_dir: str = ".", agents=None) -> bool:
    """Install the skills for `agents`, beside the package in `package_dir`.

    The files go to the root of the git repository holding the package, because
    that is what an editor opens as its workspace; when the package is not in a
    repository, they go next to the package itself. This is the same root
    `add_render_configuration` writes into, and for the same reason.

    `agents` is the names to install for, defaulting to all of them. An unknown
    name is an error rather than a no-op: a typo that silently installs nothing
    looks exactly like an agent PartCAD does not support yet.

    Returns True when anything was installed. Nothing here is a reason for
    `pc init` to fail -- the package is created either way -- so every failure
    is reported and returns False.
    """
    if agents is None:
        agents = list(AGENTS)

    unknown = [agent for agent in agents if agent not in AGENTS]
    if unknown:
        pc_logging.error("Unknown agent(s): %s. Known: %s" % (", ".join(sorted(unknown)), ", ".join(sorted(AGENTS))))
        return False

    root = find_repository_root(package_dir) or os.path.abspath(package_dir)
    # Every one of them runs: a refusal for one agent is not a reason to skip
    # the next, so this must not short-circuit the way `and`/`or` would.
    installed = [AGENTS[agent](root) for agent in agents]
    return any(installed)
