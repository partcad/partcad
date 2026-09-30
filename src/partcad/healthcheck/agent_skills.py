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
`version` moves with the release. Cursor has no manifest, so the skills carry a
`metadata.partcad` stamp instead -- see `STAMP_KEY` in `partcad.ai_agents`, and
the note there about why neither of those is a literal anybody has to remember
to bump.
"""

import json
import os

from .. import __version__, ai_agents
from ..launch_config import find_repository_root
from .tests import HealthCheckReport, HealthCheckTest


class AgentSkillsCheck(HealthCheckTest):
    """Report AI agent skills that an older PartCAD installed."""

    def __init__(self):
        super().__init__(
            name="AgentSkills",
            tags=["skills", "agents", "claude", "cursor"],
            description="check whether the installed AI agent skills match this PartCAD",
        )
        # Where `pc init` would have put them: the repository holding the
        # current directory, or the directory itself when it is in none.
        self._root = find_repository_root(os.getcwd()) or os.path.abspath(os.getcwd())
        self._stale: list[str] = []

    def auto_fixable(self) -> bool:
        return True

    def _claude_plugin(self) -> str:
        return os.path.join(self._root, ai_agents.CLAUDE_SKILLS_DIR, ai_agents.plugin_name())

    def _cursor_skills(self) -> str:
        return os.path.join(self._root, ai_agents.CURSOR_SKILLS_DIR)

    def is_applicable(self) -> bool:
        """Only where somebody has installed them. Absent is not stale."""
        if os.path.isdir(self._claude_plugin()):
            return True
        cursor = self._cursor_skills()
        if not os.path.isdir(cursor):
            return False
        return any(name.startswith(ai_agents.CURSOR_PREFIX) for name in os.listdir(cursor))

    def _claude_version(self):
        """The version in the installed plugin manifest, or None if unreadable."""
        manifest = os.path.join(self._claude_plugin(), ai_agents.CLAUDE_PLUGIN_DIR, "plugin.json")
        try:
            with open(manifest, "r", encoding="utf-8") as f:
                return json.load(f).get("version")
        except (OSError, UnicodeDecodeError, ValueError):
            return None

    def _cursor_versions(self) -> dict:
        """The stamp on each installed Cursor skill that carries one.

        A skill with no stamp is not reported: it is either a user's own or one
        an older PartCAD wrote before stamping existed, and neither is something
        to tell the user is out of date. `partcad.ai_agents` leaves both alone
        for the same reason.
        """
        versions = {}
        cursor = self._cursor_skills()
        if not os.path.isdir(cursor):
            return versions

        for name in sorted(os.listdir(cursor)):
            if not name.startswith(ai_agents.CURSOR_PREFIX):
                continue
            try:
                with open(os.path.join(cursor, name, "SKILL.md"), "r", encoding="utf-8") as f:
                    stamp = ai_agents.stamped_version(f.read())
            except (OSError, UnicodeDecodeError):
                continue
            if stamp is not None:
                versions[name] = stamp
        return versions

    def test(self) -> HealthCheckReport:
        self.findings = []
        self._stale = []

        claude = self._claude_version()
        if claude is not None and claude != __version__:
            self._stale.append("claude")
            self.findings.append(
                "The Claude plugin in '%s' is from PartCAD %s; this is %s"
                % (self._claude_plugin(), claude, __version__)
            )

        outdated = sorted({name for name, stamp in self._cursor_versions().items() if stamp != __version__})
        if outdated:
            self._stale.append("cursor")
            self.findings.append(
                "%d Cursor skill(s) in '%s' are from an older PartCAD: %s"
                % (len(outdated), self._cursor_skills(), ", ".join(outdated))
            )

        if self.findings:
            self.findings.append("Run 'pc init --skills-only' to update them")

        return HealthCheckReport(self.name, self.findings)

    def fix(self) -> bool:
        """Reinstall for the agents that were found stale, and only those.

        Installing for an agent whose skills are not here would be creating a
        `.cursor/skills` for somebody who does not use Cursor, which is not a
        repair.
        """
        if not self._stale:
            return True
        return ai_agents.install_agent_skills(self._root, self._stale)
