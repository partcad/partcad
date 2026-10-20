#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A folder with a '.pcignore' file in it is not part of the package around it.

A package's subfolders are its subpackages when they have a 'partcad.yaml' of
their own, and a workspace's root is the topmost folder of an unbroken chain of
them. Both are worked out from the directory tree alone, which is usually what
is wanted and occasionally exactly wrong: a plugin package keeps its tests in a
'tests/' folder holding packages of their own -- each importing the plugin, as a
user's would -- and those are not the plugin's subpackages. Nor is the plugin
their workspace root, which is what climbing out of 'tests/' would make it.

An empty '.pcignore' in such a folder says so. The folder and everything below
it are left out of the package containing it -- never a subpackage, its files
never part of the package's sources -- and the climb to a workspace root stops
there, so a package inside it is a workspace of its own.

Here rather than in 'partcad', because both ends ask: 'partcad.Context' to
find its root and its subpackages, and 'partcad_utils.workspace' to find which
daemon serves a directory. Two copies of the rule are two copies that can
disagree, and a disagreement is a client starting a second daemon.
"""

import os

IGNORE_FILE = ".pcignore"
PACKAGE_FILE = "partcad.yaml"


def is_ignored(directory: str) -> bool:
    """Whether 'directory' says it is not part of the package around it."""
    return os.path.isfile(os.path.join(directory, IGNORE_FILE))


def is_subpackage(directory: str) -> bool:
    """Whether 'directory', a subfolder of a package, is one of its subpackages."""
    return os.path.isfile(os.path.join(directory, PACKAGE_FILE)) and not is_ignored(directory)


def climbs_to_parent(directory: str) -> bool:
    """Whether the workspace root search goes on from 'directory' to its parent.

    It does while the parent is a package and 'directory' is not a folder that
    package ignores.
    """
    return os.path.exists(os.path.join(directory, "..", PACKAGE_FILE)) and not is_ignored(directory)
