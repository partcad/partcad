# A 'cam:' implementation, in the shape every one of them has.
#
# It writes what PartCAD told it rather than a program a machine could run: what
# the fixture is for is the plumbing around an implementation - which entry
# point is called, what the request carries, where the file ends up - and a real
# slicer here would only obscure it.

import json


def _describe(request):
    return {
        "shape_name": request.get("shape_name"),
        "manufacturing": request.get("manufacturing"),
        "tool": request.get("tool"),
        "greeting": request.get("greeting"),
    }


def process(path, request):
    with open(path, "w", encoding="utf-8") as f:
        f.write("; instructions\n")
        f.write(json.dumps(_describe(request), sort_keys=True) + "\n")
    return {"success": True}


def process_visual(path, request):
    # A real plugin writes a 3D model here. This one writes the smallest valid
    # ASCII STL there is, because what is being tested is that the second entry
    # point is reached and its file lands where the first one's would not.
    with open(path, "w", encoding="utf-8") as f:
        f.write("solid visual\nendsolid visual\n")
    return {"success": True}
