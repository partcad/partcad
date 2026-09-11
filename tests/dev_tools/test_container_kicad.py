#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The one KiCad image, and the two workflows that have to wait for it.

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
    return yaml.safe_load((WORKFLOWS / workflow).read_text())["jobs"]


def _needs(job):
    """A job's dependencies, whichever of the two spellings it uses."""
    needs = job.get("needs") or []
    return [needs] if isinstance(needs, str) else needs


def test_the_image_is_built_by_one_reusable_workflow():
    jobs = _jobs("container-kicad.yml")
    assert len(jobs) == 1
    (job,) = jobs.values()

    step = [s for s in job["steps"] if s.get("uses", "").startswith("devcontainers/ci")]
    assert len(step) == 1
    assert step[0]["with"]["configFile"] == "tools/containers/devcontainer-kicad.json"
    # Published, not merely built: what waits on this job waits for a tag it can
    # pull from somewhere else entirely.
    assert step[0]["with"]["push"] == "always"


def test_the_build_is_not_cancellable():
    """Cancelling it is exactly the missing image everything else waits for."""
    (job,) = _jobs("container-kicad.yml").values()
    assert job["concurrency"]["cancel-in-progress"] is False


@pytest.mark.parametrize("workflow", sorted(CALLERS))
def test_both_test_workflows_call_it(workflow):
    calls = [name for name, job in _jobs(workflow).items() if job.get("uses") == REUSABLE]
    assert calls == ["container-kicad"], workflow


@pytest.mark.parametrize("workflow", sorted(CALLERS))
def test_the_job_running_the_unit_tests_waits_for_it(workflow):
    job = _jobs(workflow)[CALLERS[workflow]]
    assert "container-kicad" in _needs(job), workflow


@pytest.mark.parametrize("workflow", sorted(CALLERS))
def test_the_caller_grants_the_permission_to_publish(workflow):
    """A called workflow gets the calling job's permissions and no more."""
    job = _jobs(workflow)["container-kicad"]
    assert job["permissions"]["packages"] == "write"
