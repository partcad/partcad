#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The PartCAD addon for FreeCAD.

The package is split so that only the ``gui`` subpackage and :mod:`importer`
need FreeCAD (or Qt) to import. Everything else -- the JSON-RPC client, the
service provisioning, the package/object model and the parameter model -- is
plain Python and is unit tested without FreeCAD installed.
"""

__version__: str = "0.8.20"
