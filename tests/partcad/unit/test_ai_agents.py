#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""Tests for the AI agent skills ``pc init`` installs into a repository.

The skills themselves are checked by
``tests/partcad_cli/unit/test_ai_agent_skills.py`` -- front matter, names,
whether they are in the wheel at all. What is checked here is the installation:
where the files land, what the two agents get (they do not get the same thing),
and what is refused rather than overwritten.
"""

import json
import os

import pytest
import yaml

import partcad.ai_agents as ai_agents


def read_front_matter(path):
    """The skill's YAML front matter, parsed the way a session loading it would."""
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    return yaml.safe_load(text[4 : text.index("\n---", 3)])


@pytest.fixture
def repository(tmp_path):
    """A git repository, as far as anything here can tell."""
    (tmp_path / ".git").mkdir()
    return tmp_path


def test_the_wheel_carries_the_skills():
    """Everything below is a way of copying these; there have to be some."""
    assert ai_agents.available_skills()
    assert os.path.isfile(ai_agents.CLAUDE_PLUGIN_MANIFEST)


def test_claude_gets_a_plugin_rather_than_loose_skills(tmp_path):
    """The manifest is what puts every skill under one `/pc:` namespace."""
    assert ai_agents.install_claude_plugin(str(tmp_path))

    plugin = tmp_path / ".claude" / "skills" / "pc"
    manifest = json.loads((plugin / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "pc"
    # The same manifest a marketplace install would produce, version included:
    # the plugin and the CLI it drives come from one release.
    assert manifest == ai_agents.plugin_manifest()

    for skill in ai_agents.available_skills():
        shipped = plugin / "skills" / skill / "SKILL.md"
        assert shipped.is_file()
        # Byte for byte. Claude has a namespace, so nothing has to be rewritten.
        with open(os.path.join(ai_agents.SKILLS_DIR, skill, "SKILL.md"), "rb") as f:
            assert shipped.read_bytes() == f.read()
        assert read_front_matter(shipped)["name"] == skill


def test_cursor_gets_prefixed_skills(tmp_path):
    """Cursor has no plugin, so the prefix is the only namespace there is."""
    assert ai_agents.install_cursor_skills(str(tmp_path))

    skills = tmp_path / ".cursor" / "skills"
    for skill in ai_agents.available_skills():
        installed = skills / ("pc-" + skill)
        assert (installed / "SKILL.md").is_file()
        # The front matter has to name the directory, or the skill answers to a
        # command nobody typed.
        assert read_front_matter(installed / "SKILL.md")["name"] == "pc-" + skill

    # And the generic names are not what got installed: an unprefixed `init` or
    # `render` in a user's `.cursor/skills` is PartCAD claiming a word.
    assert not (skills / "init").exists()
    assert not (skills / "render").exists()


def test_cursor_skills_do_not_point_at_a_namespace_cursor_has_not_got(tmp_path):
    """`/pc:setup` resolves to nothing there, and these files are full of it."""
    ai_agents.install_cursor_skills(str(tmp_path))

    for skill in ai_agents.available_skills():
        text = (tmp_path / ".cursor" / "skills" / ("pc-" + skill) / "SKILL.md").read_text(encoding="utf-8")
        assert "pc:" not in text, "%s still refers to a skill through the plugin namespace" % skill


def test_the_command_lines_in_the_text_are_left_alone(tmp_path):
    """`pc render` is a command; `pc:render` is a skill. Only one is rewritten."""
    ai_agents.install_cursor_skills(str(tmp_path))

    installed = (tmp_path / ".cursor" / "skills" / "pc-render" / "SKILL.md").read_text(encoding="utf-8")
    with open(os.path.join(ai_agents.SKILLS_DIR, "render", "SKILL.md"), encoding="utf-8") as f:
        source = f.read()

    assert "pc render" in source
    assert installed.count("pc render") == source.count("pc render")


def test_renaming_touches_the_name_and_the_cross_references_only():
    original = "\n".join(
        [
            "---",
            "name: render",
            "description: Use when the user runs /pc:render, and see /pc:export.",
            "---",
            "",
            "# pc:render",
            "",
            "Run `pc render --view front`. Not to be confused with pc:renderer.",
            "",
        ]
    )
    rewritten = ai_agents.rename_skill(original, "pc-render", ["render", "export"])

    assert "name: pc-render" in rewritten
    assert "/pc-render" in rewritten and "/pc-export" in rewritten
    assert "# pc-render" in rewritten
    # A command line, and a word that merely starts like a skill name.
    assert "`pc render --view front`" in rewritten
    assert "pc:renderer" in rewritten


def test_everything_is_installed_beside_the_package_at_the_repository_root(repository):
    """An editor opens the repository, not the package directory inside it."""
    package = repository / "packages" / "widget"
    package.mkdir(parents=True)

    assert ai_agents.install_agent_skills(str(package))

    assert (repository / ".claude" / "skills" / "pc" / ".claude-plugin" / "plugin.json").is_file()
    assert (repository / ".cursor" / "skills" / "pc-init" / "SKILL.md").is_file()
    assert not (package / ".claude").exists()
    assert not (package / ".cursor").exists()


def test_without_a_repository_they_go_next_to_the_package(tmp_path):
    assert ai_agents.install_agent_skills(str(tmp_path))
    assert (tmp_path / ".claude" / "skills" / "pc" / ".claude-plugin" / "plugin.json").is_file()


def test_installing_twice_updates_rather_than_duplicates(tmp_path):
    ai_agents.install_agent_skills(str(tmp_path))
    stale = tmp_path / ".claude" / "skills" / "pc" / "skills" / "init" / "SKILL.md"
    stale.write_text("# out of date\n", encoding="utf-8")

    assert ai_agents.install_agent_skills(str(tmp_path))
    assert stale.read_text(encoding="utf-8") != "# out of date\n"


def test_a_skill_of_the_users_own_is_not_touched(tmp_path):
    """Everything installed is namespaced, so nothing else in there is ours."""
    theirs = tmp_path / ".cursor" / "skills" / "init"
    theirs.mkdir(parents=True)
    (theirs / "SKILL.md").write_text("---\nname: init\n---\n", encoding="utf-8")

    ai_agents.install_agent_skills(str(tmp_path))

    assert (theirs / "SKILL.md").read_text(encoding="utf-8") == "---\nname: init\n---\n"


@pytest.fixture
def one_skill_library(tmp_path, monkeypatch):
    """A library of exactly one skill, so a failure can be arranged for all of it."""
    library = tmp_path / "library" / "widget"
    library.mkdir(parents=True)
    (library / "SKILL.md").write_text("---\nname: widget\n---\n\n# pc:widget\n", encoding="utf-8")
    monkeypatch.setattr(ai_agents, "SKILLS_DIR", str(library.parent))
    return library.parent


def test_an_installation_carrying_no_skills_installs_nothing(tmp_path, monkeypatch):
    """What a wheel built without the `package-data` patterns would look like.

    `tests/partcad_cli/unit/test_ai_agent_skills.py` is what keeps that from
    happening; this is what the installer does if it ever did.
    """
    monkeypatch.setattr(ai_agents, "SKILLS_DIR", str(tmp_path / "not-in-this-install"))

    assert ai_agents.available_skills() == []
    assert not ai_agents.install_claude_plugin(str(tmp_path))
    assert not ai_agents.install_cursor_skills(str(tmp_path))
    assert not ai_agents.install_agent_skills(str(tmp_path))
    assert not (tmp_path / ".claude").exists()


def test_a_copy_that_fails_is_reported_rather_than_raised(tmp_path, monkeypatch, one_skill_library):
    """A full disk is not a reason for `pc init` to stop with a traceback.

    The package is created before any of this runs, so the command has already
    done the thing it was asked to do.
    """

    def full(*args, **kwargs):
        raise OSError("No space left on device")

    monkeypatch.setattr(ai_agents.shutil, "copytree", full)

    assert not ai_agents.install_claude_plugin(str(tmp_path))
    assert not ai_agents.install_cursor_skills(str(tmp_path))


@pytest.mark.skipif(os.name == "nt", reason="symlinks need a privilege Windows does not grant by default")
def test_a_symlinked_skill_is_left_alone_one_by_one(tmp_path, one_skill_library):
    """The per-skill half of the rule the whole destination is checked against."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    skills = tmp_path / ".cursor" / "skills"
    skills.mkdir(parents=True)
    os.symlink(elsewhere, skills / "pc-widget")

    assert not ai_agents.install_cursor_skills(str(tmp_path))
    assert not any(elsewhere.iterdir())


def test_text_that_is_not_a_skill_is_returned_as_it_is():
    """Front matter is the block at the top of the file, or there is none.

    A `---` further down is a horizontal rule, and a file that opens one and
    never closes it has no front matter to rewrite -- in neither case is there a
    `name` to change, and in neither case is that an error.
    """
    assert ai_agents.rename_skill("# pc:render\n", "pc-render", ["render"]) == "# pc-render\n"

    unterminated = "---\nname: render\n"
    assert ai_agents.rename_skill(unterminated, "pc-render", ["render"]) == unterminated


@pytest.mark.skipif(os.name == "nt", reason="symlinks need a privilege Windows does not grant by default")
def test_a_symlinked_destination_is_refused(tmp_path):
    """PartCAD's own repository has `.claude/skills/pc` pointing into the tree.

    Following it would have `pc init` overwrite the working copy of the plugin
    with the installed copy of itself.
    """
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (tmp_path / ".claude" / "skills").mkdir(parents=True)
    os.symlink(elsewhere, tmp_path / ".claude" / "skills" / "pc")

    assert not ai_agents.install_claude_plugin(str(tmp_path))
    assert not any(elsewhere.iterdir())
    # The other half is unaffected: one refusal is not the other's problem.
    assert ai_agents.install_agent_skills(str(tmp_path))
    assert (tmp_path / ".cursor" / "skills" / "pc-init" / "SKILL.md").is_file()


def test_a_destination_that_is_a_file_is_refused(tmp_path):
    (tmp_path / ".cursor").mkdir()
    (tmp_path / ".cursor" / "skills").write_text("not a directory\n", encoding="utf-8")

    assert not ai_agents.install_cursor_skills(str(tmp_path))
    assert (tmp_path / ".cursor" / "skills").read_text(encoding="utf-8") == "not a directory\n"
