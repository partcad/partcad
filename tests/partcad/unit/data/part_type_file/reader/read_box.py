#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Read a '.box' file -- three numbers, the box's sizes -- as a part.

It also leaves a mark in the cache directory it is handed, which is how the
test that builds it knows the directory reached it.
"""

import os

CACHE_VERSION = 1

if __name__ == "__partcad_part__":
    from build123d import Box

    with open(request["path"], encoding="utf-8") as f:  # noqa: F821 - injected
        x, y, z = (float(value) for value in f.read().split())
    os.makedirs(request["cache_dir"], exist_ok=True)  # noqa: F821
    with open(os.path.join(request["cache_dir"], "read"), "w", encoding="utf-8") as f:  # noqa: F821
        f.write(request["path"])  # noqa: F821
    output = {"shape": Box(x, y, z).wrapped}
