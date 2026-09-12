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
import re
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
SHA = "abc1234def5678"
SHORT = SHA[:7]


def _action():
    return yaml.safe_load(ACTION.read_text())


def _workflow(name):
    return yaml.safe_load((WORKFLOWS / name).read_text())


def _decide_script():
    (step,) = [s for s in _action()["runs"]["steps"] if s.get("id") == "decide"]
    return step["run"]


def decide(tmp_path, wanted="false", branch="my-branch", release_publish="false", fork="false", sha=SHA):
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
            "SHA": sha,
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

    assert out["release"] == RELEASE
    assert out["push"] == "true"
    # The tag and the override are one value: the thing built is the thing the
    # tests in this run resolve. Its shape is pinned separately below; here
    # what matters is that a run which built its own images says so twice and
    # says the same thing both times.
    assert out["tag"] == out["override"]
    assert out["tag"].startswith("%s-my-branch-" % RELEASE)
    assert out["tag"].endswith("-%s" % SHORT)


def test_the_bump_wins_over_the_branch_tag(tmp_path):
    """A version bump that also changed `tools/containers` still publishes the
    release. It is on `devel`, it is the run every installed PartCAD is waiting
    on, and a branch tag there would leave that release with no image.
    """
    out = decide(tmp_path, wanted="true", release_publish="true")
    assert out["tag"] == RELEASE
    assert out["override"] == ""


def test_every_stem_carries_a_digest_of_the_whole_branch(tmp_path):
    """ "Every" is the load-bearing word, and it was learnt the hard way.

    The digest was added only where sanitising had changed the name, on the
    reasoning that a name a registry already accepts maps to itself and so
    cannot land on anybody else's stem. It can: `feat_x-79b4cc` is a name a
    branch may have, and it is also what `feat/x` produces. One shape, two
    ways to reach it.

    Unconditional, the stem is a function of the whole branch name and of
    nothing else, which is what "no two branches share a tag" actually asks
    for.
    """
    tag = decide(tmp_path, wanted="true", branch="my-branch")["tag"]

    release, rest = tag.split("-", 1)
    stem, digest, sha = rest.rsplit("-", 2)

    assert release == RELEASE
    assert stem == "my-branch"
    assert len(digest) == 10 and set(digest) <= set("0123456789abcdef")
    assert sha == SHORT


@pytest.mark.parametrize(
    "branch, stem",
    [
        ("claude/ci-images", "claude_ci-images"),
        ("a/b/c", "a_b_c"),
        # A tag is [A-Za-z0-9_.-]; a branch name is very nearly anything.
        ("feat/x:y z", "feat_x_y_z"),
        # 128 characters is the whole tag, and a branch name is unbounded.
        ("z" * 80, "z" * 40),
    ],
)
def test_a_branch_name_is_made_into_something_a_registry_accepts(tmp_path, branch, stem):
    """A tag the registry refuses is a build that fails at the push.

    The substitution `setup-devcontainer` makes for "/", widened to everything
    a tag may not hold, and truncated for length. Both are lossy, so the stem
    carries a digest of the whole original after it -- see the collision tests
    below for what that is for.
    """
    tag = decide(tmp_path, wanted="true", branch=branch)["tag"]

    assert tag.startswith("%s-%s-" % (RELEASE, stem))
    assert tag.endswith("-%s" % SHORT)


@pytest.mark.parametrize(
    "one, other",
    [
        # Sanitised alike.
        ("feat/x", "feat_x"),
        ("a/b", "a_b"),
        # Truncated alike: the same first forty characters.
        ("z" * 40 + "/first", "z" * 40 + "/second"),
        # Clean names, which the conditional digest used to leave alone and
        # which therefore could not collide -- until one of them was somebody
        # else's stem. See the round trip below.
        ("feat_x", "feat_y"),
    ],
)
def test_two_branches_that_sanitise_alike_still_get_two_tags(tmp_path, one, other):
    """The commit does not cover for this, because two branches can sit on one.

    And then it is two runs with one tag again: each publishing over the other,
    and each deleting the other's images on the way out. The digest of the
    whole original name is what keeps them apart.
    """
    assert decide(tmp_path, wanted="true", branch=one)["tag"] != decide(tmp_path, wanted="true", branch=other)["tag"]


def test_a_stem_is_not_reachable_as_somebody_elses_branch_name(tmp_path):
    """The collision the conditional digest left behind.

    `feat/x` produced the stem `feat_x-<digest>`, and a branch *named*
    `feat_x-<digest>` was clean, so it was left alone and produced that same
    stem. Two branches, one tag, and at one commit one image.

    Built out of the action's own output rather than a literal digest, so that
    changing the digest's length or algorithm cannot quietly stop this from
    testing anything: whatever stem the action makes of `feat/x` is fed back in
    as a branch name.
    """
    lossy = decide(tmp_path, wanted="true", branch="feat/x")["tag"]
    # Everything between the release and the commit: the stem as published.
    stem = lossy[len(RELEASE) + 1 : -(len(SHORT) + 1)]
    assert stem.startswith("feat_x-")

    impersonator = decide(tmp_path, wanted="true", branch=stem)["tag"]
    assert impersonator != lossy


def test_the_digest_is_of_the_branch_and_not_of_the_run(tmp_path):
    """So the same branch is the same stem every time.

    A tag that changed between two runs of one branch would be a tag no cache
    ever hits and no reader could predict.
    """
    first = decide(tmp_path, wanted="true", branch="feat/x", sha="1111111aaa")["tag"]
    second = decide(tmp_path, wanted="true", branch="feat/x", sha="2222222bbb")["tag"]

    assert first.rsplit("-", 1)[0] == second.rsplit("-", 1)[0]


def test_the_tag_names_one_commit_and_not_just_one_branch(tmp_path):
    """Two pushes to a branch are two runs, and each has to own its own tag.

    Their concurrency groups do not serialise them across workflows, so both
    would build `<release>-<branch>`, publish it, and test against whichever
    landed last. And `cleanup-images` runs under `always()` -- which includes
    *cancelled* -- so the superseded run would delete the tags of the run that
    superseded it, while that one was still using them.
    """
    first = decide(tmp_path, wanted="true", sha="1111111aaaaaaa")["tag"]
    second = decide(tmp_path, wanted="true", sha="2222222bbbbbbb")["tag"]

    assert first.endswith("-1111111")
    assert second.endswith("-2222222")
    assert first != second


def test_the_release_tag_carries_no_commit(tmp_path):
    """It is the release, which is a name an installed PartCAD resolves.

    The commit belongs only to a tag nobody outside its own run asks for.
    """
    assert decide(tmp_path, release_publish="true")["tag"] == RELEASE
    assert decide(tmp_path)["tag"] == RELEASE


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

    assert 'PC_IMAGE_REF="${IMAGE}:${IMAGE_TAG}-py${PY}-${ARCH}"' in step["run"]
    assert 'PC_PARTCAD_VERSION="${PC_VERSION}"' in step["run"]


def test_a_run_that_builds_its_own_tag_builds_both_architectures():
    """Otherwise the tag is half a tag, and nothing says so.

    A pull request builds amd64 alone, because arm64 goes through QEMU. That is
    a gap in *coverage* on an ordinary run and a gap in the *tag* on this one:
    every Arm job resolves `<release>-<branch>-<digest>-<commit>-py<X>-arm64` like every
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
    "Container images: <the branch tag> (built from this commit)" in its
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


# --------------------------------------------------------------------------- #
# One build, and the tags cleaned up after it                                  #
# --------------------------------------------------------------------------- #

BUILD_SCRIPT = "dev-tools/ci/build-sandbox-image.sh"
PRUNE = "prune-container-images.yml"


def test_only_one_thing_knows_how_to_build_a_sandbox_image():
    """Two spellings of it do not fail when they drift -- they disagree.

    `Build the Python sandbox images` publishes one, and
    `.github/actions/sandbox-image` builds one when the pull comes up empty.
    They used to be two `docker build` invocations in two files with the same
    Dockerfile and the same two build arguments, and nothing keeping them in
    step: a job testing an image built differently from the one the run
    published, under a name saying they are the same.
    """
    assert (REPO_ROOT / BUILD_SCRIPT).is_file()

    (step,) = [
        s
        for s in _workflow("test.yml")["jobs"]["build-containers"]["steps"]
        if s.get("name", "").startswith("Build the Python sandbox")
    ]
    action = (REPO_ROOT / ".github" / "actions" / "sandbox-image" / "action.yml").read_text()

    for where, text in (("build-containers", step["run"]), ("sandbox-image", action)):
        assert BUILD_SCRIPT in text, where
        # ...and neither builds it a second way of its own.
        assert "docker buildx build" not in text, where
        assert "docker build " not in text, where


def test_the_build_script_keeps_the_tag_and_the_release_apart():
    """The tag goes on the image; the release goes into it.

    One caller passes a branch tag and the release; the other passes the tag it
    just failed to pull. A script that derived either from the other would make
    that impossible.
    """
    script = (REPO_ROOT / BUILD_SCRIPT).read_text()

    assert "PC_IMAGE_REF" in script
    assert "PC_PARTCAD_VERSION" in script
    assert '--build-arg "PARTCAD_VERSION=${PC_PARTCAD_VERSION}"' in script
    assert '--tag "${PC_IMAGE_REF}"' in script


def test_a_test_job_no_longer_builds_the_image_it_renders_in():
    """It pulls what `build-containers` built, which is the point.

    Every job in `test.yml` that can reach a container waits for that job, so
    the tag it needs is published before it starts -- and the build that stayed
    in the action is for `Examples via bundle` in `build-standalone.yml`, which
    has no such `needs:` because it is in another workflow.
    """
    action = (REPO_ROOT / ".github" / "actions" / "sandbox-image" / "action.yml").read_text()

    assert "docker pull" in action
    # The build is reached only when the pull did not work.
    body = action[action.index("docker pull") :]
    assert body.index("else") < body.index(BUILD_SCRIPT)


def test_the_run_deletes_the_python_tags_it_published():
    """And only on a run that published any: `image-override` is empty
    otherwise, so an ordinary pull request does not have this job at all.

    `always()`, because a red run leaks exactly as much as a green one.
    """
    job = _workflow("test.yml")["jobs"]["cleanup-images"]
    condition = " ".join(str(job["if"]).split())

    assert "always()" in condition
    assert "outputs.image-override != ''" in condition
    assert job["permissions"]["packages"] == "write"

    # Everything that could still be pulling one.
    for consumer in CONSUMERS["test.yml"]:
        assert consumer in job["needs"], consumer
    assert "build-containers" in job["needs"]


def test_the_run_does_not_delete_the_kicad_tag():
    """`CI-Dev` pulls it too, and a `needs:` does not reach across a workflow.

    That is the fact this whole mechanism was built around, and deleting the
    tag here would turn it into the same `manifest unknown` -- arriving as a
    race rather than as a certainty. The nightly sweep takes it instead. The
    Python images have no such reader: the dev container cannot use the
    `docker` sandbox at all, so `CI` is their only consumer.
    """
    (step,) = _workflow("test.yml")["jobs"]["cleanup-images"]["steps"]

    assert "container-python" in step["run"]
    assert "container-kicad" not in step["run"]


def test_the_nightly_sweep_covers_every_package_that_grows_branch_tags():
    """Including the dev container image, which predates all of this.

    `setup-devcontainer` has been publishing `<release>-<branch>` on every
    non-bump run of `CI-Dev` for as long as it has existed, and nothing has
    ever deleted one.
    """
    jobs = _workflow(PRUNE)["jobs"]
    (job,) = jobs.values()
    (step,) = job["steps"]

    assert job["permissions"]["packages"] == "write"
    for package in ("-devcontainer", "-container-python", "-container-kicad"):
        assert package in step["run"], package

    # A schedule, and a way to run it by hand without deleting anything.
    on = _workflow(PRUNE)[True]  # YAML parses a bare `on:` key as the boolean
    assert "schedule" in on
    assert "dry-run" in on["workflow_dispatch"]["inputs"]


def _tag_rule():
    """The sweep's `is_branch_tag`, extracted so it can be run over real tags."""
    (step,) = list(_workflow(PRUNE)["jobs"].values())[0]["steps"]
    match = re.search(r"^is_branch_tag\(\) \{.*?^\}$", step["run"], re.S | re.M)
    assert match, "the sweep no longer has an 'is_branch_tag' function"
    return match.group(0)


@pytest.mark.parametrize(
    "tag, deleted",
    [
        # What a released PartCAD resolves. Deleting one of these is the only
        # way this workflow can do real damage.
        ("0.8.70", False),
        ("0.8.70-py3.11-amd64", False),
        ("0.8.70-py3.14-arm64", False),
        # The moving tag a third-party plugin builds `FROM`.
        ("py3.11-amd64", False),
        ("py3.14-arm64", False),
        # Anything with no release in front of it is not ours to reason about.
        ("latest", False),
        ("main", False),
        # What a run publishes for itself, which is what this exists to remove.
        ("0.8.70-my-branch", True),
        ("0.8.70-claude_ci-images", True),
        ("0.8.70-my-branch-py3.11-amd64", True),
        ("0.8.70-feat_x-py3.14-arm64", True),
        # With the commit in it, which is the shape a run actually publishes.
        ("0.8.70-my-branch-abc1234", True),
        ("0.8.70-my-branch-abc1234-py3.11-amd64", True),
        ("0.10.0-devel", True),
        # A branch actually called "py3-weird" is kept forever. That is the
        # harmless half of being wrong, and it is which half that matters.
        ("0.8.70-py3-weird-py3.11-amd64", False),
    ],
)
def test_the_sweep_deletes_branch_tags_and_nothing_else(tmp_path, tag, deleted):
    script = tmp_path / "rule.sh"
    script.write_text(
        'set -euo pipefail\n%s\nif is_branch_tag "$1"; then echo DELETE; else echo KEEP; fi\n' % _tag_rule()
    )
    result = subprocess.run(
        ["bash", str(script), tag],
        env={"PATH": "/usr/bin:/bin:/usr/local/bin"},
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == ("DELETE" if deleted else "KEEP"), tag


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
    # The release still goes *into* the image it may have to build, and it is
    # the one thing the tag does not tell the build script.
    assert 'PC_PARTCAD_VERSION="${release}"' in action
