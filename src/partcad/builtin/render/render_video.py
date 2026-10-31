#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The built-in video renderer (see '//builtin/render' in partcad.yaml).

A video of the object turning, as it turns in the Digital Thread's 3D view with
Animate ticked: drawn the way that view draws it ('video_scene.py'), turning
about its middle at a speed of its own about each axis - about the vertical, at
the IDE's thirty degrees a second, unless told otherwise - and encoded by
GStreamer into whichever container the file type names ('video_encode.py').

What makes it a post rather than a recording is what GStreamer adds on the way:
text over the picture, timed or not ('text'); a logo in a corner ('logo'); a
fade in from and out to a colour ('fade_in', 'fade_out'); a piece of a
soundtrack, cut, faded and set to a volume ('audio'); and any of GStreamer's own
video filters ('filters'). Sized for wherever it is going ('size': Reels,
Shorts, a square feed post, 4K...), at the trade between encoding time and
file size the package wants ('preset', 'quality').

'append: true' adds to the video already at the output path instead of writing
it again. The video keeps where its turn stopped in a tag of its container (see
'video_encode.state_text'), and the video appended to it starts from there, so
that a turn rendered in several runs - after each change to the object, or at
another speed, with other text - plays as one turn.

Every option is a field of the file type, so a package declares it once and
'pc render' or the IDE changes it per run. See 'docs/source/render.rst'.
"""

import concurrent.futures
import math
import os
import queue
import shlex
import sys
import tempfile

import numpy as np

# Pinned before the CAD imports below, for the reason 'render_svg' gives.
import pyexpat  # noqa: F401

sys.path.append(os.path.dirname(__file__))
import appearance
import video_encode
import video_scene
import wrapper_common

# What this implementation reports for what it produces (see 'partcad.code_version'):
# raise it with any change that changes that, and everything it produced
# before is produced again.
CACHE_VERSION = 1

# The sizes 'size' may name. Where a video is posted decides its shape, so the
# names are mostly the places: the vertical 9:16 every short-video feed plays
# full screen, the 4:5 and 1:1 a photo feed shows in line, and the 16:9 of
# everything watched sideways. 1080 pixels across the narrow side, which is
# what those feeds play at; the broadcast names keep their own.
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
DEFAULT_SIZE = "reels"

# The smallest and the largest side a video may have, in pixels: one smaller is
# not a picture of anything, and one larger is no screen's (and GStreamer's
# encoders refuse it).
MIN_SIDE = 16
MAX_SIDE = 7680

DEFAULT_FPS = 30
MAX_FPS = 240

# How fast the object turns about each of X, Y and Z, in degrees a second: about
# the vertical alone, at the speed Animate turns it in the IDE - OrbitControls'
# 'autoRotateSpeed' of 5, which is a turn every twelve seconds.
DEFAULT_SPEED = (0.0, 0.0, 30.0)

# How long a video is when 'duration' does not say and nothing turns.
STILL_DURATION = 5.0

# The editor's background, which is what the IDE's 3D view is drawn over: the
# PartCAD IDE's, VSCodium's own default theme ("Dark Modern").
DEFAULT_BACKGROUND = "#1F1F1F"

DEFAULT_ANTIALIAS = 2
MAX_ANTIALIAS = 4

# Text over the picture: its height as a fraction of the frame's, and the margin
# around it and a logo as a fraction of the frame's narrower side.
DEFAULT_TEXT_SIZE = 0.045
DEFAULT_MARGIN = 0.04
DEFAULT_FONT = "Sans Bold"
DEFAULT_LOGO_WIDTH = 0.2

# Where text and a logo may go, as GStreamer's vertical and horizontal alignment.
POSITIONS = {
    "top": ("top", "center"),
    "center": ("center", "center"),
    "middle": ("center", "center"),
    "bottom": ("bottom", "center"),
    "left": ("center", "left"),
    "right": ("center", "right"),
    "top-left": ("top", "left"),
    "top-right": ("top", "right"),
    "bottom-left": ("bottom", "left"),
    "bottom-right": ("bottom", "right"),
}

# What the name of a filter of 'filters' may not end in: it is an element in the
# middle of the pipeline, so neither a source nor a sink.
_ENDS = ("src", "sink")


class OptionError(ValueError):
    """A field of the file type that cannot be made sense of."""


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------


def _number(request, key, default, low=None, high=None, integer=False):
    value = request.get(key)
    if value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise OptionError("'%s' is a number, not %r" % (key, value)) from None
    if not math.isfinite(number) or (low is not None and number < low) or (high is not None and number > high):
        bounds = []
        if low is not None:
            bounds.append("at least %g" % low)
        if high is not None:
            bounds.append("at most %g" % high)
        raise OptionError("'%s' is %s, not %r" % (key, " and ".join(bounds) or "a finite number", value))
    return int(round(number)) if integer else number


def _vector(request, key, default, single_is=2):
    """A field holding X, Y and Z: a list of three, 'X,Y,Z', or one number for one axis ('single_is')."""
    value = request.get(key)
    if value is None:
        return tuple(float(component) for component in default)
    if isinstance(value, (int, float)):
        vector = [0.0, 0.0, 0.0]
        vector[single_is] = float(value)
        return tuple(vector)
    if isinstance(value, str):
        value = value.replace(",", " ").split()
    try:
        vector = tuple(float(component) for component in value)
    except (TypeError, ValueError):
        raise OptionError("'%s' is three numbers, X, Y and Z, not %r" % (key, request.get(key))) from None
    if len(vector) != 3 or not all(math.isfinite(component) for component in vector):
        raise OptionError("'%s' is three numbers, X, Y and Z, not %r" % (key, request.get(key)))
    return vector


def video_size(request):
    """The frame's '(width, height)' in pixels: 'width' and 'height' if given, else 'size'.

    'size' is a name of 'SIZES', '<width>x<height>', or a list of the two. Each
    side is made even, which is what a video's colour is halved by.
    """
    size = request.get("size")
    if size is None:
        size = DEFAULT_SIZE
    if isinstance(size, str):
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
    width = _number(request, "width", width, integer=True)
    height = _number(request, "height", height, integer=True)
    width -= width % 2
    height -= height % 2
    for side in (width, height):
        if not MIN_SIDE <= side <= MAX_SIDE:
            raise OptionError("A side of the video is %d pixels; a side is %d to %d" % (side, MIN_SIDE, MAX_SIDE))
    return width, height


def duration_of(request, speed):
    """How long the video is: 'duration', or one turn of the fastest axis, or 'STILL_DURATION'."""
    duration = _number(request, "duration", None, low=0)
    if duration is not None:
        if duration <= 0:
            raise OptionError("'duration' is a number of seconds above nought, not %r" % request.get("duration"))
        return duration
    fastest = max(abs(component) for component in speed)
    return 360.0 / fastest if fastest > 0 else STILL_DURATION


def color_of(value, key):
    parsed = video_scene.parse_color(value if str(value).startswith("#") else "#" + str(value))
    if parsed is None:
        raise OptionError("'%s' is a colour, '#RRGGBB', not %r" % (key, value))
    return parsed[0]


def angles_at(start, speed, seconds):
    """The angles the object is turned by 'seconds' in, each kept within a turn."""
    return tuple(math.fmod(a + s * seconds, 360.0) for a, s in zip(start, speed))


def media_path(value, request, key):
    """A file a field names, relative to the package that is rendering when it is relative."""
    if not isinstance(value, str) or not value.strip():
        raise OptionError("'%s' names a file, not %r" % (key, value))
    path = os.path.expanduser(value.strip())
    if not os.path.isabs(path):
        package = request.get("package_dir")
        if package and not os.path.isdir(package):
            # A sandbox that exchanges files rather than sharing them -
            # 'remote', or 'docker' with 'useDockerRemote' - is sent the
            # directories its command names and nothing else, and this is not
            # one of them. Only a relative path is read from it: an absolute
            # one is wherever it says, and is a file there or is not.
            raise OptionError(
                "'%s' names a file of the package, and this sandbox cannot see the package's files: it is "
                "sent only what its command names. Render with a sandbox that shares them - 'venv', 'conda', "
                "or 'docker' without 'useDockerRemote'" % key
            )
        path = os.path.join(package or os.getcwd(), path)
    if not os.path.isfile(path):
        raise OptionError("'%s' names '%s', which is not a file" % (key, path))
    return path


def _entries(value):
    """A field that takes one or several of something: a list of them, or one."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


# ---------------------------------------------------------------------------
# What GStreamer draws over the picture
# ---------------------------------------------------------------------------


def text_overlays(request, width, height, duration, work):
    """The text over the picture, as '(elements, sources)' of the encoding pipeline.

    'text' is one text or a list of them, each a string - shown for the whole
    video at the bottom - or a map: 'text', 'start' and 'end' (or 'duration') in
    seconds, 'position' (one of 'POSITIONS'), 'size' (a fraction of the frame's
    height), 'font' (a Pango font family and style), 'color', 'outline' (a colour,
    or false), 'shadow' and 'box' (a shaded box behind it). Each is timed by a
    subtitle file of its own, which GStreamer's 'textoverlay' reads its text from.
    """
    elements, sources = [], []
    margin = int(round(DEFAULT_MARGIN * min(width, height)))
    for index, entry in enumerate(_entries(request.get("text"))):
        if isinstance(entry, str):
            entry = {"text": entry}
        if not isinstance(entry, dict) or not str(entry.get("text") or "").strip():
            raise OptionError("An entry of 'text' is a string, or a map with a 'text', not %r" % (entry,))
        start = _number(entry, "start", 0.0, low=0)
        end = _number(entry, "end", None, low=0)
        if end is None:
            length = _number(entry, "duration", None, low=0)
            end = duration if length is None else start + length
        if end <= start:
            raise OptionError(
                "The text %r ends at %gs, which is not after it starts (%gs)" % (entry["text"], end, start)
            )
        position = str(entry.get("position") or "bottom").strip().lower()
        if position not in POSITIONS:
            raise OptionError("A text's 'position' is one of %s, not %r" % (", ".join(POSITIONS), position))
        valign, halign = POSITIONS[position]
        size = _number(entry, "size", DEFAULT_TEXT_SIZE, low=0.001, high=1)
        pixels = max(4, int(round(size * height)))
        font = str(entry.get("font") or DEFAULT_FONT)
        name = "text%d" % index
        subtitles = os.path.join(work, "%s.srt" % name)
        with open(subtitles, "w", encoding="utf-8") as stream:
            stream.write(video_encode.srt([(start, end, entry["text"])]))
        outline = entry.get("outline", "#000000")
        element = [
            "textoverlay",
            "name=%s" % name,
            video_encode.prop("font-desc", "%s %dpx" % (font, pixels)),
            "auto-resize=false",
            "wait-text=false",
            "valignment=%s" % valign,
            "halignment=%s" % halign,
            "line-alignment=center",
            "xpad=%d" % margin,
            "ypad=%d" % margin,
            "color=%s" % video_encode.argb(color_hex(entry.get("color", "#FFFFFF"), "color")),
            "draw-outline=%s" % ("true" if outline not in (False, None) else "false"),
            "draw-shadow=%s" % ("true" if entry.get("shadow") else "false"),
            "shaded-background=%s" % ("true" if entry.get("box") else "false"),
        ]
        if outline not in (False, None, True):
            element.append("outline-color=%s" % video_encode.argb(color_hex(outline, "outline")))
        elements.append(element)
        sources.append(
            ["filesrc", video_encode.prop("location", subtitles), "!", "subparse", "!", "%s.text_sink" % name]
        )
    return elements, sources


def color_hex(value, key):
    """A colour field as '#RRGGBB' or '#RRGGBBAA', checked."""
    text = str(value).strip()
    text = text if text.startswith("#") else "#" + text
    if video_scene.parse_color(text) is None:
        raise OptionError("'%s' is a colour, '#RRGGBB' or '#RRGGBBAA', not %r" % (key, value))
    return text


def logo_overlay(request, width, height):
    """The logo in a corner, as an element of the encoding pipeline, or None.

    'logo' is the path of an image, or a map: 'path', 'position' (one of
    'POSITIONS'), 'width' (a fraction of the frame's width), 'opacity'.
    """
    logo = request.get("logo")
    if logo is None:
        return None
    if isinstance(logo, str):
        logo = {"path": logo}
    if not isinstance(logo, dict):
        raise OptionError("'logo' is the path of an image, or a map with a 'path', not %r" % (logo,))
    path = media_path(logo.get("path"), request, "logo")
    position = str(logo.get("position") or "top-right").strip().lower()
    if position not in POSITIONS:
        raise OptionError("The logo's 'position' is one of %s, not %r" % (", ".join(POSITIONS), position))
    valign, halign = POSITIONS[position]
    target_w = max(1, int(round(_number(logo, "width", DEFAULT_LOGO_WIDTH, low=0.001, high=1) * width)))
    natural = video_encode.image_size(path)
    target_h = int(round(target_w * natural[1] / float(natural[0]))) if natural and natural[0] else target_w
    margin = int(round(DEFAULT_MARGIN * min(width, height)))
    x = {"left": margin, "center": (width - target_w) // 2, "right": width - target_w - margin}[halign]
    y = {"top": margin, "center": (height - target_h) // 2, "bottom": height - target_h - margin}[valign]
    opacity = _number(logo, "opacity", 1.0, low=0, high=1)
    return [
        "gdkpixbufoverlay",
        video_encode.prop("location", path),
        "offset-x=%d" % x,
        "offset-y=%d" % y,
        "overlay-width=%d" % target_w,
        "overlay-height=%d" % target_h,
        "alpha=%g" % opacity,
    ]


def video_filters(request):
    """'filters': GStreamer elements to put the new frames through, each '<element> <property>=<value> ...'."""
    elements = []
    for entry in _entries(request.get("filters")):
        if not isinstance(entry, str) or not entry.strip():
            raise OptionError("An entry of 'filters' is a GStreamer element with its properties, not %r" % (entry,))
        tokens = shlex.split(entry)
        name = tokens[0]
        if "!" in tokens or name.endswith(_ENDS) or "." in name:
            raise OptionError("An entry of 'filters' is one element that filters video, not %r" % (entry,))
        elements.append(tokens)
    return elements


# ---------------------------------------------------------------------------
# Sound
# ---------------------------------------------------------------------------


def soundtrack(request, seconds):
    """The new part's sound, as samples, or None for none.

    'audio' is the path of anything GStreamer can play - a song, the soundtrack
    of another video - or a map: 'path', 'start' (where in it to start, in
    seconds: which extract of it), 'volume', 'fade_in' and 'fade_out' (seconds),
    and 'loop' (to fill a video longer than what is left of it, rather than
    ending in silence).
    """
    audio = request.get("audio")
    if audio is None:
        return None
    if isinstance(audio, str):
        audio = {"path": audio}
    if not isinstance(audio, dict):
        raise OptionError("'audio' is the path of a sound file, or a map with a 'path', not %r" % (audio,))
    path = media_path(audio.get("path"), request, "audio")
    start = _number(audio, "start", 0.0, low=0)
    loop = bool(audio.get("loop", False))
    samples = video_encode.decode_audio(path, seconds=None if loop else seconds, start=start)
    samples = video_encode.fit_audio(samples, seconds, loop=loop)
    return video_encode.fade_audio(
        samples,
        fade_in=_number(audio, "fade_in", 0.0, low=0),
        fade_out=_number(audio, "fade_out", 0.0, low=0),
        volume=_number(audio, "volume", 1.0, low=0),
    )


# ---------------------------------------------------------------------------
# Frames
# ---------------------------------------------------------------------------


def frames(painters, start, speed, fps, count, fade_in, fade_out, fade_color):
    """The new frames, drawn by as many threads as there are 'painters', in order.

    numpy lets go of the interpreter while it works on whole arrays, which is
    most of what drawing a frame is, so frames drawn side by side take less time
    than one after the other - and they are handed out in order all the same.
    """
    pool = queue.SimpleQueue()
    for painter in painters:
        pool.put(painter)

    def draw(index):
        painter = pool.get()
        try:
            image = painter.draw(video_scene.rotation(angles_at(start, speed, index / float(fps))))
        finally:
            pool.put(painter)
        return faded(image, index, fps, count, fade_in, fade_out, fade_color)

    if len(painters) == 1:
        for index in range(count):
            yield draw(index)
        return
    window = 2 * len(painters)
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(painters)) as executor:
        pending = [executor.submit(draw, index) for index in range(min(window, count))]
        submitted = len(pending)
        while pending:
            image = pending.pop(0).result()
            if submitted < count:
                pending.append(executor.submit(draw, submitted))
                submitted += 1
            yield image


def faded(image, index, fps, count, fade_in, fade_out, color):
    """'image', mixed with 'color' as far as the fades in and out have got by frame 'index'."""
    seconds = index / float(fps)
    remaining = (count - 1 - index) / float(fps)
    amount = 0.0
    if fade_in > 0 and seconds < fade_in:
        amount = max(amount, 1.0 - seconds / fade_in)
    if fade_out > 0 and remaining < fade_out:
        amount = max(amount, 1.0 - remaining / fade_out)
    if amount <= 0:
        return image
    mixed = image.astype(np.float32) * (1.0 - amount) + np.asarray(color, dtype=np.float32) * amount
    return np.round(mixed).astype(np.uint8)


def threads_of(request):
    """How many frames are drawn at once: 'threads', or one per core up to four."""
    default = max(1, min(4, os.cpu_count() or 1))
    return _number(request, "threads", default, low=1, high=64, integer=True)


# ---------------------------------------------------------------------------
# The implementation
# ---------------------------------------------------------------------------


def process(path, request):
    try:
        return _process(path, request)
    except OptionError as e:
        return {"success": False, "exception": "The video cannot be made as configured: %s" % e}
    except video_encode.GStreamerError as e:
        return {"success": False, "exception": str(e)}
    except Exception as e:
        wrapper_common.handle_exception(e)
        return {"success": False, "exception": wrapper_common.exception_to_str(e)}


def _process(path, request):
    warnings = []
    # Not 'container', which is the protocol's: an implementation declaring one
    # is run in that container image (see 'output.Implementation.container').
    container = request.get("container_format")
    if container not in video_encode.CONTAINERS:
        raise OptionError(
            "'container_format' is one of %s, not %r" % (", ".join(sorted(video_encode.CONTAINERS)), container)
        )
    width, height = video_size(request)
    fps = _number(request, "fps", DEFAULT_FPS, low=1, high=MAX_FPS)
    speed = _vector(request, "speed", DEFAULT_SPEED)
    start = _vector(request, "start_angle", (0.0, 0.0, 0.0))
    duration = duration_of(request, speed)
    count = max(1, int(round(duration * fps)))
    preset = request.get("preset") or video_encode.DEFAULT_PRESET
    video_encode.preset_index(preset)
    quality = video_encode.quality_of(request.get("quality"))
    bitrate = _number(request, "bitrate", None, low=1)
    audio_bitrate = _number(request, "audio_bitrate", 192, low=8, high=1024)
    antialias = _number(request, "antialias", DEFAULT_ANTIALIAS, low=1, high=MAX_ANTIALIAS, integer=True)
    background = color_of(request.get("background") or DEFAULT_BACKGROUND, "background")
    fade_color = color_of(request.get("fade_color") or "#000000", "fade_color")
    fade_in = _number(request, "fade_in", 0.0, low=0)
    fade_out = _number(request, "fade_out", 0.0, low=0)
    zoom = _number(request, "zoom", 1.0, low=0.01, high=100)
    line_weight = _number(request, "line_weight", None, low=0.1, high=100)
    if line_weight is None:
        line_weight = max(1.0, round(min(width, height) / 540.0))
    origin = request.get("viewport_origin") or video_scene.VIEW_DIRECTION
    up = request.get("viewport_up") or video_scene.UP

    # GStreamer is asked for before anything is drawn: a machine without it
    # should hear so at once, not after minutes of frames.
    video_encode.launcher()
    video_codec = video_encode.codec_for(container, request.get("codec"), "video")

    # What is being appended to, if anything, and where its turn stopped.
    previous = None
    if request.get("append") and os.path.isfile(path) and os.path.getsize(path) > 0:
        previous = video_encode.discover(path)
        if not previous["video"]:
            raise OptionError("'append' is set, and '%s' has no video in it to append to" % path)
        state = video_encode.read_state(path, previous["text"])
        if state is not None:
            start = state
        elif not video_encode.keeps_state(container):
            warnings.append(
                "A '%s' file keeps no tags, so '%s' cannot say where its turn stopped, and the part appended to it "
                "starts at 'start_angle'" % (container, path)
            )
        else:
            warnings.append(
                "'%s' does not say where its turn stopped - PartCAD did not write it - so the part appended to it "
                "starts at 'start_angle'" % path
            )
    previous_count = 0
    if previous is not None:
        previous_count = int(round((previous["duration"] or 0.0) * fps))

    # The object, by colour, made ready to be drawn.
    whole = request["wrapped"]
    tree = request.get("shape_tree")
    if tree is None:
        groups = [(appearance.DEFAULT_COLOR, whole)]
    else:
        groups = appearance.split_by_color(tree, whole, warnings)
    scene = video_scene.Scene(groups, max(width, height), warnings)
    camera = video_scene.Camera(
        direction=[float(component) for component in origin],
        up=[float(component) for component in up],
        distance=video_scene.fit_distance(scene.radius, width / float(height)) / zoom,
    )

    tags = {}
    state_tag = video_encode.CONTAINERS[container]["state_tag"]
    end = angles_at(start, speed, count / float(fps))
    if state_tag:
        tags[state_tag] = video_encode.state_text(end, previous_count + count, fps)
    if request.get("title"):
        tags["title"] = str(request["title"])
    # Ogg's are Vorbis comments, written once the file is (see 'write_comments').
    comments = []
    if video_encode.CONTAINERS[container].get("comments"):
        comments = video_encode.state_comments(end, previous_count + count, fps)
        if request.get("title"):
            comments.append((video_encode.COMMENT_TITLE, str(request["title"])))

    directory = os.path.dirname(os.path.abspath(path))
    partial = os.path.join(directory, ".%s.partial" % os.path.basename(path))
    with tempfile.TemporaryDirectory(prefix="partcad-video-") as work:
        elements, sources = text_overlays(request, width, height, duration, work)
        chain = video_filters(request) + elements
        logo = logo_overlay(request, width, height)
        if logo is not None:
            chain.append(logo)

        # The sound: what the video appended to had, then the new part's.
        audio_path = None
        new_audio = soundtrack(request, count / float(fps))
        old_audio = None
        if previous is not None and previous["audio"]:
            if video_encode.CONTAINERS[container]["audio"]:
                old_audio = video_encode.fit_audio(
                    video_encode.decode_audio(path, seconds=previous_count / float(fps)), previous_count / float(fps)
                )
            else:
                warnings.append(
                    "A '%s' file carries no sound here, so the sound of '%s' is dropped" % (container, path)
                )
        if new_audio is not None or old_audio is not None:
            silence = np.zeros((0, video_encode.AUDIO_CHANNELS), dtype=np.float32)
            parts = []
            if previous is not None:
                parts.append(
                    old_audio if old_audio is not None else video_encode.fit_audio(silence, previous_count / float(fps))
                )
            parts.append(new_audio if new_audio is not None else video_encode.fit_audio(silence, count / float(fps)))
            audio_path = os.path.join(work, "sound.wav")
            video_encode.write_wav(audio_path, np.concatenate(parts))

        pipeline = video_encode.Pipeline(
            partial,
            container,
            width,
            height,
            fps,
            video_codec=video_codec,
            audio_codec=request.get("audio_codec"),
            preset=preset,
            quality=quality,
            bitrate=bitrate,
            audio_bitrate=audio_bitrate,
            video=chain,
            sources=sources,
            prefix=previous is not None,
            audio=audio_path,
            tags=tags,
        )
        threads = threads_of(request)
        painters = [
            video_scene.Painter(scene, camera, width, height, background, antialias, line_weight)
            for _ in range(threads)
        ]
        prefix = ()
        if previous is not None:
            # A bound, so that a file whose timestamps are wrong cannot have the
            # frame rate converter fill hours: the length it says it is, and a
            # second.
            prefix = video_encode.decode_frames(path, width, height, fps, limit=previous_count + int(fps) + 1)
        try:
            written_before, written = pipeline.run(
                frames(painters, start, speed, fps, count, fade_in, fade_out, fade_color), prefix=prefix
            )
            if comments:
                video_encode.write_comments(partial, comments)
            os.replace(partial, path)
        finally:
            if os.path.exists(partial):
                os.remove(partial)

    # An answer that says what it wrote is remembered, and put back the next
    # time the same file is asked for (see 'output.FILES_KEY'). One that read a
    # file - the video it was appended to, a soundtrack, a logo - says nothing
    # (None, which is not a list): what those files hold is not in the
    # question, so the same question can have another answer. An append says
    # nothing whether or not there was a video to append to this time: its
    # first run, remembered, was the answer every later run of it got - the
    # first part, put back over the parts that should have followed it.
    read_a_file = bool(request.get("append")) or request.get("audio") is not None or request.get("logo") is not None
    result = {"success": True, "exception": None, "files": None if read_a_file else []}
    if warnings:
        result["warnings"] = warnings
    result["viewport"] = {
        "viewport_origin": [float(component) for component in origin],
        "viewport_up": [float(component) for component in up],
    }
    result["video"] = {
        "width": width,
        "height": height,
        "fps": fps,
        "frames": written,
        "appended_to": written_before if previous is not None else None,
        "seconds": (written_before + written) / float(fps),
        "start_angle": list(start),
        "end_angle": list(end),
        "triangles": scene.triangle_count,
    }
    return result
