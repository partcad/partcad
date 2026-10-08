#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Where the bind-mount path rules used to live; they are `partcad_utils.docker_mount` now.

Moved so that a client -- `pc ide open` starting an application's container --
binds directories by the same rules as the sandbox without importing the core.
This name *is* that module (not a copy of its names), so that patching one of
its globals here patches the one every caller reads.
"""

import sys

from partcad_utils import docker_mount as _moved

sys.modules[__name__] = _moved
