#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Where PartCAD finds the OpenSCAD executable to run.

The standalone bundle carries its own OpenSCAD, and that copy is preferred over
anything installed on the host: the point of the bundle is to behave the same
on every machine, while a host OpenSCAD is whatever version happened to be
installed there. Everywhere else -- the wheels, a source checkout -- there is
no bundled copy and this falls back to the host's, exactly as before.

Only the standalone bundles for Linux and Windows carry OpenSCAD; see
`dev-tools/pyinstaller/build.sh` for why macOS does not.
"""

import os
import shutil
import sys

# Where `partcad.spec` puts OpenSCAD inside the bundle, relative to the
# directory holding the frozen interpreter.
#
# Linux ships the contents of the upstream AppImage, whose `AppRun` launcher
# sets up the library paths that its Qt build needs -- the OpenSCAD binary
# beside it is not meant to be run directly. `AppRun` also resolves those paths
# relative to its own location, so it has to be invoked by its real path rather
# than through a symlink placed on PATH.
#
# Windows ships the upstream portable build, which is a single statically
# linked executable with no libraries of its own.
BUNDLED_SUBPATH = ("openscad", "openscad.exe") if os.name == "nt" else ("openscad", "AppRun")


def find_bundled_executable() -> str | None:
    """Return the OpenSCAD shipped inside the standalone bundle, or None.

    Returns None whenever PartCAD is not running from a bundle, and also when
    it is running from a bundle built without OpenSCAD (macOS, or a bundle
    built by hand without staging the payload).
    """
    if not getattr(sys, "frozen", False):
        return None

    # PyInstaller points `sys._MEIPASS` at the directory it unpacked the bundle
    # into, which is where the payload lives.
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if not bundle_dir:
        return None

    path = os.path.join(bundle_dir, *BUNDLED_SUBPATH)
    if os.path.isfile(path) and os.access(path, os.X_OK):
        return path
    return None


def find_executable() -> str | None:
    """Return the OpenSCAD executable to run, or None if there is none."""
    return find_bundled_executable() or shutil.which("openscad")
