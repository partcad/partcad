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


def test_the_fix_leaves_the_mcp_configuration_alone(workspace):
    """Stale skills are repaired; an `.mcp.json` the user never had, or deleted, is not "repaired" into being."""
    ai_agents.install_agent_skills(str(workspace), mcp=False)
    age_the_plugin(workspace)
    age_the_cursor_skill(workspace)

    check = AgentSkillsCheck()
    check.test()
    assert check.fix()

    assert not (workspace / ".mcp.json").exists()
    assert not (workspace / ".cursor" / "mcp.json").exists()


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


def age_a_skill(workspace, directory, name="pc-init", version="0.0.1"):
    """`age_the_cursor_skill` for any agent's directory."""
    path = workspace.joinpath(*directory.split("/")) / name / "SKILL.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("  partcad: %s" % partcad.__version__, "  partcad: %s" % version),
        encoding="utf-8",
    )


@pytest.mark.parametrize("agent, directory", [("copilot", ".agents/skills"), ("kiro", ".kiro/skills")])
def test_it_reports_older_skills_in_every_agents_directory(workspace, agent, directory):
    ai_agents.install_agent_skills(str(workspace), [agent], mcp=False, instructions=False)
    age_a_skill(workspace, directory)

    check = AgentSkillsCheck()
    assert check.is_applicable()
    findings = check.test().findings
    assert any("pc-init" in finding and directory.split("/")[0] in finding for finding in findings)

    assert check.fix()
    assert check.test().findings == []
    # Repairing one directory creates no other.
    assert not (workspace / ".cursor").exists()


def age_the_instructions(workspace, version="0.0.1"):
    path = workspace / "AGENTS.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "BEGIN partcad %s " % partcad.__version__, "BEGIN partcad %s " % version
        ),
        encoding="utf-8",
    )


def test_it_reports_and_rewrites_an_older_agents_md_section(workspace):
    ai_agents.install_agent_skills(str(workspace), ["cursor"], mcp=False)
    age_the_instructions(workspace)

    check = AgentSkillsCheck()
    findings = check.test().findings
    assert any("AGENTS.md" in finding and "0.0.1" in finding for finding in findings)

    assert check.fix()
    assert check.test().findings == []
    assert ai_agents.instructions_version((workspace / "AGENTS.md").read_text(encoding="utf-8")) == partcad.__version__


def test_an_agents_md_section_alone_makes_it_apply(workspace):
    ai_agents.install_instructions(str(workspace), str(workspace))

    assert AgentSkillsCheck().is_applicable()


def test_the_fix_writes_no_agents_md_that_was_not_there(workspace):
    ai_agents.install_agent_skills(str(workspace), ["cursor"], mcp=False, instructions=False)
    age_the_cursor_skill(workspace)

    check = AgentSkillsCheck()
    check.test()
    assert check.fix()

    assert not (workspace / "AGENTS.md").exists()


def test_a_repair_run_elsewhere_keeps_the_package_the_section_names(workspace, monkeypatch):
    """`pc healthcheck --fix` from the root must not rewrite a nested package's section for the root."""
    package = workspace / "models" / "robot"
    package.mkdir(parents=True)
    ai_agents.install_agent_skills(str(package), ["cursor"], mcp=False)
    age_the_instructions(workspace)
    monkeypatch.chdir(workspace)

    check = AgentSkillsCheck()
    check.test()
    assert check.fix()

    text = (workspace / "AGENTS.md").read_text(encoding="utf-8")
    assert ai_agents.instructions_package(text) == "models/robot"
    assert "pc --no-ansi -p models/robot" in text


def test_a_marker_naming_a_package_outside_the_repository_is_not_followed(workspace):
    (workspace / "AGENTS.md").write_text(
        '<!-- BEGIN partcad 0.0.1 package="../../elsewhere": old -->\nstale\n<!-- END partcad -->\n', encoding="utf-8"
    )

    check = AgentSkillsCheck()
    check.test()
    assert check.fix()

    assert ai_agents.instructions_package((workspace / "AGENTS.md").read_text(encoding="utf-8")) == "."


# --- Where they are: not always where `pc init` would put them by default ---


def test_skills_an_older_release_put_beside_a_subpackage_are_found(tmp_path, monkeypatch):
    """Outside a repository, an older PartCAD installed them beside the package, subpackage or not.

    The default folder is now the PartCAD root above it, and the check has to
    find them where they are rather than report nothing to repair.
    """
    (tmp_path / "partcad.yaml").write_text("desc: root\n", encoding="utf-8")
    arm = tmp_path / "arm"
    arm.mkdir()
    (arm / "partcad.yaml").write_text("desc: arm\n", encoding="utf-8")
    ai_agents.install_agent_skills(str(arm), ["cursor"], mcp=False, editor_folder=str(arm))
    age_the_cursor_skill(arm)
    monkeypatch.chdir(arm)

    check = AgentSkillsCheck()
    assert check.is_applicable()
    assert check.test().findings
    assert check.fix()
    # Repaired where they were, not copied up to the root.
    assert check.test().findings == []
    assert not (tmp_path / ".cursor").exists()


def test_skills_in_an_editor_folder_inside_the_repository_are_found(workspace, monkeypatch):
    """`pc init --editor-folder hw` put them in `hw`; run from inside it, that is where they are."""
    hw = workspace / "hw"
    (hw / "motor").mkdir(parents=True)
    ai_agents.install_agent_skills(str(hw), ["cursor"], mcp=False, editor_folder=str(hw))
    age_the_cursor_skill(hw)
    monkeypatch.chdir(hw / "motor")

    check = AgentSkillsCheck()
    assert check.is_applicable()
    assert check.test().findings
    assert check.fix()
    assert check.test().findings == []
    assert not (workspace / ".cursor").exists()


def test_with_nothing_installed_on_the_way_up_it_is_the_default_folder(workspace, monkeypatch):
    (workspace / "hw").mkdir()
    monkeypatch.chdir(workspace / "hw")
    assert AgentSkillsCheck()._root == str(workspace)
