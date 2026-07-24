#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#
"""Repository plugin serving a hierarchy of packages from one endpoint.

PartCAD runs this for every data request, with the generic key in
``request["key"]`` and ``__name__`` set to the API ("get"); it returns
``{"result": <value>}``.

The key space is uniform (see ProjectExternalRepository):

    deps                          -> child package names of the top package
    objects/<kind>                -> the top package's objects of that kind
    <subfolder>/deps              -> child names under that subfolder
    <subfolder>/objects/<kind>    -> that subfolder's objects

So a child in 'motors' is served the same way as the top package, just under
the 'motors/' key prefix - which is exactly how PartCAD forwards a child's
requests. The catalog here is static; a real plugin would look it up remotely.
"""

# The top package hosts two sub-packages and a shared supply provider that any
# inner part can be quoted through.
CATALOG = {
    "deps": ["brackets", "motors"],
    "objects/provider": {
        "supplier": {"type": "store", "desc": "Shared supplier for all inner parts"},
    },
    # The 'brackets' sub-package: sketches and parts.
    "brackets/deps": [],
    "brackets/objects/sketch": {
        "outline": {"type": "dxf", "path": "outline.dxf"},
    },
    "brackets/objects/part": {
        "l_bracket": {"type": "cadquery", "path": "l_bracket.py"},
    },
    # The 'motors' sub-package: parts and an assembly.
    "motors/deps": [],
    "motors/objects/part": {
        "shaft": {"type": "cadquery", "path": "shaft.py"},
    },
    "motors/objects/assembly": {
        "gearbox": {"type": "assy", "path": "gearbox.assy"},
    },
}


def handle(request):
    return {"result": CATALOG.get(request["key"])}


if __name__ == "get":
    output = handle(request)  # noqa: F821 - 'request' is injected by the runtime
