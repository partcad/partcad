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
lands. Such a run builds ``<release>-<branch>-<commit>`` and exports
``PC_CONTAINER_IMAGE_TAG``.

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
