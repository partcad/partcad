#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Make PartCAD's sandbox helpers importable, as they are when PartCAD runs the script.

The analysis scripts import `cae_support`, which lives beside PartCAD's
meta-wrapper and is on `sys.path` whenever PartCAD runs an implementation. Under
pytest nothing put it there, so this does -- from the `partcad` installed beside
the tests, or from `$PARTCAD_WRAPPERS`, or from a PartCAD checkout beside this
package's own. A `partcad` too old to have it skips the tests that need it
rather than failing them.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _wrappers():
    named = os.environ.get("PARTCAD_WRAPPERS")
    if named:
        yield named
    try:
        import partcad

        yield os.path.join(os.path.dirname(partcad.__file__), "wrappers")
    except ImportError:
        pass
    # Incubated in partcad/partcad, or checked out beside it.
    for up in ("../../src/partcad/wrappers", "../partcad/src/partcad/wrappers"):
        yield os.path.normpath(os.path.join(HERE, up))


for candidate in _wrappers():
    if os.path.isfile(os.path.join(candidate, "cae_support.py")):
        sys.path.append(candidate)
        break

sys.path.insert(0, HERE)
