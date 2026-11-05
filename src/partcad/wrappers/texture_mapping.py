#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""How an image a colour is drawn with is laid on a surface (see 'cmf_section.Texture').

One way, for everything that draws one - a shaded picture and a video
('raster_scene.py') and the glTF the IDE draws ('wrapper_gltf.py') - so that a
part looks the same in both: **box mapping**, in the part's own frame. Each
triangle of a face is looked at along the axis its face looks along most - X,
Y or Z, from whichever side it faces - and the image is laid on it as it would
be laid on the side of a box seen from there: upright, its top towards +Z (on a
face looking up or down, towards +Y), not mirrored, and repeated every 'width'
by 'height' millimetres of that view, from the origin of the part.

Why that and not the face's own parameters, which OCCT gives every point of a
mesh: a face's parameters are its own business. A plane's run in millimetres
from wherever its origin happens to be, a cylinder's in radians around and
millimetres along, a B-spline's from 0 to 1 whatever its size - so one image
laid by them would be a different size on every face of a part, and turned
differently on two faces that meet at an edge. A box laid on every face from
outside, at one size, is what a CAD tool's appearance does unless told
otherwise, and what makes a wooden panel look like one board.

What it costs is a seam where a curved face turns from looking along one axis
to looking along another, which is where box mapping always shows its seams.

Works on the mesh only, as numpy arrays, so that it needs no kernel and both
callers hand it what they already have.
"""

import numpy as np

# The two coordinates of a point that are the image's right and up, seen from
# each of the six sides, as '(axis, sign) -> ((index, sign), (index, sign))'.
# Seen from +X the right is +Y; from +Y it is -X; from above (+Z), with +Y up
# the view, it is +X - and from the opposite side of each, its opposite.
_VIEWS = {
    (0, 1): ((1, 1.0), (2, 1.0)),
    (0, -1): ((1, -1.0), (2, 1.0)),
    (1, 1): ((0, -1.0), (2, 1.0)),
    (1, -1): ((0, 1.0), (2, 1.0)),
    (2, 1): ((0, 1.0), (1, 1.0)),
    (2, -1): ((0, -1.0), (1, 1.0)),
}


def box_uv(points, corners, width, height):
    """Where each corner of each triangle is on the image, as a (M, 3, 2) array of copies of it.

    'points' is (N, 3), in millimetres, in the frame of the shape the image is
    laid on; 'corners' is (M, 3) indices into it, each triangle wound
    counter-clockwise seen from outside - which is what says which side a
    triangle looks towards. A corner shared by triangles that look along
    different axes is somewhere different on the image for each, which is why
    the answer is per corner of a triangle rather than per point.

    '(u, v)' with 'u' along the image's width and 'v' up its height, a whole
    number of copies of the image apart wherever the image starts again: so
    the image's pixel at a point is at 'frac(u)' across and 'frac(v)' up from
    its bottom (see 'pixel_rows').
    """
    points = np.asarray(points, dtype=np.float64)
    corners = np.asarray(corners, dtype=np.int64)
    if not len(corners):
        return np.zeros((0, 3, 2))
    triangle = points[corners]
    normal = np.cross(triangle[:, 1] - triangle[:, 0], triangle[:, 2] - triangle[:, 0])
    axis = np.argmax(np.abs(normal), axis=1)
    sign = np.where(normal[np.arange(len(normal)), axis] < 0, -1, 1)
    uv = np.zeros((len(corners), 3, 2))
    for (view_axis, view_sign), ((right, right_sign), (up, up_sign)) in _VIEWS.items():
        chosen = (axis == view_axis) & (sign == view_sign)
        if not chosen.any():
            continue
        uv[chosen, :, 0] = triangle[chosen][:, :, right] * (right_sign / float(width))
        uv[chosen, :, 1] = triangle[chosen][:, :, up] * (up_sign / float(height))
    return uv


def gltf_texcoords(uv):
    """'(u, v)' as glTF's TEXCOORD_0: 's' across from the image's left, 't' down from its top.

    glTF starts an image at its top left corner and runs 't' downwards, so 'v'
    up the image is 't' negated - which, with the image repeated, is the same
    pixel as '1 - frac(v)'.
    """
    uv = np.asarray(uv, dtype=np.float64)
    return np.stack([uv[..., 0], -uv[..., 1]], axis=-1)


def pixel_rows(uv, width, height):
    """Where '(u, v)' falls on an image 'width' by 'height' pixels: '(x, y)' in pixels, 'y' down from its top row.

    Continuous, with the centre of the top left pixel at (0.5, 0.5); a sampler
    wraps it around the image.
    """
    uv = np.asarray(uv, dtype=np.float64)
    x = (uv[..., 0] - np.floor(uv[..., 0])) * width
    y = (1.0 - (uv[..., 1] - np.floor(uv[..., 1]))) * height
    return x, y


def sample(image, uv):
    """The colour of 'image' - an (H, W, C) array - at each '(u, v)', blended between its four nearest pixels.

    The image repeats, so the pixels at one edge blend into the ones at the
    other: copies of it laid side by side meet as they would printed.
    """
    image = np.asarray(image)
    rows, columns = image.shape[0], image.shape[1]
    x, y = pixel_rows(uv, columns, rows)
    x -= 0.5
    y -= 0.5
    x0 = np.floor(x)
    y0 = np.floor(y)
    ax = (x - x0)[..., None]
    ay = (y - y0)[..., None]
    x0 = x0.astype(np.int64) % columns
    y0 = y0.astype(np.int64) % rows
    x1 = (x0 + 1) % columns
    y1 = (y0 + 1) % rows
    top = image[y0, x0] * (1.0 - ax) + image[y0, x1] * ax
    bottom = image[y1, x0] * (1.0 - ax) + image[y1, x1] * ax
    return top * (1.0 - ay) + bottom * ay
