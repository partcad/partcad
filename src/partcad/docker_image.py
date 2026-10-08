#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Where the image-name convention used to live; it is `partcad_utils.docker_image` now.

Moved beside `partcad_utils.containers`, which is the one place that pulls an
image, so that a client can resolve one without importing the core. Re-exported
here for everything that imported it from here.
"""

from partcad_utils.docker_image import ARCH_ALIASES, arch_suffix, candidates

__all__ = ["ARCH_ALIASES", "arch_suffix", "candidates"]
