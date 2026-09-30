#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The one commit on "devel" that CI builds, and the gate that says so.

Every push to `devel` is followed within minutes by the version bump
`version-bump.yml` makes of it, so a workflow that fans out over a matrix on
both builds the same tree twice -- and the first of the two produces artifacts
stamped with the version that merge had just replaced. `test.yml`, `build.yml`
and `test-dev.yml` have always declined the merge and waited for the bump;
`build-standalone.yml` and `build-ide-standalone.yml` did not, which is how
`devel` came to hold two sets of standalone bundles per merge, the earlier one
carrying the older version.

Nothing fails when that gate is dropped or written the wrong way round. Too
loose and CI merely does the work twice, which looks like CI being slow; too
tight -- the `head_commit` test put before the event name, say -- and the merge
queue, every manual dispatch and every release path go quiet, which looks like
nothing at all. `test.yml`'s nightly run was skipped every night for exactly
that reason, from the day its guard was written until 0.8.32.

So these pin the shape of the condition, and that the whole workflow really
hangs off it: one job with no `needs`, carrying the gate, that every other job
reaches.
"""

import pathlib

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

# Every workflow that fans out over a matrix on a push to "devel". The four
# cheap ones -- the extension's "npm test", the ".vsix" and the plugin builds,
# the version bump itself -- are not here: they run one job on one image, and
# two of them have no push trigger at all.
GATED = [
    "test.yml",
    "build.yml",
    "test-dev.yml",
    "build-standalone.yml",
    "build-ide-standalone.yml",
]


def workflow(name):
    """One workflow file, parsed.

    `on:` comes back as the boolean `True`: YAML 1.1 reads the bare word as one,
    and every parser this repository has does the same thing to it.
    """
    loaded = yaml.safe_load((WORKFLOWS / name).read_text())
    loaded["on"] = loaded.pop(True, loaded.get("on"))
    return loaded


def gate_job(parsed):
    """The job everything else in the workflow hangs off: the one with no `needs`."""
    roots = [name for name, job in parsed["jobs"].items() if not job.get("needs")]
    assert len(roots) == 1, f"expected exactly one job with no 'needs', found {roots}"
    return roots[0], parsed["jobs"][roots[0]]


def gate_condition(parsed):
    """That job's `if`, whitespace collapsed -- these are written as folded scalars."""
    name, job = gate_job(parsed)
    assert "if" in job, f"the '{name}' job carries no condition at all"
    return " ".join(str(job["if"]).split())


@pytest.mark.parametrize("name", GATED)
def test_the_matrix_is_gated_on_the_version_bump(name):
    """A push to "devel" builds the bump and nothing else.

    The bump carries the merge's own tree, so this is not coverage given up: it
    is the same build, once, from the commit a release is cut from and under the
    version it will be published as.
    """
    condition = gate_condition(workflow(name))

    assert "refs/heads/devel" in condition
    assert "startsWith(github.event.head_commit.message, 'Version updated')" in condition


@pytest.mark.parametrize("name", GATED)
def test_the_event_name_leads_the_message_test(name):
    """Only a push carries `head_commit`.

    On every other trigger it is null, `startsWith` reads that as the empty
    string, and a condition that asks the message first is false for the merge
    queue, for a manual dispatch and for the nightly run -- silently, since a
    skipped job reports "skipped" and that counts as passing.
    """
    condition = gate_condition(workflow(name))

    assert "github.event_name != 'push'" in condition
    assert condition.index("github.event_name != 'push'") < condition.index("startsWith(")


@pytest.mark.parametrize("name", GATED)
def test_a_called_workflow_is_let_through_first(name):
    """A caller has already decided; the commit message is not its to read.

    "deploy.yml" calls "build-standalone.yml" and "build-ide-standalone.yml" to
    build what a release carries. Inside a called workflow the whole `github`
    context is the *caller's* -- `github.event_name` reads "push" on the release
    path, never "workflow_call" -- so the `inputs` context, which exists only
    under `workflow_call` and `workflow_dispatch`, is the only thing that can
    recognise one.
    """
    parsed = workflow(name)
    if "workflow_call" not in parsed["on"]:
        pytest.skip("nothing calls this workflow")

    condition = gate_condition(parsed)

    assert condition.startswith("${{ toJSON(inputs."), condition
    assert "!= 'null'" in condition.split("||")[0]


@pytest.mark.parametrize("name", GATED)
def test_nothing_runs_without_passing_the_gate(name):
    """Which is what lets the gate be stated in one place.

    A job that does not reach the gating job through `needs` runs on a merge as
    happily as on a bump, so the guard above would be describing a workflow it
    does not govern.
    """
    parsed = workflow(name)
    gate, _ = gate_job(parsed)

    def reaches(job_name, seen):
        needs = parsed["jobs"][job_name].get("needs") or []
        needs = [needs] if isinstance(needs, str) else needs
        return any(n == gate or (n not in seen and reaches(n, seen | {n})) for n in needs)

    orphans = [n for n in parsed["jobs"] if n != gate and not reaches(n, {n})]
    assert not orphans, f"these jobs do not depend on '{gate}': {orphans}"


@pytest.mark.parametrize("name", GATED)
def test_no_paths_filter_stands_in_front_of_the_gate(name):
    """A second filter on the trigger could only ever hide the first one.

    A bump touches "pyproject.toml", "src/**" and "ide/vscode/package.json"
    today, so the lists these triggers used to carry passed it. The day
    "dev-tools/bumpversion.toml" stops naming a file on one of them, that
    workflow stops running on "devel" entirely and says nothing about it -- the
    failure being a missing run rather than a failing one.
    """
    push = workflow(name)["on"]["push"]

    assert "devel" in push["branches"]
    assert "paths" not in push
    assert "paths-ignore" not in push
