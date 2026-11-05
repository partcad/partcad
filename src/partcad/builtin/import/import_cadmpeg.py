#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The assembly types cadmpeg reads: a native CAD file's components, placed.

The reader for every format '//builtin/import' reads as an assembly through
cadmpeg -- Fusion 360 and Creo View. cadmpeg converts the file to STEP, product
structure and all, and the tree is read out of that STEP file by the one tree
walk PartCAD has for a STEP assembly ('wrappers/wrapper_import_assy.py'): one
STEP file written per distinct body, and a node per placement of it.

Two things are said to that walk that a STEP file read as itself is not told:

  * what the document *shows* is what is read ('step_visible'): a body its author
    hid is not a part of the assembly;
  * what a body is ('bodies'): a shell or a face that bounds nothing is a body of
    its own and is kept, so that a solid that did not come through whole is a part
    PartCAD fails by name -- the type declares 'requireSolid' -- rather than a part
    that is quietly missing. Sketch curves and points are no part at all. And a
    closed shell is the solid it bounds ('wrapper_common.solidify'), as it is for
    the part types: each part is written out as a STEP file, which PartCAD reads
    as the authority on what it is and never converts, so it is converted here.

What the file called a component is what its node is called, as far as a name
can say it (see 'node_name'); a body that is nothing but a solid of its
component's is called after its place. The joints a document keeps between its
components do not reach STEP, so they are not read: the assembly is the
mechanism at rest, as the document last placed it.

The import contract is 'wrappers/wrapper_import.py's: a file goes in, a tree
of placed parts comes out, each part naming the STEP file it is read from.
"""

import os
import re
import sys
import tempfile

# Siblings are imported by bare name, and the sandbox sets PYTHONSAFEPATH.
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Raise with any change to what this produces (see 'partcad.code_version'),
# which includes every change of the cadmpeg 'cadmpeg_tool' pins.
CACHE_VERSION = 1

# How many digits a placement is rounded to: a micrometre at millimetre scale,
# as the STEP assembly type rounds.
PRECISION = 5

# What OpenCASCADE calls a label nobody named: its entry ('=>[0:1:1:2]'), or the
# kind of shape it is.
_UNNAMED = re.compile(r"=>\[[0-9:]*\]")
_GENERIC = frozenset({"", "unnamed", "compound", "solid", "shell", "face", "cadmpeg_model"})
# What an object name may hold, less the '/' that separates the assembly's name
# from its parts' (see the 'parts' section of the package schema).
_NOT_IN_A_NAME = re.compile(r"[^A-Za-z0-9_.-]+")


def node_name(raw, fallback):
    """A name for a node, out of what the file called it, or 'fallback' when it called it nothing."""
    name = _NOT_IN_A_NAME.sub("_", _UNNAMED.sub("", raw or "")).strip("_.-")
    return fallback if name.lower() in _GENERIC else name


def named(node, fallback):
    """'node' and everything under it, each with a name an object can have."""
    node = dict(node)
    node["name"] = node_name(node.get("name"), fallback)
    children = node.get("children") or []
    if children:
        node["children"] = [
            named(child, "%s_%s%d" % (node["name"], "part" if child["type"] == "part" else "component", index))
            for index, child in enumerate(children, start=1)
        ]
    return node


def with_part_types(node):
    """The flattened tree, each part named after the file it is read from and typed as STEP.

    Named after its file because a part is registered once per name: two
    placements of one body share a file and so are one part, and two bodies a
    file happened to call alike are two files and two parts.
    """
    if node["type"] == "part":
        return {
            **node,
            "name": os.path.splitext(os.path.basename(node["part_file"]))[0],
            "part_type": "step",
        }
    return {**node, "links": [with_part_types(child) for child in node.get("links") or []]}


def bodies(shape):
    """What the parts of an assembly are made of in 'shape': its bodies, a closed shell as its solid."""
    import cadmpeg_step
    import wrapper_common

    return [wrapper_common.solidify(body) for body in cadmpeg_step.bodies(shape)]


def process(_path, request):
    import cadmpeg_step
    import step_visible
    import wrapper_import_assy
    from OCP.gp import gp_Trsf

    source = request["source_file"]
    model_name = node_name(os.path.splitext(os.path.basename(source))[0], "model")
    # Not into the directory the reader is handed: that is the declaring
    # package's own, which for this one is inside the installation.
    with tempfile.TemporaryDirectory(prefix="partcad-cadmpeg-") as tmp:
        step = cadmpeg_step.to_step(source, request["cache_dir"], tmp)
        with step_visible.shown(step) as shown:
            roots = [root for root in wrapper_import_assy.parse_step_tree(shown, bodies=bodies) if root]
    if not roots:
        raise RuntimeError("%s shows no body" % os.path.basename(source))

    # One root, the model itself, as a STEP file has it -- or several, under
    # one of the file's name, as the STEP assembly type does.
    if len(roots) == 1 and roots[0]["type"] == "assembly":
        tree = roots[0]
    else:
        tree = {"type": "assembly", "name": model_name, "trsf": gp_Trsf(), "children": roots}
    tree = named(tree, model_name)

    os.makedirs(request["output_folder"], exist_ok=True)
    root = with_part_types(wrapper_import_assy.flatten(tree, request["output_folder"], PRECISION))
    return {"root": root, "model_name": tree["name"]}
