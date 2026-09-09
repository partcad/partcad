#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What `pc system prune` will and will not remove.

The interesting half of a cleanup command is what it leaves alone. A machine
running PartCAD is a machine somebody also uses for other things, and an image
removed because it happened to be sitting there is the kind of thing that gets a
tool uninstalled. So every test here is really the same test twice: the labelled
thing goes, the unlabelled one stays.

No daemon is needed to decide any of it, which is why `docker_prune` takes a
client rather than making one.
"""

import types

import pytest

from partcad import docker_prune


def _image(tags=None, labels=None, image_id="sha256:abc"):
    return types.SimpleNamespace(tags=tags or [], labels=labels or {}, id=image_id, short_id=image_id[:12])


def _container(name="pc-sandbox-abc", labels=None, status="exited"):
    return types.SimpleNamespace(name=name, labels=labels or {}, status=status, id="c" * 12, short_id="c" * 10)


class _Client:
    """Just enough docker SDK to be asked what is here."""

    def __init__(self, images=(), containers=()):
        self.images = types.SimpleNamespace(list=lambda all=False: list(images))
        self.containers = types.SimpleNamespace(list=lambda all=False: list(containers))


# --------------------------------------------------------------------------- #
# Images                                                                       #
# --------------------------------------------------------------------------- #


def test_an_unlabelled_image_is_never_touched():
    """Somebody else's image, on somebody else's machine."""
    client = _Client(images=[_image(tags=["postgres:16"]), _image(tags=["my/thing:1"], labels={"other": "1"})])
    assert docker_prune.managed_images(client) == []


def test_a_labelled_image_is_ours_to_remove():
    ours = _image(tags=["ghcr.io/partcad/partcad-container-python:0.8.58-py3.11"], labels={"partcad.image": "1"})
    client = _Client(images=[_image(tags=["postgres:16"]), ours])
    assert docker_prune.managed_images(client) == [ours]


def test_stale_keeps_the_release_that_is_running():
    """The image this PartCAD is about to use is not litter."""
    current = _image(tags=["pc:new"], labels={"partcad.image": "1", "partcad.version": "0.8.58"})
    old = _image(tags=["pc:old"], labels={"partcad.image": "1", "partcad.version": "0.8.40"})
    client = _Client(images=[current, old])

    assert docker_prune.managed_images(client, stale_only=True, version="0.8.58") == [old]
    # Without --stale both go: the user asked for everything PartCAD made.
    assert docker_prune.managed_images(client) == [current, old]


def test_an_image_with_no_version_is_never_stale():
    """A third party's image, whose author did not say when it goes out of date.

    Guessing on their behalf is how a cleanup command removes the image
    somebody is about to use.
    """
    theirs = _image(tags=["ghcr.io/you/solver:abc"], labels={"partcad.image": "1"})
    client = _Client(images=[theirs])

    assert docker_prune.managed_images(client, stale_only=True, version="0.8.58") == []
    # It is still ours to remove when asked for everything.
    assert docker_prune.managed_images(client) == [theirs]


# --------------------------------------------------------------------------- #
# Containers                                                                   #
# --------------------------------------------------------------------------- #


def test_only_containers_partcad_started():
    ours = _container(labels={"partcad.container": "1"})
    client = _Client(containers=[_container(name="somebody-elses", labels={}), ours])
    assert docker_prune.managed_containers(client) == [ours]


def test_stale_leaves_a_running_container_alone():
    """A sandbox container is started once and reused, so a running one is work."""
    running = _container(name="pc-sandbox-busy", labels={"partcad.container": "1"}, status="running")
    stopped = _container(name="pc-sandbox-idle", labels={"partcad.container": "1"}, status="exited")
    client = _Client(containers=[running, stopped])

    assert docker_prune.managed_containers(client, stale_only=True) == [stopped]
    assert docker_prune.managed_containers(client) == [running, stopped]


@pytest.mark.parametrize("status", ["paused", "restarting", "created"])
def test_stale_leaves_anything_not_finished_alone(status):
    """'--stale' removes with force, and only "running" was being skipped.

    A paused container is somebody's work in progress as much as a running one
    is, and a restarting one is on its way to being running.
    """
    busy = _container(name="pc-sandbox-busy", labels={"partcad.container": "1"}, status=status)
    stopped = _container(name="pc-sandbox-idle", labels={"partcad.container": "1"}, status="exited")
    client = _Client(containers=[busy, stopped])

    assert docker_prune.managed_containers(client, stale_only=True) == [stopped]
    # Without '--stale' the user asked for all of them, and gets all of them.
    assert docker_prune.managed_containers(client) == [busy, stopped]


# --------------------------------------------------------------------------- #
# Reading labels off whatever the SDK hands back                               #
# --------------------------------------------------------------------------- #


def test_labels_are_found_under_attrs_too():
    """`images.list()` populates `labels`; a freshly pulled image may not.

    Both shapes appear in the SDK, and a prune that saw only one of them would
    silently decide it had nothing to do.
    """
    from_attrs = types.SimpleNamespace(
        tags=["pc:x"], attrs={"Config": {"Labels": {"partcad.image": "1"}}}, id="sha256:d", short_id="d"
    )
    assert docker_prune.managed_images(_Client(images=[from_attrs])) == [from_attrs]


def test_something_with_no_name_at_all_still_logs_as_something():
    assert docker_prune.name_of(types.SimpleNamespace(id="sha256:beef", short_id="beef")) == "beef"
