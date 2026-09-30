#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The build backend that refuses a wheel with no AI agent skills in it.

The wheel ships the skills through two symlinks from `src/partcad/ai_agents`
into `ai-agents/`. A checkout where git did not materialize them has, in their
place, a text file holding the path each pointed at -- and setuptools packages
that without complaint: `skills/**/*` matches nothing, and `plugin.json` matches
a 52-byte file whose content is a path. The result builds, installs, imports,
and runs `pc version`; it just has no skills in it, on every machine that wheel
reaches.

Git for Windows is where this comes from -- `core.symlinks` is off unless it is
turned on -- but not only Windows: a GitHub source zip drops symlinks on every
platform, so `pip install <that zip>` has the same hole.

`dev-tools/build-backend/partcad_build_backend.py` is `setuptools.build_meta`
with that precondition in front of the two hooks that produce a redistributable
artifact. These tests drive the precondition directly, against trees built to
look like each case, rather than building a wheel: a build is slow, and what is
worth pinning is the decision, not setuptools.
"""

import importlib.util
import json
import os
from pathlib import Path

import pytest
from setuptools.command.egg_info import manifest_maker

# `tomllib` is only in the standard library from Python 3.11, and this repo
# still supports 3.10 -- see the same note in `test_versions.py`.
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "dev-tools" / "build-backend"
BACKEND = BACKEND_DIR / "partcad_build_backend.py"
# The sdist manifest template, beside the backend rather than at the root.
TEMPLATE = REPO_ROOT / "dev-tools" / "MANIFEST.in"

# What the backend looks at, relative to the project root a build runs in.
PACKAGE = Path("src") / "partcad" / "ai_agents"


def _backend():
    """The backend module, loaded from the path `backend-path` names."""
    spec = importlib.util.spec_from_file_location("partcad_build_backend", BACKEND)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A project root laid out the way the backend expects to find one."""
    (tmp_path / PACKAGE).mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def materialized(project):
    """What a checkout with the symlinks resolved gives setuptools to package."""
    skill = project / PACKAGE / "skills" / "init"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: init\n---\n", encoding="utf-8")
    (project / PACKAGE / "plugin.json").write_text('{"name": "pc", "version": "0.0.0"}\n', encoding="utf-8")


def dropped(project):
    """And what one without them gives it: the symlink targets, as text."""
    (project / PACKAGE / "skills").write_text("../../../ai-agents/common/skills", encoding="utf-8")
    (project / PACKAGE / "plugin.json").write_text(
        "../../../ai-agents/claude/.claude-plugin/plugin.json", encoding="utf-8"
    )


def test_the_backend_is_the_one_pyproject_declares():
    """A backend nothing points at is a file, not a gate."""
    build_system = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["build-system"]

    assert build_system["build-backend"] == "partcad_build_backend"
    # Relative to the project root, and it has to be the directory the module
    # is actually in or the build fails to import it at all.
    assert [str(BACKEND_DIR.relative_to(REPO_ROOT)).replace(os.sep, "/")] == build_system["backend-path"]
    assert BACKEND.is_file()


def test_the_sdist_carries_the_backend():
    """`python -m build` builds the wheel out of the sdist, so it needs it there.

    An sdist without this module cannot be built from at all -- the wheel half
    fails on a `backend-path` that does not exist, and so does
    `pip install partcad-<version>.tar.gz` for anyone installing from the sdist
    on PyPI. A manifest template is the only thing that puts a file from outside
    the packages into an sdist, and this is the only reason there is one.
    """
    manifest = TEMPLATE.read_text(encoding="utf-8")
    relative = str(BACKEND.relative_to(REPO_ROOT)).replace(os.sep, "/")

    assert "include %s" % relative in manifest, "%s does not include %s" % (TEMPLATE.name, relative)


def test_setuptools_is_pointed_at_the_template_where_it_actually_is():
    """The template is not at the top of the repository, and `MANIFEST.in` is a
    name setuptools resolves against the project root.

    `[sdist] template` in a `setup.cfg` does not reach it -- the file list is
    built by `egg_info`'s `manifest_maker`, not by `sdist` -- so the backend sets
    that class attribute instead. It is the one piece of this that reaches into
    setuptools rather than calling it, and it is pinned here so that moving the
    template without moving the pointer is a failing test rather than an sdist
    that quietly lost a file.

    If a future setuptools stops honouring it, the failure is still loud: the
    sdist loses the backend, and the wheel `python -m build` then builds out of
    that sdist stops on the missing `backend-path`.
    """
    _backend()

    assert manifest_maker.template == os.path.join("dev-tools", "MANIFEST.in")
    assert TEMPLATE.is_file()
    assert not (REPO_ROOT / "MANIFEST.in").exists(), "there is a MANIFEST.in at the root after all"


def test_it_passes_a_tree_that_has_the_skills(project):
    materialized(project)

    # Returns None; what matters is that it does not raise.
    assert _backend()._check_the_skills_are_there() is None


def test_it_refuses_a_tree_where_the_symlinks_were_dropped(project):
    """The failure this whole file exists for, and it must name the cure."""
    dropped(project)

    with pytest.raises(SystemExit) as refusal:
        _backend()._check_the_skills_are_there()

    message = str(refusal.value)
    assert "skills is not a directory" in message
    assert "core.symlinks" in message


def test_it_refuses_a_manifest_that_is_a_path_rather_than_a_manifest(project):
    """The half that would otherwise be packaged: a file, and the wrong one.

    `plugin.json` is a file whether or not git resolved it, so existing proves
    nothing about it -- which is why the backend parses it.
    """
    materialized(project)
    (project / PACKAGE / "plugin.json").write_text(
        "../../../ai-agents/claude/.claude-plugin/plugin.json", encoding="utf-8"
    )

    with pytest.raises(SystemExit) as refusal:
        _backend()._check_the_skills_are_there()

    assert "does not parse as JSON" in str(refusal.value)


def test_it_refuses_a_skills_directory_with_no_skills_in_it(project):
    """An empty directory is not what a dropped symlink leaves, but it ships the same."""
    materialized(project)
    (project / PACKAGE / "skills" / "init" / "SKILL.md").unlink()

    with pytest.raises(SystemExit) as refusal:
        _backend()._check_the_skills_are_there()

    assert "holds no <name>/SKILL.md" in str(refusal.value)


def test_it_refuses_a_manifest_that_is_json_but_not_a_manifest(project):
    materialized(project)
    (project / PACKAGE / "plugin.json").write_text("[]", encoding="utf-8")

    with pytest.raises(SystemExit) as refusal:
        _backend()._check_the_skills_are_there()

    assert "is not a plugin manifest" in str(refusal.value)


def test_the_hooks_that_ship_an_artifact_are_the_guarded_ones():
    """`build_editable` is deliberately not one of them.

    An editable install reads the working tree as it is, so nothing is frozen
    into an artifact that outlives the checkout -- and refusing there would fail
    `poetry install`, the whole development environment, over a data file.
    """
    backend = _backend()

    for hook in ("build_wheel", "build_sdist"):
        assert getattr(backend, hook).__module__ == "partcad_build_backend", "%s is not guarded" % hook

    # Present, so a frontend can call it, and setuptools' own.
    assert backend.build_editable.__module__ == "setuptools.build_meta"


def test_this_repository_would_build(project):
    """The check, against the tree it is actually shipped in.

    Skipped where git did not materialize the symlinks, which is the one case it
    is supposed to fail: that is a property of the checkout, and a contributor
    on Windows without `core.symlinks` should not read it as a broken test.
    """
    skills = REPO_ROOT / PACKAGE / "skills"
    if not skills.is_dir():
        pytest.skip("the checkout did not materialize symlinks")

    os.chdir(REPO_ROOT)
    assert _backend()._check_the_skills_are_there() is None
    assert json.loads((REPO_ROOT / PACKAGE / "plugin.json").read_text(encoding="utf-8"))["name"] == "pc"
