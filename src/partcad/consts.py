#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-12-22
#
# Licensed under Apache License, Version 2.0.
#

# The constants a CAD file keeps reaching for. They are defined beside the rest
# of what a 'partcad.yaml' template may name, in 'partcad_utils.config_template',
# because a client renders that file too and must not import this package to do
# it; 'expr' reads them from here, as it always has.
from partcad_utils.config_template import CAD_CONSTANTS  # noqa: F401

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
DEVEL_INDEX_REPO_PATHS = (
    "partcad/partcad-index",
    "openvmp/partcad-index",
)

# The branch of the public index that carries what has not been released yet.
# Its 'main' is fast-forwarded to this branch during a release, so 'devel' is
# always either equal to, or ahead of, what a default clone gets.
DEVEL_INDEX_REVISION = "devel"
