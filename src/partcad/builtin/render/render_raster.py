#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Every raster picture PartCAD renders, in one of two styles: a PNG, a JPEG, and each frame of a video.

'style' picks how the picture is drawn:

  * 'lines' (what a PNG and a JPEG are unless told otherwise) - the projection's
    visible edges, the very drawing the SVG is: projected here through
    'render_svg.py' and rasterized by svglib and reportlab;
  * 'shaded' - the object lit and in perspective, as the Digital Thread's 3D view
    draws it: drawn by 'raster_scene.py' ('Shaded' below says with what), which is
    also what draws every frame of a video ('render_video.py'). So a frame of a
    video is a picture 'pc render -t png --style shaded' draws, given the same
    size, background and turn - the frame's turn being the video's 'turn' plus
    its 'speed' times the time.

PNG and JPEG differ only in what PIL is told to write at the very last step, so
both implementations draw here and pass their own PIL options in.

Keeping both on one code path is also what keeps the dependency list short:
rasterizing lines needs svglib, reportlab and rlPyCairo (see the
'pythonRequirements' of '//builtin/render'), and JPEG adds nothing to that.
reportlab already depends on Pillow, and both styles hand the finished image to
'PIL.Image.save()' with 'configPIL' as its keyword arguments -- so every JPEG
encoder option is reachable without a single extra package in the sandbox. The
shaded style adds none either: it is numpy, which build123d brings with it, and
OCP, which is what everything here projects with. svglib and reportlab are
needed by the lines style alone, so that a video, which draws shaded, needs
neither in its sandbox.

This module is imported by its siblings rather than run on its own: it is not
declared as the 'path' of any file type.

'reproducible' reaches the projection through the request, which is handed to
'render_svg.process()' whole - so a raster asked for reproducibly is drawn from
the projection that is. It settles the picture and not the encoding: the bytes
below this point are svglib's, reportlab's and Pillow's, and a new release of
any of the three moves them by a few tens without moving the picture. That is
why the four raster projections under 'examples/feature_render/images' are on
the CI job's UNSTABLE list and the SVGs beside them are not. A shaded picture
has nothing to decide: it is the same pixels every time on one machine, and on
another only as the same as the tessellation OCCT makes there.
"""

import math
import os
import sys
import tempfile

sys.path.append(os.path.dirname(__file__))
import wrapper_common
import render_svg
import viewpoint

# What rasterizes the lines style. A video draws shaded, and its sandbox has
# neither of them: there they are None, and only a picture of lines - which no
# video draws - says so.
try:
    import svglib.svglib as svglib
    import reportlab.graphics.renderPM as renderPM

    _LINES_MISSING = None
except ImportError as e:
    svglib = renderPM = None
    _LINES_MISSING = str(e)

# How a picture may be drawn; 'lines' unless the request says otherwise.
STYLES = ("lines", "shaded")
DEFAULT_STYLE = "lines"

DEFAULT_SIZE = 512

# The sizes 'size' may name. Where a picture or a video is posted decides its
# shape, so the names are mostly the places: the vertical 9:16 every short-video
# feed plays full screen, the 4:5 and 1:1 a photo feed shows in line, and the
# 16:9 of everything watched sideways. 1080 pixels across the narrow side, which
# is what those feeds play at; the broadcast names keep their own.
SIZES = {
    # 9:16, full screen on a phone: Instagram Reels and Stories, YouTube Shorts,
    # TikTok, Facebook Reels, Snapchat.
    "reels": (1080, 1920),
    "reel": (1080, 1920),
    "shorts": (1080, 1920),
    "tiktok": (1080, 1920),
    "story": (1080, 1920),
    "stories": (1080, 1920),
    "vertical": (1080, 1920),
    "9:16": (1080, 1920),
    "vertical-720p": (720, 1280),
    "vertical-4k": (2160, 3840),
    # 4:5, the tallest a photo feed shows in line: Instagram, Facebook, LinkedIn.
    "portrait": (1080, 1350),
    "4:5": (1080, 1350),
    # 2:3, Pinterest's pin.
    "pinterest": (1000, 1500),
    "2:3": (1000, 1500),
    # 1:1.
    "square": (1080, 1080),
    "1:1": (1080, 1080),
    # 16:9, watched sideways: YouTube, X, LinkedIn, a slide.
    "landscape": (1920, 1080),
    "youtube": (1920, 1080),
    "16:9": (1920, 1080),
    "480p": (854, 480),
    "hd": (1280, 720),
    "720p": (1280, 720),
    "fhd": (1920, 1080),
    "1080p": (1920, 1080),
    "qhd": (2560, 1440),
    "1440p": (2560, 1440),
    "4k": (3840, 2160),
    "uhd": (3840, 2160),
    "2160p": (3840, 2160),
    # 4:3 and the cinema's 21:9.
    "4:3": (1440, 1080),
    "21:9": (2560, 1080),
}

# The smallest and the largest side a shaded picture may have, in pixels: one
# smaller is not a picture of anything, and one larger is no screen's (and a
# video's encoders refuse it). The memory a picture is drawn in grows with it
# and with 'antialias' squared, which is the other reason for a bound.
MIN_SIDE = 16
MAX_SIDE = 7680

# What a raster render is drawn on top of when nothing else is asked for. The
# SVG has a transparent background and JPEG has no alpha channel at all, so
# some color has to be chosen; white matches what PNG has always produced.
DEFAULT_BACKGROUND = 0xFFFFFF

# How much of a picture is left empty on each side of the object, as a fraction
# of the picture: 7.5% on each side, so that the object spans 85% of it. What a
# picture of a product is held to where pictures of products are published:
# Google Merchant Center asks for the product to take up 75% to 90% of the
# image, and Amazon for its main image to fill 85% or more of the frame. A
# picture of lines leaves it around the drawing, all round; a shaded one around
# the sphere about the object, on its narrower side - which is what keeps every
# turn of it, every frame of a video, inside the picture. 'margin' sets it.
DEFAULT_MARGIN = 0.075
MAX_MARGIN = 0.45

# How many samples each way a shaded pixel is the mean of: what smooths its
# edges, at the square of it in time and memory.
DEFAULT_ANTIALIAS = 2
MAX_ANTIALIAS = 4

# The side 'line_weight' is measured against: a line is 'line_weight' pixels
# wide in a picture this many pixels across its narrower side, and as much
# wider as a larger picture is - which is what the projection's lines do too,
# drawn 'line_weight' wide on a page 512 across and scaled with it.
LINE_WEIGHT_SIDE = 512.0


class OptionError(ValueError):
    """A field of the file type that cannot be made sense of."""


def number(request, key, default, low=None, high=None, integer=False):
    """A numeric field: 'default' when absent, and an OptionError when it is not a number within bounds."""
    value = request.get(key)
    if value is None:
        return default
    try:
        figure = float(value)
    except (TypeError, ValueError):
        raise OptionError("'%s' is a number, not %r" % (key, value)) from None
    if not math.isfinite(figure) or (low is not None and figure < low) or (high is not None and figure > high):
        bounds = []
        if low is not None:
            bounds.append("at least %g" % low)
        if high is not None:
            bounds.append("at most %g" % high)
        raise OptionError("'%s' is %s, not %r" % (key, " and ".join(bounds) or "a finite number", value))
    return int(round(figure)) if integer else figure


def style_of(request):
    """How the picture is drawn: one of 'STYLES'."""
    style = request.get("style")
    if style is None:
        return DEFAULT_STYLE
    style = str(style).strip().lower()
    if style not in STYLES:
        raise OptionError("'style' is one of %s, not %r" % (", ".join(STYLES), request.get("style")))
    return style


def size_of(request, default=(DEFAULT_SIZE, DEFAULT_SIZE)):
    """The picture's '(width, height)' in pixels: 'size', with 'width' and 'height' each overriding its side.

    'size' is a name of 'SIZES', '<width>x<height>', or a list of the two. A
    package that sets 'width' alone keeps the other side of whatever 'size' is.
    """
    size = request.get("size")
    if size is None:
        width, height = default
    elif isinstance(size, str):
        text = size.strip().lower()
        if text in SIZES:
            width, height = SIZES[text]
        else:
            parts = text.replace("×", "x").replace("*", "x").split("x")
            try:
                width, height = (int(part) for part in parts)
            except ValueError:
                raise OptionError(
                    "'size' is one of %s, or '<width>x<height>', not %r" % (", ".join(sorted(SIZES)), size)
                ) from None
    else:
        try:
            width, height = (int(side) for side in size)
        except (TypeError, ValueError):
            raise OptionError("'size' is a name, '<width>x<height>' or [width, height], not %r" % (size,)) from None
    return number(request, "width", width, integer=True), number(request, "height", height, integer=True)


def parse_background(value):
    """Turn a background color from the render options into reportlab's integer.

    Accepts what a YAML config can hold: an integer already in 0xRRGGBB form, or
    a string such as "#ffffff", "ffffff" or "#fff".
    """
    if value is None:
        return DEFAULT_BACKGROUND
    if isinstance(value, int):
        return value

    text = str(value).strip().lstrip("#")
    if len(text) == 3:
        # The CSS shorthand: each digit stands for a doubled byte.
        text = "".join(digit * 2 for digit in text)
    if len(text) != 6:
        raise ValueError("Invalid background color: %r" % (value,))
    return int(text, 16)


def rgb_of(request, key="background"):
    """A colour field as '(red, green, blue)' bytes, read as 'background' is; white when absent."""
    try:
        value = parse_background(request.get(key))
    except ValueError:
        raise OptionError("'%s' is a colour, '#RRGGBB', not %r" % (key, request.get(key))) from None
    if not 0 <= value <= 0xFFFFFF:
        raise OptionError("'%s' is a colour, '#RRGGBB', not %r" % (key, request.get(key)))
    return ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF)


def margin_of(request):
    """'margin': the fraction of the picture left empty on each side of the object (see 'DEFAULT_MARGIN')."""
    return number(request, "margin", DEFAULT_MARGIN, low=0, high=MAX_MARGIN)


def scale_for(drawing, request, margin=0.0):
    """How much to scale the projection by to fit the requested pixel size, and the padding around it.

    '(scale, padding)', the padding in pixels on every side: 'margin' of the
    picture's larger side, so that the drawing spans '1 - 2 * margin' of it and
    is as far from every edge. Both dimensions bound the result, so the smaller
    ratio wins. A request with no 'size' needs only one of 'width' and
    'height': the other is then whatever keeps the aspect ratio, rather than the
    default silently bounding the dimension that was asked for.
    """
    if request.get("size") is not None:
        width, height = size_of(request)
    else:
        width = request.get("width")
        height = request.get("height")
        if width is None and height is None:
            width = height = DEFAULT_SIZE

    # A dimension that is not a positive, finite number has no image to
    # describe, and none of them fail on their own: zero and negatives produce
    # a scale to match and the exporter writes a degenerate image, while a YAML
    # '.nan' passes any comparison and an '.inf' scales past what can be
    # rasterized. Say what is wrong instead.
    for name, value in (("width", width), ("height", height)):
        if value is not None and not (math.isfinite(float(value)) and float(value) > 0):
            raise Exception(
                "The '%s' of a raster projection has to be a positive finite number, not %s" % (name, value)
            )

    # The padding, in the drawing's own units: so many of its larger side.
    pad = margin / (1.0 - 2.0 * margin) * max(float(drawing.width), float(drawing.height))
    ratios = []
    if width is not None:
        ratios.append(float(width) / (float(drawing.width) + 2.0 * pad))
    if height is not None:
        ratios.append(float(height) / (float(drawing.height) + 2.0 * pad))
    scale = min(ratios)
    return scale, pad * scale


class Shaded:
    """A shaded picture of the object a request is for, ready to be drawn: the scene, the camera, the look.

    Everything it is drawn with is a field of the request, which is what makes a
    frame of a video a picture 'pc render' draws: the size ('size', 'width',
    'height'), 'background', 'antialias' (samples each way per pixel),
    'margin' (see 'DEFAULT_MARGIN'), 'zoom',
    'perspective' (the vertical field of view in degrees - the 3D view's 50 by
    default - or nought, or false, for none), 'line_weight' (see
    'LINE_WEIGHT_SIDE'), 'viewport_origin' and 'viewport_up' (the 3D view's own
    when not given, whatever the kind of shape: it is that view being drawn),
    and 'turn'.

    Made in two steps: the fields are read and checked at once, which is cheap,
    and 'build' then tessellates and lights the object, which is most of the
    work - so that a video says what is wrong with it before anything takes time.
    Built once, it is drawn as many times as there are pictures to draw: once for
    a PNG, once a frame for a video, each with a turn of its own.
    """

    def __init__(self, request, width, height):
        import raster_scene

        self.raster_scene = raster_scene
        self.request = request
        for side in (width, height):
            if not MIN_SIDE <= side <= MAX_SIDE:
                raise OptionError("A side of the picture is %d pixels; a side is %d to %d" % (side, MIN_SIDE, MAX_SIDE))
        self.width, self.height = int(width), int(height)
        self.background = rgb_of(request)
        self.antialias = number(request, "antialias", DEFAULT_ANTIALIAS, low=1, high=MAX_ANTIALIAS, integer=True)
        self.zoom = number(request, "zoom", 1.0, low=0.01, high=100)
        self.margin = margin_of(request)
        self.perspective = perspective_of(request, raster_scene.FOV)
        self.line_weight = number(request, "line_weight", 1.0, low=0.01, high=100)
        self.origin = tuple(float(c) for c in (request.get("viewport_origin") or raster_scene.VIEW_DIRECTION))
        self.up = tuple(float(c) for c in (request.get("viewport_up") or raster_scene.UP))
        try:
            self.turn = viewpoint.turn_of(request)
        except ValueError as e:
            raise OptionError(str(e)) from None
        self.scene = None
        self.camera = None

    def build(self, warnings):
        """Tessellate and light the object, and frame the camera on it: what drawing needs. Returns itself."""
        raster_scene = self.raster_scene
        _whole, groups = render_svg._by_color(self.request, warnings)
        self.scene = raster_scene.Scene(groups, max(self.width, self.height), warnings)
        aspect = self.width / float(self.height)
        sphere = self.scene.sphere
        # The light is seen from where a perspective camera would stand, and a
        # camera with perspective comes nearer to zoom in; one without makes the
        # object larger on the picture instead, from where it stands.
        distance = raster_scene.frame_distance(sphere, aspect, self.perspective or raster_scene.FOV, self.margin)
        if self.perspective:
            distance /= self.zoom
        self.camera = raster_scene.Camera(
            direction=self.origin,
            up=self.up,
            distance=distance,
            fov=self.perspective,
            height=raster_scene.frame_height(sphere, aspect, self.margin) / self.zoom,
        )
        return self

    @property
    def line_width(self):
        """How wide a line is, in pixels of the picture."""
        return self.line_weight * min(self.width, self.height) / LINE_WEIGHT_SIDE

    def painter(self):
        """What draws the pictures: one per thread that draws them, each with memory of its own."""
        return self.raster_scene.Painter(
            self.scene, self.camera, self.width, self.height, self.background, self.antialias, self.line_width
        )

    def draw(self, turn=None, painter=None):
        """The picture of the object turned by 'turn' degrees - the request's own when not given - as (h, w, 3) bytes."""
        turn = self.turn if turn is None else turn
        return (painter or self.painter()).draw(self.raster_scene.rotation(turn))

    def viewport(self, turn=None):
        """Where the object, turned by 'turn', is looked at from, as the projection says it: see 'viewpoint.turned'."""
        origin, up = viewpoint.turned(self.origin, self.up, self.turn if turn is None else turn)
        return {"viewport_origin": [float(c) for c in origin], "viewport_up": [float(c) for c in up]}

    def fields(self, turn=None):
        """The fields a PNG is rendered with to be this picture, turned by 'turn': what 'pc render' is told."""
        return {
            "style": "shaded",
            "size": "%dx%d" % (self.width, self.height),
            "background": "#%02X%02X%02X" % self.background,
            "antialias": self.antialias,
            "zoom": self.zoom,
            "margin": self.margin,
            "perspective": self.perspective,
            "line_weight": self.line_weight,
            "viewport_origin": list(self.origin),
            "viewport_up": list(self.up),
            "turn": [float(angle) for angle in (self.turn if turn is None else turn)],
        }


def perspective_of(request, default):
    """'perspective': the vertical field of view in degrees, nought (or false) for none, 'default' when absent."""
    value = request.get("perspective")
    if value is None or value is True:
        return float(default)
    if value is False:
        return 0.0
    fov = number(request, "perspective", default, low=0, high=150)
    if 0 < fov < 1:
        raise OptionError("'perspective' is a field of view of 1 to 150 degrees, or nought for none, not %r" % value)
    return fov


def process(path, request, fmt, config_pil=None):
    """Render the requested shape into 'path' as a raster image, in the style it asks for.

    'fmt' is the format name Pillow knows ("PNG", "JPEG"); 'config_pil' is passed
    through to 'PIL.Image.save()'.
    """
    try:
        if style_of(request) == "shaded":
            return _shaded(path, request, fmt, config_pil)
        return _lines(path, request, fmt, config_pil)
    except OptionError as e:
        return {"success": False, "exception": "The picture cannot be made as configured: %s" % e}
    except Exception as e:
        wrapper_common.handle_exception(e)
        return {"success": False, "exception": wrapper_common.exception_to_str(e)}


def _shaded(path, request, fmt, config_pil):
    from PIL import Image

    warnings = []
    width, height = size_of(request)
    shaded = Shaded(request, width, height).build(warnings)
    image = shaded.draw()
    # 'transparent' is renderPM's, which the lines style is written through.
    options = {key: value for key, value in (config_pil or {}).items() if key != "transparent"}
    Image.fromarray(image, "RGB").save(path, format=fmt, **options)

    result = {"success": True, "exception": None, "files": []}
    if warnings:
        result["warnings"] = warnings
    # Where the picture was looked at from, as the projection says it (see
    # 'render_svg.VIEWPORT_KEY'): the object turned is the camera turned back.
    result[render_svg.VIEWPORT_KEY] = shaded.viewport()
    return result


def _lines(path, request, fmt, config_pil):
    if svglib is None or renderPM is None:
        raise OptionError(
            "a picture of lines is rasterized by svglib and reportlab, and this sandbox has neither (%s): render "
            "it as a 'png' or a 'jpeg', which ask for them, or in the 'shaded' style" % _LINES_MISSING
        )

    # A private directory, not a bare temporary name: 'tempfile.mktemp()'
    # only invents a path and reserves nothing, leaving a window in which
    # another local process can plant a symlink there and have the SVG
    # written through it. The directory also takes care of the cleanup, so
    # the intermediate SVG never accumulates in a long render job.
    with tempfile.TemporaryDirectory(prefix="partcad-render-") as temp_dir:
        svg_path = os.path.join(temp_dir, "projection.svg")

        svg_response = render_svg.process(svg_path, request)
        # Report why the projection failed instead of the "Failed to convert
        # to RLG" that an absent or empty SVG would produce below.
        if not svg_response.get("success", False):
            return {
                "success": False,
                "exception": "SVG render failed: %s" % svg_response.get("exception"),
            }

        # Render the raster image
        drawing = svglib.svg2rlg(svg_path)

    if drawing is None:
        return {
            "success": False,
            "exception": "Failed to convert to RLG. Aborting.",
        }

    scale, pad = scale_for(drawing, request, margin_of(request))
    drawing.scale(scale, scale)
    # Moved in by the padding, in the drawing's units now that it is scaled.
    drawing.translate(pad / scale, pad / scale)
    drawing.width = drawing.width * scale + 2.0 * pad
    drawing.height = drawing.height * scale + 2.0 * pad
    renderPM.drawToFile(
        drawing,
        path,
        fmt=fmt,
        bg=parse_background(request.get("background")),
        configPIL=config_pil,
    )

    result = {"success": True, "exception": None, "files": []}
    # What the projection had to say about the shape - a colour a part
    # states that is not one - is said about this picture too, which is
    # drawn from it.
    if svg_response.get("warnings"):
        result["warnings"] = svg_response["warnings"]
    # And where it was looked at from, for the same reason ('viewport' is
    # 'render_svg.VIEWPORT_KEY').
    if svg_response.get("viewport"):
        result["viewport"] = svg_response["viewport"]
    return result
