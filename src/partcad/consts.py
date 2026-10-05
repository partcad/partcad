#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-12-22
#
# Licensed under Apache License, Version 2.0.
#

import math

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

# The constants a CAD file keeps reaching for, by the names a declaration may
# use for them. One table for both places a value in 'partcad.yaml' is computed:
# the Jinja2 template the file is rendered from (see 'config_template'), and the
# '%...%' expressions resolved once an object is asked for (see 'expr'). A name
# that works in '{{ ... }}' and fails in '%...%' is two languages for one file.
#
# A constant is named in upper case, and that is the whole of the convention:
# what is lower case in an expression is a function ('sqrt', 'sin') or one of
# the object's own parameters. So there is no 'pi' or 'e' here, which would be
# a parameter's name as often as a constant's.
CAD_CONSTANTS = {
    "PI": math.pi,
    "M_PI": math.pi,
    "E": math.e,
    "M_E": math.e,
    "SQRT_2": math.sqrt(2),
    "SQRT_3": math.sqrt(3),
    "SQRT_5": math.sqrt(5),
    # Millimetres per imperial unit
    "INCH": 25.4,
    "INCHES": 25.4,
    "FOOT": 304.8,
    "FEET": 304.8,
}
