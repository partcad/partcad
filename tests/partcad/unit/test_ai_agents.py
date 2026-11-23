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

import partcad
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
    # The MCP server and the AGENTS.md section are not package data -- both are
    # written by code -- so they are left out here, where the question is what
    # the missing data costs.
    assert not ai_agents.install_agent_skills(str(tmp_path), mcp=False, instructions=False)
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


# --- The stamp: which PartCAD wrote a skill, and whose skill it is ---


def test_installed_cursor_skills_say_which_partcad_wrote_them(tmp_path):
    """Nothing else in a `.cursor/skills` directory records that.

    The Claude side has the plugin manifest; this is the Cursor equivalent, and
    it is what `pc healthcheck` compares against the version running.
    """
    ai_agents.install_cursor_skills(str(tmp_path))

    for skill in ai_agents.available_skills():
        text = (tmp_path / ".cursor" / "skills" / ("pc-" + skill) / "SKILL.md").read_text(encoding="utf-8")
        assert ai_agents.stamped_version(text) == partcad.__version__


def test_the_stamp_is_added_to_an_existing_metadata_block():
    """An author's own `metadata:` is added to rather than replaced."""
    original = "\n".join(["---", "name: render", "metadata:", "  author: somebody", "---", "", "body", ""])
    stamped = ai_agents.rename_skill(original, "pc-render", ["render"], "1.2.3")

    assert "  author: somebody" in stamped
    assert "  partcad: 1.2.3" in stamped
    assert stamped.count("metadata:") == 1
    assert ai_agents.stamped_version(stamped) == "1.2.3"


def test_re_stamping_replaces_rather_than_repeats():
    """Installing twice must not leave two versions in one file."""
    once = ai_agents.rename_skill("---\nname: render\n---\n\nbody\n", "pc-render", ["render"], "1.0.0")
    twice = ai_agents.rename_skill(once, "pc-render", ["render"], "2.0.0")

    assert ai_agents.stamped_version(twice) == "2.0.0"
    assert twice.count("partcad:") == 1


def test_an_unstamped_skill_reports_no_version():
    """A user's own skill, and one an older PartCAD installed, look the same."""
    assert ai_agents.stamped_version("---\nname: mine\n---\n") is None
    assert ai_agents.stamped_version("no front matter at all\n") is None


# --- Retirement: a skill PartCAD stopped shipping stops being offered ---


def test_a_retired_skill_is_removed_from_both_agents(tmp_path):
    """It would otherwise be offered forever, describing a CLI that moved on.

    That is worse than no skill at all: the agent follows it, and it looks like
    a working one.
    """
    ai_agents.install_agent_skills(str(tmp_path))

    ghost = tmp_path / ".cursor" / "skills" / "pc-ghost"
    ghost.mkdir()
    (ghost / "SKILL.md").write_text(
        "---\nname: pc-ghost\ndescription: retired\nmetadata:\n  partcad: 0.0.1\n---\n", encoding="utf-8"
    )
    plugin_ghost = tmp_path / ".claude" / "skills" / "pc" / "skills" / "ghost"
    plugin_ghost.mkdir()
    (plugin_ghost / "SKILL.md").write_text("---\nname: ghost\n---\n", encoding="utf-8")

    ai_agents.install_agent_skills(str(tmp_path))

    assert not ghost.exists()
    assert not plugin_ghost.exists()
    # And everything still shipped survived the pruning.
    assert len(list((tmp_path / ".claude" / "skills" / "pc" / "skills").iterdir())) == len(ai_agents.available_skills())


def test_a_skill_the_user_wrote_is_never_retired(tmp_path):
    """`pc-` is PartCAD's namespace, but the stamp is what proves authorship.

    Somebody's hand-written `pc-mine` has none, so it stays -- and so does one
    an older PartCAD installed before stamping existed. The cost is a retired
    skill lingering; the alternative is deleting a file PartCAD did not write.
    """
    theirs = tmp_path / ".cursor" / "skills" / "pc-mine"
    theirs.mkdir(parents=True)
    (theirs / "SKILL.md").write_text("---\nname: pc-mine\ndescription: mine\n---\n", encoding="utf-8")
    unrelated = tmp_path / ".cursor" / "skills" / "openspec-propose"
    unrelated.mkdir()
    (unrelated / "SKILL.md").write_text("---\nname: openspec-propose\n---\n", encoding="utf-8")

    ai_agents.install_cursor_skills(str(tmp_path))

    assert (theirs / "SKILL.md").is_file()
    assert (unrelated / "SKILL.md").is_file()


def test_retirement_does_not_follow_symlinks(tmp_path):
    """The same rule the installation side keeps: never write through one."""
    if os.name == "nt":
        pytest.skip("symlinks need a privilege Windows does not grant by default")

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "SKILL.md").write_text("---\nname: pc-linked\nmetadata:\n  partcad: 0.0.1\n---\n", encoding="utf-8")
    skills = tmp_path / ".cursor" / "skills"
    skills.mkdir(parents=True)
    os.symlink(elsewhere, skills / "pc-linked")

    ai_agents.install_cursor_skills(str(tmp_path))

    assert (elsewhere / "SKILL.md").is_file()


# --- Which agents ---


def test_only_the_named_agents_are_installed_for(tmp_path):
    assert ai_agents.install_agent_skills(str(tmp_path), ["cursor"])

    assert (tmp_path / ".cursor" / "skills" / "pc-init" / "SKILL.md").is_file()
    assert not (tmp_path / ".claude").exists()


def test_an_unknown_agent_is_an_error_rather_than_a_quiet_no_op(tmp_path):
    """A typo that installs nothing looks exactly like an unsupported agent."""
    assert not ai_agents.install_agent_skills(str(tmp_path), ["cursor", "emacs"])

    assert not (tmp_path / ".cursor").exists()


def test_the_default_is_the_three_agents_with_an_install_base_and_whatever_the_repository_uses(tmp_path):
    """A `.kiro`, a `.zed` and a `.codex` in every new repository would be litter for agents nobody here uses."""
    ai_agents.install_agent_skills(str(tmp_path))

    assert (tmp_path / ".claude" / "skills" / "pc").is_dir()
    assert (tmp_path / ".cursor" / "skills" / "pc-init").is_dir()
    assert (tmp_path / ".agents" / "skills" / "pc-init").is_dir()
    for absent in (".kiro", ".codex", ".gemini", ".zed", ".devin"):
        assert not (tmp_path / absent).exists(), absent


@pytest.mark.parametrize(
    "marker, agent",
    [(".kiro", "kiro"), (".codex", "codex"), ("GEMINI.md", "gemini"), (".zed", "zed"), (".windsurf", "devin")],
)
def test_an_agent_the_repository_already_uses_is_installed_for_by_default(tmp_path, marker, agent):
    (tmp_path / marker).mkdir() if marker.startswith(".") else (tmp_path / marker).write_text("", encoding="utf-8")

    assert agent in ai_agents.default_agents(str(tmp_path))


def test_all_means_every_agent(tmp_path, monkeypatch):
    from click.testing import CliRunner

    from partcad_cli.click.command import cli

    # `init` writes beside the `partcad.yaml` of the current directory.
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["--no-ansi", "init", "--skills-only", "--agents", "all"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / ".kiro" / "skills" / "pc-init").is_dir()
    assert (tmp_path / ".codex" / "config.toml").is_file()


def test_every_agent_reading_the_shared_directory_shares_one_copy(tmp_path):
    shared = [name for name, spec in ai_agents.AGENT_SPECS.items() if spec.skills == "shared"]
    assert sorted(shared) == ["codex", "copilot", "devin", "gemini", "opencode", "zed"]

    assert ai_agents.install_agent_skills(str(tmp_path), shared, mcp=False, instructions=False)

    installed = sorted(os.listdir(tmp_path / ".agents" / "skills"))
    assert installed == ["pc-" + skill for skill in ai_agents.available_skills()]
    # Stamped and renamed like Cursor's: no plugin namespace there either.
    assert read_front_matter(tmp_path / ".agents" / "skills" / "pc-gen" / "SKILL.md")["name"] == "pc-gen"


def test_kiro_has_a_directory_of_its_own(tmp_path):
    assert ai_agents.install_agent_skills(str(tmp_path), ["kiro"], mcp=False, instructions=False)

    assert (tmp_path / ".kiro" / "skills" / "pc-init" / "SKILL.md").is_file()
    assert not (tmp_path / ".agents").exists()


def test_windsurf_is_devin(tmp_path):
    assert ai_agents.install_agent_skills(str(tmp_path), ["windsurf"], instructions=False)

    assert (tmp_path / ".devin" / "mcp_config.json").is_file()


def test_every_skill_name_is_one_every_agent_accepts():
    """Copilot, Zed and Kiro take lowercase letters, digits and single hyphens, at most 64; a bad name fails silently."""
    import re

    for skill in ai_agents.available_skills():
        name = "pc-" + skill
        assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) and len(name) <= 64, name


# --- The MCP server ---


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_both_agents_are_given_the_mcp_server(tmp_path):
    assert ai_agents.install_agent_skills(str(tmp_path))

    # `.mcp.json` names the root relative to the folder holding it, which `pc
    # mcp --root` finds for itself (see `partcad_utils.agent_config`).
    claude = read_json(tmp_path / ".mcp.json")["mcpServers"]["partcad"]
    assert claude == {"type": "stdio", "command": "pc", "args": ["mcp", "--root", ".", "--from", ".mcp.json"]}
    # Cursor spells that folder itself.
    cursor = read_json(tmp_path / ".cursor" / "mcp.json")["mcpServers"]["partcad"]
    assert cursor == {"command": "pc", "args": ["-p", "${workspaceFolder}", "mcp"]}


def test_the_server_is_pointed_at_a_package_below_the_repository_root(repository):
    """The file is at the root, where the editor reads it; the package it serves need not be."""
    package = repository / "packages" / "widget"
    package.mkdir(parents=True)

    ai_agents.install_agent_skills(str(package))

    assert read_json(repository / ".mcp.json")["mcpServers"]["partcad"]["args"] == [
        "mcp",
        "--root",
        "packages/widget",
        "--from",
        ".mcp.json",
    ]
    assert read_json(repository / ".cursor" / "mcp.json")["mcpServers"]["partcad"]["args"][1] == (
        "${workspaceFolder}/packages/widget"
    )
    assert not (package / ".mcp.json").exists()


def test_the_entry_runs_the_command_pc_has():
    """`pc mcp --root <path>` for Claude Code, `pc -p <path> mcp` for Cursor."""
    from partcad_cli.click.command import cli

    claude = ai_agents.mcp_server_entry("claude", "/repo", "/repo")
    assert claude["command"] == "pc"
    mcp = cli.get_command(None, claude["args"][0])
    assert claude["args"][1] in next(param for param in mcp.params if param.name == "root").opts

    cursor = ai_agents.mcp_server_entry("cursor", "/repo", "/repo")
    assert cursor["args"][0] in next(param for param in cli.params if param.name == "path").opts
    assert cli.get_command(None, cursor["args"][-1]) is not None


def test_other_servers_in_the_file_are_kept(tmp_path):
    theirs = {"mcpServers": {"github": {"command": "gh-mcp"}}, "something": "else"}
    (tmp_path / ".mcp.json").write_text(json.dumps(theirs), encoding="utf-8")

    assert ai_agents.install_mcp_config("claude", str(tmp_path), str(tmp_path))

    config = read_json(tmp_path / ".mcp.json")
    assert config["mcpServers"]["github"] == {"command": "gh-mcp"}
    assert config["something"] == "else"
    assert config["mcpServers"]["partcad"]["command"] == "pc"


def test_an_out_of_date_entry_is_replaced(tmp_path):
    stale = {"mcpServers": {"partcad": {"command": "/old/venv/bin/pc", "args": ["mcp"]}}}
    (tmp_path / ".mcp.json").write_text(json.dumps(stale), encoding="utf-8")

    assert ai_agents.install_mcp_config("claude", str(tmp_path), str(tmp_path))

    assert read_json(tmp_path / ".mcp.json")["mcpServers"]["partcad"] == ai_agents.mcp_server_entry(
        "claude", str(tmp_path), str(tmp_path)
    )


@pytest.mark.parametrize("content", ["{ not json", "[]", '{"mcpServers": []}'])
def test_a_file_that_cannot_be_merged_into_is_left_alone(tmp_path, content):
    (tmp_path / ".mcp.json").write_text(content, encoding="utf-8")

    assert not ai_agents.install_mcp_config("claude", str(tmp_path), str(tmp_path))

    assert (tmp_path / ".mcp.json").read_text(encoding="utf-8") == content


@pytest.mark.skipif(not hasattr(os, "symlink") or os.name == "nt", reason="needs symlinks")
def test_a_symlinked_configuration_is_refused(tmp_path):
    shared = tmp_path / "shared.json"
    shared.write_text("{}", encoding="utf-8")
    os.symlink(shared, tmp_path / ".mcp.json")

    assert not ai_agents.install_mcp_config("claude", str(tmp_path), str(tmp_path))

    assert shared.read_text(encoding="utf-8") == "{}"


def test_no_mcp_means_no_server(tmp_path):
    assert ai_agents.install_agent_skills(str(tmp_path), mcp=False)

    assert not (tmp_path / ".mcp.json").exists()
    assert not (tmp_path / ".cursor" / "mcp.json").exists()


def test_only_the_named_agents_are_given_the_server(tmp_path):
    ai_agents.install_agent_skills(str(tmp_path), ["cursor"])

    assert (tmp_path / ".cursor" / "mcp.json").is_file()
    assert not (tmp_path / ".mcp.json").exists()


def test_every_agent_has_somewhere_to_put_the_server():
    """An agent added to AGENT_SPECS without one would get the skills and silently no server -- unless it says why."""
    assert sorted([*ai_agents.MCP_CONFIGS, *ai_agents.MCP_NOT_WRITTEN]) == sorted(ai_agents.AGENT_SPECS)
    assert not set(ai_agents.MCP_CONFIGS) & set(ai_agents.MCP_NOT_WRITTEN)


@pytest.mark.parametrize(
    "agent, path, key",
    [
        ("gemini", (".gemini", "settings.json"), "mcpServers"),
        ("zed", (".zed", "settings.json"), "context_servers"),
        ("kiro", (".kiro", "settings", "mcp.json"), "mcpServers"),
        ("devin", (".devin", "mcp_config.json"), "mcpServers"),
    ],
)
def test_an_agent_with_no_project_variable_is_given_the_root_relative_to_its_file(repository, agent, path, key):
    """None of these document a variable for the project; `--root` is relative to the folder holding the file."""
    package = repository / "packages" / "widget"
    package.mkdir(parents=True)

    assert ai_agents.install_mcp_config(agent, str(repository), str(package))

    assert read_json(repository.joinpath(*path))[key]["partcad"] == {
        "command": "pc",
        "args": ["mcp", "--root", "packages/widget", "--from", "/".join(path)],
    }


def test_a_json_file_with_comments_is_left_alone(tmp_path):
    """Zed's settings are usually commented; a parse and re-dump would drop every comment."""
    (tmp_path / ".zed").mkdir()
    text = '{\n  // mine\n  "theme": "One Dark"\n}\n'
    (tmp_path / ".zed" / "settings.json").write_text(text, encoding="utf-8")

    assert not ai_agents.install_mcp_config("zed", str(tmp_path), str(tmp_path))

    assert (tmp_path / ".zed" / "settings.json").read_text(encoding="utf-8") == text


# --- Codex's TOML ---


def read_toml(path):
    tomllib = pytest.importorskip("tomllib")
    return tomllib.loads(path.read_text(encoding="utf-8"))


def test_codex_is_given_a_table_of_its_own(tmp_path):
    assert ai_agents.install_mcp_config("codex", str(tmp_path), str(tmp_path))

    assert read_toml(tmp_path / ".codex" / "config.toml")["mcp_servers"]["partcad"] == {
        "command": "pc",
        "args": ["mcp", "--root", ".", "--from", ".codex/config.toml"],
    }


def test_the_rest_of_codexs_file_is_kept_byte_for_byte(tmp_path):
    (tmp_path / ".codex").mkdir()
    before = (
        '# my settings\nmodel = "o5"\n\n[mcp_servers.github]\ncommand = "gh-mcp" # theirs\n\n'
        '[mcp_servers.partcad]\ncommand = "/old/pc"\nargs = ["mcp"]\n\n[mcp_servers.partcad.env]\nX = "1"\n\n'
        '[profiles.fast]\nmodel = "o5-mini"\n'
    )
    (tmp_path / ".codex" / "config.toml").write_text(before, encoding="utf-8")

    assert ai_agents.install_mcp_config("codex", str(tmp_path), str(tmp_path))

    after = (tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert after.startswith('# my settings\nmodel = "o5"\n\n[mcp_servers.github]\ncommand = "gh-mcp" # theirs\n')
    assert after.endswith('[profiles.fast]\nmodel = "o5-mini"\n')
    config = read_toml(tmp_path / ".codex" / "config.toml")
    # PartCAD's table, sub-tables and all, is replaced whole.
    assert config["mcp_servers"]["partcad"] == {
        "command": "pc",
        "args": ["mcp", "--root", ".", "--from", ".codex/config.toml"],
    }
    assert config["mcp_servers"]["github"] == {"command": "gh-mcp"}

    # And a second run changes nothing.
    assert ai_agents.install_mcp_config("codex", str(tmp_path), str(tmp_path))
    assert (tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8") == after


@pytest.mark.parametrize(
    "content",
    # Ours, written inline under `[mcp_servers]`: a table of the same name
    # beside it would declare it twice.
    ["not = [valid", '[mcp_servers]\npartcad = { command = "pc", args = ["-p", ".", "mcp"] }\n'],
)
def test_a_toml_file_this_cannot_edit_is_left_alone(tmp_path, content):
    pytest.importorskip("tomllib")
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "config.toml").write_text(content, encoding="utf-8")

    assert not ai_agents.install_mcp_config("codex", str(tmp_path), str(tmp_path))

    assert (tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8") == content


# --- Gemini reads AGENTS.md only when told to ---


def test_gemini_is_told_to_read_agents_md_beside_gemini_md(tmp_path):
    assert ai_agents.install_agent_skills(str(tmp_path), ["gemini"])

    assert read_json(tmp_path / ".gemini" / "settings.json")["context"]["fileName"] == ["AGENTS.md", "GEMINI.md"]


@pytest.mark.parametrize(
    "before, after",
    [
        ("NOTES.md", ["AGENTS.md", "NOTES.md"]),
        (["NOTES.md", "GEMINI.md"], ["AGENTS.md", "NOTES.md", "GEMINI.md"]),
        (["AGENTS.md"], ["AGENTS.md"]),
    ],
)
def test_the_context_files_gemini_had_are_kept(tmp_path, before, after):
    (tmp_path / ".gemini").mkdir()
    settings = {"context": {"fileName": before, "other": 1}, "theme": "x"}
    (tmp_path / ".gemini" / "settings.json").write_text(json.dumps(settings), encoding="utf-8")

    assert ai_agents.install_gemini_context(str(tmp_path))

    written = read_json(tmp_path / ".gemini" / "settings.json")
    assert written["context"] == {"fileName": after, "other": 1}
    assert written["theme"] == "x"


def test_no_instructions_means_gemini_is_not_reconfigured(tmp_path):
    assert ai_agents.install_agent_skills(str(tmp_path), ["gemini"], mcp=False, instructions=False)

    assert not (tmp_path / ".gemini" / "settings.json").exists()


# --- AGENTS.md ---


def test_agents_md_gets_a_partcad_section(tmp_path):
    assert ai_agents.install_agent_skills(str(tmp_path), ["cursor"])

    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert ai_agents.instructions_version(text) == partcad.__version__
    assert "pc --no-ansi" in text
    for skill in ai_agents.available_skills():
        assert "`pc-%s`" % skill in text
    assert "`.cursor/skills/`" in text
    # No `/pc:<skill>` left pointing into a namespace most agents have not got,
    # beyond the one sentence saying the two spellings are the same skill.
    assert text.count("pc:") == 1


def test_the_section_names_the_package_where_it_is(repository):
    package = repository / "packages" / "widget"
    package.mkdir(parents=True)

    ai_agents.install_agent_skills(str(package), ["cursor"])

    text = (repository / "AGENTS.md").read_text(encoding="utf-8")
    assert "`packages/widget/partcad.yaml`" in text
    assert "pc --no-ansi -p packages/widget" in text
    assert not (package / "AGENTS.md").exists()


def test_the_rest_of_agents_md_is_the_users_and_is_kept(tmp_path):
    (tmp_path / "AGENTS.md").write_text("# Mine\n\nKeep this.\n", encoding="utf-8")
    ai_agents.install_agent_skills(str(tmp_path), ["cursor"])
    with open(tmp_path / "AGENTS.md", "a", encoding="utf-8") as f:
        f.write("\n## Also mine\n\nAnd this.\n")

    ai_agents.install_agent_skills(str(tmp_path), ["cursor"])

    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert text.startswith("# Mine\n\nKeep this.\n\n<!-- BEGIN partcad ")
    assert text.endswith("<!-- END partcad -->\n\n## Also mine\n\nAnd this.\n")
    assert text.count("<!-- BEGIN partcad ") == 1


def test_an_older_section_is_replaced(tmp_path):
    (tmp_path / "AGENTS.md").write_text(
        "<!-- BEGIN partcad 0.0.1: old -->\nstale\n<!-- END partcad -->\n", encoding="utf-8"
    )

    ai_agents.install_instructions(str(tmp_path), str(tmp_path))

    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "stale" not in text
    assert ai_agents.instructions_version(text) == partcad.__version__


def test_the_section_lists_every_place_skills_are_installed_not_only_this_runs(tmp_path):
    ai_agents.install_agent_skills(str(tmp_path), ["kiro"])
    ai_agents.install_agent_skills(str(tmp_path), ["cursor"])

    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "`.kiro/skills/`" in text and "`.cursor/skills/`" in text


def test_a_claude_md_is_pointed_at_agents_md(tmp_path):
    """Claude Code reads AGENTS.md itself only where there is no CLAUDE.md."""
    (tmp_path / "CLAUDE.md").write_text("# Mine\n", encoding="utf-8")

    ai_agents.install_agent_skills(str(tmp_path), ["cursor"])
    ai_agents.install_agent_skills(str(tmp_path), ["cursor"])

    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == "# Mine\n\n@AGENTS.md\n"


def test_no_claude_md_is_created(tmp_path):
    ai_agents.install_agent_skills(str(tmp_path), ["claude"])

    assert not (tmp_path / "CLAUDE.md").exists()


@pytest.mark.skipif(not hasattr(os, "symlink") or os.name == "nt", reason="needs symlinks")
def test_linked_instruction_files_are_left_alone(tmp_path):
    (tmp_path / "shared.md").write_text("theirs\n", encoding="utf-8")
    os.symlink(tmp_path / "shared.md", tmp_path / "AGENTS.md")
    os.symlink(tmp_path / "shared.md", tmp_path / "CLAUDE.md")

    assert not ai_agents.install_instructions(str(tmp_path), str(tmp_path))

    assert (tmp_path / "shared.md").read_text(encoding="utf-8") == "theirs\n"


def test_no_instructions_means_no_agents_md(tmp_path):
    assert ai_agents.install_agent_skills(str(tmp_path), ["cursor"], instructions=False)

    assert not (tmp_path / "AGENTS.md").exists()


# --- The install links in the documentation ---


def _documented_link(prefix):
    import re

    path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "docs", "source", "ai_agents", "mcp.rst")
    with open(path, encoding="utf-8") as f:
        found = re.search(re.escape(prefix) + r"[^\s>`]+", f.read())
    assert found, prefix
    return found.group(0)


def test_the_cursor_install_link_is_the_entry_pc_init_writes():
    """A one-click install that starts something else than `pc init` configures is two servers that disagree."""
    import base64
    import urllib.parse

    link = _documented_link("cursor://anysphere.cursor-deeplink/mcp/install?")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)
    assert query["name"] == ["partcad"]
    assert json.loads(base64.b64decode(query["config"][0])) == ai_agents.mcp_server_entry("cursor", "/r", "/r")


def test_the_vscode_install_link_is_the_server_the_documentation_shows():
    import urllib.parse

    link = _documented_link("https://vscode.dev/redirect?url=")
    inner = urllib.parse.unquote(urllib.parse.urlparse(link).query[len("url=") :])
    assert inner.startswith("vscode:mcp/install?")
    config = json.loads(urllib.parse.unquote(inner[len("vscode:mcp/install?") :]))
    assert config == {"name": "partcad", "type": "stdio", "command": "pc", "args": ["-p", "${workspaceFolder}", "mcp"]}


# --- OpenCode's V2 configuration ---


def test_opencode_is_given_a_server_in_its_current_shape(repository):
    """`mcp.servers.<name>`, a `type` and the command as one array (`Mcp.LocalConfigEncoded`)."""
    package = repository / "packages" / "widget"
    package.mkdir(parents=True)

    assert ai_agents.install_mcp_config("opencode", str(repository), str(package))

    config = read_json(repository / "opencode.json")
    assert config["$schema"] == "https://opencode.ai/config.json"
    assert config["mcp"]["servers"]["partcad"] == {
        "type": "local",
        "command": ["pc", "mcp", "--root", "packages/widget", "--from", "opencode.json"],
    }


def test_opencodes_deprecated_entry_of_ours_is_moved_and_the_rest_kept(tmp_path):
    """OpenCode 2 migrates a server kept directly under `mcp`; two of ours, in both places, would be one too many."""
    before = {
        "$schema": "https://opencode.ai/config.json",
        "model": "theirs",
        "mcp": {
            "partcad": {"type": "local", "command": ["pc", "-p", ".", "mcp"]},
            "github": {"type": "local", "command": ["gh"]},
        },
    }
    (tmp_path / "opencode.json").write_text(json.dumps(before), encoding="utf-8")

    assert ai_agents.install_mcp_config("opencode", str(tmp_path), str(tmp_path))

    config = read_json(tmp_path / "opencode.json")
    assert config["model"] == "theirs"
    assert "partcad" not in config["mcp"]
    assert config["mcp"]["github"] == {"type": "local", "command": ["gh"]}
    assert config["mcp"]["servers"]["partcad"]["command"] == ["pc", "mcp", "--root", ".", "--from", "opencode.json"]


@pytest.mark.parametrize("existing", ["opencode.jsonc", ".opencode/opencode.json"])
def test_the_opencode_file_a_repository_already_has_is_the_one_written(tmp_path, existing):
    """OpenCode merges every file it finds; a second one beside the first would be one more place to look."""
    path = tmp_path.joinpath(*existing.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"model": "theirs"}', encoding="utf-8")

    assert ai_agents.install_mcp_config("opencode", str(tmp_path), str(tmp_path))

    assert read_json(path)["mcp"]["servers"]["partcad"]["type"] == "local"
    assert not (tmp_path / "opencode.json").exists() or existing == "opencode.json"


def test_an_opencode_file_with_comments_is_left_alone(tmp_path):
    text = '{\n  // mine\n  "model": "theirs"\n}\n'
    (tmp_path / "opencode.jsonc").write_text(text, encoding="utf-8")

    assert not ai_agents.install_mcp_config("opencode", str(tmp_path), str(tmp_path))

    assert (tmp_path / "opencode.jsonc").read_text(encoding="utf-8") == text


def test_the_opencode_documentation_shows_what_pc_init_writes():
    """One snippet, and it is the configuration `pc init` produces -- so the two cannot come to differ."""
    import re

    path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "docs", "source", "ai_agents", "mcp.rst")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    section = text[text.index("OpenCode\n========\n") : text.index("Claude Desktop\n==============")]
    blocks = re.findall(r"\.\. code-block:: json\n\n((?:  .*\n|\n)+)", section)
    assert len(blocks) == 1
    documented = json.loads(blocks[0])

    config = ai_agents.MCP_CONFIGS["opencode"]
    assert documented == {
        **dict(config.preamble),
        "mcp": {"servers": {"partcad": ai_agents.mcp_server_entry("opencode", "/r", "/r")}},
    }


# --- What review found ---


def test_a_description_that_mentions_partcad_is_not_a_stamp():
    """Only `metadata.partcad` is a stamp; a skill mistaken for PartCAD's is one `pc init` may delete."""
    text = "---\nname: pc-notes\ndescription: |\n  partcad: notes\n---\n\n# Notes\n"
    assert ai_agents.stamped_version(text) is None


def test_a_users_skill_whose_description_mentions_partcad_is_not_retired(tmp_path):
    theirs = tmp_path / ".agents" / "skills" / "pc-notes"
    theirs.mkdir(parents=True)
    (theirs / "SKILL.md").write_text("---\nname: pc-notes\ndescription: |\n  partcad: notes\n---\n", encoding="utf-8")

    ai_agents.install_agent_skills(str(tmp_path), ["copilot"], mcp=False, instructions=False)

    assert (theirs / "SKILL.md").is_file()


def test_an_array_of_tables_after_ours_in_codexs_file_is_kept(tmp_path):
    pytest.importorskip("tomllib")
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "config.toml").write_text(
        '[mcp_servers.partcad]\ncommand = "pc"\nargs = ["-p", ".", "mcp"]\n\n[[skills.config]]\nname = "mine"\n',
        encoding="utf-8",
    )

    assert ai_agents.install_mcp_config("codex", str(tmp_path), str(tmp_path))

    config = read_toml(tmp_path / ".codex" / "config.toml")
    assert config["skills"]["config"] == [{"name": "mine"}]
    assert config["mcp_servers"]["partcad"]["command"] == "pc"


def test_a_table_between_two_of_ours_in_codexs_file_is_kept(tmp_path):
    """TOML lets `[mcp_servers.partcad.env]` come after somebody else's table."""
    pytest.importorskip("tomllib")
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "config.toml").write_text(
        '[mcp_servers.partcad]\ncommand = "pc"\nargs = ["-p", ".", "mcp"]\n\n[mcp_servers.github]\ncommand = "gh-mcp"\n\n'
        '[mcp_servers.partcad.env]\nX = "1"\n\n[profiles.fast]\nmodel = "m"\n',
        encoding="utf-8",
    )

    assert ai_agents.install_mcp_config("codex", str(tmp_path), str(tmp_path))

    config = read_toml(tmp_path / ".codex" / "config.toml")
    assert config["mcp_servers"]["github"] == {"command": "gh-mcp"}
    assert config["mcp_servers"]["partcad"] == {
        "command": "pc",
        "args": ["mcp", "--root", ".", "--from", ".codex/config.toml"],
    }
    assert config["profiles"]["fast"] == {"model": "m"}


@pytest.mark.skipif(not hasattr(os, "symlink") or os.name == "nt", reason="needs symlinks")
def test_linked_gemini_settings_are_left_alone_by_the_context_too(tmp_path):
    shared = tmp_path / "shared.json"
    shared.write_text("{}", encoding="utf-8")
    (tmp_path / ".gemini").mkdir()
    os.symlink(shared, tmp_path / ".gemini" / "settings.json")

    assert not ai_agents.install_gemini_context(str(tmp_path))

    assert shared.read_text(encoding="utf-8") == "{}"


def test_the_section_marker_names_the_package(repository):
    package = repository / "models" / "robot"
    package.mkdir(parents=True)

    ai_agents.install_instructions(str(repository), str(package))

    assert ai_agents.instructions_package((repository / "AGENTS.md").read_text(encoding="utf-8")) == "models/robot"


def test_the_plugin_names_its_icon_and_it_is_a_real_png():
    """The directory reads the icon once; a pointer file there would be listed for good."""
    manifest = ai_agents.plugin_manifest()
    path = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "ai-agents", "claude", manifest["icon"].removeprefix("./")
    )
    with open(path, "rb") as f:
        assert f.read(8) == b"\x89PNG\r\n\x1a\n"


def test_a_header_inside_a_multiline_string_in_codexs_file_is_text_and_is_kept(tmp_path):
    """TOML allows header-shaped lines in a multi-line string; an edit that took them for tables is refused."""
    pytest.importorskip("tomllib")
    (tmp_path / ".codex").mkdir()
    text = (
        '[mcp_servers.partcad]\ncommand = "pc"\nargs = ["-p", ".", "mcp"]\n\n[profiles.fast]\nmodel_instructions = """\n'
        '[mcp_servers.partcad.env]\nKeep this instruction.\n[example]\nremaining text\n"""\n'
    )
    (tmp_path / ".codex" / "config.toml").write_text(text, encoding="utf-8")

    assert not ai_agents.install_mcp_config("codex", str(tmp_path), str(tmp_path))

    assert (tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8") == text


def test_a_multiline_string_elsewhere_does_not_stop_an_edit_that_keeps_it(tmp_path):
    pytest.importorskip("tomllib")
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "config.toml").write_text(
        '[profiles.fast]\nmodel_instructions = """\nplain text\n"""\n', encoding="utf-8"
    )

    assert ai_agents.install_mcp_config("codex", str(tmp_path), str(tmp_path))

    config = read_toml(tmp_path / ".codex" / "config.toml")
    assert config["profiles"]["fast"]["model_instructions"] == "plain text\n"
    assert config["mcp_servers"]["partcad"]["command"] == "pc"


def test_an_invalid_codex_file_is_left_alone(tmp_path):
    pytest.importorskip("tomllib")
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "config.toml").write_text("not = [valid\n", encoding="utf-8")

    assert not ai_agents.install_mcp_config("codex", str(tmp_path), str(tmp_path))


# --------------------------------------------------------------------------- #
# The server in the PartCAD image                                              #
# --------------------------------------------------------------------------- #


@pytest.fixture
def in_the_image(monkeypatch):
    """What the PartCAD image sets on everything that runs in it."""
    from partcad_utils import app_image

    monkeypatch.setenv(app_image.MANAGED_BY_ENV, app_image.MANAGED_BY_IMAGE)
    monkeypatch.delenv(app_image.IMAGE_ENV, raising=False)


@pytest.fixture
def not_in_the_image(monkeypatch):
    from partcad_utils import app_image

    monkeypatch.delenv(app_image.MANAGED_BY_ENV, raising=False)


def test_in_the_image_the_agents_are_given_docker_run(tmp_path, in_the_image):
    """Its user has no `pc` outside the container: the agent starts the image instead."""
    ai_agents.install_agent_skills(str(tmp_path))

    claude = read_json(tmp_path / ".mcp.json")["mcpServers"]["partcad"]
    assert claude == {
        "type": "stdio",
        "command": "docker",
        "args": [
            "run",
            "-i",
            "--rm",
            "-v",
            "partcad-home:/home/pc/.partcad",
            "-v",
            "${PWD}:${PWD}",
            "-w",
            "${PWD}",
            "ghcr.io/partcad/partcad",
            "mcp",
            "--root",
            ".",
            "--from",
            ".mcp.json",
        ],
    }
    cursor = read_json(tmp_path / ".cursor" / "mcp.json")["mcpServers"]["partcad"]
    assert cursor["command"] == "docker"
    assert cursor["args"][5:9] == ["-v", "${workspaceFolder}:${workspaceFolder}", "-w", "${workspaceFolder}"]
    assert cursor["args"][-3:] == ["-p", "${workspaceFolder}", "mcp"]


def test_the_docker_entry_mounts_the_folder_and_serves_the_root(repository, in_the_image):
    """The folder holds the repository the revision tools read; the root may be deeper.

    Mounted where it is on the host, so that a path PartCAD reports is the path
    the agent, on the host, would use.
    """
    hw = package(repository / "hw")

    ai_agents.install_agent_skills(str(package(hw / "motor")))

    cursor = read_json(repository / ".cursor" / "mcp.json")["mcpServers"]["partcad"]["args"]
    assert cursor[cursor.index("-w") - 1] == "${workspaceFolder}:${workspaceFolder}"
    assert cursor[-3:] == ["-p", "${workspaceFolder}/hw", "mcp"]
    # Claude Code has no spelling for the folder: the directory it was started
    # in, and `pc mcp --root` inside the container to say when that is wrong.
    claude = read_json(repository / ".mcp.json")["mcpServers"]["partcad"]["args"]
    assert claude[claude.index("-w") - 1] == "${PWD}:${PWD}"
    assert claude[-5:] == ["mcp", "--root", "hw", "--from", ".mcp.json"]


def test_a_root_the_image_is_not_given_is_warned_about(repository, in_the_image, monkeypatch):
    hw = package(repository / "hw")
    docs = hw / "docs"
    docs.mkdir()
    warnings = []
    monkeypatch.setattr(ai_agents.pc_logging, "warning", warnings.append)

    ai_agents.install_agent_skills(str(hw), ["claude"], editor_folder=str(docs))

    assert any("outside" in warning for warning in warnings)


def test_the_docker_entry_does_not_hand_over_the_hosts_docker(tmp_path, in_the_image):
    """The socket gives the container the host's Docker; that is for a person to add, knowingly."""
    ai_agents.install_agent_skills(str(tmp_path))

    for path in (tmp_path / ".mcp.json", tmp_path / ".cursor" / "mcp.json"):
        assert not any("docker.sock" in arg for arg in read_json(path)["mcpServers"]["partcad"]["args"])


def test_the_way_to_start_it_can_be_chosen_either_way(tmp_path, monkeypatch, in_the_image):
    ai_agents.install_agent_skills(str(tmp_path), mcp_via="pc")
    assert read_json(tmp_path / ".mcp.json")["mcpServers"]["partcad"]["command"] == "pc"

    monkeypatch.delenv("PARTCAD_MANAGED_BY")
    ai_agents.install_agent_skills(str(tmp_path), mcp_via="docker")
    # The same entry, rewritten: it serves the same root.
    assert list(read_json(tmp_path / ".mcp.json")["mcpServers"]) == ["partcad"]
    assert read_json(tmp_path / ".mcp.json")["mcpServers"]["partcad"]["command"] == "docker"


def test_outside_the_image_the_default_is_pc(tmp_path, not_in_the_image):
    assert ai_agents.default_mcp_via() == "pc"
    ai_agents.install_agent_skills(str(tmp_path))
    assert read_json(tmp_path / ".mcp.json")["mcpServers"]["partcad"]["command"] == "pc"


def test_the_image_named_is_the_one_this_runs_in(tmp_path, monkeypatch, in_the_image):
    """A fork's image starts the fork's image."""
    monkeypatch.setenv("PARTCAD_IMAGE", "ghcr.io/someone/partcad")
    entry = ai_agents.mcp_server_entry("cursor", str(tmp_path), str(tmp_path), "docker")
    assert "ghcr.io/someone/partcad" in entry["args"]


def test_an_unknown_way_to_start_it_is_an_error():
    with pytest.raises(ValueError):
        ai_agents.mcp_server_entry("claude", "/repo", "/repo", "podman")


def test_the_docker_entry_runs_the_command_the_image_has():
    """`<image> mcp --root <path>` and `<image> -p <path> mcp`: the entrypoint hands both to `pc`."""
    from partcad_cli.click.command import cli

    claude = ai_agents.mcp_server_entry("claude", "/repo", "/repo", "docker")["args"]
    image = claude.index("ghcr.io/partcad/partcad")
    mcp = cli.get_command(None, claude[image + 1])
    assert claude[image + 2] in next(param for param in mcp.params if param.name == "root").opts

    cursor = ai_agents.mcp_server_entry("cursor", "/repo", "/repo", "docker")["args"]
    image = cursor.index("ghcr.io/partcad/partcad")
    assert cursor[image + 1] in next(param for param in cli.params if param.name == "path").opts
    assert cli.get_command(None, cursor[-1]) is not None


@pytest.mark.parametrize("agent", ["codex", "gemini", "zed", "kiro", "devin", "opencode"])
def test_an_agent_with_no_project_variable_is_not_given_docker_run(tmp_path, agent, in_the_image, caplog):
    """Docker has to mount the project at an absolute path, and these name it only as where they start the server."""
    config = ai_agents.MCP_CONFIGS[agent]

    with caplog.at_level("WARNING", logger="partcad"):
        assert not ai_agents.install_mcp_config(agent, str(tmp_path), str(tmp_path), "docker")

    assert not os.path.exists(config.file(str(tmp_path)))
    assert any("as 'docker run'" in record.getMessage() for record in caplog.records)
    with pytest.raises(ValueError):
        ai_agents.mcp_server_entry(agent, str(tmp_path), str(tmp_path), "docker")


# --------------------------------------------------------------------------- #
# One entry per PartCAD root                                                   #
# --------------------------------------------------------------------------- #
#
# Three directories decide what `pc init` writes, and these tests keep them
# apart: the folder the editor opens (where the files go, `editor_folder`), the
# git repository's root (only the default for it), and the PartCAD root each
# entry serves (`partcad_utils.workspace.determine_root_path`).


def package(path):
    """A PartCAD package at `path`."""
    path.mkdir(parents=True, exist_ok=True)
    (path / "partcad.yaml").write_text("desc: a package\n", encoding="utf-8")
    return path


def servers(path, key="mcpServers"):
    document = read_json(path)
    for part in key.split("."):
        document = document[part]
    return document


def roots(path, key="mcpServers"):
    """What each entry in the file serves, by name: the `--root`, or the `-p` after `${workspaceFolder}`."""
    served = {}
    for name, entry in servers(path, key).items():
        command = entry.get("command")
        line = command if isinstance(command, list) else [command, *entry.get("args", [])]
        for option in ("--root", "-p"):
            if option in line:
                served[name] = line[line.index(option) + 1]
                break
    return served


def test_a_package_below_its_root_is_served_by_the_roots_entry(repository):
    """`pc mcp` serves the root whichever of its packages is named, so the entry names the root."""
    hw = package(repository / "hw")
    motor = package(hw / "motor")

    ai_agents.install_agent_skills(str(motor), ["claude", "cursor"])
    assert roots(repository / ".mcp.json") == {"partcad": "hw"}

    # And the root's own `pc init`, or a sibling subpackage's, is the same entry.
    ai_agents.install_agent_skills(str(hw), ["claude", "cursor"])
    ai_agents.install_agent_skills(str(package(hw / "frame")), ["claude", "cursor"])
    assert roots(repository / ".mcp.json") == {"partcad": "hw"}
    assert roots(repository / ".cursor" / "mcp.json") == {"partcad": "${workspaceFolder}/hw"}


ALL_FILES = [
    ("claude", (".mcp.json",), "mcpServers"),
    ("cursor", (".cursor", "mcp.json"), "mcpServers"),
    ("gemini", (".gemini", "settings.json"), "mcpServers"),
    ("zed", (".zed", "settings.json"), "context_servers"),
    ("kiro", (".kiro", "settings", "mcp.json"), "mcpServers"),
    ("devin", (".devin", "mcp_config.json"), "mcpServers"),
    ("opencode", ("opencode.json",), "mcp.servers"),
]


@pytest.mark.parametrize("agent, path, key", ALL_FILES)
def test_every_root_in_a_repository_gets_an_entry_of_its_own(repository, agent, path, key):
    """The second root's `pc init` used to replace the first root's one `partcad` entry."""
    hw = package(repository / "hw")
    jigs = package(repository / "tools" / "jigs")

    ai_agents.install_agent_skills(str(hw), [agent])
    ai_agents.install_agent_skills(str(jigs), [agent])

    prefix = "${workspaceFolder}/" if agent == "cursor" else ""
    assert roots(repository.joinpath(*path), key) == {
        "partcad": prefix + "hw",
        "partcad-tools-jigs": prefix + "tools/jigs",
    }

    # Running either one again touches neither.
    before = repository.joinpath(*path).read_bytes()
    ai_agents.install_agent_skills(str(hw), [agent])
    ai_agents.install_agent_skills(str(jigs), [agent])
    assert repository.joinpath(*path).read_bytes() == before


def test_every_root_in_a_repository_gets_a_codex_table_of_its_own(repository):
    hw = package(repository / "hw")
    jigs = package(repository / "tools" / "jigs")

    ai_agents.install_agent_skills(str(hw), ["codex"])
    ai_agents.install_agent_skills(str(jigs), ["codex"])
    before = (repository / ".codex" / "config.toml").read_text(encoding="utf-8")
    ai_agents.install_agent_skills(str(hw), ["codex"])

    assert (repository / ".codex" / "config.toml").read_text(encoding="utf-8") == before
    config = read_toml(repository / ".codex" / "config.toml")["mcp_servers"]
    assert {name: entry["args"][2] for name, entry in config.items()} == {
        "partcad": "hw",
        "partcad-tools-jigs": "tools/jigs",
    }


def test_two_codex_tables_for_one_root_become_one(repository):
    """Read without a parser too: the tables `pc init` writes are the ones it can read back as text."""
    hw = package(repository / "hw")
    (repository / ".codex").mkdir()
    (repository / ".codex" / "config.toml").write_text(
        '[mcp_servers.partcad]\ncommand = "pc"\nargs = ["-p", "hw", "mcp"]\n\n'
        '[mcp_servers.partcad-hw]\ncommand = "pc"\nargs = ["mcp", "--root", "hw"]\n',
        encoding="utf-8",
    )

    assert ai_agents.install_mcp_config("codex", str(repository), str(hw))

    text = (repository / ".codex" / "config.toml").read_text(encoding="utf-8")
    entry = '["mcp", "--root", "hw", "--from", ".codex/config.toml"]'
    assert text == '[mcp_servers.partcad]\ncommand = "pc"\nargs = %s\n' % entry
    assert ai_agents._toml_servers(text, "mcp_servers", None) == {
        "partcad": {"command": "pc", "args": json.loads(entry)}
    }


def test_a_pcignore_sets_a_root_apart(repository):
    """A package in a folder its parent ignores is a root of its own, and so gets a server of its own."""
    plugin = package(repository / "plugin")
    case = package(plugin / "tests" / "case")
    (plugin / "tests" / ".pcignore").write_text("", encoding="utf-8")

    ai_agents.install_agent_skills(str(plugin), ["claude"])
    ai_agents.install_agent_skills(str(case), ["claude"])

    assert roots(repository / ".mcp.json") == {"partcad": "plugin", "partcad-plugin-tests-case": "plugin/tests/case"}


def test_without_a_repository_everything_goes_to_the_partcad_root(tmp_path):
    """Not into a subpackage's directory, which nobody opens an editor on."""
    robot = package(tmp_path / "robot")
    arm = package(robot / "arm")

    assert ai_agents.install_agent_skills(str(arm), ["claude", "cursor"])

    assert roots(robot / ".mcp.json") == {"partcad": "."}
    assert (robot / ".claude" / "skills" / "pc" / ".claude-plugin" / "plugin.json").is_file()
    assert (robot / "AGENTS.md").is_file()
    assert not (arm / ".mcp.json").exists()
    assert not (arm / ".claude").exists()


def test_an_editor_opened_above_the_repository(tmp_path):
    """A folder of repositories: none of the agents reads a repository's files from there.

    So `--editor-folder` writes them into the folder the editor does open, with
    the root named relative to it.
    """
    projects = tmp_path / "projects"
    repository = projects / "robot"
    (repository / ".git").mkdir(parents=True)
    hw = package(repository / "hw")

    ai_agents.install_agent_skills(str(hw), ["claude", "cursor", "codex"], editor_folder=str(projects))

    assert roots(projects / ".mcp.json") == {"partcad": "robot/hw"}
    assert roots(projects / ".cursor" / "mcp.json") == {"partcad": "${workspaceFolder}/robot/hw"}
    assert read_toml(projects / ".codex" / "config.toml")["mcp_servers"]["partcad"]["args"][2] == "robot/hw"
    assert (projects / ".cursor" / "skills" / "pc-init" / "SKILL.md").is_file()
    assert "`robot/hw/partcad.yaml`" in (projects / "AGENTS.md").read_text(encoding="utf-8")
    assert not (repository / ".mcp.json").exists()


def test_an_editor_opened_on_the_partcad_root_below_the_repository(repository):
    hw = package(repository / "hw")

    ai_agents.install_agent_skills(str(package(hw / "motor")), ["claude", "cursor"], editor_folder=str(hw))

    assert roots(hw / ".mcp.json") == {"partcad": "."}
    assert roots(hw / ".cursor" / "mcp.json") == {"partcad": "${workspaceFolder}"}


def test_an_editor_opened_inside_the_root_still_reaches_it(repository):
    """A folder inside the root: the root is above the folder, so the path climbs."""
    hw = package(repository / "hw")
    docs = hw / "docs"
    docs.mkdir()

    ai_agents.install_agent_skills(str(hw), ["claude", "cursor"], editor_folder=str(docs))

    assert roots(docs / ".mcp.json") == {"partcad": ".."}
    assert roots(docs / ".cursor" / "mcp.json") == {"partcad": "${workspaceFolder}/.."}


@pytest.mark.parametrize("agent", ["claude", "codex", "gemini", "zed", "kiro", "devin", "opencode"])
def test_an_agent_started_below_the_folder_serves_the_right_root(repository, agent):
    """What the old `-p ${CLAUDE_PROJECT_DIR:-.}/hw` got wrong.

    Claude Code reads the `.mcp.json` of every folder above the one it was
    started in, and starts the server in the one it was started in. Started in
    `hw/motor`, a path relative to the server's directory meant `hw/motor/hw`;
    `--root` is relative to the file's folder wherever that is, in every file
    it is written into.
    """
    from partcad_utils import agent_config

    hw = package(repository / "hw")
    motor = package(hw / "motor")
    ai_agents.install_agent_skills(str(hw), [agent])

    for started_in in (repository, hw, motor):
        assert agent_config.resolve_root(str(started_in), "hw") == str(hw)


def test_every_file_a_root_entry_is_written_to_is_one_pc_mcp_reads():
    """`pc mcp --root` looks for its entry in `agent_config.CONFIG_FILES`; an agent missing there would never start."""
    from partcad_utils import agent_config

    for config in ai_agents.MCP_CONFIGS.values():
        if config.project is None:
            for path in (config.path, *config.alternatives):
                assert path.replace(os.sep, "/") in agent_config.CONFIG_FILES


@pytest.mark.parametrize(
    "agent, legacy",
    [
        # What `pc init` wrote before it told the three directories apart.
        ("claude", {"type": "stdio", "command": "pc", "args": ["-p", "${CLAUDE_PROJECT_DIR:-.}/hw", "mcp"]}),
        ("cursor", {"command": "pc", "args": ["-p", "${workspaceFolder}/hw", "mcp"]}),
        ("gemini", {"command": "pc", "args": ["-p", "hw", "mcp"]}),
        # The PartCAD image.
        (
            "claude",
            {
                "type": "stdio",
                "command": "docker",
                "args": ["run", "-i", "--rm", "-v", "${PWD}:${PWD}", "-w", "${PWD}", "ghcr.io/partcad/partcad"]
                + ["-p", "${PWD}/hw", "mcp"],
            },
        ),
        # Pointed at a subpackage, which a subpackage's `pc init` used to do.
        ("claude", {"type": "stdio", "command": "pc", "args": ["-p", "${CLAUDE_PROJECT_DIR:-.}/hw/motor", "mcp"]}),
        # Or by hand, through `uvx`.
        ("claude", {"command": "uvx", "args": ["partcad", "-p", "hw", "mcp"]}),
    ],
)
def test_an_entry_an_older_release_wrote_is_updated_where_it_is(repository, agent, legacy):
    """Under the name it has, and where it is in the file: an agent's approvals are keyed by that name."""
    hw = package(repository / "hw")
    package(hw / "motor")
    path = repository / ai_agents.MCP_CONFIGS[agent].path
    path.parent.mkdir(parents=True, exist_ok=True)
    theirs = {"command": "gh-mcp"}
    path.write_text(json.dumps({"mcpServers": {"partcad": legacy, "github": theirs}}), encoding="utf-8")

    ai_agents.install_mcp_config(agent, str(repository), str(hw))

    assert servers(path) == {"partcad": ai_agents.mcp_server_entry(agent, str(repository), str(hw)), "github": theirs}


def test_an_entry_under_a_name_of_the_users_own_choosing_is_kept(repository):
    hw = package(repository / "hw")
    (repository / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"partcad-robot": {"command": "pc", "args": ["mcp", "--root", "hw"]}}}),
        encoding="utf-8",
    )

    ai_agents.install_mcp_config("claude", str(repository), str(hw))

    assert list(servers(repository / ".mcp.json")) == ["partcad-robot"]


@pytest.mark.parametrize(
    "theirs",
    [
        {"type": "http", "url": "https://example.com/mcp"},
        # Named like ours and given an `mcp`, but not PartCAD: review found
        # that one taken for PartCAD's and replaced.
        {"command": "other-tool", "args": ["mcp"]},
        {"command": "docker", "args": ["run", "-v", "/home/me/partcad:/home/me/partcad", "other/image", "mcp"]},
    ],
)
def test_a_partcad_entry_pc_did_not_write_is_left_alone(repository, theirs):
    """Somebody else's server called `partcad` keeps its name; PartCAD's goes beside it."""
    hw = package(repository / "hw")
    (repository / ".mcp.json").write_text(json.dumps({"mcpServers": {"partcad": theirs}}), encoding="utf-8")

    ai_agents.install_mcp_config("claude", str(repository), str(hw))

    assert servers(repository / ".mcp.json")["partcad"] == theirs
    assert roots(repository / ".mcp.json")["partcad-hw"] == "hw"


def test_a_partcad_toml_table_pc_did_not_write_is_left_alone(tmp_path):
    pytest.importorskip("tomllib")
    hw = package(tmp_path / "hw")
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "config.toml").write_text('[mcp_servers]\npartcad = { command = "other" }\n', "utf-8")

    assert ai_agents.install_mcp_config("codex", str(tmp_path), str(hw))

    config = read_toml(tmp_path / ".codex" / "config.toml")["mcp_servers"]
    assert config["partcad"] == {"command": "other"}
    assert config["partcad-hw"]["args"] == ["mcp", "--root", "hw", "--from", ".codex/config.toml"]


def test_two_entries_for_one_root_become_one(repository):
    hw = package(repository / "hw")
    duplicates = {
        "partcad": {"command": "pc", "args": ["-p", "${CLAUDE_PROJECT_DIR:-.}/hw", "mcp"]},
        "partcad-hw": {"type": "stdio", "command": "pc", "args": ["mcp", "--root", "hw"]},
    }
    (repository / ".mcp.json").write_text(json.dumps({"mcpServers": duplicates}), encoding="utf-8")

    ai_agents.install_mcp_config("claude", str(repository), str(hw))

    assert list(servers(repository / ".mcp.json")) == ["partcad"]


def test_an_entry_for_a_folder_that_is_gone_is_removed(repository):
    """It can only fail to start -- `pc -p` refuses a path that does not exist."""
    hw = package(repository / "hw")
    gone = {"command": "pc", "args": ["-p", "${CLAUDE_PROJECT_DIR:-.}/renamed-since", "mcp"]}
    (repository / ".mcp.json").write_text(json.dumps({"mcpServers": {"partcad": gone}}), encoding="utf-8")

    ai_agents.install_mcp_config("claude", str(repository), str(hw))

    assert servers(repository / ".mcp.json") == {
        "partcad": ai_agents.mcp_server_entry("claude", str(repository), str(hw))
    }


def test_an_entry_of_another_shape_is_not_read_as_ours():
    assert ai_agents.served_directory({"command": "pc", "args": ["-p", "${input:package}", "mcp"]}, "/r") is None
    assert ai_agents.served_directory({"command": "docker", "args": ["run", "-p", "80:80", "img", "mcp"]}, "/r") is None
    assert ai_agents.served_directory({"command": "pc", "args": ["--path", "x", "--verbose", "mcp"]}, "/r") is None
    assert ai_agents.served_directory({"type": "http", "url": "https://example.com"}, "/r") is None
    assert (
        ai_agents.served_directory({"command": "docker", "args": ["run", "--name", "partcad", "x", "mcp"]}, "/r")
        is None
    )
    # PartCAD, run any of the ways it is run, with no path: where it is started.
    for line in (["/old/venv/bin/pc", "mcp"], ["pc.exe", "mcp"], ["uvx", "partcad", "mcp"]):
        entry = {"command": line[0], "args": line[1:]}
        assert ai_agents.served_directory(entry, "/r") == os.path.normpath("/r")
    image = {"command": ["docker", "run", "-i", "mcp/partcad:0.10", "-p", "/abs/hw", "mcp"]}
    assert ai_agents.served_directory(image, "/r") == os.path.normpath("/abs/hw")


def test_names_are_ones_every_agent_accepts(repository):
    """Claude Code's rule is letters, digits, `-` and `_`; Cursor's limit is 60 for a name and a tool together."""
    taken = {"partcad"}
    name = ai_agents.server_name(str(repository / "my parts" / "v2.0"), str(repository), taken)
    assert name == "partcad-my-parts-v2-0"

    deep = repository / "mechanical" / "subsystems" / "drivetrain" / "gearbox-assembly"
    name = ai_agents.server_name(str(deep), str(repository), taken)
    assert name.startswith("partcad-mechanical-")
    assert len(name) <= ai_agents.MAX_SERVER_NAME
    assert all(character.isalnum() or character in "-_" for character in name)
    # Two long paths that start alike do not end up with one name.
    other = repository / "mechanical" / "subsystems" / "drivetrain" / "gearbox-housing"
    assert ai_agents.server_name(str(other), str(repository), taken) != name


def test_skills_only_at_the_top_of_a_repository_serves_every_root_below_it(repository):
    """`pc init --skills-only` at a repository whose packages are all in subfolders."""
    package(repository / "hw")
    package(repository / "hw" / "motor")
    package(repository / "tools" / "jigs")
    package(repository / "node_modules" / "something")
    package(repository / ".cache" / "something")

    ai_agents.install_agent_skills(str(repository), ["claude"])

    assert roots(repository / ".mcp.json") == {"partcad": "hw", "partcad-tools-jigs": "tools/jigs"}


def test_nothing_written_names_this_machine(repository):
    """The files are committed: an absolute path in them is one only this checkout has."""
    package(repository / "hw")
    package(repository / "tools" / "jigs")

    for via in ai_agents.MCP_VIA:
        ai_agents.install_agent_skills(str(repository), list(ai_agents.AGENT_SPECS), mcp_via=via)
        for agent, config in ai_agents.MCP_CONFIGS.items():
            path = config.file(str(repository))
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    assert str(repository) not in f.read(), agent


def test_another_drive_writes_no_path(tmp_path, monkeypatch):
    """On Windows there is no relative path between two drives, and an absolute one would be this machine's."""
    hw = package(tmp_path / "hw")
    real = ai_agents.relative_to

    def across_drives(path, folder):
        if os.path.abspath(path).startswith(str(hw)):
            raise ValueError("path is on mount 'C:', start on mount 'D:'")
        return real(path, folder)

    monkeypatch.setattr(ai_agents, "relative_to", across_drives)

    assert ai_agents.install_agent_skills(str(hw), ["claude"], editor_folder=str(tmp_path))

    assert (tmp_path / ".claude" / "skills" / "pc").is_dir()
    assert not (tmp_path / ".mcp.json").exists()
    assert not (tmp_path / "AGENTS.md").exists()


# --- What review found, the second time ---


def test_an_entry_naming_the_partcad_yaml_is_the_roots_and_is_not_gone(repository):
    """`pc -p` takes a package's directory or its `partcad.yaml`; the file is no reason to remove the entry."""
    hw = package(repository / "hw")
    jigs = package(repository / "jigs")
    theirs = {"command": "pc", "args": ["-p", "${CLAUDE_PROJECT_DIR:-.}/hw/partcad.yaml", "mcp"]}
    (repository / ".mcp.json").write_text(json.dumps({"mcpServers": {"partcad": theirs}}), encoding="utf-8")

    # Another root's `pc init` leaves it alone...
    ai_agents.install_mcp_config("claude", str(repository), str(jigs))
    assert servers(repository / ".mcp.json")["partcad"] == theirs
    # ...and this root's updates it, under its name.
    ai_agents.install_mcp_config("claude", str(repository), str(hw))
    assert roots(repository / ".mcp.json") == {"partcad": "hw", "partcad-jigs": "jigs"}


def test_an_opencode_entry_moved_out_of_the_old_shape_keeps_its_name(tmp_path):
    """Its approvals are keyed by the name; moving it under `servers` is no reason to change that."""
    before = {"mcp": {"partcad-robot": {"type": "local", "command": ["pc", "-p", ".", "mcp"]}}}
    (tmp_path / "opencode.json").write_text(json.dumps(before), encoding="utf-8")

    assert ai_agents.install_mcp_config("opencode", str(tmp_path), str(tmp_path))

    config = read_json(tmp_path / "opencode.json")
    assert "partcad-robot" not in config["mcp"]
    assert list(config["mcp"]["servers"]) == ["partcad-robot"]


def test_a_codex_table_for_a_folder_that_is_gone_is_replaced_where_it_is(tmp_path):
    """Its name is free once it goes, and is the name the replacement takes: replaced, not removed and refused."""
    pytest.importorskip("tomllib")
    hw = package(tmp_path / "hw")
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "config.toml").write_text(
        '[mcp_servers.partcad]\ncommand = "pc"\nargs = ["-p", "renamed-since", "mcp"]\n\n[profiles.fast]\nmodel = "m"\n',
        encoding="utf-8",
    )

    assert ai_agents.install_mcp_config("codex", str(tmp_path), str(hw))

    text = (tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert text.startswith("[mcp_servers.partcad]\n")
    assert read_toml(tmp_path / ".codex" / "config.toml")["mcp_servers"]["partcad"]["args"][2] == "hw"
    assert read_toml(tmp_path / ".codex" / "config.toml")["profiles"]["fast"] == {"model": "m"}


@pytest.mark.parametrize("existing", ["opencode.jsonc", ".opencode/opencode.json"])
def test_the_entry_names_the_file_it_is_in(tmp_path, existing):
    """`--from` is the file actually written -- the one a repository already has, where there is one."""
    from partcad_utils import agent_config

    path = tmp_path.joinpath(*existing.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")

    assert ai_agents.install_mcp_config("opencode", str(tmp_path), str(tmp_path))

    command = read_json(path)["mcp"]["servers"]["partcad"]["command"]
    assert agent_config.source_argument(command) == existing
    assert agent_config.resolve_root(str(tmp_path), ".", existing) == str(tmp_path)
