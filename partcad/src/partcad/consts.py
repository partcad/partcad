#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-12-22
#
# Licensed under Apache License, Version 2.0.
#

# The alias of the current package: the one Context object was initialized with.
CURRENT = "."

# The top level package: the top-most found by Context while traversing '..'.
ROOT = "//"

# Which file to look for if the directory name is passed instead of the config
# filename.
DEFAULT_PACKAGE_CONFIG = "partcad.yaml"

# The public PartCAD index (the "pub" dependency) lives in a repository of its
# own. Both the path it has now and the one it moved from are listed: packages
# published before the move still import it under the old organization, and
# GitHub keeps serving that spelling.
PUB_INDEX_REPO_PATHS = (
    "partcad/partcad-index",
    "openvmp/partcad-index",
)

# The branch of the public index that carries what has not been released yet.
# Its 'main' is fast-forwarded to this branch during a release, so 'devel' is
# always either equal to, or ahead of, what a default clone gets.
PUB_INDEX_DEVEL_REVISION = "devel"
