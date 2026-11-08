#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""How the object is turned in front of the camera: the 'turn' every render shares.

'viewport_origin' and 'viewport_up' say where a picture is looked at from. 'turn'
says how the object stands in front of that camera: turned by '(x, y, z)'
degrees about X, then Y, then Z, each about the fixed axes and through the
middle of the object - the way the Digital Thread's 3D view turns it when
Animate is ticked, which is about Z. So '--view front --turn 0,0,45' is the front
view of the object turned an eighth of a turn, and a video is a 'turn' that
grows by its 'speed' every frame (see 'render_video.py'): any one of its frames
is the picture 'pc render -t png --style shaded' draws with that frame's turn.

An object turned in front of a camera that stands still looks exactly like the
object standing still with the camera turned the other way about it, so a
renderer that only knows a viewport asks 'turned' for the one that draws the
turned object. That is the whole of what the line drawing does with it
('render_svg.py'); the shaded one turns its camera by the same rotation
('raster_scene.Camera.turned').

Plain Python: the projection imports this, and needs nothing else of it.
"""

import math

# The field of a request that holds the turn.
TURN_KEY = "turn"


def turn_of(request, key=TURN_KEY):
    """'(x, y, z)' degrees from the request: three numbers, 'X,Y,Z', or one number for a turn about Z.

    Nought where the request says nothing. Raises ValueError for anything that is
    not one of those.
    """
    value = request.get(key)
    if value is None:
        return (0.0, 0.0, 0.0)
    if isinstance(value, bool):
        raise ValueError("'%s' is three numbers, X, Y and Z, or one, about Z - not %r" % (key, value))
    if isinstance(value, (int, float)):
        value = [0.0, 0.0, value]
    elif isinstance(value, str):
        value = value.replace(",", " ").split()
        if len(value) == 1:
            value = [0.0, 0.0, value[0]]
    try:
        degrees = tuple(float(component) for component in value)
    except (TypeError, ValueError):
        raise ValueError("'%s' is three numbers, X, Y and Z, or one, about Z - not %r" % (key, request.get(key)))
    if len(degrees) != 3 or not all(math.isfinite(component) for component in degrees):
        raise ValueError("'%s' is three numbers, X, Y and Z, or one, about Z - not %r" % (key, request.get(key)))
    return degrees


def rotation(degrees):
    """The turn by '(x, y, z)' degrees as a 3x3 matrix (rows): about X, then Y, then Z, each about the fixed axes."""
    ax, ay, az = (math.radians(float(angle)) for angle in degrees)
    cx, sx, cy, sy, cz, sz = math.cos(ax), math.sin(ax), math.cos(ay), math.sin(ay), math.cos(az), math.sin(az)
    rx = ((1.0, 0.0, 0.0), (0.0, cx, -sx), (0.0, sx, cx))
    ry = ((cy, 0.0, sy), (0.0, 1.0, 0.0), (-sy, 0.0, cy))
    rz = ((cz, -sz, 0.0), (sz, cz, 0.0), (0.0, 0.0, 1.0))
    return _product(rz, _product(ry, rx))


def _product(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def turned(origin, up, degrees):
    """The viewport that draws the object turned by 'degrees' in front of 'origin' and 'up'.

    The camera turned the other way about the object: each vector by the
    transpose of the turn. A turn of nothing hands both back as they are, so a
    picture that asks for none is drawn from exactly the viewport it was before
    there was a turn to ask for.
    """
    if not any(degrees):
        return tuple(origin), tuple(up)
    matrix = rotation(degrees)

    def back(vector):
        return tuple(sum(matrix[k][i] * float(vector[k]) for k in range(3)) for i in range(3))

    return back(origin), back(up)
