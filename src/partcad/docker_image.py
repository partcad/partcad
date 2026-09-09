#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The image name PartCAD actually pulls, given the one a package declared.

A package declares one name and gets every architecture its image was built
for. PartCAD appends this machine's architecture to the tag before pulling and
falls back to the bare name when there is no such tag::

    ghcr.io/example/solver:1a2b3c4d5e6f-arm64   # tried first
    ghcr.io/example/solver:1a2b3c4d5e6f         # used if that does not exist

That is a naming convention rather than a manifest list, and deliberately: a
manifest list needs `buildx` and a registry that supports it, and the first
thing a would-be plugin author does is `docker build` and `docker push`. The
suffixes work with that, and a manifest list under the bare name keeps working
too -- it is simply reached through the fallback.

The fallback is also why a bare name is not an error. Somebody experimenting has
one image and one machine, and should not have to read about architectures to
get their first analysis to run; it is the public index that refuses a package
whose image has no suffixed tag, because that is a package that works only where
it was written.
"""

import platform
from typing import Optional

# What the machine's architecture is called in an image tag, keyed by what
# 'platform.machine()' calls it. Docker's own spelling wins wherever they
# differ, because these tags name images and Docker is what pulls them: an
# 'x86_64' host pulls '-amd64', which is what `docker buildx --platform
# linux/amd64` produces.
ARCH_ALIASES = {
    "x86_64": "amd64",
    "amd64": "amd64",
    "aarch64": "arm64",
    "arm64": "arm64",
    "armv7l": "arm",
    "armv6l": "arm",
    "i386": "386",
    "i686": "386",
    "x86": "386",
}


def arch_suffix(machine: Optional[str] = None) -> Optional[str]:
    """The tag suffix for this machine, or None where there is no name for it.

    None rather than a guess: a suffix nobody publishes images under would send
    every pull down the fallback path anyway, and inventing one would make the
    log say an architecture Docker has never heard of.
    """
    if machine is None:
        machine = platform.machine()
    return ARCH_ALIASES.get(machine.lower())


def _split(image: str):
    """An image reference as (name, tag), with tag None when it carries none.

    The tag separator is the last ':' *after* the last '/', which is what keeps
    a registry's port out of it: in 'localhost:5000/pc/solver' the only colon
    belongs to the host, and the reference has no tag at all.
    """
    slash = image.rfind("/")
    colon = image.rfind(":")
    if colon > slash:
        return image[:colon], image[colon + 1 :]
    return image, None


def candidates(image: str, machine: Optional[str] = None) -> list:
    """The names to try, most specific first.

    Always at least the name as declared, so nothing here can make a reference
    unpullable that would otherwise have worked.
    """
    if "@" in image:
        # A digest reference names one image and one architecture already.
        # There is no tag to suffix and nothing to fall back to.
        return [image]

    suffix = arch_suffix(machine)
    if suffix is None:
        return [image]

    name, tag = _split(image)
    # A reference with no tag means ':latest', so that is what gets suffixed --
    # 'ghcr.io/x/y' is tried as 'ghcr.io/x/y:latest-arm64' before 'ghcr.io/x/y'.
    return ["%s:%s-%s" % (name, tag or "latest", suffix), image]
