#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""No test starts before every container it might run in has been published.

`tests/partcad/unit/test_part.py::test_part_example_kicad` starts
`ghcr.io/partcad/partcad-container-kicad:<release>` -- the release PartCAD
itself reports, see `part_factory_kicad.get_runtime`. Nothing in that test, or
in the workflow that runs it, says where the image comes from: it is published
by a CI job, and a commit that bumps the version is the first and only commit
for which that tag has never existed.

So the two workflows that run that test have to *wait* for the job that
publishes it, and neither can wait on a job in the other file -- `needs:` does
not reach across a workflow. What makes that possible is that the build lives in
a reusable workflow both of them call. Lose the call from either one and the
failure is not a missing job: it is `APIError: ... ("manifest unknown")` from a
test whose whole purpose is to fail when the KiCad path is broken, hours into a
run, on the version bump and nowhere else.

The rule the later half of this file pins is the general form of that: a test
job waits for every container it might run in, and a container's build is gated
no more narrowly than the jobs waiting for it. The second half is not a detail.
A job whose dependency is skipped is skipped rather than delayed, so a builder
gated on less than its dependents does not make them wait -- it deletes them,
and a suite that stops running is the one kind of CI failure nothing reports.
"""

import pathlib

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
REUSABLE = "./.github/workflows/container-kicad.yml"

# The workflow, and the job in it that runs the unit tests.
CALLERS = {
    "test.yml": "test-pytest",
    "test-dev.yml": "pytest",
}


def _jobs(workflow):
    """The `jobs:` mapping of one workflow file, parsed."""
    return yaml.safe_load((WORKFLOWS / workflow).read_text())["jobs"]


def _needs(job):
    """A job's dependencies, whichever of the two spellings it uses.

    `needs:` takes a bare string as readily as a list, and a workflow here uses
    both, so a membership test against the raw value would pass on a substring.
    """
    needs = job.get("needs") or []
    return [needs] if isinstance(needs, str) else needs


def test_the_image_is_built_by_one_reusable_workflow():
    """One build step, and it is the KiCad devcontainer definition it builds."""
    jobs = _jobs("container-kicad.yml")
    assert len(jobs) == 1
    (job,) = jobs.values()

    step = [s for s in job["steps"] if s.get("uses", "").startswith("devcontainers/ci")]
    assert len(step) == 1
    assert step[0]["with"]["configFile"] == "tools/containers/devcontainer-kicad.json"


def test_the_tag_it_publishes_is_the_tag_the_runtime_pulls():
    """Whatever the caller decided, and the same thing the caller's tests read.

    Both readers build the tag the same way -- `part_factory_kicad.get_runtime`
    and `partcad_client.external.KICAD` each write
    `...-container-kicad:` + `container_image.image_tag(__version__)` -- so a
    tag carrying anything else is a tag nobody pulls. This step used to take
    `setup-devcontainer`'s IMAGE_TAG, which is `<release>-<branch>` on every
    commit that is not a version bump: published where nothing looks, and
    agreeing with the readers on the one commit whose tests need a new image
    only by accident. The branch tag is back, but as one end of a wire rather
    than a coincidence -- the caller hands it here *and* exports it as
    `PC_CONTAINER_IMAGE_TAG`, which is what `image_tag` reads.

    The cache is the exception, and deliberately so: it comes from the release's
    image, because on the run that matters most -- the first build of a branch
    tag -- the tag itself does not exist yet.
    """
    (job,) = _jobs("container-kicad.yml").values()
    (step,) = [s for s in job["steps"] if s.get("uses", "").startswith("devcontainers/ci")]

    assert step["with"]["imageTag"] == "${{ inputs.tag }}"
    assert step["with"]["cacheFrom"].endswith(":${{ inputs.release }}")

    # That the readers agree is pinned where the agreement lives, in
    # tests/partcad_utils/test_container_image.py: both of them resolve the tag
    # through `container_image.image_tag`, which is the release unless CI has
    # redirected them at the images built out of this commit.
    for source in ("src/partcad/part_factory_kicad.py", "src/partcad_client/external.py"):
        text = (REPO_ROOT / source).read_text()
        assert "partcad-container-kicad:" in text, source
        assert "image_tag(" in text, source


def test_whether_it_publishes_is_the_callers_answer_and_not_a_second_one():
    """The rule "Build the Python sandbox images" states at length in test.yml.

    Build always, because the build is the test; publish where publishing is
    this run's to do. Which runs those are is one question with one answer --
    `.github/actions/container-images`, whose conditions
    `tests/dev_tools/test_container_images.py` pins -- and this workflow is told
    it rather than working it out again. It has to be: the caller exports the
    same tag to its test jobs, and a second copy of the condition here is a
    second chance to build one tag and look for another.
    """
    (job,) = _jobs("container-kicad.yml").values()
    (step,) = [s for s in job["steps"] if s.get("uses", "").startswith("devcontainers/ci")]
    push = " ".join(step["with"]["push"].split())

    assert push == "${{ inputs.push && 'always' || 'never' }}"


def test_the_build_is_in_no_concurrency_group_at_all():
    """Because a group is a thing a build can be displaced *out* of.

    There was one, to build the image once per commit rather than once per
    caller, and that is a trade this cannot make: GitHub queues a group by
    running one job and leaving the next pending, and a *third* arrival cancels
    the pending one. `cancel-in-progress: false` does not prevent that; it only
    protects the one that is running. Two callers plus a re-run of either is
    enough, and so is a manual dispatch beside a push -- and the cancelled call
    takes `Run: pytest`, `Run: behave` and `Run: pc` with it, a job whose
    dependency is cancelled being skipped.

    A suite that stops running is the one kind of CI failure nothing reports,
    which is the rule the gating test below is written around too. Keying the
    group per caller narrows it; keying it per invocation leaves a group of
    one, which is a block that does nothing. So there is none, every call
    builds, and two calls for one commit build the same image from the same
    tag, Dockerfile and cache.
    """
    (job,) = _jobs("container-kicad.yml").values()
    assert "concurrency" not in job


def test_nothing_else_is_built_alongside_it():
    """`devcontainers/ci` pushes in its *post-job* step, so the tag appears when
    the job ends rather than when the build finishes. A second image built in
    this job would hold the push back by however long that image takes -- which
    is how a build that finished at 22:37 came to publish at 23:03.
    """
    (job,) = _jobs("container-kicad.yml").values()
    builds = [s for s in job["steps"] if "docker build" in s.get("run", "") or "buildx build" in s.get("run", "")]
    assert builds == []


@pytest.mark.parametrize("workflow", sorted(CALLERS))
def test_both_test_workflows_call_it(workflow):
    """Once each. A caller that loses the call loses the wait with it."""
    calls = [name for name, job in _jobs(workflow).items() if job.get("uses") == REUSABLE]
    assert calls == ["container-kicad"], workflow


@pytest.mark.parametrize("workflow", sorted(CALLERS))
def test_the_job_running_the_unit_tests_waits_for_it(workflow):
    """`test_part_example_kicad` lives in both, and starts the container."""
    job = _jobs(workflow)[CALLERS[workflow]]
    assert "container-kicad" in _needs(job), workflow


@pytest.mark.parametrize("workflow", sorted(CALLERS))
def test_the_caller_grants_the_permission_to_publish(workflow):
    """A called workflow gets the calling job's permissions and no more.

    Declared in the called workflow too, but that can only narrow: without the
    grant here the publish fails on the one run that has to make it.
    """
    job = _jobs(workflow)["container-kicad"]
    assert job["permissions"]["packages"] == "write"


# Every job that runs a test and can reach a container. On Linux that is all of
# them: the "docker" Python sandbox is the default wherever a container runtime
# answers, and "Sandbox (docker)" is left out only because it builds the image
# it runs in rather than consuming a published one.
CONSUMERS = {
    "test.yml": ["test-pytest", "test-behave", "test-examples-partcad", "test-examples-all", "test-pub-repo"],
    "test-dev.yml": ["pytest", "behave", "integration-tests"],
}

BUILDERS = {"test.yml": ["build-containers", "container-kicad"], "test-dev.yml": ["container-kicad"]}

# The scopes a job can be gated on. "deep" is not one of them: it only ever
# narrows a gate further, and a builder is not obliged to cover it.
SCOPES = ("pytest", "behave", "examples")


def _scopes_named(job):
    """The `changed-scopes` outputs a job's `if:` is gated on.

    Read out of the condition text rather than evaluated: what matters is which
    scopes a gate mentions at all, since that is what decides whether a builder
    can be skipped on a run where something waiting for it is not.
    """
    condition = str(job.get("if") or "")
    return {scope for scope in SCOPES if "outputs.%s ==" % scope in condition}


@pytest.mark.parametrize("workflow", sorted(CONSUMERS))
def test_every_test_job_waits_for_every_container(workflow):
    """The rule, job by job: no test starts before every image exists."""
    jobs = _jobs(workflow)
    for consumer in CONSUMERS[workflow]:
        missing = [b for b in BUILDERS[workflow] if b not in _needs(jobs[consumer])]
        assert missing == [], "%s: %s does not wait for %s" % (workflow, consumer, missing)


def test_the_builders_are_gated_no_narrower_than_what_waits_for_them():
    """A job whose dependency is skipped is skipped, not delayed.

    So a builder gated on less than its dependents does not make them wait --
    it deletes them. "Behave" is gated on the `behave` scope and "Examples" on
    `examples`, while both builders carried the `pytest` gate they were written
    with; the three come out of the same buckets today, which is exactly what
    would have made the day they stop agreeing hard to see.
    """
    jobs = _jobs("test.yml")
    wanted = set()
    for consumer in CONSUMERS["test.yml"]:
        wanted |= _scopes_named(jobs[consumer])
    assert wanted == set(SCOPES)  # or this test is checking less than it reads

    for builder in BUILDERS["test.yml"]:
        assert _scopes_named(jobs[builder]) >= wanted, builder


def test_the_dev_container_build_follows_the_scope_that_runs_its_dependents():
    """`devcontainer`, not `devcontainer-pytest`.

    A change under ".devcontainer" runs "Run: behave" and "Run: pc" and not
    "Run: pytest" -- so the narrower gate would skip this build, and with it
    the two jobs that such a change is the whole reason to run.
    """
    jobs = _jobs("test-dev.yml")
    condition = jobs["container-kicad"]["if"]
    assert "outputs.devcontainer ==" in condition
    assert "outputs.pytest ==" not in condition
    # ...and it carries the gate the chain those jobs hang off already carries,
    # widened and never narrowed. The one disjunct beyond it is the run that
    # built images of its own, which no scope implies -- see the note there.
    assert jobs["devcontainer"]["if"].strip("${} ") in " ".join(condition.split())
