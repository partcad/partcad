#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#
"""A minimal "remote" repository endpoint for the 'full' example.

Conceptually this is a remote server; it happens to live in the same package so
the example runs standalone. It exposes a single key/value endpoint:

    GET /data?key=<key>   ->   {"result": <value>}   (or 404 when unknown)

The keys are the ones ``ProjectExternalRepository`` uses:

    objects/<kind>            -> {name: config, ...}
    objects/<kind>/<name>     -> config

The catalog below is tiny and static; a real server would look it up in a
database or a filesystem. Everything here is ordinary Python with no CAD-kernel
dependency, so it can be started on demand and unit-tested directly (see
``test_full_server.py``).
"""

from flask import Flask, jsonify, request

import base64

# The CadQuery scripts the parts are built from. A real server would keep these
# in a database or object store; here they are inline so the example is
# self-contained. They are served (base64-encoded) under the 'files/<path>' key
# and materialized by PartCAD into the package's cache directory.
_CUBE = "import cadquery as cq\nshow_object(cq.Workplane().box(10, 10, 10))\n"
_CYLINDER = "import cadquery as cq\nshow_object(cq.Workplane().cylinder(10, 5))\n"

# The repository's catalog: parts addressable by the generic key space.
PARTS = {
    "cube": {"type": "cadquery", "path": "cube.py", "desc": "A cube"},
    "cylinder": {"type": "cadquery", "path": "cylinder.py", "desc": "A cylinder"},
}

FILES = {
    "cube.py": _CUBE,
    "cylinder.py": _CYLINDER,
}

CATALOG = {
    "objects/part": PARTS,
    **{"objects/part/" + name: config for name, config in PARTS.items()},
    **{"files/" + path: base64.b64encode(text.encode()).decode() for path, text in FILES.items()},
    # No sketches or assemblies in this flat example.
    "objects/sketch": {},
    "objects/assembly": {},
    "deps": [],
}


def lookup(key):
    """Return the value for a key, or None if the key is unknown."""
    return CATALOG.get(key)


def create_app():
    app = Flask(__name__)

    @app.get("/data")
    def data():
        key = request.args.get("key", "")
        value = lookup(key)
        if value is None:
            return jsonify({"error": "unknown key", "key": key}), 404
        return jsonify({"result": value})

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000)
