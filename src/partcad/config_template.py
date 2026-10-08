#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The names a package configuration may use while it is being rendered.

Defined in 'partcad_utils.config_template', where a client that checks a
'partcad.yaml' without loading PartCAD can reach them too; this is the name the
rest of this package has always imported them by.
"""

from partcad_utils.config_template import (  # noqa: F401
    CAD_CONSTANTS,
    render_context,
    version_at_least,
    version_components,
)
