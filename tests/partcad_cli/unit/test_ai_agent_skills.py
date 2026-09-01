#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The shared skills library and the Claude plugin that wraps it.

`claude plugin validate` runs in CI and is the authority on the manifests, but it
cannot be the only check. Run against `ai-agents/claude` it reads *nothing*: the
plugin's `skills` is a symlink into `ai-agents/common/skills`, and validation
does not follow symlinks -- it says so, as a warning, and passes. So a skill with
no front matter, or with a `name` that does not match the directory it is in,
passes the workflow that exists to catch exactly that and is discovered by
whoever installs the plugin.

These run wherever pytest runs, which includes the Windows jobs of the matrix,
so nothing here asserts anything about symlinks: whether git materialized one is
a property of the checkout, and the artifact that gets published has none by
construction. `.github/workflows/plugin.yml` owns that end.
"""

import json
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS = REPO_ROOT / "ai-agents" / "common" / "skills"
PLUGIN = REPO_ROOT / "ai-agents" / "claude"
PLUGIN_MANIFEST = PLUGIN / ".claude-plugin" / "plugin.json"
MARKETPLACE = REPO_ROOT / ".claude-plugin" / "marketplace.json"

# A skill's directory name is the command it is invoked as -- `/pc:<name>` -- so
# it is spelled the way a command is.
SKILL_NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# Front matter: the first block of a `SKILL.md`, fenced by `---` lines.
FRONT_MATTER = re.compile(r"\A---\n(?P<body>.*?)\n---\n", re.DOTALL)


def _skill_dirs():
    return sorted(p for p in SKILLS.iterdir() if p.is_dir())


def _skill_ids():
    return [p.name for p in _skill_dirs()]


def _front_matter(skill: Path) -> dict:
    match = FRONT_MATTER.match((skill / "SKILL.md").read_text(encoding="utf-8"))
    assert match, "%s/SKILL.md has no `---` front matter block at the top of the file" % skill.name
    parsed = yaml.safe_load(match.group("body"))
    assert isinstance(parsed, dict), "%s/SKILL.md front matter is not a mapping" % skill.name
    return parsed


def test_there_are_skills_to_ship():
    """An empty library is what a Windows checkout of the symlink looks like."""
    assert _skill_dirs(), "no skill directories under ai-agents/common/skills"


@pytest.mark.parametrize("name", _skill_ids())
def test_every_skill_directory_holds_a_skill(name):
    assert (SKILLS / name / "SKILL.md").is_file(), "ai-agents/common/skills/%s has no SKILL.md" % name


@pytest.mark.parametrize("name", _skill_ids())
def test_every_skill_is_named_after_its_directory(name):
    """The directory decides the command; the front matter decides the name.

    They are two different fields and nothing but this makes them agree, so a
    renamed directory leaves a skill that answers to a command nobody typed.
    """
    front_matter = _front_matter(SKILLS / name)
    assert front_matter.get("name") == name, "ai-agents/common/skills/%s: front matter names %r" % (
        name,
        front_matter.get("name"),
    )
    assert SKILL_NAME.match(name), "%r is not a usable command name for /pc:<name>" % name


@pytest.mark.parametrize("name", _skill_ids())
def test_every_skill_says_when_to_use_it(name):
    """The description is the whole of what an agent sees before invoking."""
    description = _front_matter(SKILLS / name).get("description")
    assert isinstance(description, str) and description.strip(), (
        "ai-agents/common/skills/%s has no description in its front matter" % name
    )


def test_the_marketplace_entry_and_the_plugin_manifest_agree():
    """`claude plugin tag` refuses to tag a release where these disagree.

    It refuses at the point of release, which is the wrong end of the process to
    find out: the plugin is published by the same run that publishes the wheel,
    and a run that gets that far has already built everything else.
    """
    manifest = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
    catalog = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
    entries = [entry for entry in catalog["plugins"] if entry["name"] == manifest["name"]]
    assert len(entries) == 1, "%s is not listed exactly once in .claude-plugin/marketplace.json" % manifest["name"]
    # Relative to the root of the marketplace, which is the repository root --
    # not to the ".claude-plugin" directory the catalog itself sits in.
    source = (REPO_ROOT / entries[0]["source"]).resolve()
    assert source == PLUGIN.resolve(), "the catalog's source %r is not %s" % (entries[0]["source"], PLUGIN)
