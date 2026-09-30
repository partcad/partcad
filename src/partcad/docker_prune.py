#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Which containers and images are PartCAD's to remove, and which are not.

The whole of this module is one rule: **only what carries PartCAD's labels**.
A machine that runs PartCAD is a machine somebody also uses for other things,
and a cleanup command that removed an image it did not put there would be a
command nobody dares run twice.

That is why the labels exist at all, and why third-party images are asked to
carry them (see ``tools/containers/README.md``). An unlabelled image still
works perfectly well as a sandbox; it simply cannot be told apart afterwards,
so it is left alone and accumulates until its owner removes it by hand.

Every function here takes the Docker client rather than making one. What is
worth testing is which things get chosen, and choosing has nothing to do with
whether a daemon is running.
"""

from typing import Optional

# Carried by every image PartCAD builds, and asked of every image a third party
# builds for it. The value is not read: presence is the whole signal.
LABEL_IMAGE = "partcad.image"

# Carried by every container PartCAD starts. A separate label because an image
# can be labelled by whoever built it while a container is labelled by whoever
# ran it, and only the second is always PartCAD.
LABEL_CONTAINER = "partcad.container"

# Which release an image was built for, where it was built by PartCAD itself.
# Absent on a third-party image, which is deliberate: their versions are their
# own business, and `--stale` should not decide that somebody else's image is
# out of date.
LABEL_VERSION = "partcad.version"


def _labels(thing) -> dict:
    """The labels of an image or a container, however the SDK exposes them."""
    labels = getattr(thing, "labels", None)
    if labels:
        return labels
    attrs = getattr(thing, "attrs", None) or {}
    config = attrs.get("Config") or {}
    return config.get("Labels") or attrs.get("Labels") or {}


def managed_containers(client, stale_only: bool = False) -> list:
    """The containers PartCAD started.

    With ``stale_only``, the ones nothing is using: a sandbox container is
    started once and reused for the life of a context, so a running one is
    almost certainly somebody's work in progress rather than litter.
    """
    found = []
    for container in client.containers.list(all=True):
        if LABEL_CONTAINER not in _labels(container):
            continue
        # Terminal states only. Skipping just "running" left "paused" and
        # "restarting" to be removed with force -- and those are somebody's work
        # in progress as much as a running one is.
        if stale_only and getattr(container, "status", "") not in ("exited", "dead"):
            continue
        found.append(container)
    return found


def managed_images(client, stale_only: bool = False, version: Optional[str] = None) -> list:
    """The images PartCAD built, or that were built for it.

    With ``stale_only``, only those built for a *different* release of PartCAD.
    An image with no version label is never stale: it belongs to somebody else,
    who did not tell us when it goes out of date, and guessing on their behalf
    is how a cleanup command deletes the image somebody is about to use.
    """
    found = []
    for image in client.images.list(all=False):
        labels = _labels(image)
        if LABEL_IMAGE not in labels:
            continue
        if stale_only:
            built_for = labels.get(LABEL_VERSION)
            if not built_for or built_for == version:
                continue
        found.append(image)
    return found


def name_of(thing) -> str:
    """Something to put in a log line, whatever the SDK gave back."""
    tags = getattr(thing, "tags", None)
    if tags:
        return tags[0]
    name = getattr(thing, "name", None)
    if name:
        return name
    return str(getattr(thing, "short_id", None) or getattr(thing, "id", "") or "?")
