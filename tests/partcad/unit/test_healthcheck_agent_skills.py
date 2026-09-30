#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""The healthcheck that notices AI agent skills an older PartCAD installed.

`pc init` installs them out of the PartCAD running it, so they match on the day
they are written. `pc upgrade` then replaces PartCAD and leaves them alone, and
an agent goes on reading instructions for a CLI that has moved -- silently,
because a stale skill looks exactly like a current one. This is what breaks the
silence, so what is checked here is mostly that it stays quiet when it should
and speaks when it should.
"""

import json

import pytest

import partcad
import partcad.ai_agents as ai_agents
from partcad.healthcheck.agent_skills import AgentSkillsCheck


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A repository the check will look at, as the current directory."""
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


def age_the_cursor_skill(workspace, name="pc-init", version="0.0.1"):
    """Rewrite one Cursor skill's stamp, the way an older install left it."""
    path = workspace / ".cursor" / "skills" / name / "SKILL.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("  partcad: %s" % partcad.__version__, "  partcad: %s" % version),
        encoding="utf-8",
    )


def age_the_plugin(workspace, version="0.0.1"):
    """And the Claude plugin manifest, which is where its version lives."""
    path = workspace / ".claude" / "skills" / "pc" / ".claude-plugin" / "plugin.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["version"] = version
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def test_it_does_not_apply_where_nothing_is_installed(workspace):
    """Absent is not stale. Most repositories have no skills in them at all."""
    assert not AgentSkillsCheck().is_applicable()


def test_it_is_quiet_about_a_fresh_install(workspace):
    ai_agents.install_agent_skills(str(workspace))

    check = AgentSkillsCheck()
    assert check.is_applicable()
    assert check.test().findings == []


def test_it_reports_an_older_plugin(workspace):
    ai_agents.install_agent_skills(str(workspace))
    age_the_plugin(workspace)

    findings = AgentSkillsCheck().test().findings

    assert any("0.0.1" in finding and partcad.__version__ in finding for finding in findings)
    assert any("pc init --skills-only" in finding for finding in findings)


def test_it_reports_older_cursor_skills_by_name(workspace):
    ai_agents.install_agent_skills(str(workspace))
    age_the_cursor_skill(workspace)

    findings = AgentSkillsCheck().test().findings

    assert any("pc-init" in finding for finding in findings)


def test_it_says_nothing_about_skills_it_did_not_write(workspace):
    """An unstamped `pc-` skill is a user's own, or predates stamping.

    Telling somebody their own file is out of date would be wrong, and offering
    to overwrite it would be worse.
    """
    theirs = workspace / ".cursor" / "skills" / "pc-mine"
    theirs.mkdir(parents=True)
    (theirs / "SKILL.md").write_text("---\nname: pc-mine\ndescription: mine\n---\n", encoding="utf-8")

    check = AgentSkillsCheck()
    assert check.is_applicable()
    assert check.test().findings == []


def test_the_fix_reinstalls_what_was_stale(workspace):
    ai_agents.install_agent_skills(str(workspace))
    age_the_plugin(workspace)
    age_the_cursor_skill(workspace)

    check = AgentSkillsCheck()
    check.test()
    assert check.fix()

    assert check.test().findings == []


def test_the_fix_does_not_install_for_an_agent_that_was_not_there(workspace):
    """Repairing Cursor must not create a `.claude` for somebody who has none."""
    ai_agents.install_agent_skills(str(workspace), ["cursor"])
    age_the_cursor_skill(workspace)

    check = AgentSkillsCheck()
    check.test()
    assert check.fix()

    assert not (workspace / ".claude").exists()


def test_it_is_found_by_the_healthcheck_discovery(workspace):
    """The runner discovers checks by walking the package, so this must be in it.

    It is also gated on `is_applicable`, which is why this installs first: a
    check that is never applicable is discovered and then dropped.
    """
    ai_agents.install_agent_skills(str(workspace))

    from partcad.healthcheck.tests import discover_healthchecks

    assert any(isinstance(check, AgentSkillsCheck) for check in discover_healthchecks())


def test_it_looks_at_the_repository_rather_than_the_directory(tmp_path, monkeypatch):
    """`pc init` writes at the repository root; this has to read the same place."""
    (tmp_path / ".git").mkdir()
    ai_agents.install_agent_skills(str(tmp_path))
    package = tmp_path / "packages" / "widget"
    package.mkdir(parents=True)
    monkeypatch.chdir(package)

    assert AgentSkillsCheck().is_applicable()


def test_an_unreadable_manifest_is_not_reported_as_stale(workspace):
    """A manifest that cannot be parsed says nothing about which version wrote it.

    Guessing "stale" there would offer to overwrite a file on the strength of
    not having understood it.
    """
    ai_agents.install_agent_skills(str(workspace))
    path = workspace / ".claude" / "skills" / "pc" / ".claude-plugin" / "plugin.json"
    path.write_text("{not json", encoding="utf-8")

    assert AgentSkillsCheck().test().findings == []


def test_the_version_is_the_running_one_rather_than_a_literal(workspace):
    """The stamp and the manifest are compared against `partcad.__version__`.

    Nothing in this feature carries a version literal that a release would have
    to remember to bump -- see the note on `STAMP_KEY` in `partcad.ai_agents`.
    """
    ai_agents.install_agent_skills(str(workspace))
    monkeyed = partcad.__version__ + ".1"

    age_the_plugin(workspace, monkeyed)

    assert any(monkeyed in finding for finding in AgentSkillsCheck().test().findings)
