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

import base64

# The CadQuery scripts the parts are built from, served (base64-encoded) under
# 'files/<path>' and materialized by PartCAD. Inline so the example is
# self-contained.
_SCRIPTS = {
    "brackets/l_bracket.py": "import cadquery as cq\nshow_object(cq.Workplane().box(20, 20, 4))\n",
    "motors/shaft.py": "import cadquery as cq\nshow_object(cq.Workplane().cylinder(30, 3))\n",
}

# The top package hosts two sub-packages ('brackets' and 'motors'). Each is a
# child external package, served under its own key prefix - which is how PartCAD
# forwards a child's requests. The catalog is static; a real plugin would look
# it up remotely.
CATALOG = {
    "deps": ["brackets", "motors"],
    # The 'brackets' sub-package.
    "brackets/deps": [],
    "brackets/objects/part": {
        "l_bracket": {"type": "cadquery", "path": "l_bracket.py"},
    },
    # The 'motors' sub-package.
    "motors/deps": [],
    "motors/objects/part": {
        "shaft": {"type": "cadquery", "path": "shaft.py"},
    },
    # File contents, keyed the way a child forwards them ('<subfolder>/files/...').
    **{"brackets/files/l_bracket.py": base64.b64encode(_SCRIPTS["brackets/l_bracket.py"].encode()).decode()},
    **{"motors/files/shaft.py": base64.b64encode(_SCRIPTS["motors/shaft.py"].encode()).decode()},
}


def handle(request):
    return {"result": CATALOG.get(request["key"])}


if __name__ == "get":
    output = handle(request)  # noqa: F821 - 'request' is injected by the runtime
