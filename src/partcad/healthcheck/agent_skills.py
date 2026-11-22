#
# PartCAD, 2026
#
# Author: PartCAD (support@partcad.org)
# Created: 2026-09-11
#
# Licensed under Apache License, Version 2.0.
#

"""The AI agent skills installed in this repository, against the PartCAD running.

`pc init` installs the skills out of the PartCAD that runs it, so they match it
exactly -- on the day they are installed. `pc upgrade` then replaces PartCAD and
leaves them where they are, and nothing says a word: an agent goes on reading
instructions written for a CLI that has moved on, which is worse than having no
skills at all, because a stale skill looks like a working one.

This is the thing that says the word. It compares what is installed against the
version running and offers to reinstall, which is `pc init --skills-only` and
which also retires whatever PartCAD has stopped shipping.

Each agent is asked in its own terms. Claude Code has the plugin manifest, whose
`version` moves with the release. The others -- `.cursor/skills`,
`.agents/skills`, `.kiro/skills` -- have no manifest, so the skills carry a
`metadata.partcad` stamp instead, and the `AGENTS.md` section carries the version
in its opening marker -- see `STAMP_KEY` in `partcad.ai_agents`, and
the note there about why neither of those is a literal anybody has to remember
to bump.
"""

import json
import os

from .. import __version__, ai_agents
from ..launch_config import editor_folder
from .tests import HealthCheckReport, HealthCheckTest


class AgentSkillsCheck(HealthCheckTest):
    """Report AI agent skills, and the `AGENTS.md` section, that an older PartCAD installed."""

    def __init__(self):
        super().__init__(
            name="AgentSkills",
            tags=["skills", "agents", "claude", "cursor", "copilot", "codex", "gemini", "kiro"],
            description="check whether the installed AI agent skills match this PartCAD",
        )
        # Where they are: see `_installation_folder`.
        self._root = self._installation_folder(os.getcwd())
        # What was found stale: the `SKILL_TARGETS` to reinstall, and whether
        # the `AGENTS.md` section is one of them.
        self._stale: list[str] = []
        self._stale_instructions = False

    def auto_fixable(self) -> bool:
        return True

    def _claude_plugin(self) -> str:
        return os.path.join(self._root, ai_agents.CLAUDE_SKILLS_DIR, ai_agents.plugin_name())

    def _prefixed_targets(self) -> dict:
        """Every place prefixed skills are installed, by `SKILL_TARGETS` name: `.cursor/skills`, `.agents/skills`, ..."""
        return {
            target: os.path.join(self._root, directory)
            for target, (directory, _) in ai_agents.SKILL_TARGETS.items()
            if target != "claude"
        }

    def _agents_md(self) -> str:
        return os.path.join(self._root, ai_agents.AGENTS_MD)

    @classmethod
    def _installation_folder(cls, start: str) -> str:
        """The folder the skills `start` is under were installed in, or where `pc init` would put them.

        Looked for from `start` upwards, nearest first, because the folder
        `pc init` writes into by default -- the repository's root, or the
        PartCAD root outside one -- is not the only place they can be: `pc init
        --editor-folder` (or the editor extension) may have put them in a folder
        inside the repository or in one above it holding several, and outside a
        repository an older PartCAD put them beside the package, subpackage or
        not. Never in the home directory itself, whose `.claude/skills` is a
        user's own, for every project. A repair writes where they were found.
        """
        default = editor_folder(start)
        home = os.path.abspath(os.path.expanduser("~"))
        current = os.path.abspath(start)
        while current != home:
            if cls._installed_in(current):
                return current
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
        return default

    @staticmethod
    def _installed_in(folder: str) -> bool:
        """Whether any of PartCAD's skills, or its `AGENTS.md` section, are installed in `folder`."""
        if os.path.isdir(os.path.join(folder, ai_agents.CLAUDE_SKILLS_DIR, ai_agents.plugin_name())):
            return True
        try:
            with open(os.path.join(folder, ai_agents.AGENTS_MD), "r", encoding="utf-8") as f:
                if ai_agents.instructions_version(f.read()) is not None:
                    return True
        except (OSError, UnicodeDecodeError):
            pass
        for target, (directory, _) in ai_agents.SKILL_TARGETS.items():
            path = os.path.join(folder, directory)
            if target != "claude" and os.path.isdir(path) and AgentSkillsCheck._prefixed_versions(path):
                return True
        return False

    def is_applicable(self) -> bool:
        """Only where somebody has installed them. Absent is not stale."""
        return self._installed_in(self._root)

    def _claude_version(self):
        """The version in the installed plugin manifest, or None if unreadable."""
        manifest = os.path.join(self._claude_plugin(), ai_agents.CLAUDE_PLUGIN_DIR, "plugin.json")
        try:
            with open(manifest, "r", encoding="utf-8") as f:
                return json.load(f).get("version")
        except (OSError, UnicodeDecodeError, ValueError):
            return None

    def _instructions_version(self):
        """The version that wrote the PartCAD section of `AGENTS.md`, or None where there is none."""
        try:
            with open(self._agents_md(), "r", encoding="utf-8") as f:
                return ai_agents.instructions_version(f.read())
        except (OSError, UnicodeDecodeError):
            return None

    @staticmethod
    def _prefixed_versions(directory: str) -> dict:
        """The stamp on each installed prefixed skill in `directory` that carries one.

        A skill with no stamp is not reported: it is either a user's own or one
        an older PartCAD wrote before stamping existed, and neither is something
        to tell the user is out of date. `partcad.ai_agents` leaves both alone
        for the same reason.
        """
        versions = {}
        if not os.path.isdir(directory):
            return versions

        for name in sorted(os.listdir(directory)):
            if not name.startswith(ai_agents.CURSOR_PREFIX):
                continue
            try:
                with open(os.path.join(directory, name, "SKILL.md"), "r", encoding="utf-8") as f:
                    stamp = ai_agents.stamped_version(f.read())
            except (OSError, UnicodeDecodeError):
                continue
            if stamp is not None:
                versions[name] = stamp
        return versions

    def _cursor_versions(self) -> dict:
        """The stamps on the Cursor skills (see `_prefixed_versions`)."""
        return self._prefixed_versions(self._prefixed_targets()["cursor"])

    def test(self) -> HealthCheckReport:
        self.findings = []
        self._stale = []
        self._stale_instructions = False

        claude = self._claude_version()
        if claude is not None and claude != __version__:
            self._stale.append("claude")
            self.findings.append(
                "The Claude plugin in '%s' is from PartCAD %s; this is %s"
                % (self._claude_plugin(), claude, __version__)
            )

        for target, directory in self._prefixed_targets().items():
            outdated = sorted(
                {name for name, stamp in self._prefixed_versions(directory).items() if stamp != __version__}
            )
            if outdated:
                self._stale.append(target)
                self.findings.append(
                    "%d skill(s) in '%s' are from an older PartCAD: %s"
                    % (len(outdated), directory, ", ".join(outdated))
                )

        written = self._instructions_version()
        if written is not None and written != __version__:
            self._stale_instructions = True
            self.findings.append(
                "The PartCAD section of '%s' is from PartCAD %s; this is %s" % (self._agents_md(), written, __version__)
            )

        if self.findings:
            self.findings.append("Run 'pc init --skills-only' to update them")

        return HealthCheckReport(self.name, self.findings)

    def fix(self) -> bool:
        """Reinstall what was found stale, and only that.

        Installing for an agent whose skills are not here would be creating a
        `.cursor/skills` for somebody who does not use Cursor, which is not a
        repair; nor is writing an `AGENTS.md` section into a repository that
        had none.
        """
        if not self._stale and not self._stale_instructions:
            return True
        ok = True
        for target in self._stale:
            ok = ai_agents.SKILL_TARGETS[target][1](self._root) and ok
        if self._stale_instructions:
            # The package the section names is where it says it is: the one in
            # the repository, found the way `pc init` would find it.
            ok = ai_agents.install_instructions(self._root, self._package_dir()) and ok
        # The MCP entries `pc init` writes beside the skills are not stale when
        # the skills are, and a repair that recreates an `.mcp.json` its user
        # deleted is not one -- so they are not touched here.
        return ok

    def _package_dir(self) -> str:
        """The directory of the package the `AGENTS.md` section is about.

        The one its marker names, so that a repair run from anywhere in the
        repository writes the section for the package `pc init` wrote it for --
        not for the repository's root, which would drop the `-p` an agent needs.
        A section whose marker names none was written for the root.
        """
        try:
            with open(self._agents_md(), "r", encoding="utf-8") as f:
                package = ai_agents.instructions_package(f.read())
        except (OSError, UnicodeDecodeError):
            package = None
        if package:
            candidate = os.path.normpath(os.path.join(self._root, package))
            # Only inside the repository: the marker is text anybody can edit.
            try:
                inside = os.path.commonpath([candidate, self._root]) == self._root
            except ValueError:  # another drive, on Windows
                inside = False
            if inside:
                return candidate
        return self._root
