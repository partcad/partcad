#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The picture and video options of 'pc render': how a raster or a video of an object is made, for this one run.

Each is a field of the raster file types ('png', 'jpeg') or of the video ones
('mp4', 'mov', 'webm', ...) of '//builtin/render', which a package declares once
in its 'render:' section and these override - so they mean exactly what the
fields mean. Like '--view', each is handed to every file type a run renders, and
means something to the ones that have a field of that name: '--style',
'--size' and '--background' to a picture and a video alike, which draw their
pictures the same way ('render_raster.py'), '--quality' to a video and a JPEG,
whose 'quality' is the same 0 to 100, and the rest to a video. What each one
accepts is the implementation's to say; what is checked here is only what can
be checked without it, so that a typo costs a message rather than a round trip
to the daemon.

The preset and style names are inlined rather than imported for the reason
'viewport.py' gives: the client does not load the package that renders.
"""

import rich_click as click

from .viewport import turn_vector

# x264's names for the trade between encoding time and file size, fastest
# first; the twin of 'PRESETS' in '//builtin/render/video_encode.py'.
PRESETS = ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"]

# How a picture is drawn; the twin of 'STYLES' in '//builtin/render/render_raster.py'.
STYLES = ["lines", "shaded"]

_OPTIONS = (
    click.option(
        "--style",
        help=(
            "How a picture is drawn: lines (the projection's visible edges, what a PNG or a JPEG is by "
            "default) or shaded (lit and in perspective, as the Digital Thread's 3D view draws it - and "
            "as every frame of a video is drawn)"
        ),
        type=click.Choice(STYLES),
        show_envvar=True,
    ),
    click.option(
        "--size",
        help=(
            "The size of a picture or a video, by where it is going: reels (a video's default: also shorts, "
            "tiktok, story, vertical), portrait, square, pinterest, landscape (also youtube), 720p, 1080p, "
            "1440p, 4k, 4:3, 21:9 -- or WIDTHxHEIGHT (a picture's default is 512x512)"
        ),
        type=str,
        show_envvar=True,
    ),
    click.option(
        "--background",
        help=(
            "What a picture or a video is drawn on, as '#RRGGBB': white for a PNG or a JPEG, the editor's "
            "#1F1F1F for a video"
        ),
        type=str,
        show_envvar=True,
    ),
    click.option(
        "--fps",
        help="Frames a second of a video (30 by default)",
        type=click.FloatRange(min=1, max=240),
        show_envvar=True,
    ),
    click.option(
        "--duration",
        help="How many seconds long a video is. One turn of the fastest-turning axis by default",
        type=click.FloatRange(min=0, min_open=True),
        show_envvar=True,
    ),
    click.option(
        "--speed",
        help=(
            "How fast the object turns in a video, in degrees a second about X, Y and Z, as 'X,Y,Z' -- "
            "or one number, about Z. 30 about Z by default, as the 3D view's Animate turns it"
        ),
        type=str,
        callback=turn_vector,
        show_envvar=True,
    ),
    click.option(
        "--append",
        help=(
            "Add to the video already at the output path instead of writing it again, carrying on its "
            "turn from where it stopped"
        ),
        is_flag=True,
        default=None,
        show_envvar=True,
    ),
    click.option(
        "--preset",
        help="The trade between how long a video takes to encode and how small it is (medium by default)",
        type=click.Choice(PRESETS),
        show_envvar=True,
    ),
    click.option(
        "--quality",
        help=(
            "How much of the picture survives a video's encoder, 0 to 100 (65 by default). Like the other "
            "options here it is handed to every file type rendered, so it sets a JPEG's quality too"
        ),
        type=click.FloatRange(min=0, max=100),
        show_envvar=True,
    ),
)


def video_options(command):
    """Add the picture and video options to a command, in the order they read in '--help'."""
    for option in reversed(_OPTIONS):
        command = option(command)
    return command


def video_params(style, size, background, fps, duration, speed, append, preset, quality):
    """The picture and video options as JSON-RPC params, so every caller sends the same names."""
    return {
        "style": style,
        "size": size,
        "background": background,
        "fps": fps,
        "duration": duration,
        "speed": speed,
        "append": append,
        "preset": preset,
        "quality": quality,
    }
