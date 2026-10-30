#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The video options of 'pc render': how a video of an object is made, for this one run.

Each is a field of the video file types of '//builtin/render' ('mp4', 'mov',
'webm', ...), which a package declares once in its 'render:' section and these
override - so they mean exactly what the fields mean, and a file type that is
not a video ignores them, as a video ignores '--with-ports'. What each one
accepts is the implementation's to say ('render_video.py'); what is checked here
is only what can be checked without it, so that a typo costs a message rather
than a round trip to the daemon.

The preset names are inlined rather than imported for the reason 'viewport.py'
gives: the client does not load the package that renders.
"""

import rich_click as click

# x264's names for the trade between encoding time and file size, fastest
# first; the twin of 'PRESETS' in '//builtin/render/video_encode.py'.
PRESETS = ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"]


def speed_vector(ctx, param, value):
    """'X,Y,Z' degrees a second as three floats; one number is about Z alone."""
    if value is None:
        return None
    try:
        vector = [float(component) for component in value.replace(",", " ").split()]
    except ValueError:
        raise click.BadParameter("expected 'X,Y,Z' or one number, got: %s" % value, ctx=ctx, param=param) from None
    if len(vector) == 1:
        return [0.0, 0.0, vector[0]]
    if len(vector) != 3:
        raise click.BadParameter("expected 'X,Y,Z' or one number, got: %s" % value, ctx=ctx, param=param)
    return vector


_OPTIONS = (
    click.option(
        "--size",
        help=(
            "The size of a video, by where it is going: reels (the default: also shorts, tiktok, story, "
            "vertical), portrait, square, pinterest, landscape (also youtube), 720p, 1080p, 1440p, 4k, "
            "4:3, 21:9 -- or WIDTHxHEIGHT"
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
        callback=speed_vector,
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
        help="How much of the picture survives a video's encoder, 0 to 100 (65 by default)",
        type=click.FloatRange(min=0, max=100),
        show_envvar=True,
    ),
)


def video_options(command):
    """Add the video options to a command, in the order they read in '--help'."""
    for option in reversed(_OPTIONS):
        command = option(command)
    return command


def video_params(size, fps, duration, speed, append, preset, quality):
    """The video options as JSON-RPC params, so every caller sends the same names."""
    return {
        "size": size,
        "fps": fps,
        "duration": duration,
        "speed": speed,
        "append": append,
        "preset": preset,
        "quality": quality,
    }
