#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The shared skills library, the Claude plugin, and the wheel that carries both.

`claude plugin validate` runs in CI and is the authority on the manifests, but it
cannot be the only check. Run against `ai-agents/claude` it reads *nothing*: the
plugin's `skills` is a symlink into `ai-agents/common/skills`, and validation
does not follow symlinks -- it says so, as a warning, and passes. So a skill with
no front matter, or with a `name` that does not match the directory it is in,
passes the workflow that exists to catch exactly that and is discovered by
whoever installs the plugin.

The library ships in the wheel as well, because `pc init` installs it into a
user's repository out of the installed PartCAD, and `src/partcad/ai_agents` is
two symlinks that put it there. That is the second thing checked here: the
symlinks, and whether `pyproject.toml` declares what they resolve to. Neither is
visible to `claude plugin validate`, and neither would be noticed by a test run
from a checkout, where every file is on disk whether it was packaged or not.

These run wherever pytest runs, which includes the Windows jobs of the matrix,
so nothing here reads anything *through* a symlink: whether git materialized one
is a property of the checkout, and the checks that do look at them skip when it
did not. The published artifact has none by construction.
`.github/workflows/plugin.yml` owns that end.
"""

import fnmatch
import json
import re
from pathlib import Path

import pytest
import yaml

# `tomllib` is only in the standard library from Python 3.11, and this repo
# still supports 3.10 -- see the same note in `test_versions.py`.
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

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
    """Every skill in the library, as a directory, sorted for stable test ids."""
    return sorted(p for p in SKILLS.iterdir() if p.is_dir())


def _skill_ids():
    """The names pytest parametrizes over, which are also the `/pc:<name>` commands."""
    return [p.name for p in _skill_dirs()]


def _front_matter(skill: Path) -> dict:
    """The skill's YAML front matter, parsed the way a session loading it would."""
    match = FRONT_MATTER.match((skill / "SKILL.md").read_text(encoding="utf-8"))
    assert match, "%s/SKILL.md has no `---` front matter block at the top of the file" % skill.name
    parsed = yaml.safe_load(match.group("body"))
    assert isinstance(parsed, dict), "%s/SKILL.md front matter is not a mapping" % skill.name
    return parsed


def test_there_are_skills_to_ship():
    """An empty library is what a Windows checkout of the symlink looks like."""
    assert _skill_dirs(), "no skill directories under %s" % SKILLS


@pytest.mark.parametrize("name", _skill_ids())
def test_every_skill_directory_holds_a_skill(name):
    """A directory with no SKILL.md ships as a component that loads nothing."""
    assert (SKILLS / name / "SKILL.md").is_file(), "%s has no SKILL.md" % (SKILLS / name)


@pytest.mark.parametrize("name", _skill_ids())
def test_every_skill_is_named_after_its_directory(name):
    """The directory decides the command; the front matter decides the name.

    They are two different fields and nothing but this makes them agree, so a
    renamed directory leaves a skill that answers to a command nobody typed.
    """
    front_matter = _front_matter(SKILLS / name)
    assert front_matter.get("name") == name, "%s: front matter names %r" % (
        SKILLS / name,
        front_matter.get("name"),
    )
    assert SKILL_NAME.match(name), "%r is not a usable command name for /pc:<name>" % name


@pytest.mark.parametrize("name", _skill_ids())
def test_every_skill_says_when_to_use_it(name):
    """The description is the whole of what an agent sees before invoking."""
    description = _front_matter(SKILLS / name).get("description")
    assert isinstance(description, str) and description.strip(), "%s has no description in its front matter" % (
        SKILLS / name
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


# --- Shipping: the wheel is where a user's copy comes from ---
#
# `pc init` reads the skills out of the *installed* PartCAD, so what matters is
# not that they are in this repository but that they are in the distribution.
# Two things put them there and neither is visible from a checkout: the symlinks
# under `src/partcad/ai_agents`, and the `package-data` patterns that name what
# they resolve to.


PYPROJECT = REPO_ROOT / "pyproject.toml"
PYINSTALLER_SPEC = REPO_ROOT / "dev-tools" / "pyinstaller" / "partcad.spec"

# The package the library is data of, and the two names it is data under.
DATA_PACKAGE = "partcad.ai_agents"
DATA_DIR = REPO_ROOT / "src" / "partcad" / "ai_agents"
SKILLS_LINK = DATA_DIR / "skills"
MANIFEST_LINK = DATA_DIR / "plugin.json"


def _library_files():
    """Every file the library and the manifest consist of, as the wheel sees them.

    Relative to the data package, which is what a `package-data` pattern is
    matched against: `skills/init/SKILL.md`, `plugin.json`.
    """
    names = [p.relative_to(SKILLS.parent).as_posix() for p in SKILLS.rglob("*") if p.is_file()]
    return sorted(names + [MANIFEST_LINK.name])


def test_every_library_file_is_declared_as_package_data():
    """A file setuptools does not know about is not in the wheel.

    Nothing else would notice. The tests run from a checkout, where these files
    are on disk whether they were packaged or not, so a pattern that misses one
    produces an install where the skill exists in the repository, passes every
    test above, and is simply absent from what a user gets.
    """
    patterns = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]["setuptools"]["package-data"]
    declared = patterns.get(DATA_PACKAGE)
    assert declared, "%s is not in [tool.setuptools.package-data] of pyproject.toml" % DATA_PACKAGE

    missed = [
        name
        for name in _library_files()
        # `**` in a setuptools pattern is `glob`'s: any number of directories.
        # `fnmatch` has no such thing, so the pattern is lowered to one that
        # spans separators, which is what `**/` means here.
        if not any(fnmatch.fnmatch(name, pattern.replace("**/", "*")) for pattern in declared)
    ]
    assert not missed, "not covered by %s in pyproject.toml: %s" % (DATA_PACKAGE, missed)


def test_the_frozen_bundle_carries_them_too():
    """`package-data` is setuptools', and PyInstaller does not read it.

    The standalone bundle is the install whose user is least likely to have
    another copy of these files anywhere -- they have no Python at all -- and it
    is built from a spec that lists its data by hand.
    """
    spec = PYINSTALLER_SPEC.read_text(encoding="utf-8")
    assert '"partcad/ai_agents/skills"' in spec, "the spec does not carry the skills into the bundle"
    assert '"partcad/ai_agents"' in spec, "the spec does not carry the plugin manifest into the bundle"


# Skipped rather than failed where git did not materialize the symlinks: that is
# a property of the checkout (Windows, without `core.symlinks`), and it is the
# wheel *built* from such a checkout that would be short, not this repository.
# What must not happen is that they quietly stop pointing at the library.


@pytest.mark.skipif(not SKILLS_LINK.is_symlink(), reason="the checkout did not materialize symlinks")
def test_the_wheel_ships_the_library_itself():
    """One copy of every skill, not a second one under `src/` to keep in step."""
    assert SKILLS_LINK.resolve() == SKILLS.resolve()


@pytest.mark.skipif(not MANIFEST_LINK.is_symlink(), reason="the checkout did not materialize symlinks")
def test_the_wheel_ships_the_manifest_that_gets_bumped():
    """`dev-tools/bumpversion.toml` names the file in `ai-agents`; this is it.

    The version in the installed plugin is therefore the version of the PartCAD
    that installed it, with nothing keeping the two in step but this.
    """
    assert MANIFEST_LINK.resolve() == PLUGIN_MANIFEST.resolve()


@pytest.mark.skipif(not SKILLS_LINK.is_symlink(), reason="the checkout did not materialize symlinks")
def test_the_plugin_ships_the_library_itself():
    """And so does the plugin, through a symlink of its own."""
    assert (PLUGIN / "skills").resolve() == SKILLS.resolve()
