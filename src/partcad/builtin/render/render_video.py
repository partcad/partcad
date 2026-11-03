#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The built-in video renderer (see '//builtin/render' in partcad.yaml).

A video of the object turning, as it turns in the Digital Thread's 3D view with
Animate ticked: turning about its middle at a speed of its own about each axis -
about the vertical, at the IDE's thirty degrees a second, unless told otherwise
- and encoded by GStreamer into whichever container the file type names
('video_encode.py').

Every frame is a picture 'render_raster.py' draws in its shaded style - the
same code, from the same fields, as 'pc render -t png --style shaded' - turned
by the video's 'turn' plus its 'speed' times the time. So any frame can be had
as a picture of its own, and the result says what to ask for ('picture'). What
the video adds over its frames is its own: the text, the logo, the fades and the
filters below.

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

import math
import os
import shlex
import sys
import tempfile

import numpy as np

# Pinned before the CAD imports below, for the reason 'render_svg' gives.
import pyexpat  # noqa: F401

sys.path.append(os.path.dirname(__file__))
import frame_schedule
import raster_scene
import render_raster
import video_encode
import wrapper_common

# What this implementation reports for what it produces (see 'partcad.code_version'):
# raise it with any change that changes that, and everything it produced
# before is produced again.
CACHE_VERSION = 1

# The size a video is when nothing says: the vertical 9:16 every short-video
# feed plays full screen. 'size' names the others ('render_raster.SIZES').
DEFAULT_SIZE = "reels"

DEFAULT_FPS = 30
MAX_FPS = 240

# How fast the object turns about each of X, Y and Z, in degrees a second: about
# the vertical alone, at the speed Animate turns it in the IDE - OrbitControls'
# 'autoRotateSpeed' of 5, which is a turn every twelve seconds.
DEFAULT_SPEED = (0.0, 0.0, 30.0)

# How long a video is when 'duration' does not say and nothing turns.
STILL_DURATION = 5.0

# The editor's background, which is what the IDE's 3D view is drawn over: the
# PartCAD IDE's, VSCodium's own default theme ("Dark Modern"). Declared as the
# video file types' 'background'; this is for a caller that hands none.
DEFAULT_BACKGROUND = "#1F1F1F"

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


# A field of the file type that cannot be made sense of: the pictures' own, since
# a frame's fields are a picture's.
OptionError = render_raster.OptionError
_number = render_raster.number


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------


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
    """The frame's '(width, height)' in pixels: a picture's ('render_raster.size_of'), reels when nothing says.

    Each side is made even, which is what a video's colour is halved by.
    """
    width, height = render_raster.size_of(request, default=render_raster.SIZES[DEFAULT_SIZE])
    width -= width % 2
    height -= height % 2
    for side in (width, height):
        if not render_raster.MIN_SIDE <= side <= render_raster.MAX_SIDE:
            raise OptionError(
                "A side of the video is %d pixels; a side is %d to %d"
                % (side, render_raster.MIN_SIDE, render_raster.MAX_SIDE)
            )
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
            # 'remote', or 'docker' with 'useDockerRemote' - is sent the package
            # when a field names a file that is in it ('output.PACKAGE_DIR_ARGUMENT'),
            # and handed where it put it. This one was not: there was no such
            # file there. Only a relative path is read from the package: an
            # absolute one is wherever it says, and is a file there or is not.
            raise OptionError("'%s' names %r, which is not a file of the package" % (key, value))
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
    if raster_scene.parse_color(text) is None:
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


def frames(shaded, the_plan, start, speed, fps, count, fade_in, fade_out, fade_color):
    """The new frames, drawn as 'the_plan' says ('frame_schedule'), in order.

    Frame 'index' is the picture 'shaded' draws turned by 'start' plus 'speed'
    times its time: what 'pc render -t png' draws with the same fields.

    numpy lets go of the interpreter while it works on whole arrays, which is
    most of what drawing a frame is, so the bands and frames drawn side by side
    take less time than one after the other - and the frames are handed out in
    order all the same, straight into the encoder and never kept anywhere.
    """
    painter = shaded.painter()

    def turn_of(index):
        return raster_scene.rotation(angles_at(start, speed, index / float(fps)))

    for index, image in enumerate(frame_schedule.frames(painter, count, turn_of, the_plan)):
        yield faded(image, index, fps, count, fade_in, fade_out, fade_color)


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
    """How many threads draw the frames: 'threads', or one per core this process may run on.

    PartCAD says, when it runs the video: as many as it has process slots free
    for, or one where its user's 'video.parallel' is off (see
    'output.VIDEO_EXTENSIONS' in PartCAD).
    """
    try:
        cores = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        cores = os.cpu_count() or 1
    return _number(request, "threads", max(1, min(cores, 64)), low=1, high=64, integer=True)


# The scene every frame is drawn from - the object tessellated, centred and lit,
# the most of the work after the frames themselves - as PartCAD keeps it between
# videos, always (see 'output.VIDEO_EXTENSIONS' in PartCAD): handed in under
# 'scene' when it has one for this object at this size, and asked for under
# 'scene_wanted' when it has not, in which case the answer carries it, as bytes,
# under 'scene'. The frames themselves are never kept anywhere (see
# 'frame_schedule').
SCENE_KEY = "scene"
SCENE_WANTED_KEY = "scene_wanted"


# What share of the memory available when a video starts its frames may take,
# when nothing says otherwise ('memory'): half, leaving the other half for
# whatever else this machine is doing - other renders among it.
MEMORY_SHARE = 0.5

# What is assumed to be available where the machine does not say.
MEMORY_UNKNOWN = 2 << 30


def memory_budget(request):
    """How many bytes the frames may take while they are drawn: 'memory' (megabytes), or a share of what is free.

    What is free is asked when the frames are about to start, after the object
    has been made ready to be drawn, so what that took is not counted twice.
    """
    megabytes = _number(request, "memory", None, low=1)
    if megabytes is not None:
        return int(megabytes * (1 << 20))
    available = available_memory()
    return int(MEMORY_SHARE * (available if available is not None else MEMORY_UNKNOWN))


def available_memory():
    """How many bytes of memory this process could have now, or None where that cannot be told.

    The least of what the machine has available and what the control group it
    runs in - a container, say - still allows.
    """
    found = []
    try:
        with open("/proc/meminfo") as stream:
            for line in stream:
                if line.startswith("MemAvailable:"):
                    found.append(int(line.split()[1]) * 1024)
                    break
    except (OSError, ValueError, IndexError):
        pass
    for limit_path, usage_path in (
        ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory.current"),
        ("/sys/fs/cgroup/memory/memory.limit_in_bytes", "/sys/fs/cgroup/memory/memory.usage_in_bytes"),
    ):
        try:
            with open(limit_path) as stream:
                limit = stream.read().strip()
            with open(usage_path) as stream:
                usage = int(stream.read().strip())
        except (OSError, ValueError):
            continue
        # 'max', or the near-infinite number cgroup v1 reports, is no limit at all.
        if limit.isdigit() and int(limit) < (1 << 60):
            found.append(max(0, int(limit) - usage))
        break
    if not found and sys.platform == "win32":
        found.append(_windows_available_memory())
    if not found and hasattr(os, "sysconf"):
        try:
            # macOS says how much there is, not how much is free: half of it.
            found.append(os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") // 2)
        except (OSError, ValueError):
            pass
    found = [value for value in found if value]
    return min(found) if found else None


def _windows_available_memory():  # pragma: no cover - exercised on Windows only
    import ctypes

    class _MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = _MemoryStatus()
    status.dwLength = ctypes.sizeof(_MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return int(status.ullAvailPhys)


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
    # A frame is a shaded picture; a drawing of lines is fitted to each one's
    # own extent, and would not hold still from one frame to the next.
    if render_raster.style_of({"style": request.get("style") or "shaded"}) != "shaded":
        raise OptionError("a video is drawn in the 'shaded' style, not %r" % request.get("style"))
    width, height = video_size(request)
    fps = _number(request, "fps", DEFAULT_FPS, low=1, high=MAX_FPS)
    speed = _vector(request, "speed", DEFAULT_SPEED)
    duration = duration_of(request, speed)
    count = max(1, int(round(duration * fps)))
    preset = request.get("preset") or video_encode.DEFAULT_PRESET
    video_encode.preset_index(preset)
    quality = video_encode.quality_of(request.get("quality"))
    bitrate = _number(request, "bitrate", None, low=1)
    audio_bitrate = _number(request, "audio_bitrate", 192, low=8, high=1024)
    fade_color = render_raster.rgb_of({"fade_color": request.get("fade_color") or "#000000"}, "fade_color")
    fade_in = _number(request, "fade_in", 0.0, low=0)
    fade_out = _number(request, "fade_out", 0.0, low=0)
    # What every frame is a picture of, its fields checked before anything takes
    # time: where the turn starts, unless the video appended to says otherwise.
    picture = dict(request)
    picture.setdefault("background", DEFAULT_BACKGROUND)
    shaded = render_raster.Shaded(picture, width, height)
    start = shaded.turn

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
                "starts at 'turn'" % (container, path)
            )
        else:
            warnings.append(
                "'%s' does not say where its turn stopped - PartCAD did not write it - so the part appended to it "
                "starts at 'turn'" % path
            )
    previous_count = 0
    if previous is not None:
        previous_count = int(round((previous["duration"] or 0.0) * fps))

    # The object made ready to be drawn - or the scene PartCAD kept of it from
    # an earlier video, read back (see 'SCENE_KEY').
    shaded.build(warnings, scene=request.get(SCENE_KEY))

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
        # How the frames are drawn: on as many threads, and as many at once, as
        # the memory left after the object was made ready holds.
        the_plan = frame_schedule.plan(shaded.painter(), threads_of(request), memory_budget(request))
        if not the_plan.fits:
            warnings.append(
                "A frame of %dx%d at 'antialias: %d' takes about %d MB to draw, more than the %d MB it was given "
                "('memory'); it is drawn by one thread, a band at a time"
                % (width, height, shaded.antialias, the_plan.needed >> 20, the_plan.budget >> 20)
            )
        prefix = ()
        if previous is not None:
            # A bound, so that a file whose timestamps are wrong cannot have the
            # frame rate converter fill hours: the length it says it is, and a
            # second.
            prefix = video_encode.decode_frames(path, width, height, fps, limit=previous_count + int(fps) + 1)
        try:
            written_before, written = pipeline.run(
                frames(shaded, the_plan, start, speed, fps, count, fade_in, fade_out, fade_color), prefix=prefix
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
    # Where the first new frame is looked at from, as a picture's result says it.
    result["viewport"] = shaded.viewport(start)
    result["video"] = {
        "width": width,
        "height": height,
        "fps": fps,
        "frames": written,
        "appended_to": written_before if previous is not None else None,
        "seconds": (written_before + written) / float(fps),
        "start_angle": list(start),
        "end_angle": list(end),
        "triangles": shaded.scene.triangle_count,
        # How the frames were drawn (see 'frame_schedule.plan').
        "threads": the_plan.workers,
        "bands": the_plan.bands,
        "frames_at_once": the_plan.frames,
        # The first new frame, as the fields 'pc render -t png' draws it with:
        # frame 'k' of them is the same with 'turn' grown by 'speed' times k / fps.
        "picture": shaded.fields(start),
        "speed": list(speed),
        "scene_reused": shaded.reused,
    }
    if request.get(SCENE_WANTED_KEY) and not shaded.reused:
        result[SCENE_KEY] = shaded.scene_bytes()
    return result
