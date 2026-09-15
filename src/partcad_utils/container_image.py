#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The tag PartCAD's own container images are pulled and published under.

A few images belong to PartCAD rather than to a package -- the Python sandbox
base images, and the KiCad sandbox -- and every one of them is addressed by the
release that built it: ``<name>:<release>``, plus the architecture suffix
``docker_image.candidates`` appends where there is one. That is what an
installed PartCAD pulls, and it is what this returns when nothing says
otherwise.

CI needs one other answer. A change to ``tools/containers`` builds images that
are not the release's, and the tests in that same run have to reach *those*
rather than the ones the last release published -- otherwise a Dockerfile fix
cannot be proven and a Dockerfile regression cannot be caught until after it
lands. Such a run builds ``<release>-<branch>-<digest>-<commit>`` and exports
``PC_CONTAINER_IMAGE_TAG``.

A fork needs one more. It cannot publish into ``partcad``, so a fork that
builds images of its own publishes them under its own owner -- and a run there
that went on pulling ``ghcr.io/partcad/...`` would test the upstream release's
images while reporting on its own. ``PC_CONTAINER_IMAGE_OWNER`` redirects the
owner the way the tag above redirects the tag; see `image_name`.

Read out of the environment, and that is deliberately the whole of the mechanism
on this side. The alternative -- asking here whether this is CI, on what branch,
and whether that branch is ``devel`` -- would put a build system's facts inside
a library that mostly runs on somebody's laptop, where those questions have no
answers and a wrong one means ``pc open --with kicad`` quietly starting an
unreviewed branch's image. The run that knows the answer decides; this obeys.
Which also makes it one variable to set in a test, rather than a CI environment
to simulate.
"""

import os

# The variable CI exports when the images under test are not the release's. It
# is unset everywhere else, and nothing but CI is expected to set it.
ENV_VAR = "PC_CONTAINER_IMAGE_TAG"


def image_tag(release: str) -> str:
    """The tag to address PartCAD's own images by, given this release.

    Empty or blank is treated as unset rather than as a tag. An exported
    variable that arrived empty is a CI expression that evaluated to nothing,
    and a reference ending in ``:`` is one no registry can resolve -- so the
    failure would be a pull error somewhere far from the empty expression.
    """
    override = (os.environ.get(ENV_VAR) or "").strip()
    return override or release


# The variable CI exports when the images under test are not in PartCAD's own
# namespace: a fork that built and published its own. Unset everywhere else,
# and like the tag above, nothing but CI is expected to set it.
ENV_VAR_OWNER = "PC_CONTAINER_IMAGE_OWNER"

# The owner PartCAD's own images are published under, and the only one
# `image_name` will redirect away from. A declaration may name any image at all
# -- `//builtin/open` is data, and a user may add a tool of their own with a
# tool of their own to run it in -- and rewriting the owner of somebody else's
# image would point a run at a repository that has nothing to do with it.
PARTCAD_OWNER = "partcad"


def image_name(default: str) -> str:
    """The image to address, given the name PartCAD ships with.

    These references are ``<registry>/<owner>/<name>``, and only the owner is
    replaceable. The registry and the image's own name are what the Dockerfile,
    the build script and every reader already agree on; the owner is the one
    part that says *whose copy* this run is about.

    A fork cannot publish into ``partcad``, so a fork that builds images of its
    own publishes them under its own owner and nowhere else. Without this, such
    a run builds its images, pushes them, and then has every test pull
    ``ghcr.io/partcad/...`` -- the upstream release's -- so the images it just
    built go untested exactly as they do on a fork's pull request. That is the
    failure ``PC_CONTAINER_IMAGE_TAG`` exists to prevent, one level up.

    Lowercased, because a GitHub login may hold capitals and a registry path
    may not: ``ghcr.io/SeekBirdy/...`` is refused at the push with an error
    about the name, not about the case.

    Empty or blank is treated as unset, for the reason given on `image_tag`. So
    is a name this cannot parse -- fewer than three segments is not one of
    PartCAD's images, and rewriting a segment of it would invent a reference
    rather than redirect one.

    And so is an image belonging to anyone but `PARTCAD_OWNER`. This redirects
    PartCAD's own images at the copy this run built, and that is the whole of
    its domain: `//builtin/open` is data, a user may declare a tool of their own
    with an image of their own, and moving *that* to a fork's namespace would
    point the run at a repository with nothing to do with it.
    """
    owner = (os.environ.get(ENV_VAR_OWNER) or "").strip().lower()
    if not owner:
        return default
    parts = default.split("/")
    if len(parts) != 3 or parts[1] != PARTCAD_OWNER:
        return default
    parts[1] = owner
    return "/".join(parts)
