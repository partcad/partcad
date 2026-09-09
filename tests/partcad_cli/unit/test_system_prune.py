#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What `pc system prune` does once it has decided what to remove.

`test_docker_prune.py` pins the *choosing* -- which containers and images carry
PartCAD's labels and are therefore ours. This pins the *acting*, which is a
different thing and mostly a question of what the command does when a removal
does not work.

The distinction that matters here is between the two ways a removal fails. An
image the daemon refuses because a container is still using it is not a failure:
the user asked for what is safe to remove and that is the answer. Anything else
leaves the machine holding what the user asked to be rid of, and so has to reach
the exit code -- which, in PartCAD, is what logging an error does.
"""

import types
from collections.abc import Iterator

import docker
import pytest
from click.testing import CliRunner

import partcad as pc
from partcad import docker_prune
from partcad_cli.click.command import cli


def _image(tags=None, labels=None, image_id="sha256:abc"):
    return types.SimpleNamespace(
        tags=tags or [],
        labels=dict(labels or {}, **{docker_prune.LABEL_IMAGE: "1"}),
        id=image_id,
        short_id=image_id[:12],
    )


def _container(name="pc-sandbox-abc", status="exited", removes=None):
    made = types.SimpleNamespace(
        name=name,
        labels={docker_prune.LABEL_CONTAINER: "1"},
        status=status,
        id="c" * 12,
        short_id="c" * 10,
        removed=False,
    )

    def remove(force=False):
        if removes is not None:
            raise removes
        made.removed = True

    made.remove = remove
    return made


class _Daemon:
    """Just enough of the SDK for the command to list and remove."""

    def __init__(self, images=(), containers=(), image_removes=None):
        self.removed_images = []
        self._image_removes = image_removes

        def remove_image(image_id, force=False):
            if self._image_removes is not None:
                raise self._image_removes
            self.removed_images.append(image_id)

        self.images = types.SimpleNamespace(list=lambda all=False: list(images), remove=remove_image)
        self.containers = types.SimpleNamespace(list=lambda all=False: list(containers))


@pytest.fixture
def daemon(monkeypatch):
    """A container runtime that answers, and whatever it is told to hold."""

    def install(**kwargs):
        made = _Daemon(**kwargs)
        monkeypatch.setattr(pc.runtime, "docker_available", lambda: True)
        monkeypatch.setattr(docker, "from_env", lambda *a, **k: made)
        return made

    return install


def _prune(click_runner, *extra):
    return click_runner.invoke(cli, ["--no-ansi", "system", "prune", *extra])


# --------------------------------------------------------------------------- #
# Nothing to do                                                                #
# --------------------------------------------------------------------------- #


def test_without_a_container_runtime_it_says_so_and_succeeds(click_runner: Iterator[CliRunner], monkeypatch) -> None:
    """A machine with no daemon has nothing of PartCAD's on it to remove.

    It must not be an error: `pc system prune` is the kind of thing that goes in
    a cleanup script, and a script that fails on a machine with no Docker is a
    script nobody runs.
    """
    monkeypatch.setattr(pc.runtime, "docker_available", lambda: False)
    monkeypatch.setattr(docker, "from_env", lambda *a, **k: pytest.fail("asked the daemon after finding none"))

    assert _prune(click_runner).exit_code == 0


def test_an_empty_machine_succeeds(click_runner: Iterator[CliRunner], daemon) -> None:
    daemon()
    assert _prune(click_runner).exit_code == 0


def test_an_unlabelled_image_leaves_nothing_to_do(click_runner: Iterator[CliRunner], daemon) -> None:
    """The command reaches the daemon and still removes nothing."""
    theirs = types.SimpleNamespace(tags=["postgres:16"], labels={}, id="sha256:zzz", short_id="sha256:zzz")
    made = daemon(images=[theirs])

    assert _prune(click_runner).exit_code == 0
    assert made.removed_images == []


# --------------------------------------------------------------------------- #
# Removing                                                                     #
# --------------------------------------------------------------------------- #


def test_a_labelled_container_and_image_are_removed(click_runner: Iterator[CliRunner], daemon) -> None:
    ours = _image(tags=["ghcr.io/partcad/partcad-container-python:0.8.61-py3.11"])
    container = _container()
    made = daemon(images=[ours], containers=[container])

    assert _prune(click_runner).exit_code == 0
    assert container.removed is True
    assert made.removed_images == [ours.id]


def test_stale_leaves_a_running_container_alone(click_runner: Iterator[CliRunner], daemon) -> None:
    """A running sandbox is somebody's work in progress, not litter."""
    running = _container(name="pc-sandbox-live", status="running")
    daemon(containers=[running])

    assert _prune(click_runner, "--stale").exit_code == 0
    assert running.removed is False


# --------------------------------------------------------------------------- #
# When a removal does not work                                                 #
# --------------------------------------------------------------------------- #


def test_a_container_removed_by_somebody_else_is_not_a_failure(click_runner: Iterator[CliRunner], daemon) -> None:
    """Gone between the listing and the removal is the outcome that was asked for."""
    daemon(containers=[_container(removes=docker.errors.NotFound("gone"))])

    assert _prune(click_runner).exit_code == 0


def test_a_container_that_will_not_go_is_a_failure(click_runner: Iterator[CliRunner], daemon) -> None:
    """The machine is still holding what the user asked to be rid of."""
    daemon(containers=[_container(removes=RuntimeError("device busy"))])

    assert _prune(click_runner).exit_code != 0


def test_one_stuck_container_does_not_keep_the_rest(click_runner: Iterator[CliRunner], daemon) -> None:
    stuck = _container(name="pc-sandbox-stuck", removes=RuntimeError("device busy"))
    fine = _container(name="pc-sandbox-fine")
    daemon(containers=[stuck, fine])

    assert _prune(click_runner).exit_code != 0
    assert fine.removed is True


def test_an_image_already_gone_is_not_a_failure(click_runner: Iterator[CliRunner], daemon) -> None:
    daemon(images=[_image(tags=["pc:1"])], image_removes=docker.errors.ImageNotFound("gone"))

    assert _prune(click_runner).exit_code == 0


def test_an_image_still_in_use_is_kept_rather_than_failed(click_runner: Iterator[CliRunner], daemon) -> None:
    """`--stale` can choose an image whose container this run did not choose.

    The daemon refusing that is the correct answer to what was asked, so it is a
    warning and the command still succeeds.
    """
    daemon(images=[_image(tags=["pc:1"])], image_removes=docker.errors.APIError("conflict: still in use"))

    assert _prune(click_runner).exit_code == 0


def test_an_image_that_fails_for_any_other_reason_is_a_failure(click_runner: Iterator[CliRunner], daemon) -> None:
    """Not the registry saying no, then -- so the command says so on the way out."""
    daemon(images=[_image(tags=["pc:1"])], image_removes=RuntimeError("disk went away"))

    assert _prune(click_runner).exit_code != 0


# --------------------------------------------------------------------------- #
# Naming a thing in a log line                                                 #
# --------------------------------------------------------------------------- #


def test_a_thing_with_no_tag_and_no_name_is_still_nameable() -> None:
    """`name_of` is only ever used to build a log line, so it must not raise."""
    assert docker_prune.name_of(types.SimpleNamespace(tags=[], name=None, short_id="abc123")) == "abc123"
    assert docker_prune.name_of(types.SimpleNamespace(tags=[], name=None, short_id=None, id="")) == "?"
