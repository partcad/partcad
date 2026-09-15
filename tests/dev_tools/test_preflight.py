#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a run is told when it does not have what the jobs after it reach for.

Every credential in this repository's CI is one `partcad/partcad` has and a
fork does not. Before `.github/actions/preflight` existed, a fork that ran this
found that out as a push refused by a registry half an hour in, on a job whose
error named the registry rather than the setup -- and a fork whose pull request
changed a Dockerfile found it out not at all, because the run degraded to the
release's images and went green having tested the change it was opened for.

So the questions are asked once, up front, and answered in terms of what to go
and change. This file pins the one decision that is easy to get backwards:
*when to stop*. Stopping a run that can be fixed is the point; stopping one that
cannot be is a contributor's pull request blocked forever on a setting nobody
can reach. The difference is whether the head is in another repository -- not
whether the head repository is a fork of one, which is a different question with
a different answer for a pull request opened inside a fork. The two halves are
`test_a_fork_is_told_where_to_get_the_coverage_not_failed` and
`test_a_missing_write_that_can_be_fixed_stops_the_run`; the distinction itself is
`test_a_fork_is_its_head_being_elsewhere_not_its_repository_being_a_fork`.

The library half of the same subject is `tests/partcad_utils/test_container_image.py`;
the tag it threads is `tests/dev_tools/test_container_images.py`.
"""

import base64
import json
import os
import pathlib
import subprocess

import pytest
import yaml

# POSIX only, for the reason `test_container_images.py` gives: the action is
# bash and only ever runs on a Linux runner, and a Windows `bash.exe` is the WSL
# launcher, which answers a script by telling you to install a distribution.
pytestmark = pytest.mark.skipif(os.name == "nt", reason="the action is bash, and it only ever runs on Linux runners")

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
ACTION = REPO_ROOT / ".github" / "actions" / "preflight" / "action.yml"
USES = "./.github/actions/preflight"

PATH = "/usr/bin:/bin:/usr/local/bin"

# What stands in for the key. Deliberately not a real `-----BEGIN ... PRIVATE
# KEY-----` header: the action only ever asks whether the value is non-empty, so
# a realistic one buys these tests nothing, and it costs a `detect-private-key`
# failure in "Lint (pre-commit)" -- which is what happened. Splicing the header
# together at runtime to slip past that hook would be defeating a security gate
# on purpose, so the value is simply not key-shaped.
SECRET_SENTINEL = "a-key-would-be-here-and-must-never-be-printed"


def _check_script():
    action = yaml.safe_load(ACTION.read_text())
    (step,) = [s for s in action["runs"]["steps"] if s.get("id") == "check"]
    return step["run"]


def _jwt(actions, spacing=False):
    """A registry token shaped the way ghcr's token endpoint returns one.

    `{"token": "<header>.<claims>.<signature>"}`, the claims carrying the
    `access[].actions` the registry decided to grant. Nothing verifies the
    signature -- the action reads what was granted, it does not authenticate
    the answer, because the answer arrived over TLS from the registry it asked.
    """
    claims = {"access": [{"type": "repository", "name": "partcad/partcad-container-python", "actions": actions}]}
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    # Compact, the way a registry actually answers. `spacing` is the other
    # shape the same response can take, and the reason the action peels the
    # field a piece at a time -- see the test below.
    body = {"token": "header.%s.signature" % payload}
    return json.dumps(body, separators=(",", ":")) if not spacing else json.dumps(body)


def _curl_stub(tmp_path, body=None):
    """A `curl` on PATH that answers with `body`, or fails when it is None.

    The real registry is not reachable from the suite and should not be: what
    is under test is how the action reads an answer, and the two answers that
    matter -- push granted and push withheld -- are not ones a test can
    provoke from ghcr on demand.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    stub = bindir / "curl"
    if body is None:
        stub.write_text("#!/bin/sh\nexit 22\n")
    else:
        stub.write_text("#!/bin/sh\ncat <<'BODY'\n%s\nBODY\n" % body)
    stub.chmod(0o755)
    return "%s:%s" % (bindir, PATH)


def preflight(
    tmp_path,
    needs_ghcr="false",
    needs_ssh="false",
    ssh_key="",
    token="t0ken",
    fork="false",
    granted=("pull", "push"),
    path=None,
):
    """Run the action's one step; return (outputs, returncode, summary, stdout)."""
    output = tmp_path / "output"
    output.touch()
    summary = tmp_path / "summary"
    summary.touch()

    if path is None:
        answer = _jwt(list(granted)) if granted is not None else None
        path = _curl_stub(tmp_path, answer)

    done = subprocess.run(
        ["bash", "-c", _check_script()],
        env={
            "PATH": path,
            "NEEDS_GHCR": needs_ghcr,
            "NEEDS_SSH": needs_ssh,
            "SSH_KEY": ssh_key,
            "REGISTRY": "ghcr.io",
            "TOKEN": token,
            "FROM_A_FORK": fork,
            "REPO": "partcad/partcad",
            "OWNER": "partcad",
            "GITHUB_OUTPUT": str(output),
            "GITHUB_STEP_SUMMARY": str(summary),
        },
        capture_output=True,
        text=True,
    )
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines() if line)
    return outputs, done.returncode, summary.read_text(), done.stdout + done.stderr


def test_a_run_that_needs_nothing_passes_with_nothing(tmp_path):
    """The ordinary pull request: it pulls the release's images and clones no
    private repository, so a fork with no secrets at all runs it in full.

    This is the case that decides whether the gate is worth having. A preflight
    that demanded credentials of every run would stop every fork instead of the
    ones that cannot do what they were asked.
    """
    outputs, rc, summary, _ = preflight(tmp_path, token="")

    assert rc == 0
    assert outputs == {"ghcr-write": "false", "ssh-key": "false"}
    assert "not needed" in summary


def test_a_withheld_push_does_not_stop_the_run(tmp_path):
    """The registry's negative answer is not evidence, so it cannot be a gate.

    On `partcad/partcad` -- the repository whose workflows publish every one of
    these images, with `packages: write` and the same `GITHUB_TOKEN` -- the
    token endpoint answers `pull` and no `push`. The release tags on ghcr are
    the evidence that the push works anyway, so a gate stopping on that answer
    would stop this repository from building its own images, and the person it
    stopped would have nothing to fix.

    Found by reading the `Prerequisites` output on this PR's own run rather
    than by any test failing: the check was green because the run did not need
    the write. The cost is real and is stated where the code is -- a fork with
    read-only workflow permissions is no longer caught before its push.
    """
    outputs, rc, summary, out = preflight(tmp_path, needs_ghcr="true", granted=["pull"])

    assert rc == 0
    assert outputs["ghcr-write"] == "true"
    assert "::error" not in out
    assert "assumed writable" in summary


def test_a_fork_is_told_where_to_get_the_coverage_not_failed(tmp_path):
    """The case that must NOT stop, and the reason this is not one `if`.

    GitHub gives a fork's pull request a read-only token whatever the workflow
    declares, so there is nothing the contributor can change to make this run
    publish. Failing it would leave an outside contributor's Dockerfile change
    permanently un-mergeable for a reason they cannot act on. So the gap keeps
    the warning it has always had, and gains the thing it was missing: where to
    go to close it.
    """
    outputs, rc, summary, out = preflight(tmp_path, needs_ghcr="true", fork="true")

    assert rc == 0
    assert outputs["ghcr-write"] == "false"
    assert "::warning" in out and "::error" not in out
    assert "no fix inside this run" in summary
    assert "your own fork" in summary


def test_a_granted_push_reports_the_write(tmp_path):
    outputs, rc, summary, _ = preflight(tmp_path, needs_ghcr="true", granted=["pull", "push"])

    assert rc == 0
    assert outputs["ghcr-write"] == "true"
    assert "is writable" in summary


def test_whitespace_in_the_registry_answer_does_not_defeat_the_probe(tmp_path):
    """The bug this probe had when it was written, kept from coming back.

    The JWT was pulled out with a single pattern that assumed `{"token":"..."}`
    with no space after the colon. A response spelled `{"token": "..."}` left
    the whole body in the variable, the decode produced nothing, and the run
    fell through to the "could not be asked" fallback -- which assumes writable
    and carries on. So the probe reported success for every answer it could not
    read, which is the one failure mode a check like this must not have.
    """
    path = _curl_stub(tmp_path, _jwt(["pull", "push"], spacing=True))
    outputs, rc, summary, _ = preflight(tmp_path, needs_ghcr="true", path=path)

    # "is writable" is only reachable by actually decoding the claims; "could
    # not be asked" is what an unreadable answer falls through to. Both end at
    # writable now, so the detail is the only thing that tells them apart --
    # which is exactly why it is asserted rather than the exit code.
    assert rc == 0
    assert "is writable" in summary, "a spaced-out answer was not parsed"
    assert "could not be asked" not in summary


def test_a_probe_that_cannot_run_assumes_writable_rather_than_crashing(tmp_path):
    """No route to the registry, no `curl`, an answer in an unreadable shape.

    Two things must not happen. `set -e` must not take the job down before the
    summary is written -- the message is the deliverable here, and a preflight
    that dies without one fails in the same illegible way as the jobs it
    replaced. And a run must not be called broken because a *check* could not
    be made: the token is writable in principle here, so the run proceeds and
    the push says otherwise if it is.
    """
    outputs, rc, summary, _ = preflight(tmp_path, needs_ghcr="true", granted=None)

    assert rc == 0
    assert outputs["ghcr-write"] == "true"
    assert "could not be asked" in summary


def test_the_ssh_key_is_reported_as_present_without_being_printed(tmp_path):
    outputs, rc, summary, out = preflight(tmp_path, ssh_key=SECRET_SENTINEL)

    assert rc == 0
    assert outputs["ssh-key"] == "true"
    # Never the value. GitHub masks registered secrets in its own log, but this
    # runs the script directly and the guarantee wanted here is that the script
    # does not print it in the first place.
    assert SECRET_SENTINEL not in summary
    assert SECRET_SENTINEL not in out


def test_a_private_repository_without_a_key_is_stopped(tmp_path):
    """The rule the caller passes, exercised end to end.

    A private fork's packages may depend on repositories that are private too,
    and `pc install` cloning one is what the key is for. Left to the suite, a
    missing key surfaces as a `git` authentication failure inside one behave
    scenario in one shard, a long way from the cause.
    """
    outputs, rc, summary, out = preflight(tmp_path, needs_ssh="true", ssh_key="")

    assert rc == 1
    assert outputs["ssh-key"] == "false"
    assert "::error" in out
    assert "SSH_PRIVATE_KEY_RO" in summary
    assert "deploy key" in summary
    # A heuristic has to say how to turn it off, or it is a wall.
    assert 'needs-ssh: "false"' in summary


def test_a_private_repository_with_a_key_carries_on(tmp_path):
    outputs, rc, summary, _ = preflight(tmp_path, needs_ssh="true", ssh_key=SECRET_SENTINEL)

    assert rc == 0
    assert outputs["ssh-key"] == "true"
    assert "private dependency" in summary


@pytest.mark.parametrize("workflow", ["test.yml", "test-dev.yml"])
def test_the_key_is_asked_for_where_the_repository_is_private(workflow):
    """And nowhere else.

    Hard-coded `"false"`, the key would be dead weight -- which is what it
    looked like from the public upstream, whose own dependencies are public and
    clone over https. Hard-coded `"true"`, every public fork would be stopped
    for a credential it has no use for. The repository being private is the one
    signal available here that correlates with "its dependencies are private
    too".
    """
    (step,) = [s for s in _jobs(workflow)["preflight"]["steps"] if s.get("uses") == USES]
    needs_ssh = " ".join(str(step["with"]["needs-ssh"]).split())

    assert "github.event.repository.private" in needs_ssh, needs_ssh


@pytest.mark.parametrize("action", ["preflight", "container-images"])
def test_a_fork_is_its_head_being_elsewhere_not_its_repository_being_a_fork(action):
    """The distinction that decides whether a fork can test its own work.

    GitHub's read-only-token rule turns on the head being in *another*
    repository. `head.repo.fork` asks something else: whether the head
    repository is a fork of anything. For a pull request opened inside a fork,
    branch to branch, the two disagree -- `fork` is true (that repository is a
    fork of this one) while the token is fully writable (the head is that same
    repository).

    Read the wrong one, and a contributor's own pull request in their own fork
    is treated as untrusted there: no images published, no coverage of the
    change it makes to them. That is the run they open to check their work
    before sending it here, so it is the one that most needs to behave like a
    pull request in this repository -- which is the whole ask.
    """
    lines = (REPO_ROOT / ".github" / "actions" / action / "action.yml").read_text().splitlines()
    index = next(i for i, ln in enumerate(lines) if "FROM_A_FORK:" in ln)
    expression = " ".join((lines[index] + " " + lines[index + 1]).split())

    assert "head.repo.full_name != github.repository" in expression, expression

    # Comments here name the wrong spelling in order to explain it, so only
    # what is actually evaluated is checked.
    code = "\n".join(ln for ln in lines if not ln.lstrip().startswith("#"))
    assert "head.repo.fork" not in code, action


def _jobs(name):
    return yaml.safe_load((WORKFLOWS / name).read_text())["jobs"]


@pytest.mark.parametrize(
    "workflow,credentialed",
    [
        ("test.yml", ("container-kicad", "build-containers")),
        ("test-dev.yml", ("devcontainer", "container-kicad")),
    ],
)
def test_every_job_that_holds_a_credential_waits_for_the_check(workflow, credentialed):
    """And through them, every job that runs a test.

    The gate is deliberately narrow: these are the jobs that talk to the
    registry, and every test job already needs them, so the graph that exists
    carries the rest. What must not happen is a credentialed job that does not
    need `preflight` -- that is the push that fails at the registry with the
    check sitting green beside it.
    """
    jobs = _jobs(workflow)
    assert "preflight" in jobs, workflow

    for name in credentialed:
        needs = jobs[name].get("needs") or []
        needs = [needs] if isinstance(needs, str) else needs
        assert "preflight" in needs, "%s: %s does not wait for the preflight" % (workflow, name)


@pytest.mark.parametrize(
    "workflow,speaks_for",
    [("test.yml", "build-containers"), ("test-dev.yml", "devcontainer")],
)
def test_the_check_holds_the_same_token_as_the_job_it_speaks_for(workflow, speaks_for):
    """A GITHUB_TOKEN is scoped per job, so the probe must request what it measures.

    Left at the workflow default of `contents: read`, the preflight would ask
    the registry about a token nothing else uses: the answer would be "pull but
    not push" on this repository too, where the push works fine, and every run
    that builds an image would stop on a check that was measuring the wrong
    thing. Requesting the write is not assuming it -- whether the repository
    grants it is exactly the question.
    """
    jobs = _jobs(workflow)
    assert (jobs["preflight"].get("permissions") or {}).get("packages") == "write", workflow
    assert (jobs[speaks_for].get("permissions") or {}).get("packages") == "write", workflow

    # And "contents: read" alongside it. A job-level block REPLACES the
    # workflow's rather than adding to it, so every scope left out is "none" --
    # and with "contents" at none, "actions/checkout" cannot clone a private
    # repository and the job dies before the check runs. On a private fork,
    # which is the case this action exists for.
    assert (jobs["preflight"].get("permissions") or {}).get("contents") == "read", workflow


@pytest.mark.parametrize("workflow,scope", [("test.yml", "set-matrix"), ("test-dev.yml", "scope")])
def test_the_check_is_asked_about_wanting_rather_than_succeeding(workflow, scope):
    """Reading `image-push` alone would make it silent on the run that matters.

    `push` is already false for the fork that could not publish -- that is what
    the action degraded to -- so a preflight gated on it would say nothing
    exactly when there is something to say. `image-degraded` is the other half.
    """
    (step,) = [s for s in _jobs(workflow)["preflight"]["steps"] if s.get("uses") == USES]
    needs_ghcr = " ".join(str(step["with"]["needs-ghcr"]).split())

    assert "%s.outputs.image-push" % scope in needs_ghcr
    assert "%s.outputs.image-degraded" % scope in needs_ghcr


def test_a_devcontainer_change_counts_as_needing_the_registry():
    """It publishes an image while setting neither image output.

    A change to ".devcontainer" alone leaves `image-push` and `image-degraded`
    both false, and the `devcontainer` job still runs -- its only condition is
    `scope.outputs.devcontainer` -- and still pushes, with `push: always`. Read
    only the image outputs, and a fork's pull request changing that one
    directory is told nothing about the publish it cannot do.
    """
    jobs = _jobs("test-dev.yml")
    (step,) = [s for s in jobs["preflight"]["steps"] if s.get("uses") == USES]
    needs_ghcr = " ".join(str(step["with"]["needs-ghcr"]).split())

    assert "scope.outputs.devcontainer" in needs_ghcr, needs_ghcr

    # The premise: that job publishes, and is gated on that output alone.
    devcontainer = jobs["devcontainer"]
    assert "scope.outputs.devcontainer" in str(devcontainer.get("if")), devcontainer.get("if")
    assert any(
        "push: always" in str(s.get("with", {})) or s.get("with", {}).get("push") == "always"
        for s in devcontainer["steps"]
    ), "the dev container job no longer pushes"


@pytest.mark.parametrize("workflow", ["test.yml", "test-dev.yml"])
def test_a_fork_pulls_the_images_it_published_rather_than_upstreams(workflow):
    """`image-owner` has to follow publishing, not the tag override.

    A fork running CI by hand from its Actions tab is a `workflow_dispatch`,
    which `container-images` reads as a release publish: it pushes the *release*
    tag into the fork's namespace and overrides no tag at all. Keyed on
    `override`, the redirection would be empty for exactly that run -- the fork
    would build its images, push them, and then have every test pull
    `ghcr.io/partcad/...`, which is the failure this whole mechanism exists to
    prevent, arriving through the one door the tag cannot cover.

    And `fork` has to be in it, because `push` is true in this repository too
    -- for the version bump and for a branch-image run -- and both publish to
    `partcad`, where the name in the source is already right.
    """
    jobs = yaml.safe_load((WORKFLOWS / workflow).read_text())["jobs"]
    (gate,) = [j for j in jobs.values() if "image-owner" in str(j.get("outputs") or {})]
    owner = " ".join(str(gate["outputs"]["image-owner"]).split())

    assert "outputs.push == 'true'" in owner, owner
    assert "github.event.repository.fork" in owner, owner
    assert "github.repository_owner" in owner, owner


@pytest.mark.parametrize("workflow", ["test.yml", "test-dev.yml"])
def test_the_ssh_agent_starts_only_where_there_is_a_key(workflow):
    """Through the preflight's output, because nothing else can see a secret.

    `secrets` is not readable from an `if:` and a step's own `env:` is not
    readable from that same step's `if:`. Unconditional -- which is what this
    was -- the action is handed an empty string on a fork and fails the job
    with "The ssh-private-key argument is empty", which names neither the
    secret nor the fork.
    """
    for job in _jobs(workflow).values():
        for step in job.get("steps") or []:
            if "webfactory/ssh-agent" in str(step.get("uses", "")):
                assert "needs.preflight.outputs.ssh-key" in str(step.get("if", "")), workflow
                break
