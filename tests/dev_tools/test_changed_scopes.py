#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The CI gate that decides which jobs a change runs.

`.github/actions/changed-scopes` sorts the files a pull request touches into
buckets and turns each CI subject on or off from them, and a pull request or a
merge queue run then *skips* whatever it turned off. So a mistake in it does not
show up as a failure: it shows up as a job that quietly did not run, on the one
change it should have run for.

The property that makes that safe is one line of the action -- a path it has not
been taught falls through to "code", and "code" turns everything on -- so a
mistake can only ever run too much. These check that property directly, against
every top-level entry this repository actually has and against a directory it
does not, and then check the handful of mappings the gate exists for.

The script is extracted from the action and run as-is rather than reimplemented
here. A copy of the rules would be a second thing to keep in step, and it would
agree with itself while disagreeing with CI.
"""

import os
import pathlib
import subprocess

import pytest
import yaml

# POSIX only, and not because the tests are lazy about paths: every job that
# runs this action is `runs-on: ubuntu-latest`, so a Linux shell is the only one
# it will ever be interpreted by. Windows has no `bash` that would tell us
# anything about that -- `bash.exe` on a GitHub Windows runner is the WSL
# launcher, which answers a script with "use 'wsl --install -d <Distro>' to
# install" and exits non-zero (which is how these tests took the whole Windows
# `Pytest` session down with them under `-x`, on the run that introduced them).
# Git Bash would run them, and would be testing a shell CI never uses.
pytestmark = pytest.mark.skipif(os.name == "nt", reason="the action is bash, and it only ever runs on Linux runners")

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
ACTION = REPO_ROOT / ".github" / "actions" / "changed-scopes" / "action.yml"

# Every subject the action emits. Kept here as well so that adding an output
# without deciding what turns it on is a failure rather than a silent "false".
SUBJECTS = {
    "wheel",
    "docs",
    "pytest",
    "behave",
    "examples",
    "devcontainer",
    "devcontainer-pytest",
    "bundle",
    "ide",
    "vsix",
    "plugin",
}


def step_script(step_id):
    """One step of the composite action, as a shell script."""
    action = yaml.safe_load(ACTION.read_text())
    steps = [s for s in action["runs"]["steps"] if s.get("id") == step_id]
    assert len(steps) == 1, f"the action no longer has exactly one '{step_id}' step"
    return steps[0]["run"]


def classify_script():
    """The 'classify' step of the composite action, as a shell script."""
    return step_script("classify")


def classify(tmp_path, paths, all_=False):
    """Run the gate over `paths` and return {subject: bool} plus the buckets."""
    listing = tmp_path / "changed-files.txt"
    listing.write_text("".join(f"{p}\n" for p in paths))
    output = tmp_path / "output"
    output.touch()
    summary = tmp_path / "summary"
    summary.touch()

    result = subprocess.run(
        ["bash", "-c", classify_script()],
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "ALL": "true" if all_ else "false",
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_OUTPUT": str(output),
            "GITHUB_STEP_SUMMARY": str(summary),
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    values = {}
    for line in output.read_text().splitlines():
        key, _, value = line.partition("=")
        values[key] = value
    buckets = set(values.pop("buckets").split())
    assert set(values) == SUBJECTS, "the action's outputs and SUBJECTS have drifted apart"
    return {k: v == "true" for k, v in values.items()}, buckets


def test_a_deep_run_turns_everything_on(tmp_path):
    """A deep run is what "#deepTest", the nightly schedule and every push get."""
    subjects, _ = classify(tmp_path, [], all_=True)
    assert all(subjects.values()), subjects


def test_an_unknown_path_runs_everything(tmp_path):
    """The fail-safe, and the reason it lands in two buckets rather than one.

    "code" alone would leave the standalone bundles unbuilt for a path nobody
    has classified -- and an unclassified path is precisely the one nobody has
    thought about. A file has to be *named* as source before it stops being
    treated as something that can change what gets frozen.
    """
    subjects, buckets = classify(tmp_path, ["a-brand-new-directory/whatever.py"])
    assert buckets == {"code", "deps"}
    # Not "all of them": the IDE is not rebuilt by a source change, here or in
    # "build-ide-standalone.yml", because it downloads the bundles rather than
    # freezing them. Everything else is on.
    assert subjects["pytest"] and subjects["behave"] and subjects["wheel"] and subjects["bundle"]


def test_source_alone_does_not_freeze_a_bundle(tmp_path):
    """The one place a source change and a dependency change part company.

    Freezing is the most expensive thing in CI, and what makes a bundle differ
    from a working wheel is almost always what went into it. So a change to
    "src/" runs the tests and builds the wheel but does not freeze; the push to
    "devel" that follows the merge still does, its "paths:" filter still lists
    "src/**", and "#deepTest" still freezes everything before a merge.
    """
    subjects, buckets = classify(tmp_path, ["src/partcad/context.py"])
    assert buckets == {"code"}
    assert subjects["pytest"] and subjects["behave"] and subjects["wheel"]
    assert not subjects["bundle"]


@pytest.mark.parametrize(
    "path",
    ["pyproject.toml", "poetry.lock", "requirements.txt", "requirements-aws.txt", "requirements-dev.in"],
)
def test_a_dependency_change_freezes_a_bundle(tmp_path, path):
    subjects, buckets = classify(tmp_path, [path])
    assert buckets == {"deps"}
    assert subjects["bundle"]
    # And everything a source change runs, since the dependency is under it.
    assert subjects["pytest"] and subjects["behave"] and subjects["wheel"]


@pytest.mark.parametrize(
    "path",
    ["docs/requirements.txt", ".devcontainer/requirements.txt", "ide/vscode/requirements.txt"],
)
def test_only_the_root_dependency_files_are_dependencies(tmp_path, path):
    """A "requirements.txt" belongs to whatever directory it is in.

    The patterns for these are anchored at the start of the path -- "*" matches
    "/" in a case pattern -- and each of these directories has a rule of its own
    above them. Sphinx's requirements are not PartCAD's.
    """
    subjects, _ = classify(tmp_path, [path])
    assert not subjects["bundle"]


@pytest.mark.parametrize(
    "path, expected_bucket",
    [
        # Prose, and the scaffolding that only an agent working here reads.
        ("docs/source/contributing.rst", "docs"),
        ("README.md", "docs"),
        ("src/partcad/AGENTS.md", "docs"),
        ("ide/vscode/AGENTS.md", "vscode"),
        (".claude/skills/steward/SKILL.md", "docs"),
        ("openspec/whatever.md", "docs"),
        # The Claude Code plugin, which is Markdown that ships.
        ("ai-agents/common/skills/render/SKILL.md", "ai"),
        (".claude-plugin/marketplace.json", "ai"),
        # The dev container.
        (".devcontainer/devcontainer.json", "devcontainer"),
        # The editor.
        ("ide/vscode/src/extension.ts", "vscode"),
        ("ide/vscode-shim/package.json", "vscode"),
        ("ide/standalone/build.sh", "ide"),
        (".vscode/extensions.json", "ide"),
        # Freezing and installing.
        ("dev-tools/pyinstaller/build.sh", "packaging"),
        (".snapcraft.yaml", "packaging"),
        ("install.sh", "packaging"),
        # Code, in all the shapes it comes in.
        ("src/partcad/context.py", "code"),
        ("tests/partcad/unit/test_part.py", "code"),
        ("features/pc_list.feature", "code"),
        ("conftest.py", "code"),
        ("behave.ini", "code"),
        ("pyproject.toml", "deps"),
        ("poetry.lock", "deps"),
        ("requirements.txt", "deps"),
        ("cad/freecad/InitGui.py", "code"),
        # A rendered README under "examples/" is an *output* that
        # "Examples (PartCAD)" compares against a fresh render, so it must not
        # be mistaken for documentation.
        ("examples/feature_render/README.md", "code"),
        ("examples/feature_render/images/cube.png", "code"),
        # ... including one that would otherwise be caught by the rule above it.
        ("examples/produce_part_step/AGENTS.md", "code"),
        # CI itself runs everything, this being what decides what runs.
        (".github/workflows/test.yml", "ci"),
    ],
)
def test_paths_land_in_the_bucket_they_belong_to(tmp_path, path, expected_bucket):
    _, buckets = classify(tmp_path, [path])
    assert buckets == {expected_bucket}


def test_documentation_alone_runs_only_the_documentation(tmp_path):
    subjects, _ = classify(tmp_path, ["docs/source/index.rst", "README.md"])
    assert subjects["docs"]
    assert not any(v for k, v in subjects.items() if k != "docs"), subjects


def test_the_plugin_alone_runs_only_the_plugin(tmp_path):
    subjects, _ = classify(tmp_path, ["ai-agents/common/skills/render/SKILL.md"])
    assert subjects["plugin"]
    assert not any(v for k, v in subjects.items() if k != "plugin"), subjects


def test_the_dev_container_alone_runs_it_but_not_pytest_inside_it(tmp_path):
    """The one mapping that is a judgement rather than a mechanism.

    "Run: pytest" in "test-dev.yml" is the "Pytest" matrix over again on one
    image and one interpreter; the container's own configuration cannot make the
    unit tests disagree with what that matrix said. What it can break is whether
    anything works in the container at all, which is what "Run: behave" and
    "Run: pc" -- gated on `devcontainer` -- are there to ask.
    """
    subjects, _ = classify(tmp_path, [".devcontainer/devcontainer.json"])
    assert subjects["devcontainer"]
    assert not subjects["devcontainer-pytest"]
    # And nothing outside the container, which is what the rest of CI runs in.
    assert not subjects["pytest"]
    assert not subjects["behave"]
    assert not subjects["wheel"]


def test_ci_configuration_runs_everything(tmp_path):
    subjects, _ = classify(tmp_path, [".github/actions/changed-scopes/action.yml"])
    assert all(subjects.values()), subjects


def test_one_unrecognised_file_is_enough(tmp_path):
    """Buckets are a union, not a verdict on the change as a whole."""
    subjects, buckets = classify(tmp_path, ["README.md", "src/partcad/context.py"])
    assert buckets == {"docs", "code"}
    assert subjects["docs"] and subjects["pytest"]


def test_every_top_level_entry_is_classified_deliberately(tmp_path):
    """No entry of this repository may fall into an inert bucket by accident.

    The gate's rules are matched in order, and the ones that match by extension
    come last precisely so that a directory's own rule wins first. This walks
    what the repository actually has, so a new top-level directory whose name
    happens to end in ".md" -- or a rule reordered above the directory rules --
    is caught here rather than by a job that silently stopped running.
    """
    tracked = subprocess.run(
        ["git", "ls-tree", "--name-only", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()

    # What each top-level entry is allowed to be. Anything absent from here is a
    # new entry, and the assertion below says to come and decide about it. The
    # two entries that are "code" *and* "deps" are the ones nothing classifies:
    # they reach the catch-all, which is the fail-safe.
    expected = {
        ".devcontainer": {"devcontainer"},
        ".github": {"ci"},
        ".claude": {"docs"},
        ".claude-plugin": {"ai"},
        ".cursor": {"docs"},
        ".gitattributes": {"code", "deps"},
        ".gitignore": {"code", "deps"},
        ".readthedocs.yaml": {"docs"},
        ".snapcraft.yaml": {"packaging"},
        ".vscode": {"ide"},
        "AGENTS.md": {"docs"},
        "CLAUDE.md": {"docs"},
        "LICENSE.txt": {"docs"},
        "README.md": {"docs"},
        "ai-agents": {"ai"},
        "apache20.svg": {"docs"},
        "behave.ini": {"code"},
        "cad": {"code"},
        "conftest.py": {"code"},
        "dev-tools": {"code"},
        "docs": {"docs"},
        "examples": {"code"},
        "features": {"code"},
        "ide": None,  # split between "vscode" and "ide"; covered above
        "install.sh": {"packaging"},
        "openspec": {"docs"},
        "poetry.lock": {"deps"},
        "poetry.toml": {"deps"},
        "pyproject.toml": {"deps"},
        "requirements-aws.txt": {"deps"},
        "requirements-dev.in": {"deps"},
        "requirements-lint.txt": {"deps"},
        "requirements.txt": {"deps"},
        "src": {"code"},
        "tests": {"code"},
        "tools": {"code"},
    }

    unknown = sorted(set(tracked) - set(expected))
    assert not unknown, (
        f"new top-level entries {unknown}: decide which CI subjects they belong to, "
        f"add a rule to .github/actions/changed-scopes if they are inert, and list them here. "
        f"Until then they classify as 'code' and run everything, which is the safe direction."
    )

    for entry in tracked:
        want = expected[entry]
        if want is None:
            continue
        path = entry if "." in entry.rsplit("/", 1)[-1] and not entry.startswith(".") else f"{entry}/file.txt"
        if entry.startswith(".") and (REPO_ROOT / entry).is_file():
            path = entry
        _, buckets = classify(tmp_path, [path])
        assert buckets == want, f"{path} classified as {buckets}, expected {want}"


# --- The "files" step: which files the change touched, and whether we saw them all ---
#
# The gate is only as good as this list. If it comes back short and the step does
# not notice, the buckets are computed from a subset of the change and the jobs
# for everything missing are skipped -- silently, because a skipped job looks
# exactly like a job that had nothing to do.
#
# Both endpoints cap what they return, and they differ in what they tell you
# about it, which is why each needs its own check and its own test:
#
#   * "pulls/{n}/files" pages up to 3000 entries, and the pull request itself
#     carries "changed_files", the real total. Two numbers, so a comparison
#     works.
#   * "compare/{base}...{head}" caps ".files" at 300 and reports no total at
#     all. There is no second number, so a full 300 has to be *assumed*
#     truncated. The check here was a comparison against ".files | length" --
#     the length of the capped array itself, which equals the number of lines
#     written whether or not anything was dropped, so it could never fire. Found
#     by CodeRabbit on #608; these are what would have caught it.


def gh_stub(directory, file_count, declared=None, fail=False):
    """A stand-in for the "gh" CLI that serves a fixed number of filenames."""
    stub = directory / "gh"
    stub.write_text(
        "#!/bin/bash\n"
        f"if [ '{fail}' = 'True' ]; then exit 1; fi\n"
        'for arg in "$@"; do\n'
        '  case "$arg" in\n'
        # The pull request itself, asked for its "changed_files" count.
        f"    *'/pulls/'*'/files') seq 1 {file_count} | sed 's|^|src/f|;s|$|.py|'; exit 0 ;;\n"
        f"    *'/pulls/'*) echo '{declared if declared is not None else file_count}'; exit 0 ;;\n"
        f"    *'/compare/'*) seq 1 {file_count} | sed 's|^|src/f|;s|$|.py|'; exit 0 ;;\n"
        "  esac\n"
        "done\n"
        "exit 1\n"
    )
    stub.chmod(0o755)


def run_files_step(tmp_path, event, file_count, declared=None, deep=False, fail=False):
    """Run the "files" step and return whether it gave up and asked for everything."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh_stub(bin_dir, file_count, declared, fail)
    output = tmp_path / "files-output"
    output.touch()

    result = subprocess.run(
        ["bash", "-c", step_script("files")],
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "GH_TOKEN": "stub",
            "DEEP": "true" if deep else "false",
            "EVENT_NAME": event,
            "REPO": "partcad/partcad",
            "PR_NUMBER": "608",
            "MG_BASE": "0" * 40,
            "MG_HEAD": "1" * 40,
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_OUTPUT": str(output),
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    values = dict(line.partition("=")[::2] for line in output.read_text().splitlines())
    return values["all"] == "true"


def test_a_merge_group_at_the_cap_is_treated_as_truncated(tmp_path):
    """300 is the cap, and the response cannot say whether it was reached or hit."""
    assert run_files_step(tmp_path, "merge_group", file_count=300) is True


def test_a_merge_group_below_the_cap_is_classified(tmp_path):
    assert run_files_step(tmp_path, "merge_group", file_count=299) is False


def test_a_pull_request_shorter_than_its_own_count_is_truncated(tmp_path):
    """Here there *is* a second number, and it is the one that matters."""
    assert run_files_step(tmp_path, "pull_request", file_count=10, declared=40) is True


def test_a_complete_pull_request_listing_is_classified(tmp_path):
    assert run_files_step(tmp_path, "pull_request", file_count=10, declared=10) is False


def test_an_api_failure_runs_everything(tmp_path):
    assert run_files_step(tmp_path, "pull_request", file_count=10, fail=True) is True


def test_an_unknown_event_runs_everything(tmp_path):
    """Only a pull request and a merge queue reach this step; a new trigger must
    not arrive with an empty list and skip the whole workflow."""
    assert run_files_step(tmp_path, "issue_comment", file_count=10) is True


def test_a_deep_run_never_asks(tmp_path):
    """It short-circuits before the API call -- the stub would fail if reached."""
    assert run_files_step(tmp_path, "pull_request", file_count=10, deep=True, fail=True) is True
