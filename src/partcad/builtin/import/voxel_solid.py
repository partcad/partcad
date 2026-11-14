#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Voxels as solids: a grid of filled cells, made into the solids they are, one or more per label.

What the 'voxels' part type makes of a MagicaVoxel model, a binvox file or a
NumPy array, and the 'pointcloud' part type of the cells its points fall in. A
voxel is a box, so this is exact: the solids are the union of the boxes, and
nothing is approximated.

A cell holds a label - 0 for empty, anything else for what fills it: a palette
index, a material, a segment of a scan. Each label is built on its own:

  * its cells are taken greedily into as few boxes as the grid allows - each
    box as long as it can be along the grid's last axis, then as wide, then as
    tall - so that a solid run of cells is one box and not a thousand;
  * the boxes are fused with OpenCASCADE's glue option, which is made for
    shapes that only touch, faces against faces, and is far quicker than a
    general fuse for them; and the faces left in one plane are merged.

Two labels touching stay two solids, face against face, so that each keeps
what it is painted in and a print of several materials has a body per material.
Cells of one label that touch only along an edge or at a corner are two solids
of that label: one solid that met itself along an edge would not be one OCCT
calls valid.

Nothing here reads a file. It is shared by the scripts that do, and imports
OCP only to build.
"""

import numpy

# The most boxes one part may be built of unless it says otherwise: a fuse of
# this many boxes takes a minute, and a model of more is one to coarsen first.
DEFAULT_MAX_BOXES = 50000


def boxes(labels):
    """'[(label, (i0, j0, k0), (i1, j1, k1)), ...]': the filled cells of 'labels' taken into boxes, ends exclusive.

    Every box holds cells of one label only, and every filled cell is in
    exactly one box. Greedy, in the grid's own order: a box starts at the
    first cell no box holds yet and grows along the last axis, then the middle
    one, then the first, for as long as every cell it would take is of its
    label and free.
    """
    labels = numpy.asarray(labels)
    if labels.ndim != 3:
        raise ValueError("voxels are a three-dimensional grid, and this one has %d dimensions" % labels.ndim)
    nx, ny, nz = labels.shape
    taken = labels == 0
    found = []
    for i, j, k in numpy.argwhere(~taken):
        if taken[i, j, k]:
            continue
        label = labels[i, j, k]
        k1 = k + 1
        while k1 < nz and not taken[i, j, k1] and labels[i, j, k1] == label:
            k1 += 1
        j1 = j + 1
        while j1 < ny and not taken[i, j1, k:k1].any() and (labels[i, j1, k:k1] == label).all():
            j1 += 1
        i1 = i + 1
        while i1 < nx and not taken[i1, j:j1, k:k1].any() and (labels[i1, j:j1, k:k1] == label).all():
            i1 += 1
        taken[i:i1, j:j1, k:k1] = True
        found.append((label.item(), (int(i), int(j), int(k)), (int(i1), int(j1), int(k1))))
    return found


def solids(labels, size, origin=(0.0, 0.0, 0.0), max_boxes=DEFAULT_MAX_BOXES):
    """'(shape, per_solid, per_face)': the solids of the filled cells, and the label of each solid and each face.

    Both lists in TopExp order, as a part type's 'output["cmf"]' states them.

    'size' is a cell's size in mm along X, Y and Z (or one number for all
    three), and 'origin' where the grid's corner is. The shape is one solid
    when that is all there is, and a compound of them otherwise.
    """
    from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID
    from OCP.TopExp import TopExp, TopExp_Explorer
    from OCP.TopTools import TopTools_IndexedMapOfShape

    import ocp_serialize

    sx, sy, sz = (float(size),) * 3 if numpy.isscalar(size) else tuple(float(v) for v in size)
    if not (sx > 0.0 and sy > 0.0 and sz > 0.0):
        raise ValueError("a voxel is larger than nothing, and this one is %s x %s x %s mm" % (sx, sy, sz))
    found = boxes(labels)
    if not found:
        raise ValueError("there is not one filled voxel in it")
    if len(found) > max_boxes:
        raise ValueError(
            "its voxels take %d boxes, more than %d: coarsen it, or raise 'maxBoxes'" % (len(found), max_boxes)
        )
    by_label = {}
    for label, low, high in found:
        by_label.setdefault(label, []).append((low, high))
    made, labelled = [], []
    for label in sorted(by_label):
        for piece in _fused([_box(low, high, (sx, sy, sz), origin) for low, high in by_label[label]]):
            made.append(piece)
            labelled.append(label)
    shape = made[0] if len(made) == 1 else ocp_serialize.compound_of(made)
    # Each solid's label, in the order a reader of the shape meets them.
    order = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_SOLID, order)
    faces = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, faces)
    per_solid, per_face = [None] * order.Extent(), [None] * faces.Extent()
    for piece, label in zip(made, labelled):
        index = order.FindIndex(piece)
        if index > 0:
            per_solid[index - 1] = label
        # And each face of it: what a picture is drawn by.
        explorer = TopExp_Explorer(piece, TopAbs_FACE)
        while explorer.More():
            found = faces.FindIndex(explorer.Current())
            if found > 0:
                per_face[found - 1] = label
            explorer.Next()
    return shape, per_solid, per_face


def _box(low, high, size, origin):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt

    return BRepPrimAPI_MakeBox(
        gp_Pnt(*(origin[a] + low[a] * size[a] for a in range(3))),
        gp_Pnt(*(origin[a] + high[a] * size[a] for a in range(3))),
    ).Shape()


def _fused(pieces):
    """The solids of the union of boxes that touch and do not overlap."""
    from OCP.BOPAlgo import BOPAlgo_GlueEnum
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
    from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopTools import TopTools_ListOfShape

    if len(pieces) == 1:
        return pieces
    arguments, tools = TopTools_ListOfShape(), TopTools_ListOfShape()
    arguments.Append(pieces[0])
    for piece in pieces[1:]:
        tools.Append(piece)
    fuse = BRepAlgoAPI_Fuse()
    fuse.SetArguments(arguments)
    fuse.SetTools(tools)
    fuse.SetGlue(BOPAlgo_GlueEnum.BOPAlgo_GlueShift)
    fuse.SetRunParallel(True)
    fuse.Build()
    if not fuse.IsDone():
        raise RuntimeError("OpenCASCADE could not join the voxels' boxes")
    unify = ShapeUpgrade_UnifySameDomain(fuse.Shape(), True, True, True)
    unify.Build()
    result = []
    explorer = TopExp_Explorer(unify.Shape(), TopAbs_SOLID)
    while explorer.More():
        result.append(explorer.Current())
        explorer.Next()
    return result


# A label with no colour of its own is drawn in one of these, by its number:
# twelve hues far enough apart to tell the segments of a scan apart.
PALETTE = [
    (31, 119, 180),
    (255, 127, 14),
    (44, 160, 44),
    (214, 39, 40),
    (148, 103, 189),
    (140, 86, 75),
    (227, 119, 194),
    (127, 127, 127),
    (188, 189, 34),
    (23, 190, 207),
    (174, 199, 232),
    (255, 187, 120),
]


def cmf(per_solid, per_face, colours=None, convention="partcad", named=True):
    """The part's 'output["cmf"]': each solid and each face of it named by its label, in the colour 'colours' gives it.

    Said of the faces as well as of the solids: a picture is drawn face by face.

    'colours' maps a label to '(r, g, b, a)', 0-255 each; a label it does not
    have is drawn in PALETTE. None where a part has one label and no colour of
    its own: there is nothing to say then that its own colour does not. A label
    that is no name anybody would claim - a colour a scan's points were averaged
    to - is named by its colour instead ('named' false), '#RRGGBB', as a mesh's
    colours are: a set with no name says nothing, and is dropped.
    """
    present = sorted({label for label in per_solid if label is not None})
    if not colours and len(present) <= 1:
        return None

    def stated(label):
        if label is None:
            return None
        rgba = (colours or {}).get(label)
        if rgba is None:
            r, g, b = PALETTE[(int(label) - 1) % len(PALETTE)]
            rgba = (r, g, b, 255)
        return {
            "color": str(label) if named else "#%02X%02X%02X" % tuple(int(c) for c in rgba[:3]),
            "rgba": [int(rgba[0]), int(rgba[1]), int(rgba[2]), rgba[3] / 255.0],
        }

    return {
        "convention": convention,
        "solids": [stated(label) for label in per_solid],
        "faces": [stated(label) for label in per_face],
    }
