#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The tag CI builds PartCAD's own container images under, end to end.

Two facts have to agree, and nothing in a failing run says which of them moved.
A job builds `ghcr.io/partcad/partcad-container-*:<something>`, and a test in
some later job resolves a name through `partcad_utils.container_image.image_tag`
and pulls it. Where those two disagree the symptom is
`APIError: ... ("manifest unknown")`, hours in, or -- far worse -- a green run
that tested the *release's* images while claiming to have tested the ones this
commit changed.

So the tag is decided once, by `.github/actions/container-images`, and threaded:
into `container-kicad.yml` as an input, into the Python sandbox build as an
environment variable, and into every job that runs a test as
`PC_CONTAINER_IMAGE_TAG`, which is what `image_tag` reads. This file runs that
action's script over the three cases it distinguishes, and then checks that each
end of the wire is attached -- because a wire with one end loose is exactly the
green run above.

The library half of the same subject is `tests/partcad_utils/test_container_image.py`.
"""

import os
import pathlib
import subprocess

import pytest
import yaml

# POSIX only, for the reason `test_changed_scopes.py` gives at length: the
# action is bash and only ever runs on a Linux runner, and a Windows `bash.exe`
# is the WSL launcher, which answers a script by telling you to install a
# distribution and exiting non-zero. The mark is on the module rather than on
# the half that shells out, because the other half reads YAML and says the same
# thing on every platform -- one skip line is easier to read than seven marks
# for a file the Linux cells run in full.
pytestmark = pytest.mark.skipif(os.name == "nt", reason="the action is bash, and it only ever runs on Linux runners")

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
ACTION = REPO_ROOT / ".github" / "actions" / "container-images" / "action.yml"
USES = "./.github/actions/container-images"

RELEASE = "0.8.70"


def _action():
    return yaml.safe_load(ACTION.read_text())


def _workflow(name):
    return yaml.safe_load((WORKFLOWS / name).read_text())


def _decide_script():
    (step,) = [s for s in _action()["runs"]["steps"] if s.get("id") == "decide"]
    return step["run"]


def decide(tmp_path, wanted="false", branch="my-branch", release_publish="false", fork="false"):
    """Run the action's one step and return its outputs."""
    output = tmp_path / "output"
    output.touch()
    summary = tmp_path / "summary"
    summary.touch()

    subprocess.run(
        ["bash", "-c", _decide_script()],
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "WANTED": wanted,
            "RELEASE": RELEASE,
            "BRANCH": branch,
            "IS_RELEASE_PUBLISH": release_publish,
            "FROM_A_FORK": fork,
            "GITHUB_OUTPUT": str(output),
            "GITHUB_STEP_SUMMARY": str(summary),
        },
        check=True,
        capture_output=True,
        text=True,
    )
    return dict(line.split("=", 1) for line in output.read_text().splitlines() if line)


def test_an_ordinary_run_builds_the_release_and_publishes_nothing(tmp_path):
    """A pull request that changed no image: the build is the test, and the
    tests run against what an installed PartCAD pulls.
    """
    out = decide(tmp_path)
    assert out == {"tag": RELEASE, "release": RELEASE, "push": "false", "override": ""}


def test_the_version_bump_publishes_the_release_tag(tmp_path):
    """The one run whose whole purpose is to create the tag everyone else pulls.

    It overrides nothing: the tag it publishes *is* the release, so every
    reader already asks for it, and an override would be a second name for one
    image.
    """
    out = decide(tmp_path, release_publish="true")
    assert out == {"tag": RELEASE, "release": RELEASE, "push": "true", "override": ""}


def test_a_run_that_changed_the_images_builds_and_tests_its_own(tmp_path):
    """The point of the whole mechanism.

    A Dockerfile fix is provable in the pull request that makes it, and a
    Dockerfile regression is catchable there, only if the tests in that run
    reach the images that run built. The branch tag is safe to publish from an
    unreviewed branch precisely because nothing but this run asks for it.
    """
    out = decide(tmp_path, wanted="true")
    assert out == {
        "tag": "%s-my-branch" % RELEASE,
        "release": RELEASE,
        "push": "true",
        "override": "%s-my-branch" % RELEASE,
    }


def test_the_bump_wins_over_the_branch_tag(tmp_path):
    """A version bump that also changed `tools/containers` still publishes the
    release. It is on `devel`, it is the run every installed PartCAD is waiting
    on, and a branch tag there would leave that release with no image.
    """
    out = decide(tmp_path, wanted="true", release_publish="true")
    assert out["tag"] == RELEASE
    assert out["override"] == ""


@pytest.mark.parametrize(
    "branch, tag",
    [
        ("claude/ci-images", "%s-claude_ci-images" % RELEASE),
        ("a/b/c", "%s-a_b_c" % RELEASE),
    ],
)
def test_a_slash_in_the_branch_name_is_not_a_slash_in_the_tag(tmp_path, branch, tag):
    """A tag may not hold one, and a branch name routinely does. The same
    substitution `setup-devcontainer` makes.
    """
    assert decide(tmp_path, wanted="true", branch=branch)["tag"] == tag


def test_a_fork_asks_for_nothing_it_cannot_publish(tmp_path):
    """Wanted and impossible: a fork's `GITHUB_TOKEN` is read-only however the
    workflow declares its permissions.

    Degrading to the ordinary case costs the fork the coverage; claiming the tag
    anyway would cost it every job, each failing to pull an image nothing
    pushed. The gap is real, so the action says so in the run rather than
    leaving it to be worked out from a rendering that looks fine.
    """
    out = decide(tmp_path, wanted="true", fork="true")
    assert out == {"tag": RELEASE, "release": RELEASE, "push": "false", "override": ""}


def test_the_fork_test_above_is_testing_the_fork_and_not_the_default(tmp_path):
    """The same call from a branch of this repository does build its own.

    Without this, the test above would go on passing if `WANTED` stopped being
    read at all.
    """
    assert decide(tmp_path, wanted="true", fork="false")["push"] == "true"


def test_only_a_pull_request_can_be_a_fork():
    """`github.event.pull_request` is empty on every other event, and a push to
    this repository's own `devel` is what the release publish is.
    """
    (step,) = [s for s in _action()["runs"]["steps"] if s.get("id") == "decide"]
    condition = " ".join(step["env"]["FROM_A_FORK"].split())

    assert condition == "${{ github.event_name == 'pull_request' && github.event.pull_request.head.repo.fork }}"


def test_the_release_publish_is_the_bump_on_devel_and_a_dispatch():
    """Read off the action rather than re-run, because it is an Actions
    expression and not part of the script.

    `workflow_dispatch` is the recovery path for a publish that failed: it
    publishes whatever tree it is dispatched at, so it has to be dispatched at
    the bump commit and nowhere else.
    """
    (step,) = [s for s in _action()["runs"]["steps"] if s.get("id") == "decide"]
    condition = " ".join(step["env"]["IS_RELEASE_PUBLISH"].split())

    assert "github.ref == 'refs/heads/devel'" in condition
    assert "startsWith(github.event.head_commit.message, 'Version updated')" in condition
    assert "github.event_name == 'workflow_dispatch'" in condition


def test_a_branch_name_never_reaches_the_script_as_text():
    """`zizmor` template injection, the rule `test-depth` follows for the pull
    request title: a branch name is text somebody chose.
    """
    (step,) = [s for s in _action()["runs"]["steps"] if s.get("id") == "decide"]
    assert step["env"]["BRANCH"] == "${{ github.head_ref || github.ref_name }}"
    assert "github.head_ref" not in step["run"]
    assert "github.ref_name" not in step["run"]


# The job in each workflow that asks the question, and the job that calls
# `container-kicad.yml` with the answer.
DECIDERS = {"test.yml": "set-matrix", "test-dev.yml": "scope"}


@pytest.mark.parametrize("workflow", sorted(DECIDERS))
def test_both_workflows_ask_the_one_action(workflow):
    """Both call `container-kicad.yml`, which builds one image per commit and
    cannot be told two different tags to build it under. A copy of the rules in
    either file would be a second answer.
    """
    jobs = _workflow(workflow)["jobs"]
    job = jobs[DECIDERS[workflow]]
    steps = [s for s in job["steps"] if s.get("uses") == USES]
    assert len(steps) == 1, workflow
    assert steps[0]["id"] == "images", workflow

    # ...and it is asked with both halves of the question: the paths, and the
    # pull request's own `#images`.
    wanted = steps[0]["with"]["wanted"]
    assert "steps.scope.outputs.images" in wanted, workflow
    assert "steps.depth.outputs.images" in wanted, workflow

    for output in ("image-tag", "image-push", "image-release", "image-override"):
        assert output in job["outputs"], "%s: %s" % (workflow, output)


@pytest.mark.parametrize("workflow", sorted(DECIDERS))
def test_the_kicad_build_is_told_that_answer(workflow):
    """All three inputs, from the job that decided them and nowhere else."""
    jobs = _workflow(workflow)["jobs"]
    given = jobs["container-kicad"]["with"]
    decider = DECIDERS[workflow]

    assert given["tag"] == "${{ needs.%s.outputs.image-tag }}" % decider, workflow
    assert given["push"] == "${{ needs.%s.outputs.image-push == 'true' }}" % decider, workflow
    assert given["release"] == "${{ needs.%s.outputs.image-release }}" % decider, workflow


def test_the_python_sandbox_images_are_tagged_with_it_and_carry_the_release():
    """The tag goes on the image; the release goes into it.

    They part company on a branch-tag run, and they have to: what such a run is
    testing is this commit's Dockerfile, so the PartCAD installed inside is
    still the release -- only the name the image answers to changes.
    """
    (step,) = [
        s
        for s in _workflow("test.yml")["jobs"]["build-containers"]["steps"]
        if s.get("name", "").startswith("Build the Python sandbox")
    ]

    assert step["env"]["IMAGE_TAG"] == "${{ needs.set-matrix.outputs.image-tag }}"
    assert step["env"]["PC_VERSION"] == "${{ needs.set-matrix.outputs.image-release }}"
    assert step["env"]["PUSH"] == "${{ needs.set-matrix.outputs.image-push }}"

    assert '--tag "${IMAGE}:${IMAGE_TAG}-py${PY}-${ARCH}"' in step["run"]
    assert '--build-arg "PARTCAD_VERSION=${PC_VERSION}"' in step["run"]


def test_a_run_that_builds_its_own_tag_builds_both_architectures():
    """Otherwise the tag is half a tag, and nothing says so.

    A pull request builds amd64 alone, because arm64 goes through QEMU. That is
    a gap in *coverage* on an ordinary run and a gap in the *tag* on this one:
    every Arm job resolves `<release>-<branch>-py<X>-arm64` like every other
    job, finds nothing, and falls back -- `Pytest` to conda, which is the
    sandbox going untested, and the jobs with a `sandbox-image` step to a build
    of their own, which is the same QEMU time paid once per job. The run asked
    for these images.
    """
    (step,) = [
        s
        for s in _workflow("test.yml")["jobs"]["build-containers"]["steps"]
        if s.get("name", "").startswith("Build the Python sandbox")
    ]

    assert step["env"]["OWN_TAG"] == "${{ needs.set-matrix.outputs.image-override != '' }}"
    assert '[ "${DEEP}" = "true" ] || [ "${OWN_TAG}" = "true" ]' in step["run"]


BUILDERS = {"test.yml": ["build-containers", "container-kicad"], "test-dev.yml": ["container-kicad"]}


@pytest.mark.parametrize("workflow", sorted(BUILDERS))
def test_a_run_that_asked_for_images_builds_them_whatever_else_it_skips(workflow):
    """No scope implies "#images".

    A change carrying the marker need not be one that runs any test suite --
    and if the builders were gated on the suites alone, such a run would print
    "Container images: <release>-<branch> (built from this commit)" in its
    summary and build nothing at all. A summary that says what did not happen
    is worse than no summary.
    """
    jobs = _workflow(workflow)["jobs"]
    for builder in BUILDERS[workflow]:
        condition = " ".join(str(jobs[builder].get("if") or "").split())
        assert "outputs.image-override != ''" in condition, "%s: %s" % (workflow, builder)


# Every job that runs a test and can reach one of these images -- the same list
# `test_container_ordering.py` makes wait for the builds. A job that waits for
# an image and then asks for a different one has gained nothing by waiting.
CONSUMERS = {
    "test.yml": ["test-pytest", "test-behave", "test-examples-partcad", "test-examples-all", "test-pub-repo"],
    "test-dev.yml": ["pytest", "behave", "integration-tests"],
}


@pytest.mark.parametrize("job", CONSUMERS["test.yml"])
def test_every_test_job_is_pointed_at_the_images_this_run_built(job):
    """`PC_CONTAINER_IMAGE_TAG`, from the job that decided it.

    Empty on a run that built no images of its own, which `image_tag` reads as
    "the release" -- so this line changes nothing except where it matters.
    """
    jobs = _workflow("test.yml")["jobs"]
    assert jobs[job]["env"]["PC_CONTAINER_IMAGE_TAG"] == "${{ needs.set-matrix.outputs.image-override }}"
    # Job-level `env` may read `needs`, but only of a job this one declares.
    assert "set-matrix" in jobs[job]["needs"], job


@pytest.mark.parametrize("job", CONSUMERS["test-dev.yml"])
def test_the_dev_container_jobs_forward_it_inside(job):
    """`devcontainers/ci` forwards nothing by default, and the tests run in
    there rather than on the runner. A variable set on the job alone would be a
    variable PartCAD never sees.

    The `Run: ...` step is the one that runs a test; the Allure step beside it
    in `pytest` renders a report and reaches no image.
    """
    jobs = _workflow("test-dev.yml")["jobs"]
    assert "scope" in jobs[job]["needs"], job

    steps = [
        s
        for s in jobs[job]["steps"]
        if s.get("uses", "").startswith("devcontainers/ci") and s.get("name", "").startswith("Run ")
    ]
    assert steps, job
    for step in steps:
        assert "PC_CONTAINER_IMAGE_TAG=${{ needs.scope.outputs.image-override }}" in step["with"]["env"], (
            job,
            step["name"],
        )


def test_the_sandbox_action_reads_the_same_variable_and_pulls_what_was_published():
    """`.github/actions/sandbox-image` makes the base image available under the
    name PartCAD resolves, so it has to resolve it the same way.

    Out of the ambient environment rather than an input, because that is where
    `partcad_utils.container_image` reads it -- one export, and the action and
    the PartCAD running beside it cannot disagree. And where it is set, the
    image was published by this run a few jobs ago: building a second copy
    would leave the published one untested, which is the failure this action
    exists to end, with the branches swapped.
    """
    action = (REPO_ROOT / ".github" / "actions" / "sandbox-image" / "action.yml").read_text()

    assert 'tag_prefix="${PC_CONTAINER_IMAGE_TAG:-${release}}"' in action
    assert 'tag="${image}:${tag_prefix}-py${PYTHON_VERSION}-${arch}"' in action
    # The release still goes *into* the image it may have to build.
    assert '--build-arg "PARTCAD_VERSION=${release}"' in action
    assert "PREFER_PUBLISHED=true" in action
