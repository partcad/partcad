#
# OpenVMP, 2023
#
# Author: PartCAD Inc. <support@partcad.org>
# Created: 2023-12-30
#
# Licensed under Apache License, Version 2.0.
#

import os


def get(filename):
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "wrappers",
        "wrapper_" + filename,
    )
