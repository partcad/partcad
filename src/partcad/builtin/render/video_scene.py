#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The Digital Thread's 3D view, drawn on the CPU: what a video of an object is made of.

'render_video.py' writes a video of an object turning, and what a reader expects
it to look like is what they already see in the IDE: the 3D tab of the Digital
Thread with Animate ticked. That view is three.js in a webview
('ide/vscode/src/webview/scene.ts'), which a sandbox has no browser to run, so
this module draws the same picture again with numpy:

  * the camera - a perspective one, 50 degrees from top to bottom, looking at
    the middle of the object from 'VIEW_DIRECTION' and backed off until the
    object fits the frame ('fit_distance' is 'scene.ts''s 'fitDistance');
  * the material - three's MeshPhongMaterial with its defaults, both sides
    drawn, in the colour each part states and goldenrod where it states none
    (see 'appearance.py', which every drawing PartCAD makes shares);
  * the light - the rig 'scene.ts' sets up, light for light: the room's light
    as nine spherical harmonics ('ROOM_LIGHT'), the ambient, spot and point
    lights of drei's <Stage>, and Part.js's hemisphere and point lights, every
    one of them placed from the size of the object and with no falloff;
  * the colour - Khronos' PBR Neutral tone mapping, then sRGB, which is what
    the WebGL renderer writes to its canvas;
  * the lines - an edge that bounds no face (a sketch of open lines, the bend
    lines of a sheet metal blank) unlit, in the deeper shade of its colour that
    'appearance.ts''s 'edgeColor' picks.

Animate turns the camera around the model, about the vertical, with the lights
standing still around the model. Turning the model and everything lighting it
about the opposite axis, in front of a camera that stands still, draws the same
picture, and is what is done here: everything is lit once, in the model's own
frame ('Scene'), and each frame only moves the camera around it ('Camera.turned').
That is also what makes a turn about any axis, not only the vertical, a matter
of handing 'draw' another rotation.

What is drawn differently, and why:

  * The shading is worked out at the corners of each triangle and blended across
    it, where the GPU works it out at every pixel. Nearly all of the light here is
    a function of the surface's direction alone - the room, the hemisphere, the
    ambient light - and a face's direction is exact at its corners, so it is the
    positional lights that are blended, and they stand two to four times the
    object's size away. The difference is a percent or so of the brightness of a
    large flat face, and it costs a frame a fraction of what shading every pixel
    does.
  * See-through parts are blended over what is behind them one layer deep,
    rather than sorted and blended object by object as three does.
  * Edges are anti-aliased by drawing the whole frame larger and shrinking it
    ('supersample'), where the GPU samples each pixel several times.

Nothing here imports PartCAD: it runs in the render sandbox, beside the
implementation that calls it, and reaches OCP only to tessellate.
"""

import colorsys
import math

import numpy as np

# The camera of 'scene.ts': 'new THREE.PerspectiveCamera(50, ...)'. The field of
# view is the vertical one, in degrees.
FOV = 50.0

# Which way the camera looks at the model from: Stage's default, slightly above
# ('VIEW_DIRECTION' in 'scene.ts'). That one is written in glTF's frame, which is
# Y up; PartCAD's is Z up, and glTF's (x, y, z) is PartCAD's (x, -z, y).
VIEW_DIRECTION = (0.6, -0.8, 0.5)

# How far back the camera stands, in radii of the object, before the field of view
# is taken into account ('fitDistance' in 'scene.ts').
FIT = 1.6

# Which way is up on the screen: PartCAD's Z, which is glTF's Y.
UP = (0.0, 0.0, 1.0)

# '<Stage intensity={0.5}>', which scales the lights of drei's rig.
STAGE_INTENSITY = 0.5

# The diffuse light of three's RoomEnvironment as the coefficients of a
# 'SphericalHarmonics3', one number per band because the room is white: the
# 'ROOM_LIGHT' of 'scene.ts', which says how they were worked out. Evaluated in
# glTF's frame, which they were worked out in (see '_room').
ROOM_LIGHT = (3.78, 1.73, 1.59, 0.26, 0.19, 1.03, 1.19, -0.34, -0.63)

# MeshPhongMaterial's defaults: a specular colour of #111111 and a shininess of 30.
SHININESS = 30.0

# The goldenrod a shape that states no colour is drawn in, and the deeper shade
# its lines are drawn in. The twins of 'appearance.DEFAULT_COLOR' and of
# 'DEFAULT_EDGE_COLOR' in 'appearance.ts'.
DEFAULT_COLOR = (0xDA, 0xA5, 0x20)
DEFAULT_EDGE_COLOR = (0xB8, 0x86, 0x0B)

# The tessellation a frame gets, as a budget in pixels of the frame: a facet may
# be out by this much of one before it shows. The same half pixel the IDE's
# preview is tessellated to ('shape_gltf.PIXEL_BUDGET'), of the frame actually
# being drawn rather than of a nominal one, and the same angular cap.
PIXEL_BUDGET = 0.5
ANGULAR_TOLERANCE = 0.4
MIN_TOLERANCE = 0.001
MAX_TOLERANCE = 10.0

# The longest edge a triangle is drawn with, as a fraction of the object's
# radius. The shading is worked out at the corners of a triangle and blended
# across it, and the lights near enough to vary across a face stand a few radii
# away, so a flat face tessellated as two triangles - which is what OCCT makes
# of a rectangle - showed the diagonal between them as a crease in the light.
# Split until no edge is longer than this, the blend is within a hair of the
# light a GPU works out per pixel.
MAX_EDGE = 0.25

# How many candidate pixels the rasterizer works on at once. Bounds the memory a
# frame takes - about a hundred bytes per candidate - whatever is being drawn.
CHUNK = 1 << 20

# How much nearer than a face a line has to be to be drawn over it, as a fraction
# of the distance to the camera: a line lying on a face is exactly as far as the
# face is, and without this which of the two wins is a toss of the rounding.
LINE_BIAS = 1e-3


# ---------------------------------------------------------------------------
# Colour
# ---------------------------------------------------------------------------


def srgb_to_linear(channel):
    """An sRGB channel from 0 to 1 as the linear value three works with."""
    channel = np.asarray(channel, dtype=np.float64)
    return np.where(channel <= 0.04045, channel / 12.92, ((channel + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(channel):
    """The inverse of 'srgb_to_linear': what the canvas is written in."""
    channel = np.clip(np.asarray(channel, dtype=np.float64), 0.0, 1.0)
    return np.where(channel <= 0.0031308, channel * 12.92, 1.055 * channel ** (1 / 2.4) - 0.055)


# A linear value to the sRGB byte it is written as, by table: one lookup per
# channel of every pixel of every frame is the whole of the colour conversion.
_LUT_SIZE = 4096
_SRGB_LUT = np.round(linear_to_srgb(np.linspace(0.0, 1.0, _LUT_SIZE)) * 255.0).astype(np.uint8)


def to_bytes(linear):
    """Linear colours, any shape ending in 3, as sRGB bytes."""
    index = np.clip(linear * (_LUT_SIZE - 1) + 0.5, 0, _LUT_SIZE - 1).astype(np.int32)
    return _SRGB_LUT[index]


def neutral_tone_mapping(color):
    """Khronos' PBR Neutral, as three's 'NeutralToneMapping' writes it, on rows of RGB.

    Below the highlights it leaves a colour alone, which is why the view uses it:
    a face the light falls on squarely comes out as the colour that was asked for.
    """
    color = np.array(color, dtype=np.float64, copy=True)
    start = 0.8 - 0.04
    desaturation = 0.15
    low = np.min(color, axis=-1, keepdims=True)
    offset = np.where(low < 0.08, low - 6.25 * low * low, 0.04)
    color -= offset
    peak = np.max(color, axis=-1, keepdims=True)
    d = 1.0 - start
    safe_peak = np.maximum(peak, 1e-9)
    new_peak = 1.0 - d * d / (safe_peak + d - start)
    compressed = color * (new_peak / safe_peak)
    g = 1.0 - 1.0 / (desaturation * (safe_peak - new_peak) + 1.0)
    compressed = compressed * (1.0 - g) + new_peak * g
    return np.where(peak < start, color, compressed)


def parse_color(text):
    """'#RRGGBB' or '#RRGGBBAA' as ((red, green, blue), alpha), channels 0-255; None if it is not one."""
    if not isinstance(text, str):
        return None
    digits = text.strip().lstrip("#")
    if len(digits) not in (6, 8):
        return None
    try:
        channels = [int(digits[i : i + 2], 16) for i in range(0, len(digits), 2)]
    except ValueError:
        return None
    alpha = channels[3] / 255.0 if len(channels) == 4 else 1.0
    return tuple(channels[:3]), alpha


def edge_color(rgb):
    """The colour a line across a shape of colour 'rgb' is drawn in ('edgeColor' in 'appearance.ts').

    The default colour has a name for its deeper shade, and gets it. Any other is
    darkened by a quarter of its lightness, unless it is already dark, where it is
    lightened instead. In sRGB, as there.
    """
    if tuple(rgb) == DEFAULT_COLOR:
        return DEFAULT_EDGE_COLOR
    hue, lightness, saturation = colorsys.rgb_to_hls(*(channel / 255.0 for channel in rgb))
    lightness = lightness * 0.75 if lightness > 0.3 else lightness + 0.3
    return tuple(int(round(channel * 255.0)) for channel in colorsys.hls_to_rgb(hue, lightness, saturation))


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def tolerance_for(diagonal, pixels):
    """The linear deflection to tessellate an object 'diagonal' across for a frame 'pixels' across."""
    if not diagonal or diagonal <= 0:
        return 0.1
    return min(max(diagonal * PIXEL_BUDGET / max(pixels, 1), MIN_TOLERANCE), MAX_TOLERANCE)


def bounding_box(shape):
    """'(low, high)' corners of 'shape', or None for a shape with nothing in it."""
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box, False)
    if box.IsVoid():
        return None
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    return np.array([xmin, ymin, zmin]), np.array([xmax, ymax, zmax])


def _matrix(location):
    """A 'TopLoc_Location' as a 3x4 numpy matrix: rotation then translation."""
    trsf = location.Transformation()
    return np.array([[trsf.Value(row, column) for column in range(1, 5)] for row in range(1, 4)])


def triangles(shape, tolerance, angular_tolerance=ANGULAR_TOLERANCE):
    """Every face of 'shape' as triangles: '(points, normals, corners)'.

    'points' and 'normals' are (N, 3) arrays, a normal at every point pointing
    out of the material (a reversed face has its own turned round), and 'corners'
    is (M, 3) indices into them, wound counter-clockwise seen from outside. Each
    face keeps its own points, so the normals of two faces meeting at an edge do
    not blend - a box has sharp edges, as it does in the IDE, where every face of
    the glTF is a primitive of its own.
    """
    from OCP.BRep import BRep_Tool
    from OCP.BRepLib import BRepLib_ToolTriangulatedShape
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS

    BRepMesh_IncrementalMesh(shape, tolerance, False, angular_tolerance, True)

    points, normals, corners = [], [], []
    offset = 0
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        explorer.Next()
        location = TopLoc_Location()
        poly = BRep_Tool.Triangulation_s(face, location)
        if poly is None or poly.NbTriangles() == 0:
            continue
        if not poly.HasNormals():
            BRepLib_ToolTriangulatedShape.ComputeNormals_s(face, poly)
        count = poly.NbNodes()
        nodes = np.array([(p.X(), p.Y(), p.Z()) for p in (poly.Node(i) for i in range(1, count + 1))])
        directions = np.array([(d.X(), d.Y(), d.Z()) for d in (poly.Normal(i) for i in range(1, count + 1))])
        indices = np.array([poly.Triangle(i).Get() for i in range(1, poly.NbTriangles() + 1)], dtype=np.int64) - 1
        if not location.IsIdentity():
            matrix = _matrix(location)
            nodes = nodes @ matrix[:, :3].T + matrix[:, 3]
            directions = directions @ matrix[:, :3].T
        if face.Orientation() == TopAbs_REVERSED:
            directions = -directions
            indices = indices[:, [0, 2, 1]]
        points.append(nodes)
        normals.append(directions)
        corners.append(indices + offset)
        offset += count

    if not points:
        return np.zeros((0, 3)), np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64)
    normals = np.concatenate(normals)
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    normals = normals / np.where(lengths > 0, lengths, 1.0)
    return np.concatenate(points), normals, np.concatenate(corners)


def refine(points, normals, corners, longest):
    """The triangles split in four, again and again, until no edge is longer than 'longest'.

    Each triangle split is split at the middle of all three of its edges, so a
    neighbour sharing its longest edge - which is as long for both - is split at
    the same point, and the two still meet. The new points' normals are their
    edges' ends' normals blended, as the surface's are between them.
    """
    for _ in range(12):
        a, b, c = points[corners[:, 0]], points[corners[:, 1]], points[corners[:, 2]]
        edge = np.maximum(
            np.maximum(np.linalg.norm(b - a, axis=1), np.linalg.norm(c - b, axis=1)), np.linalg.norm(a - c, axis=1)
        )
        split = edge > longest
        if not split.any():
            break
        chosen = corners[split]
        count = len(chosen)
        first = len(points)
        # The middles of each split triangle's three edges: ab, bc and ca.
        middle_points, middle_normals = [], []
        for i, j in ((0, 1), (1, 2), (2, 0)):
            middle_points.append((points[chosen[:, i]] + points[chosen[:, j]]) / 2.0)
            blended = normals[chosen[:, i]] + normals[chosen[:, j]]
            length = np.linalg.norm(blended, axis=1, keepdims=True)
            middle_normals.append(
                np.where(length > 1e-12, blended / np.where(length > 1e-12, length, 1.0), normals[chosen[:, i]])
            )
        points = np.concatenate([points] + middle_points)
        normals = np.concatenate([normals] + middle_normals)
        ab = np.arange(count) + first
        bc = ab + count
        ca = bc + count
        p, q, r = chosen[:, 0], chosen[:, 1], chosen[:, 2]
        corners = np.concatenate(
            [
                corners[~split],
                np.stack([p, ab, ca], axis=1),
                np.stack([ab, q, bc], axis=1),
                np.stack([ca, bc, r], axis=1),
                np.stack([ab, bc, ca], axis=1),
            ]
        )
    return points, normals, corners


def free_edges(shape, tolerance, angular_tolerance=ANGULAR_TOLERANCE):
    """The edges of 'shape' that bound no face, as line segments: an (K, 2, 3) array.

    What a sketch of open lines is made of, and what the IDE draws as lines; the
    edges of a face are not among them, since the face already draws its outline
    (see 'wrapper_gltf._free_edges', which the IDE's copy comes from).
    """
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GCPnts import GCPnts_TangentialDeflection
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape

    ancestors = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, ancestors)
    segments = []
    for index in range(1, ancestors.Extent() + 1):
        if ancestors.FindFromIndex(index).Size() > 0:
            continue
        edge = TopoDS.Edge_s(ancestors.FindKey(index))
        if BRep_Tool.Degenerated_s(edge):
            continue
        try:
            sampled = GCPnts_TangentialDeflection(BRepAdaptor_Curve(edge), angular_tolerance, tolerance)
        except Exception:
            continue
        line = np.array([(p.X(), p.Y(), p.Z()) for p in (sampled.Value(i) for i in range(1, sampled.NbPoints() + 1))])
        if len(line) >= 2:
            segments.append(np.stack([line[:-1], line[1:]], axis=1))
    if not segments:
        return np.zeros((0, 2, 3))
    return np.concatenate(segments)


# ---------------------------------------------------------------------------
# Light
# ---------------------------------------------------------------------------


def _room(normals):
    """The room's light falling on surfaces facing 'normals', per unit albedo of a white surface.

    three's 'shGetIrradianceAt', at the light probe's intensity, in glTF's frame:
    PartCAD's (x, y, z) is glTF's (x, z, -y).
    """
    x = normals[:, 0]
    y = normals[:, 2]
    z = -normals[:, 1]
    c = ROOM_LIGHT
    result = (
        c[0] * 0.886227
        + c[1] * 2.0 * 0.511664 * y
        + c[2] * 2.0 * 0.511664 * z
        + c[3] * 2.0 * 0.511664 * x
        + c[4] * 2.0 * 0.429043 * x * y
        + c[5] * 2.0 * 0.429043 * y * z
        + c[6] * (0.743125 * z * z - 0.247708)
        + c[7] * 2.0 * 0.429043 * x * z
        + c[8] * 0.429043 * (x * x - y * y)
    )
    return result * STAGE_INTENSITY


def lights(radius):
    """The positional lights of 'scene.ts', placed for an object of 'radius': '[(position, intensity, spot)]'.

    'spot' is None for a point light, and otherwise the cosine of the cone's half
    angle: a spot light here aims at the middle of the object with a penumbra of
    one, so it fades from full at its axis to nothing at its edge. Positions are
    'frame()''s, turned into PartCAD's frame.
    """
    return [
        # <Stage>'s spot light: glTF (2r, 4r, 2r), intensity twice the stage's.
        (np.array([2.0, -2.0, 4.0]) * radius, 2 * STAGE_INTENSITY, math.cos(math.pi / 4)),
        # <Stage>'s point light: glTF (-2r, r, -2r).
        (np.array([-2.0, 2.0, 1.0]) * radius, STAGE_INTENSITY, None),
        # Part.js's '<pointLight intensity={1} />', at the origin - the middle of the object.
        (np.zeros(3), 1.0, None),
    ]


def _smoothstep(low, high, value):
    t = np.clip((value - low) / (high - low), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def diffuse(points, normals, radius):
    """The light falling on each point, per unit albedo: what a white surface there would reflect, times pi.

    Everything that does not depend on where it is seen from: the room, the
    ambient light, the hemisphere light and the diffuse half of each positional
    light. Times the surface's own colour over pi, it is the colour three's Phong
    material writes before the specular half.
    """
    irradiance = _room(normals)
    # <Stage>'s ambient light, a third of the stage's intensity.
    irradiance = irradiance + STAGE_INTENSITY / 3.0
    # The hemisphere light: white from above, black from below, at 0.7.
    irradiance = irradiance + 0.7 * (0.5 * normals[:, 2] + 0.5)
    for position, intensity, cone in lights(radius):
        towards = position - points
        distance = np.linalg.norm(towards, axis=1, keepdims=True)
        towards = towards / np.where(distance > 0, distance, 1.0)
        strength = np.full(len(points), intensity)
        if cone is not None:
            axis = position / max(np.linalg.norm(position), 1e-12)
            strength = strength * _smoothstep(cone, 1.0, towards @ axis)
        irradiance = irradiance + strength * np.clip(np.sum(normals * towards, axis=1), 0.0, 1.0)
    return irradiance


def specular(points, normals, eye, radius):
    """The specular half of the Phong material's light, for a camera at 'eye', per point.

    three's 'BRDF_BlinnPhong' with the material's specular colour of #111111 and
    its shininess, for each positional light. Grey, so one number per point.
    """
    f0 = float(srgb_to_linear(0x11 / 255.0))
    view = eye - points
    view = view / np.maximum(np.linalg.norm(view, axis=1, keepdims=True), 1e-12)
    total = np.zeros(len(points))
    for position, intensity, cone in lights(radius):
        towards = position - points
        towards = towards / np.maximum(np.linalg.norm(towards, axis=1, keepdims=True), 1e-12)
        strength = np.full(len(points), intensity)
        if cone is not None:
            axis = position / max(np.linalg.norm(position), 1e-12)
            strength = strength * _smoothstep(cone, 1.0, towards @ axis)
        dot_nl = np.clip(np.sum(normals * towards, axis=1), 0.0, 1.0)
        half = towards + view
        half = half / np.maximum(np.linalg.norm(half, axis=1, keepdims=True), 1e-12)
        dot_nh = np.clip(np.sum(normals * half, axis=1), 0.0, 1.0)
        dot_vh = np.clip(np.sum(view * half, axis=1), 0.0, 1.0)
        fresnel = np.exp2((-5.55473 * dot_vh - 6.98316) * dot_vh)
        f = f0 * (1.0 - fresnel) + fresnel
        d = (SHININESS * 0.5 + 1.0) / math.pi * dot_nh**SHININESS
        total = total + strength * dot_nl * f * 0.25 * d
    return total


# ---------------------------------------------------------------------------
# The scene
# ---------------------------------------------------------------------------


class Scene:
    """An object made ready to be drawn from anywhere: tessellated, centred and lit.

    Built once per video. Everything that does not change as the object turns is
    worked out here, in the object's own frame - the triangles, the colour each
    corner of each of them is lit to from either side, the lines - and 'draw'
    only has to look at it.
    """

    def __init__(self, groups, pixels, warnings=None):
        """'groups' is '[(colour, shape)]', a colour being what 'appearance' writes ('#RRGGBB[AA]').

        'pixels' is the larger side of the frame the object will be drawn into,
        which is what decides how finely it is tessellated.
        """
        boxes = [box for box in (bounding_box(shape) for _color, shape in groups) if box is not None]
        if not boxes:
            raise ValueError("There is nothing to draw: the object has no geometry")
        low = np.min([box[0] for box in boxes], axis=0)
        high = np.max([box[1] for box in boxes], axis=0)
        size = high - low
        self.center = (low + high) / 2.0
        # Half the largest dimension, as 'frame()' frames the camera on.
        self.radius = float(np.max(size)) / 2.0 or 1.0
        tolerance = tolerance_for(float(np.linalg.norm(size)), pixels)

        points, normals, corners, colors, opacity = [], [], [], [], []
        segments, segment_colors = [], []
        offset = 0
        for color, shape in groups:
            parsed = parse_color(color)
            if parsed is None:
                if warnings is not None:
                    warnings.append("'%s' is not a colour; drawn in the default one" % (color,))
                parsed = (DEFAULT_COLOR, 1.0)
            rgb, alpha = parsed
            p, n, c = triangles(shape, tolerance)
            if len(c):
                p, n, c = refine(p, n, c, MAX_EDGE * self.radius)
                points.append(p - self.center)
                normals.append(n)
                corners.append(c + offset)
                colors.append(np.repeat([srgb_to_linear(np.array(rgb) / 255.0)], len(p), axis=0))
                opacity.append(np.full(len(c), alpha))
                offset += len(p)
            lines = free_edges(shape, tolerance)
            if len(lines):
                segments.append(lines - self.center)
                segment_colors.append(np.repeat([edge_color(rgb)], len(lines), axis=0))

        if points:
            self.points = np.concatenate(points)
            self.normals = np.concatenate(normals)
            self.corners = np.concatenate(corners)
            self.albedo = np.concatenate(colors)
            self.opacity = np.concatenate(opacity)
        else:
            self.points = np.zeros((0, 3))
            self.normals = np.zeros((0, 3))
            self.corners = np.zeros((0, 3), dtype=np.int64)
            self.albedo = np.zeros((0, 3))
            self.opacity = np.zeros(0)
        self.segments = np.concatenate(segments) if segments else np.zeros((0, 2, 3))
        self.segment_colors = (
            np.concatenate(segment_colors).astype(np.uint8) if segment_colors else np.zeros((0, 3), np.uint8)
        )
        if not len(self.corners) and not len(self.segments):
            raise ValueError("There is nothing to draw: the object has neither faces nor edges")

        # Lit from either side: both sides of a face are drawn, and the side seen
        # is lit as a surface facing the camera ('side: THREE.DoubleSide').
        self.front = diffuse(self.points, self.normals, self.radius)
        self.back = diffuse(self.points, -self.normals, self.radius)

    @property
    def triangle_count(self):
        return len(self.corners)


def rotation(degrees):
    """The turn of the object by '(x, y, z)' degrees: about X, then Y, then Z, each about the fixed axes."""
    ax, ay, az = (math.radians(float(angle)) for angle in degrees)
    cx, sx, cy, sy, cz, sz = math.cos(ax), math.sin(ax), math.cos(ay), math.sin(ay), math.cos(az), math.sin(az)
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return rz @ ry @ rx


def fit_distance(radius, aspect, fov=FOV):
    """How far back the camera stands to fit an object of 'radius' ('fitDistance' in 'scene.ts').

    Whichever of the two fields is the narrower: 'fov' is the vertical one, and a
    frame taller than it is wide - a phone's - sees less across than up.
    """
    half_height = math.tan(math.radians(fov) / 2.0)
    return radius * FIT / (half_height * min(1.0, aspect))


class Camera:
    """Where the frame is seen from, in the frame of the object as it stands before any turn."""

    def __init__(self, direction=VIEW_DIRECTION, up=UP, distance=1.0, fov=FOV):
        back = np.asarray(direction, dtype=np.float64)
        norm = np.linalg.norm(back)
        if norm == 0:
            raise ValueError("The direction the camera looks from must not be the zero vector")
        back = back / norm
        up = np.asarray(up, dtype=np.float64)
        right = np.cross(up, back)
        if np.linalg.norm(right) < 1e-9:
            # Looking straight along 'up': any up across the line of sight will do,
            # and the one picked is the one a view from above has (Y up the page).
            right = np.cross((0.0, 1.0, 0.0) if abs(back[1]) < 0.9 else (1.0, 0.0, 0.0), back)
        right = right / np.linalg.norm(right)
        self.basis = np.stack([right, np.cross(back, right), back])
        self.distance = float(distance)
        self.fov = float(fov)

    def turned(self, turn):
        """The camera as seen from an object turned by 'turn': '(basis, eye)' in the object's frame.

        The object turned by 'turn' in front of a camera that stands still looks
        exactly like the object standing still with the camera turned the other
        way about it - which is what this works out, so that nothing about the
        object has to move.
        """
        basis = self.basis @ turn
        return basis, basis[2] * self.distance


def _project(points, basis, eye, width, height, fov):
    """Points of the object's frame on the screen: '(x, y, depth)', depth along the line of sight."""
    local = (points - eye) @ basis.T
    depth = -local[:, 2]
    focal = 1.0 / math.tan(math.radians(fov) / 2.0)
    aspect = width / float(height)
    safe = np.where(np.abs(depth) > 1e-12, depth, 1e-12)
    x = (local[:, 0] * focal / aspect / safe + 1.0) * 0.5 * width
    y = (1.0 - local[:, 1] * focal / safe) * 0.5 * height
    return x, y, depth


class Planes:
    """Each triangle's corner weights and depth as planes over the screen.

    On the screen, the weight of each corner at a point - and the reciprocal of
    the depth there - is an affine function of where the point is. So it is
    worked out once per triangle and per frame, as its slopes from the
    triangle's first corner, and a pixel costs two multiplications and two
    additions per quantity rather than the areas of three triangles. From the
    first corner rather than from the corner of the screen, because the pixels
    are worked in single precision, and a plane anchored a few thousand pixels
    away loses the digits a small triangle is drawn with.
    """

    def __init__(self, sx, sy, depth):
        x0, x1, x2 = sx[:, 0], sx[:, 1], sx[:, 2]
        y0, y1, y2 = sy[:, 0], sy[:, 1], sy[:, 2]
        ex1, ey1, ex2, ey2 = x1 - x0, y1 - y0, x2 - x0, y2 - y0
        self.area = ex1 * ey2 - ex2 * ey1
        area = np.where(np.abs(self.area) > 1e-12, self.area, 1.0)
        single = np.float32
        self.x0 = x0.astype(single)
        self.y0 = y0.astype(single)
        # The weight of the second corner - the area of the triangle it faces,
        # over the whole - and of the third, as slopes along x and y.
        self.l1 = ((ey2 / area).astype(single), (-ex2 / area).astype(single))
        self.l2 = ((-ey1 / area).astype(single), (ex1 / area).astype(single))
        # Depth is not linear on the screen; its reciprocal is.
        inverse = 1.0 / np.where(np.abs(depth) > 1e-12, depth, 1e-12)
        d1 = inverse[:, 1] - inverse[:, 0]
        d2 = inverse[:, 2] - inverse[:, 0]
        self.inverse0 = inverse[:, 0].astype(single)
        self.inverse = (
            (ey2 / area * d1 - ey1 / area * d2).astype(single),
            (-ex2 / area * d1 + ex1 / area * d2).astype(single),
        )
        self.depth = depth.astype(single)

    def offsets(self, triangle, x, y):
        """Where pixel centres '(x, y)' are from the first corner of each one's triangle."""
        return x - self.x0[triangle], y - self.y0[triangle]

    def inverse_depth(self, triangle, dx, dy):
        a, b = self.inverse
        return self.inverse0[triangle] + a[triangle] * dx + b[triangle] * dy

    def weights(self, triangle, dx, dy):
        """The three corners' weights at each pixel, corrected for perspective: an (P, 3) array."""
        l1 = self.l1[0][triangle] * dx + self.l1[1][triangle] * dy
        l2 = self.l2[0][triangle] * dx + self.l2[1][triangle] * dy
        weights = np.empty((len(triangle), 3), dtype=np.float32)
        weights[:, 0] = 1.0 - l1 - l2
        weights[:, 1] = l1
        weights[:, 2] = l2
        np.clip(weights, 0.0, 1.0, out=weights)
        # Each corner's weight on the screen, over its depth.
        weights /= self.depth[triangle]
        weights /= np.maximum(weights.sum(axis=1, keepdims=True), np.float32(1e-30))
        return weights


def rasterize(sx, sy, planes, width, height, near, zbuffer, owner, limit=None, select=None):
    """Which triangle is nearest at each pixel, into 'owner' and 'zbuffer'.

    'sx' and 'sy' are (M, 3): each triangle's corners on the screen; 'planes' is
    what 'Planes' made of them. Pixels are sampled at their centres. Triangles
    behind 'near' are dropped, as the camera's near plane drops them, and so is
    every triangle 'select' (a boolean per triangle) leaves out. Where 'limit'
    is given (one depth per pixel) only what is nearer than it is drawn - which is
    how a see-through layer is found in front of what is solid.

    Each triangle is walked a row at a time, between where the row crosses its
    edges, so that no pixel outside it is ever looked at: a CAD model is a few
    large triangles on every flat face and a great many small ones on every
    curved one, and a box around each would waste most of its pixels on the
    large ones.

    'owner' (the triangle drawn at each pixel, flattened, -1 where none is) and
    'zbuffer' (how far it is) are filled in place: they are a frame's worth of
    memory each, and allocated afresh every frame they cost more than drawing.
    """
    owner.fill(-1)
    zbuffer.fill(np.inf)
    if not len(sx):
        return

    keep = np.all(planes.depth > near, axis=1) & (np.abs(planes.area) > 1e-12)
    if select is not None:
        keep &= select
    top = np.maximum(np.ceil(sy.min(axis=1) - 0.5), 0)
    bottom = np.minimum(np.floor(sy.max(axis=1) - 0.5), height - 1)
    left = np.maximum(np.ceil(sx.min(axis=1) - 0.5), 0)
    right = np.minimum(np.floor(sx.max(axis=1) - 0.5), width - 1)
    keep &= (bottom >= top) & (right >= left)
    selected = np.nonzero(keep)[0]
    if not len(selected):
        return

    rows = (bottom - top + 1)[selected].astype(np.int64)
    # At most what each triangle's box holds, to cut the work into pieces of a
    # bounded size.
    estimate = np.cumsum(rows * (right - left + 1)[selected].astype(np.int64))
    cuts = np.unique(np.searchsorted(estimate, np.arange(CHUNK, estimate[-1], CHUNK)))
    edges = ((0, 1), (1, 2), (2, 0))

    for chunk in np.split(np.arange(len(selected)), cuts):
        if not len(chunk):
            continue
        tris = selected[chunk]
        counts = rows[chunk]
        row_tri = np.repeat(tris, counts)
        row_start = np.cumsum(counts) - counts
        row_y = np.repeat(top[tris], counts) + (np.arange(counts.sum()) - np.repeat(row_start, counts))
        centre = row_y + 0.5
        low = np.full(len(row_y), np.inf)
        high = np.full(len(row_y), -np.inf)
        for i, j in edges:
            xi, xj = sx[row_tri, i], sx[row_tri, j]
            yi, yj = sy[row_tri, i], sy[row_tri, j]
            crosses = (np.minimum(yi, yj) <= centre) & (centre <= np.maximum(yi, yj)) & (yi != yj)
            x = xi + (centre - yi) * (xj - xi) / np.where(yi != yj, yj - yi, 1.0)
            low = np.where(crosses, np.minimum(low, x), low)
            high = np.where(crosses, np.maximum(high, x), high)
        first = np.maximum(np.ceil(low - 0.5), 0).astype(np.int64)
        last = np.minimum(np.floor(high - 0.5), width - 1).astype(np.int64)
        lengths = np.maximum(last - first + 1, 0)
        total = int(lengths.sum())
        if not total:
            continue
        pixel_row = np.repeat(np.arange(len(row_y)), lengths)
        pixel_start = np.cumsum(lengths) - lengths
        px = first[pixel_row] + (np.arange(total) - pixel_start[pixel_row])
        py = row_y[pixel_row].astype(np.int64)
        triangle = row_tri[pixel_row]
        dx, dy = planes.offsets(triangle, px.astype(np.float32) + 0.5, py.astype(np.float32) + 0.5)
        z = 1.0 / planes.inverse_depth(triangle, dx, dy)
        pixel = py * width + px
        if limit is not None:
            nearer = z < limit[pixel]
            pixel, z, triangle = pixel[nearer], z[nearer], triangle[nearer]
        np.minimum.at(zbuffer, pixel, z)
        won = z <= zbuffer[pixel]
        owner[pixel[won]] = triangle[won]


def _shade(owner, planes, width, corner_colors):
    """The colour of every pixel a triangle was drawn at, blended across it as it is seen in depth."""
    covered = np.nonzero(owner >= 0)[0]
    triangle = owner[covered]
    x = (covered % width).astype(np.float32) + 0.5
    y = (covered // width).astype(np.float32) + 0.5
    weights = planes.weights(triangle, *planes.offsets(triangle, x, y))
    corners = corner_colors[triangle]
    colors = corners[:, 0] * weights[:, 0:1]
    colors += corners[:, 1] * weights[:, 1:2]
    colors += corners[:, 2] * weights[:, 2:3]
    return covered, colors


class Painter:
    """What draws the frames of one video: the frame's size and look, and the memory a frame is drawn in.

    'supersample' draws each frame that many times larger each way and shrinks
    it, which is what smooths the edges. 'line_width' is how wide a line is, in
    pixels of the frame that comes out. 'background' is the sRGB colour of
    everything the object does not cover - the editor's background, in the IDE.
    """

    def __init__(self, scene, camera, width, height, background=(0x1F, 0x1F, 0x1F), supersample=1, line_width=1.0):
        self.scene = scene
        self.camera = camera
        self.width = int(width)
        self.height = int(height)
        self.background = np.asarray(background, dtype=np.uint8)
        self.ss = max(1, int(supersample))
        self.line_width = float(line_width)
        big = self.width * self.ss * self.height * self.ss
        self.image = np.empty((big, 3), dtype=np.uint8)
        self.zbuffer = np.empty(big, dtype=np.float32)
        self.owner = np.empty(big, dtype=np.int32)
        self.layer_zbuffer = None
        self.layer_owner = None

    def draw(self, turn):
        """One frame, of the object turned by 'turn' (a 3x3 rotation), as (height, width, 3) sRGB bytes."""
        scene, camera, ss = self.scene, self.camera, self.ss
        big_w, big_h = self.width * ss, self.height * ss
        basis, eye = camera.turned(turn)
        near = scene.radius / 100.0
        image = self.image
        image[:] = self.background
        limit = None

        if scene.triangle_count:
            sx, sy, depth = _project(scene.points, basis, eye, big_w, big_h, camera.fov)
            corners = scene.corners
            tx, ty = sx[corners], sy[corners]
            planes = Planes(tx, ty, depth[corners])
            # Which side of each triangle faces the camera: its corners turn
            # counter-clockwise seen from outside, and the screen's Y runs downwards.
            front = planes.area < 0

            # The colour each corner of each triangle is lit to from the side that
            # is seen: the diffuse light worked out once, the specular for this
            # camera.
            spec_front = specular(scene.points, scene.normals, eye, scene.radius)
            spec_back = specular(scene.points, -scene.normals, eye, scene.radius)
            lit_front = scene.albedo * (scene.front / math.pi)[:, None] + spec_front[:, None]
            lit_back = scene.albedo * (scene.back / math.pi)[:, None] + spec_back[:, None]
            lit = np.where(front[:, None, None], lit_front[corners], lit_back[corners])
            lit = neutral_tone_mapping(lit.reshape(-1, 3)).reshape(lit.shape).astype(np.float32)

            solid = scene.opacity >= 1.0
            everything = bool(solid.all())
            rasterize(
                tx, ty, planes, big_w, big_h, near, self.zbuffer, self.owner, select=None if everything else solid
            )
            covered, colors = _shade(self.owner, planes, big_w, lit)
            image[covered] = to_bytes(colors)
            limit = self.zbuffer

            if not everything:
                # One see-through layer, the nearest, over whatever is solid behind it.
                if self.layer_owner is None:
                    self.layer_zbuffer = np.empty_like(self.zbuffer)
                    self.layer_owner = np.empty_like(self.owner)
                owner = self.layer_owner
                rasterize(
                    tx, ty, planes, big_w, big_h, near, self.layer_zbuffer, owner, limit=self.zbuffer, select=~solid
                )
                covered, colors = _shade(owner, planes, big_w, lit)
                alpha = scene.opacity[owner[covered]][:, None]
                under = image[covered].astype(np.float64) / 255.0
                over = to_bytes(colors).astype(np.float64) / 255.0
                image[covered] = np.round((over * alpha + under * (1.0 - alpha)) * 255.0).astype(np.uint8)

        if len(scene.segments):
            _draw_lines(image, limit, scene, basis, eye, big_w, big_h, camera.fov, near, self.line_width * ss)

        frame = image.reshape(big_h, big_w, 3)
        if ss == 1:
            return frame.copy()
        # The mean of each block of samples, as a sum of ss * ss strided views:
        # a reduction over two axes of a strided array is several times slower.
        total = np.zeros((self.height, self.width, 3), dtype=np.uint16)
        for row in range(ss):
            for column in range(ss):
                total += frame[row::ss, column::ss]
        total += (ss * ss) // 2
        total //= ss * ss
        return total.astype(np.uint8)


def draw(scene, camera, turn, width, height, background=(0x1F, 0x1F, 0x1F), supersample=1, line_width=1.0):
    """One frame of 'scene', turned by 'turn', as (height, width, 3) sRGB bytes; see 'Painter'."""
    return Painter(scene, camera, width, height, background, supersample, line_width).draw(turn)


def _draw_lines(image, zbuffer, scene, basis, eye, width, height, fov, near, line_width):
    """Draw the scene's lines into 'image', in front of nothing that is nearer than they are."""
    ends = scene.segments.reshape(-1, 3)
    sx, sy, depth = _project(ends, basis, eye, width, height, fov)
    sx, sy, depth = sx.reshape(-1, 2), sy.reshape(-1, 2), depth.reshape(-1, 2)
    keep = np.all(depth > near, axis=1)
    sx, sy, depth, colors = sx[keep], sy[keep], depth[keep], scene.segment_colors[keep]
    if not len(sx):
        return
    lengths = np.hypot(sx[:, 1] - sx[:, 0], sy[:, 1] - sy[:, 0])
    steps = np.ceil(lengths * 2).astype(np.int64) + 1
    segment = np.repeat(np.arange(len(sx)), steps)
    starts = np.cumsum(steps) - steps
    t = (np.arange(len(segment)) - starts[segment]) / np.maximum(steps[segment] - 1, 1)
    x = sx[segment, 0] + (sx[segment, 1] - sx[segment, 0]) * t
    y = sy[segment, 0] + (sy[segment, 1] - sy[segment, 0]) * t
    inverse = (1.0 - t) / depth[segment, 0] + t / depth[segment, 1]
    z = 1.0 / inverse
    color = colors[segment]

    half = max(0.5, float(line_width) / 2.0)
    reach = int(math.ceil(half - 0.5))
    for dy in range(-reach, reach + 1):
        for dx in range(-reach, reach + 1):
            px = np.floor(x + dx).astype(np.int64)
            py = np.floor(y + dy).astype(np.int64)
            inside = (px >= 0) & (px < width) & (py >= 0) & (py < height)
            pixel = py[inside] * width + px[inside]
            visible = np.ones(len(pixel), dtype=bool)
            if zbuffer is not None:
                visible = z[inside] <= zbuffer[pixel] * (1.0 + LINE_BIAS)
            image[pixel[visible]] = color[inside][visible]
