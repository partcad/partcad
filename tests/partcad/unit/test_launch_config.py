#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""Tests for the "Render" run command that ``pc init`` adds to a repository.

The file it writes belongs to the user: it may already exist, hold commands of
their own, and be full of comments explaining them. Most of what is checked here
is that none of that is lost -- a package can be created again, a comment cannot
be brought back.
"""

import json

import pytest

import partcad.launch_config as launch_config

WITH_COMMENTS = """{
  // Use IntelliSense to learn about possible attributes.
  "version": "0.2.0",
  "configurations": [
    {
      // the one that was already here
      "name": "Debug: partcad init",
      "type": "debugpy",
      "request": "launch"
    }
  ]
}
"""


def read(path):
    return launch_config.parse_launch_configuration(path.read_text(encoding="utf-8"))


def names(path):
    return [configuration["name"] for configuration in read(path)["configurations"]]


@pytest.fixture
def repository(tmp_path):
    """A git repository, as far as anything here can tell."""
    (tmp_path / ".git").mkdir()
    return tmp_path


def test_the_file_is_created_when_there_is_none(tmp_path):
    assert launch_config.add_render_configuration(str(tmp_path))

    launch = tmp_path / ".vscode" / "launch.json"
    assert read(launch)["version"] == launch_config.LAUNCH_VERSION
    (configuration,) = read(launch)["configurations"]
    assert configuration["name"] == "Render"
    assert configuration["command"] == "pc render"
    # The one launch type a stock editor has that runs a command rather than a
    # program under a debugger. Without it there is no button to press.
    assert configuration["type"] == "node-terminal"
    assert configuration["cwd"] == "${workspaceFolder}"


def test_it_is_written_at_the_root_of_the_repository(repository):
    package = repository / "packages" / "widget"
    package.mkdir(parents=True)

    assert launch_config.add_render_configuration(str(package))

    # The editor opens the repository, so its launch configuration is the one
    # that shows up in "Run and Debug"...
    assert not (package / ".vscode").exists()
    (configuration,) = read(repository / ".vscode" / "launch.json")["configurations"]
    # ...and the command still has to run where the package is.
    assert configuration["cwd"] == "${workspaceFolder}/packages/widget"


def test_a_worktree_or_submodule_is_a_repository_too(tmp_path):
    # `.git` is a file rather than a directory in both.
    (tmp_path / ".git").write_text("gitdir: ../.git/worktrees/one\n", encoding="utf-8")
    package = tmp_path / "package"
    package.mkdir()

    assert launch_config.add_render_configuration(str(package))
    assert (tmp_path / ".vscode" / "launch.json").exists()


def test_comments_and_existing_commands_survive(repository):
    launch = repository / ".vscode" / "launch.json"
    launch.parent.mkdir()
    launch.write_text(WITH_COMMENTS, encoding="utf-8")

    assert launch_config.add_render_configuration(str(repository))

    text = launch.read_text(encoding="utf-8")
    assert "// Use IntelliSense to learn about possible attributes." in text
    assert "// the one that was already here" in text
    assert names(launch) == ["Render", "Debug: partcad init"]


def test_adding_it_twice_changes_nothing(repository):
    launch = repository / ".vscode" / "launch.json"
    launch.parent.mkdir()
    launch.write_text(WITH_COMMENTS, encoding="utf-8")

    assert launch_config.add_render_configuration(str(repository))
    before = launch.read_text(encoding="utf-8")

    assert not launch_config.add_render_configuration(str(repository))
    assert launch.read_text(encoding="utf-8") == before


def test_an_empty_list_of_commands_is_filled_in(repository):
    launch = repository / ".vscode" / "launch.json"
    launch.parent.mkdir()
    launch.write_text('{\n  "version": "0.2.0",\n  "configurations": []\n}\n', encoding="utf-8")

    assert launch_config.add_render_configuration(str(repository))
    assert names(launch) == ["Render"]


def test_the_file_keeps_its_own_indentation(repository):
    launch = repository / ".vscode" / "launch.json"
    launch.parent.mkdir()
    launch.write_text('{\n\t"version": "0.2.0",\n\t"configurations": []\n}\n', encoding="utf-8")

    assert launch_config.add_render_configuration(str(repository))
    text = launch.read_text(encoding="utf-8")
    assert '\t\t\t"name": "Render"' in text
    assert names(launch) == ["Render"]


def test_a_commented_out_block_is_not_mistaken_for_the_real_one(repository):
    # This repository's own launch.json opens with a commented-out compound that
    # names its `configurations`, and inserting the command there wrote it into
    # the middle of a comment.
    launch = repository / ".vscode" / "launch.json"
    launch.parent.mkdir()
    launch.write_text(
        """{
  "version": "0.2.0",
  "compounds": [
    // {
    //   "name": "Everything",
    //   "configurations": ["One", "Two"]
    // }
  ],
  "configurations": [
    {
      "name": "One",
      "type": "debugpy",
      "request": "launch"
    }
  ]
}
""",
        encoding="utf-8",
    )

    assert launch_config.add_render_configuration(str(repository))

    text = launch.read_text(encoding="utf-8")
    assert '//   "configurations": ["One", "Two"]' in text, "the comment was edited"
    assert names(launch) == ["Render", "One"]
    assert read(launch)["compounds"] == []


def test_a_compound_launch_is_not_mistaken_for_the_real_one(repository):
    # A compound's `configurations` lists the names of other launches, not
    # commands. Adding one there produces a file that no longer describes what
    # its author wrote -- and PartCAD's own launch.json puts compounds first.
    launch = repository / ".vscode" / "launch.json"
    launch.parent.mkdir()
    launch.write_text(
        """{
  "version": "0.2.0",
  "compounds": [
    {
      "name": "Everything",
      "configurations": ["One", "Two"]
    }
  ],
  "configurations": [
    {
      "name": "One",
      "type": "debugpy",
      "request": "launch"
    }
  ]
}
""",
        encoding="utf-8",
    )

    assert launch_config.add_render_configuration(str(repository))

    parsed = read(launch)
    assert parsed["compounds"][0]["configurations"] == ["One", "Two"], "the compound was edited"
    assert names(launch) == ["Render", "One"]


def test_a_comment_between_the_brackets_of_an_empty_list(repository):
    launch = repository / ".vscode" / "launch.json"
    launch.parent.mkdir()
    launch.write_text('{\n  "configurations": [\n    // nothing here yet\n  ]\n}\n', encoding="utf-8")

    assert launch_config.add_render_configuration(str(repository))
    assert names(launch) == ["Render"]


def test_a_file_that_cannot_be_parsed_is_left_alone(repository):
    launch = repository / ".vscode" / "launch.json"
    launch.parent.mkdir()
    launch.write_text("this is not JSON at all", encoding="utf-8")

    assert not launch_config.add_render_configuration(str(repository))
    assert launch.read_text(encoding="utf-8") == "this is not JSON at all"


def test_a_file_with_nowhere_to_add_the_command_is_left_alone(repository):
    launch = repository / ".vscode" / "launch.json"
    launch.parent.mkdir()
    launch.write_text('{\n  "version": "0.2.0"\n}\n', encoding="utf-8")

    assert not launch_config.add_render_configuration(str(repository))
    assert "Render" not in launch.read_text(encoding="utf-8")


def test_trailing_commas_do_not_stop_it(repository):
    launch = repository / ".vscode" / "launch.json"
    launch.parent.mkdir()
    launch.write_text(
        '{\n  "version": "0.2.0",\n  "configurations": [\n    {\n      "name": "Other",\n    },\n  ],\n}\n',
        encoding="utf-8",
    )

    assert launch_config.add_render_configuration(str(repository))
    assert names(launch) == ["Render", "Other"]


def test_blanking_comments_keeps_every_offset():
    # What lets a match in the blanked copy be applied to the file itself.
    text = '{ // gone\n  "a": /* also gone */ 1, "b": "// kept" }'
    blanked = launch_config.blank_json_comments(text)
    assert len(blanked) == len(text)
    assert blanked.count("\n") == text.count("\n")
    assert "gone" not in blanked
    # A comment is what is outside a string, not what looks like one inside it.
    assert '"// kept"' in blanked


def test_a_url_in_a_value_is_not_a_comment():
    parsed = launch_config.parse_launch_configuration('{"url": "https://partcad.org/", "configurations": []}')
    assert parsed["url"] == "https://partcad.org/"


def test_what_is_written_is_json(tmp_path):
    # Written by hand into an existing file, so this is worth stating outright.
    (tmp_path / ".git").mkdir()
    launch = tmp_path / ".vscode" / "launch.json"
    launch.parent.mkdir()
    launch.write_text('{"version": "0.2.0", "configurations": [{"name": "Other"}]}', encoding="utf-8")

    assert launch_config.add_render_configuration(str(tmp_path))
    json.loads(launch.read_text(encoding="utf-8"))
