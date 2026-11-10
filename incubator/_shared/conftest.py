#
# PartCAD distributor plugins, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Puts PartCAD's plugin toolkit, 'plugin_models', where the plugin's sandbox has it.

A plugin runs in a sandbox that has PartCAD's wrappers on its path, and imports
'plugin_models' from there. The tests do the same: from $PARTCAD_WRAPPERS when
it is set, else from the 'partcad' that is installed ('pip install --no-deps
partcad' is enough: only the file is needed), else from a PartCAD checkout -
the one this package is incubated in, or one beside it.
"""

import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def _wrappers():
    said = os.environ.get("PARTCAD_WRAPPERS")
    if said:
        return said
    try:
        spec = importlib.util.find_spec("partcad")
    except (ImportError, ValueError):
        spec = None
    if spec is not None and spec.origin:
        return os.path.join(os.path.dirname(spec.origin), "wrappers")
    # A PartCAD checkout: the one this package is incubated in, or one beside this checkout.
    for checkout in (os.path.join(_HERE, os.pardir, os.pardir), os.path.join(_HERE, os.pardir, "partcad")):
        wrappers = os.path.join(checkout, "src", "partcad", "wrappers")
        if os.path.exists(os.path.join(wrappers, "plugin_models.py")):
            return wrappers
    return os.path.join(_HERE, os.pardir, os.pardir, "src", "partcad", "wrappers")


_PATH = os.path.abspath(_wrappers())
if not os.path.exists(os.path.join(_PATH, "plugin_models.py")):
    raise RuntimeError("PartCAD's plugin_models.py is not in %s: install partcad, or set PARTCAD_WRAPPERS" % _PATH)
if _PATH not in sys.path:
    sys.path.insert(0, _PATH)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
