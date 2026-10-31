#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Turning frames into a video file, with GStreamer.

'render_video.py' draws the frames; everything after that - the codec, the
container, the text over the picture, the logo in its corner, the music under it,
and appending to a video that is already there - is GStreamer's, run as
'gst-launch-1.0' with the frames on its standard input. This module only builds
the pipelines, runs them, and reads back what a finished file says about itself.

GStreamer is not a Python package, so pip cannot put it in a sandbox. It is
found where the sandbox runs ('find_tool'): on the PATH, where a GStreamer
installer puts it on each operating system, or wherever 'PC_GSTREAMER' says.
Where Docker runs PartCAD's sandboxes, the video file types run in PartCAD's
GStreamer image, which carries it (see 'dockerImage' in '//builtin/render').

Which elements this machine's GStreamer has is asked of it ('has_element'), and
each codec names the encoders that can write it in order of preference, so that
a GStreamer without x264 (a build that leaves out the GPL plugins) still writes
H.264 with OpenH264.

Nothing here imports anything but the standard library, and numpy where frames
and samples are handled: it is tested without the CAD stack, and 'pc
healthcheck' asks it where GStreamer is from a PartCAD that has no numpy. Nor
from one that has all of the standard library: a frozen bundle carries only
the modules its own code imports, and this file is data to it, so what only the
sandbox side needs ('wave') is imported where it is used.
"""

import functools
import os
import re
import shutil
import socket
import subprocess
import tempfile

LAUNCH = "gst-launch-1.0"
INSPECT = "gst-inspect-1.0"
DISCOVERER = "gst-discoverer-1.0"

# Where to look for GStreamer before giving up: a path to 'gst-launch-1.0' or to
# the directory holding it. For a machine with GStreamer somewhere none of the
# places below are.
ENV_VAR = "PC_GSTREAMER"

# Where the official installers put the tools, for a GStreamer that is installed
# but not on the PATH - which on macOS and Windows is the usual case.
KNOWN_DIRECTORIES = (
    "/Library/Frameworks/GStreamer.framework/Commands",
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "C:\\gstreamer\\1.0\\msvc_x86_64\\bin",
    "C:\\Program Files\\gstreamer\\1.0\\msvc_x86_64\\bin",
)
# And the variables those installers set on Windows.
ROOT_VARIABLES = ("GSTREAMER_1_0_ROOT_MSVC_X86_64", "GSTREAMER_1_0_ROOT_X86_64", "GSTREAMER_1_0_ROOT_MINGW_X86_64")

# What a video says about where its turn stopped, so that a video appended to it
# starts from there. A tag of the container: the comment, in most of them. See
# 'state_text'.
STATE_MARKER = "partcad-video/1"

# The same, in an Ogg file, as Vorbis comments: the key-value pairs every Ogg
# codec carries in a header of its own (see 'write_comments'). One pair per
# value, rather than 'STATE_MARKER''s sentence in a COMMENT, because that is
# what the format is made of: a reader of the file sees PARTCAD_ANGLES and its
# value, as it sees TITLE and its. PARTCAD_VIDEO is the version of what the
# others mean, as 'STATE_MARKER''s '/1' is.
COMMENT_VERSION = "PARTCAD_VIDEO"
COMMENT_ANGLES = "PARTCAD_ANGLES"
COMMENT_FRAMES = "PARTCAD_FRAMES"
COMMENT_FPS = "PARTCAD_FPS"
COMMENT_TITLE = "TITLE"

# The audio every file is mixed in: what a soundtrack is decoded to, cut, faded
# and written as WAV in, before the encoder of the container's choice takes it.
AUDIO_RATE = 48000
AUDIO_CHANNELS = 2

# The containers PartCAD writes, by the name a file type's 'container' gives:
#
#   'muxer'      the GStreamer element that writes it, and its properties;
#   'video'      the codecs it carries, the default first;
#   'audio'      likewise for the soundtrack;
#   'state_tag'  the tag where where a turn stopped is kept. Each muxer keeps
#                some tags and drops the rest without a word, so this is the
#                one this muxer was found to keep: the comment everywhere it is
#                kept, and the album for ASF, which drops the comment. None for
#                Ogg, which keeps none of them -
#   'comments'   - and keeps its state as Vorbis comments instead, written
#                into the video's comment header once the file is (see
#                'write_comments'). GStreamer's Theora encoder writes no tags,
#                and the Vorbis and Opus ones only into a soundtrack's header,
#                which a video need not have.
#   'faststart'  whether the index goes at the front, so that a browser or a
#                social network can start playing before it has the whole file.
#
# ASF - WMV - carries no soundtrack here. GStreamer's own ASF muxer drops video
# frames once it interleaves audio with them - a few in thirty, and a different
# few with every packet size tried - and libav's writes timestamps that make a
# second of video two thousand hours long. Without audio the first is sound.
CONTAINERS = {
    "mp4": {"muxer": "mp4mux", "video": ("h264", "h265"), "audio": ("aac", "mp3"), "state_tag": "comment", "faststart": True},
    "mov": {"muxer": "qtmux", "video": ("h264", "h265", "mjpeg"), "audio": ("aac", "mp3"), "state_tag": "comment", "faststart": True},
    "mkv": {"muxer": "matroskamux", "video": ("h264", "h265", "vp9", "vp8", "theora"), "audio": ("aac", "opus", "vorbis", "mp3"), "state_tag": "comment"},
    "webm": {"muxer": "webmmux", "video": ("vp9", "vp8"), "audio": ("opus", "vorbis"), "state_tag": "comment"},
    "avi": {"muxer": "avimux", "video": ("h264", "mjpeg", "mpeg4"), "audio": ("mp3",), "state_tag": "comment"},
    "asf": {"muxer": "asfmux", "video": ("wmv2",), "audio": (), "state_tag": "album"},
    "ogg": {"muxer": "oggmux", "video": ("theora",), "audio": ("vorbis", "opus"), "state_tag": None, "comments": True},
}  # fmt: skip

# The codecs, by name: the encoders that write each one, best first, the parser
# that has to follow the encoder for the muxer to accept what it writes, and the
# caps between them.
VIDEO_CODECS = {
    "h264": {"encoders": ("x264enc", "openh264enc"), "parse": "h264parse", "caps": "video/x-h264,profile=high"},
    "h265": {"encoders": ("x265enc",), "parse": "h265parse", "caps": None},
    "vp9": {"encoders": ("vp9enc",), "parse": None, "caps": None},
    "vp8": {"encoders": ("vp8enc",), "parse": None, "caps": None},
    "theora": {"encoders": ("theoraenc",), "parse": None, "caps": None},
    "wmv2": {"encoders": ("avenc_wmv2",), "parse": None, "caps": None},
    "mjpeg": {"encoders": ("jpegenc",), "parse": None, "caps": None},
    "mpeg4": {"encoders": ("avenc_mpeg4",), "parse": "mpeg4videoparse", "caps": None},
}
AUDIO_CODECS = {
    "aac": {"encoders": ("avenc_aac", "voaacenc", "fdkaacenc"), "parse": "aacparse"},
    "mp3": {"encoders": ("lamemp3enc",), "parse": "mpegaudioparse"},
    "opus": {"encoders": ("opusenc",), "parse": None},
    "vorbis": {"encoders": ("vorbisenc",), "parse": None},
    "wma": {"encoders": ("avenc_wmav2",), "parse": None},
}

# The trade between how long encoding takes and how small the file comes out,
# in x264's words, which are the ones most people know: each step is roughly
# twice the time of the one before it for a few percent less file. Every encoder
# is told the nearest thing it has.
PRESETS = ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow")
DEFAULT_PRESET = "medium"

# How much of the picture survives the encoder, from 0 to 100. What it means to
# each encoder is in 'video_encoder'; the default is x264's CRF 18, which is
# usually taken to be visually lossless - what a video uploaded somewhere that
# encodes it again should be.
DEFAULT_QUALITY = 65

# A keyframe every this many seconds: what a player can start from, and what a
# social network cuts a preview at.
KEYFRAME_SECONDS = 2

# How long a pipeline is given to connect to the socket the frames before the new
# ones are handed to it over, at a time: it is checked for having died meanwhile.
CONNECT_TIMEOUT = 5


class GStreamerError(Exception):
    """GStreamer is missing, lacks what a file needs, or failed writing it."""


def escape(value):
    """'value' as the inside of a double-quoted string of a GStreamer pipeline."""
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def prop(name, value):
    """A property of an element, quoted: '<name>="<value>"'.

    'gst-launch-1.0' joins its arguments into one pipeline description, and a
    value with a space in it - a font, a path - is one value only when the whole
    of it is quoted.
    """
    return '%s="%s"' % (name, escape(value))


# ---------------------------------------------------------------------------
# Finding GStreamer
# ---------------------------------------------------------------------------


def find_tool(name=LAUNCH, environ=None):
    """The path of one of GStreamer's tools, or None if this machine has none.

    Looked for where 'PC_GSTREAMER' says, on the PATH, beside 'gst-launch-1.0' if
    that was found, and where the installers put it.
    """
    environ = os.environ if environ is None else environ
    candidates = []
    configured = (environ.get(ENV_VAR) or "").strip()
    if configured:
        candidates.append(configured if os.path.isdir(configured) else os.path.dirname(configured))
    for variable in ROOT_VARIABLES:
        root = (environ.get(variable) or "").strip()
        if root:
            candidates.append(os.path.join(root, "bin"))
    for directory in candidates:
        found = shutil.which(name, path=directory)
        if found:
            return found
    found = shutil.which(name, path=environ.get("PATH"))
    if found:
        return found
    for directory in KNOWN_DIRECTORIES:
        if os.path.isdir(directory):
            found = shutil.which(name, path=directory)
            if found:
                return found
    return None


MISSING = (
    "GStreamer is not installed where this video is rendered: '%s' was not found on the PATH, in '%s', or where "
    "GStreamer's installers put it. Install GStreamer with its 'good', 'bad', 'ugly' and 'libav' plugins "
    "(on Debian and Ubuntu: apt install gstreamer1.0-tools gstreamer1.0-plugins-good gstreamer1.0-plugins-bad "
    "gstreamer1.0-plugins-ugly gstreamer1.0-libav gstreamer1.0-x), or render with Docker running, where the video "
    "file types run in PartCAD's GStreamer image."
)


def launcher():
    """'gst-launch-1.0', or GStreamerError saying how to get it."""
    found = find_tool(LAUNCH)
    if not found:
        raise GStreamerError(MISSING % (LAUNCH, ENV_VAR))
    return found


@functools.lru_cache(maxsize=None)
def has_element(name):
    """Whether this machine's GStreamer has the element 'name'."""
    inspect = find_tool(INSPECT)
    if not inspect:
        # Without the inspector there is no asking; assume the element is there
        # and let the pipeline say otherwise.
        return True
    try:
        return subprocess.run([inspect, "--exists", name], capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return True


def first_element(names, what):
    """The first of 'names' this GStreamer has, or GStreamerError naming 'what' needs one."""
    for name in names:
        if has_element(name):
            return name
    raise GStreamerError(
        "GStreamer here has none of %s, which %s needs: install the GStreamer plugins that provide %s"
        % (", ".join(names), what, "it" if len(names) == 1 else "one of them")
    )


# ---------------------------------------------------------------------------
# Encoders
# ---------------------------------------------------------------------------


def preset_index(preset):
    """Where 'preset' is among 'PRESETS', 0 being the fastest."""
    text = str(preset or DEFAULT_PRESET).strip().lower()
    if text not in PRESETS:
        raise ValueError("'preset' is one of %s, not %r" % (", ".join(PRESETS), preset))
    return PRESETS.index(text)


def quality_of(quality):
    """'quality' as a number from 0 to 100."""
    value = DEFAULT_QUALITY if quality is None else float(quality)
    if not 0 <= value <= 100:
        raise ValueError("'quality' is a number from 0 to 100, not %r" % (quality,))
    return value


def video_encoder(element, preset, quality, bitrate, fps, width, height, threads=0):
    """The encoder element and its properties, as pipeline tokens.

    'preset' trades time for size ('PRESETS'); 'quality' (0-100) is how much of
    the picture survives, as each encoder's own constant-quality setting -
    x264's and x265's CRF of 51 * (100 - quality) / 100, libvpx's constant
    quality level of 63 * (100 - quality) / 100, Theora's quality of 63 *
    quality / 100, JPEG's quality - or, for an encoder that has none, a bitrate
    worked out from it. 'bitrate', in kbit/s, asks for that bitrate instead.
    """
    speed = preset_index(preset)
    quality = quality_of(quality)
    keyframes = max(1, int(round(fps * KEYFRAME_SECONDS)))
    # Bits a pixel of a frame is worth, where an encoder has to be told a
    # bitrate: from a fiftieth of a bit to three tenths, rising with quality.
    estimate = int((0.02 + 0.28 * (quality / 100.0) ** 2) * width * height * fps / 1000.0)
    kbps = int(bitrate) if bitrate else estimate
    tokens = [element]
    if element in ("x264enc", "x265enc"):
        tokens.append("speed-preset=%s" % PRESETS[speed])
        tokens.append("key-int-max=%d" % keyframes)
        crf = int(round(51 * (100 - quality) / 100.0))
        if element == "x264enc":
            if bitrate:
                tokens.append("bitrate=%d" % kbps)
            else:
                # 'qual' is x264's constant-quality mode, and 'quantizer' its CRF.
                tokens += ["pass=qual", "quantizer=%d" % crf]
        else:
            tokens.append(prop("option-string", "bitrate=%d" % kbps if bitrate else "crf=%d" % crf))
    elif element in ("vp8enc", "vp9enc"):
        tokens.append("deadline=1000000")
        tokens.append("cpu-used=%d" % max(0, 8 - speed))
        tokens.append("keyframe-max-dist=%d" % keyframes)
        if threads:
            tokens.append("threads=%d" % threads)
        if element == "vp9enc":
            tokens.append("row-mt=true")
        if bitrate:
            tokens += ["end-usage=vbr", "target-bitrate=%d" % (kbps * 1000)]
        else:
            # Constrained quality: the level is what is aimed for, and the
            # bitrate only a ceiling over it - set to what the best quality is
            # worth, so that it never decides.
            ceiling = int(0.3 * width * height * fps)
            level = int(round(63 * (100 - quality) / 100.0))
            tokens += ["end-usage=cq", "cq-level=%d" % level, "target-bitrate=%d" % ceiling]
    elif element == "theoraenc":
        tokens.append("speed-level=%d" % (2 if speed <= 2 else 1 if speed <= 5 else 0))
        tokens.append("keyframe-force=%d" % keyframes)
        if bitrate:
            tokens.append("bitrate=%d" % kbps)
        else:
            tokens.append("quality=%d" % int(round(63 * quality / 100.0)))
    elif element == "openh264enc":
        tokens.append("complexity=%s" % ("low" if speed <= 2 else "medium" if speed <= 5 else "high"))
        tokens.append("bitrate=%d" % (kbps * 1000))
        tokens.append("gop-size=%d" % keyframes)
    elif element == "jpegenc":
        tokens.append("quality=%d" % int(round(quality)))
    elif element.startswith("avenc_"):
        tokens.append("bitrate=%d" % (kbps * 1000))
        tokens.append("gop-size=%d" % keyframes)
    return tokens


def audio_encoder(element, bitrate):
    """The audio encoder element and its properties, at 'bitrate' kbit/s."""
    kbps = int(bitrate)
    if element == "lamemp3enc":
        return [element, "target=bitrate", "cbr=true", "bitrate=%d" % kbps]
    if element in ("opusenc", "vorbisenc", "voaacenc", "fdkaacenc") or element.startswith("avenc_"):
        return [element, "bitrate=%d" % (kbps * 1000)]
    return [element]


def codec_for(container, codec, kind):
    """The codec a file of 'container' is written with: 'codec' if it carries it, its default if 'codec' is None."""
    carried = CONTAINERS[container][kind]
    if not carried:
        raise ValueError("A '%s' file carries no %s here" % (container, "video" if kind == "video" else "soundtrack"))
    if codec is None:
        return carried[0]
    codec = str(codec).strip().lower()
    if codec not in carried:
        raise ValueError(
            "A '%s' file carries %s %s, not '%s'"
            % (container, "the video codecs" if kind == "video" else "the audio codecs", ", ".join(carried), codec)
        )
    return codec


# ---------------------------------------------------------------------------
# What a file says about itself
# ---------------------------------------------------------------------------


def state_text(angles, frames, fps):
    """What a video keeps about where its turn stopped: the angle its next frame would be drawn at.

    The next frame's rather than the last one's, so that a video appended to this
    one starts where this one would have gone on, and no angle is shown twice.
    """
    return "%s angles=%s frames=%d fps=%s" % (
        STATE_MARKER,
        ",".join("%.6g" % angle for angle in angles),
        int(frames),
        "%.6g" % fps,
    )


_STATE = re.compile(re.escape(STATE_MARKER) + r"\s+angles=([-+0-9.eE]+),([-+0-9.eE]+),([-+0-9.eE]+)")


def parse_state(text):
    """The '(x, y, z)' angles 'state_text' wrote, found anywhere in 'text'; None if it is not there."""
    match = _STATE.search(text or "")
    if not match:
        return None
    return tuple(float(group) for group in match.groups())


def keeps_state(container):
    """Whether a file of 'container' can say where its turn stopped."""
    spec = CONTAINERS[container]
    return bool(spec["state_tag"] or spec.get("comments"))


def state_comments(angles, frames, fps):
    """What 'state_text' says, as the Vorbis comments an Ogg file keeps it in: '[(key, value)]'."""
    return [
        (COMMENT_VERSION, "1"),
        (COMMENT_ANGLES, ",".join("%.6g" % angle for angle in angles)),
        (COMMENT_FRAMES, "%d" % int(frames)),
        (COMMENT_FPS, "%.6g" % fps),
    ]


def comments_state(comments):
    """The '(x, y, z)' angles 'state_comments' wrote, out of '{KEY: value}'; None if they are not there."""
    if comments.get(COMMENT_VERSION) != "1" or COMMENT_ANGLES not in comments:
        return None
    try:
        angles = tuple(float(value) for value in comments[COMMENT_ANGLES].split(","))
    except ValueError:
        return None
    return angles if len(angles) == 3 else None


def read_state(path, text=""):
    """Where the turn of the video at 'path' stopped, or None if it does not say.

    From its Vorbis comments, for an Ogg file, and from what the discoverer
    printed of its tags ('text', see 'discover') for anything else.
    """
    with open(path, "rb") as stream:
        ogg = stream.read(4) == OGG_CAPTURE
    if ogg:
        return comments_state(read_comments(path))
    return parse_state(text)


def discover(path):
    """What GStreamer finds in the video at 'path': '{duration, video, audio, text}'.

    'duration' in seconds, whether it has a video and an audio stream, and the
    whole of what the discoverer printed - the tags among it - for 'parse_state'.
    """
    tool = find_tool(DISCOVERER)
    if not tool:
        raise GStreamerError(MISSING % (DISCOVERER, ENV_VAR))
    try:
        run = subprocess.run([tool, "-v", path], capture_output=True, timeout=300)
    except subprocess.SubprocessError as e:
        raise GStreamerError("Could not read '%s': %s" % (path, e)) from e
    text = run.stdout.decode("utf-8", "replace")
    if run.returncode != 0:
        raise GStreamerError("Could not read '%s': %s" % (path, (text + run.stderr.decode("utf-8", "replace"))[-500:]))
    duration = None
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if match:
        duration = int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))
    return {
        "duration": duration,
        "video": bool(re.search(r"^\s*video #\d+", text, re.MULTILINE)),
        "audio": bool(re.search(r"^\s*audio #\d+", text, re.MULTILINE)),
        "text": text,
    }


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------


def decode_audio(path, seconds=None, start=0.0):
    """The audio of the file at 'path' as float samples, (frames, channels), from 'start' for 'seconds'.

    Decoded by GStreamer, so anything it can play will do - an MP3, the
    soundtrack of a video. Only as much as is asked for is read: the decoder is
    stopped once it has written that much, so cutting a few seconds out of a long
    track does not decode the rest of it.
    """
    import numpy as np

    argv = [
        launcher(),
        "-q",
        "filesrc",
        prop("location", path),
        "!",
        "decodebin",
        "!",
        "audioconvert",
        "!",
        "audioresample",
        "!",
        "audio/x-raw,format=S16LE,layout=interleaved,rate=%d,channels=%d" % (AUDIO_RATE, AUDIO_CHANNELS),
        "!",
        "fdsink",
        "fd=1",
    ]
    frame_bytes = 2 * AUDIO_CHANNELS
    skip = int(round(max(0.0, float(start)) * AUDIO_RATE)) * frame_bytes
    wanted = None if seconds is None else skip + int(round(seconds * AUDIO_RATE)) * frame_bytes
    chunks, read = [], 0
    # What it says goes to a file rather than a pipe: a pipe nobody reads while
    # the samples are being read fills, and the decoder stops writing either.
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=errors)
        try:
            while wanted is None or read < wanted:
                chunk = process.stdout.read(1 << 20 if wanted is None else min(1 << 20, wanted - read))
                if not chunk:
                    break
                chunks.append(chunk)
                read += len(chunk)
        finally:
            if wanted is not None and read >= wanted and process.poll() is None:
                process.kill()
            process.stdout.close()
            process.wait()
        if process.returncode != 0 and not (wanted is not None and read >= wanted):
            errors.seek(0)
            raise GStreamerError(
                "Could not decode the audio of '%s': %s" % (path, errors.read().decode("utf-8", "replace")[-500:])
            )
    data = b"".join(chunks)
    data = data[skip : len(data) - (len(data) % frame_bytes)] if len(data) > skip else b""
    samples = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
    return samples.reshape(-1, AUDIO_CHANNELS)


def fit_audio(samples, seconds, loop=False):
    """'samples' cut or padded to 'seconds': looped to fill it if 'loop', and silence after it otherwise."""
    import numpy as np

    wanted = int(round(seconds * AUDIO_RATE))
    if len(samples) >= wanted:
        return samples[:wanted]
    if loop and len(samples):
        repeats = -(-wanted // len(samples))
        return np.tile(samples, (repeats, 1))[:wanted]
    return np.concatenate([samples, np.zeros((wanted - len(samples), AUDIO_CHANNELS), dtype=np.float32)])


def fade_audio(samples, fade_in=0.0, fade_out=0.0, volume=1.0):
    """'samples' at 'volume', faded in and out over that many seconds."""
    import numpy as np

    samples = samples * np.float32(volume)
    count = len(samples)
    for seconds, rising in ((fade_in, True), (fade_out, False)):
        length = min(count, int(round(max(0.0, float(seconds or 0)) * AUDIO_RATE)))
        if length <= 0:
            continue
        ramp = np.linspace(0.0, 1.0, length, dtype=np.float32)[:, None]
        if rising:
            samples[:length] *= ramp
        else:
            samples[count - length :] *= ramp[::-1]
    return samples


def write_wav(path, samples):
    """'samples' as a 16-bit WAV file, which is what the encoding pipeline reads the soundtrack from."""
    import wave

    import numpy as np

    data = (np.clip(samples, -1.0, 1.0) * 32767.0).round().astype("<i2").tobytes()
    with wave.open(path, "wb") as out:
        out.setnchannels(AUDIO_CHANNELS)
        out.setsampwidth(2)
        out.setframerate(AUDIO_RATE)
        out.writeframes(data)


# ---------------------------------------------------------------------------
# Text and images over the picture
# ---------------------------------------------------------------------------


def srt_time(seconds):
    millis = int(round(max(0.0, seconds) * 1000))
    hours, millis = divmod(millis, 3600000)
    minutes, millis = divmod(millis, 60000)
    secs, millis = divmod(millis, 1000)
    return "%02d:%02d:%02d,%03d" % (hours, minutes, secs, millis)


def srt(cues):
    """'[(start, end, text)]' as a SubRip file, which is how a text is timed on the picture."""
    blocks = []
    for index, (start, end, text) in enumerate(cues, start=1):
        blocks.append("%d\n%s --> %s\n%s\n" % (index, srt_time(start), srt_time(end), str(text).strip() or " "))
    return "\n".join(blocks) + "\n"


def argb(color, alpha=1.0):
    """A colour as the 0xAARRGGBB integer 'textoverlay' takes."""
    digits = str(color).strip().lstrip("#")
    if len(digits) == 3:
        digits = "".join(digit * 2 for digit in digits)
    if len(digits) not in (6, 8):
        raise ValueError("Not a colour: %r" % (color,))
    value = int(digits[:6], 16)
    a = int(digits[6:8], 16) if len(digits) == 8 else int(round(alpha * 255))
    return "0x%08X" % ((a << 24) | value)


def image_size(path):
    """'(width, height)' of a PNG or a JPEG, read from its header; None for anything else."""
    try:
        with open(path, "rb") as stream:
            head = stream.read(32)
            if head.startswith(b"\x89PNG\r\n\x1a\n") and head[12:16] == b"IHDR":
                return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
            if not head.startswith(b"\xff\xd8"):
                return None
            stream.seek(2)
            while True:
                marker = stream.read(4)
                if len(marker) < 4 or marker[0] != 0xFF:
                    return None
                length = int.from_bytes(marker[2:4], "big")
                if marker[1] in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    data = stream.read(5)
                    return int.from_bytes(data[3:5], "big"), int.from_bytes(data[1:3], "big")
                stream.seek(length - 2, os.SEEK_CUR)
    except OSError:
        return None


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------


class Pipeline:
    """One encoding run: frames in on standard input, a video file out.

    'video' is the chain the raw frames go through before the encoder - filters
    and overlays, as tokens (see 'render_video'); 'sources' are branches that
    feed them, such as the subtitle file a 'textoverlay' reads its text from;
    'prefix' says that frames are put before the new ones - those of the video
    being appended to, handed to 'run'; 'audio' is a WAV file to mux beside
    them; 'tags' the container's tags.
    """

    def __init__(
        self,
        output,
        container,
        width,
        height,
        fps,
        video_codec=None,
        audio_codec=None,
        preset=DEFAULT_PRESET,
        quality=None,
        bitrate=None,
        audio_bitrate=192,
        video=(),
        sources=(),
        prefix=False,
        audio=None,
        tags=None,
        threads=0,
    ):
        if container not in CONTAINERS:
            raise ValueError("Unknown container '%s'; one of %s" % (container, ", ".join(sorted(CONTAINERS))))
        self.output = output
        self.container = container
        self.width = int(width)
        self.height = int(height)
        self.fps = fps
        self.video_codec = codec_for(container, video_codec, "video")
        self.audio_codec = codec_for(container, audio_codec, "audio") if audio else None
        self.preset = preset
        self.quality = quality
        self.bitrate = bitrate
        self.audio_bitrate = audio_bitrate
        self.video = list(video)
        self.sources = list(sources)
        self.prefix = prefix
        self.port = None
        self.audio = audio
        self.tags = dict(tags or {})
        self.threads = threads

    @property
    def frame_bytes(self):
        return self.width * self.height * 3

    def framerate(self):
        """The frame rate as GStreamer's fraction."""
        fps = float(self.fps)
        if fps.is_integer():
            return "%d/1" % int(fps)
        return "%d/1000" % int(round(fps * 1000))

    def raw_caps(self):
        return "video/x-raw,format=I420,width=%d,height=%d,framerate=%s,pixel-aspect-ratio=1/1" % (
            self.width,
            self.height,
            self.framerate(),
        )

    def argv(self):
        """The whole command, ready to run."""
        spec = CONTAINERS[self.container]
        codec = VIDEO_CODECS[self.video_codec]
        encoder = first_element(codec["encoders"], "a '%s' video in %s" % (self.video_codec, self.container))
        muxer = first_element((spec["muxer"],), "a '%s' file" % self.container)

        # The new frames: raw RGB, a frame at a time, through the overlays.
        new = ["fdsrc", "fd=0", "blocksize=%d" % self.frame_bytes, "!"]
        new += [
            "rawvideoparse",
            "width=%d" % self.width,
            "height=%d" % self.height,
            "format=rgb",
            "framerate=%s" % self.framerate(),
            "!",
            "videoconvert",
            "!",
        ]
        for element in self.video:
            new += list(element) + ["!"]
        new += ["videoconvert", "!", self.raw_caps()]

        encode = ["queue", "!"]
        encode += video_encoder(
            encoder, self.preset, self.quality, self.bitrate, float(self.fps), self.width, self.height, self.threads
        )
        encode += ["!"]
        if codec["caps"] and encoder == "x264enc":
            encode += [codec["caps"], "!"]
        if codec["parse"]:
            encode += [codec["parse"], "!"]
        if self.tags:
            tags = ",".join('%s="%s"' % (key, escape(value)) for key, value in self.tags.items())
            encode += ["taginject", prop("tags", tags), "!"]
        encode += [muxer, "name=mux"]
        if spec.get("faststart"):
            encode.append("faststart=true")
        encode += ["!", "filesink", prop("location", self.output)]

        tokens = [launcher(), "-q", "-e"]
        if self.prefix:
            # The frames to put first, then the new ones: 'concat' plays its
            # inputs one after the other, in the order they were linked to it,
            # which is the order they are written in here. The overlays are on
            # the new frames' branch, so they are drawn on the new frames alone.
            #
            # The frames to put first arrive over a socket on this machine rather
            # than as the video they were decoded from: a demuxer sends what a
            # file's tags say ahead of its first frame, a muxer keeps the first
            # value it is told of each tag, and 'taginject' only ever adds - so a
            # video appended to through a decoder in this pipeline kept the state
            # of where its first part stopped turning, and lost the state of
            # where the new part did. Decoded frames carry no tags.
            tokens += ["tcpclientsrc", "host=127.0.0.1", "port=%d" % self.port, "!"]
            tokens += [
                "rawvideoparse",
                "width=%d" % self.width,
                "height=%d" % self.height,
                "format=rgb",
                "framerate=%s" % self.framerate(),
                "!",
                "videoconvert",
                "!",
                self.raw_caps(),
                "!",
                "joined.",
            ]
            # Each input's timestamps start at nought, and 'concat' says where the
            # second one starts in its segment rather than in its timestamps,
            # which an encoder that reorders frames reads as time running
            # backwards: two frames of the join were written seconds out of
            # place. One segment, and timestamps that run on, are what it needs.
            tokens += new + ["!", "joined.", "concat", "name=joined", "!", "identity", "single-segment=true", "!"]
            tokens += encode
        else:
            tokens += new + ["!"] + encode

        if self.audio:
            audio = AUDIO_CODECS[self.audio_codec]
            element = first_element(audio["encoders"], "a '%s' soundtrack in %s" % (self.audio_codec, self.container))
            tokens += ["filesrc", prop("location", self.audio), "!", "wavparse", "!", "audioconvert", "!"]
            tokens += ["audioresample", "!", "queue", "!"]
            tokens += audio_encoder(element, self.audio_bitrate) + ["!"]
            if audio["parse"]:
                tokens += [audio["parse"], "!"]
            tokens += ["mux."]

        for source in self.sources:
            tokens += list(source)
        return tokens

    def run(self, frames, log=None, prefix=()):
        """Encode 'frames' - an iterable of (height, width, 3) uint8 arrays - into the output file.

        'prefix' is the frames to put before them, in the same form, for a
        pipeline made with 'prefix' - see 'decode_frames'. Returns how many
        frames of each were written, as '(prefix, frames)'. Raises GStreamerError
        with what GStreamer said when it fails.
        """
        server = None
        if self.prefix:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            server.settimeout(CONNECT_TIMEOUT)
            self.port = server.getsockname()[1]
        argv = self.argv()
        if log is not None:
            log(" ".join(argv))
        errors_path = self.output + ".gstreamer.log"
        written = [0, 0]
        broken = False
        try:
            with open(errors_path, "wb") as errors:
                # Its own output to files of its own, never to the pipes of the
                # interpreter running this: whatever a sandbox interpreter starts
                # inherits those, and keeps them open for as long as it lives.
                process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=errors)
                try:
                    if server is not None:
                        broken = not self._send_prefix(server, process, prefix, written)
                    if not broken:
                        for frame in frames:
                            try:
                                process.stdin.write(self._bytes(frame))
                            except (BrokenPipeError, OSError):
                                broken = True
                                break
                            written[1] += 1
                except BaseException:
                    process.kill()
                    process.wait()
                    raise
                finally:
                    try:
                        process.stdin.close()
                    except (BrokenPipeError, OSError):
                        broken = True
                status = process.wait()
            with open(errors_path, "rb") as stream:
                said = stream.read().decode("utf-8", "replace")
        finally:
            if server is not None:
                server.close()
            if os.path.exists(errors_path):
                os.remove(errors_path)
        if status != 0 or broken:
            raise GStreamerError(
                "GStreamer failed writing '%s' (exit status %s): %s" % (self.output, status, said.strip()[-2000:])
            )
        return tuple(written)

    def _bytes(self, frame):
        import numpy as np

        if frame.shape != (self.height, self.width, 3) or frame.dtype != np.uint8:
            raise ValueError(
                "A frame is %s %s, not (%d, %d, 3) uint8" % (frame.shape, frame.dtype, self.height, self.width)
            )
        return np.ascontiguousarray(frame).tobytes()

    def _send_prefix(self, server, process, prefix, written):
        """Hand 'prefix' to the pipeline's socket; False if the pipeline was gone before it took it."""
        while True:
            try:
                connection, _ = server.accept()
                break
            except socket.timeout:
                if process.poll() is not None:
                    return False
        with connection:
            for frame in prefix:
                try:
                    connection.sendall(self._bytes(frame))
                except OSError:
                    return False
                written[0] += 1
            # The end of the stream, which is what moves 'concat' on to the new frames.
            connection.shutdown(socket.SHUT_WR)
        return True


def decode_frames(path, width, height, fps, limit=None):
    """The frames of the video at 'path', as (height, width, 3) uint8 arrays, one at a time.

    Scaled into a frame of 'width' by 'height' - with bars rather than stretched,
    where the two are not the same shape - and to 'fps', dropping or repeating
    frames, so that they can go before frames of that size and rate. At most
    'limit' of them: the rate is changed by repeating frames to fill the time
    between their timestamps, and a file whose timestamps are wrong can say there
    are hours between two of them.
    """
    import numpy as np

    argv = [
        launcher(),
        "-q",
        "filesrc",
        prop("location", path),
        "!",
        "decodebin",
        "!",
        "videoconvert",
        "!",
        "videoscale",
        "add-borders=true",
        "!",
        "videorate",
        "!",
        "video/x-raw,format=RGB,width=%d,height=%d,framerate=%s,pixel-aspect-ratio=1/1"
        % (width, height, Pipeline(path, "mp4", width, height, fps).framerate()),
        "!",
        "fdsink",
        "fd=1",
    ]
    size = width * height * 3
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=errors)
        count = 0
        try:
            while limit is None or count < limit:
                data = process.stdout.read(size)
                if len(data) < size:
                    break
                count += 1
                yield np.frombuffer(data, dtype=np.uint8).reshape(height, width, 3)
        finally:
            if process.poll() is None:
                process.kill()
            process.stdout.close()
            status = process.wait()
        if status not in (0, -9) and status is not None:
            errors.seek(0)
            raise GStreamerError(
                "Could not decode '%s': %s" % (path, errors.read().decode("utf-8", "replace").strip()[-1000:])
            )


# ---------------------------------------------------------------------------
# Vorbis comments, in Ogg
# ---------------------------------------------------------------------------
#
# An Ogg file is a sequence of pages, each of one logical stream - one per
# codec - and each carrying the stream's packets cut into segments of up to 255
# bytes. Every codec Ogg carries begins with header packets, and the second of
# them is the stream's comments: a vendor string and a list of 'KEY=value'
# pairs, the format Vorbis defined and Theora and Opus took over. GStreamer's
# Theora encoder writes that header empty whatever it is told, so the comments
# are written into it here, once the file is written: the page that holds the
# header is rebuilt with the comments in it and its checksum worked out again,
# and every other byte of the file is copied as it is.

OGG_CAPTURE = b"OggS"

# The identifying start of each codec's comment header, and whether a framing
# bit follows the comments (Vorbis's does; Theora's and Opus's do not).
COMMENT_HEADERS = ((b"\x81theora", False), (b"\x03vorbis", True), (b"OpusTags", False))

# Ogg's CRC: the polynomial 0x04C11DB7, from nought, not reflected, not
# inverted - not zlib's.
_OGG_CRC = []
for _byte in range(256):
    _value = _byte << 24
    for _ in range(8):
        _value = ((_value << 1) ^ 0x04C11DB7) if _value & 0x80000000 else (_value << 1)
    _OGG_CRC.append(_value & 0xFFFFFFFF)


def ogg_crc(data):
    """The checksum of an Ogg page, 'data' being the page with its checksum field nought."""
    crc = 0
    for byte in data:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ _OGG_CRC[((crc >> 24) & 0xFF) ^ byte]
    return crc


class OggPage:
    """One page of an Ogg file: its header up to the segment count, its segment sizes, and its body."""

    def __init__(self, header, lacing, body):
        self.header = header
        self.lacing = lacing
        self.body = body

    @property
    def serial(self):
        return int.from_bytes(self.header[14:18], "little")

    @property
    def continued(self):
        """Whether the page begins with the rest of a packet an earlier page began."""
        return bool(self.header[5] & 1)

    def packets(self):
        """The packets ending on this page and the one it leaves unfinished: '([bytes], bytes or None)'.

        The first one is only the end of a packet if the page is 'continued'.
        """
        finished, current, offset = [], [], 0
        for size in self.lacing:
            current.append(self.body[offset : offset + size])
            offset += size
            if size < 255:
                finished.append(b"".join(current))
                current = []
        return finished, (b"".join(current) if current else None)

    def raw(self):
        """The page as it is, checksum included."""
        return self.header + bytes([len(self.lacing)]) + bytes(self.lacing) + self.body

    def to_bytes(self):
        """The page with its checksum worked out afresh."""
        page = bytearray(self.raw())
        page[22:26] = b"\0\0\0\0"
        page[22:26] = ogg_crc(bytes(page)).to_bytes(4, "little")
        return bytes(page)


def _read_page(stream):
    """The next page of 'stream', or None at its end."""
    header = stream.read(27)
    if len(header) < 27:
        return None
    if header[:4] != OGG_CAPTURE:
        raise GStreamerError("Not an Ogg page, at %d" % (stream.tell() - len(header)))
    lacing = stream.read(header[26])
    body = stream.read(sum(lacing))
    return OggPage(header[:26], lacing, body)


def _lacing(size):
    """How a packet of 'size' bytes is cut into segments: as many 255s as fit, then the rest, nought included."""
    return [255] * (size // 255) + [size % 255]


def parse_comments(packet):
    """A comment header as '(vendor, [(key, value)], codec)', or None if 'packet' is not one."""
    for start, _framing in COMMENT_HEADERS:
        if packet.startswith(start):
            break
    else:
        return None
    offset = len(start)
    length = int.from_bytes(packet[offset : offset + 4], "little")
    vendor = packet[offset + 4 : offset + 4 + length]
    offset += 4 + length
    count = int.from_bytes(packet[offset : offset + 4], "little")
    offset += 4
    comments = []
    for _ in range(count):
        length = int.from_bytes(packet[offset : offset + 4], "little")
        text = packet[offset + 4 : offset + 4 + length].decode("utf-8", "replace")
        offset += 4 + length
        key, _, value = text.partition("=")
        comments.append((key, value))
    return vendor, comments, start


def build_comments(start, vendor, comments):
    """A comment header of the codec 'start' names, holding 'vendor' and 'comments'."""
    framing = dict(COMMENT_HEADERS)[start]
    out = bytearray(start)
    out += len(vendor).to_bytes(4, "little") + vendor
    out += len(comments).to_bytes(4, "little")
    for key, value in comments:
        if not key or "=" in key or not all(0x20 <= ord(char) <= 0x7D for char in key):
            raise ValueError("Not the key of a Vorbis comment: %r" % (key,))
        text = ("%s=%s" % (key, value)).encode("utf-8")
        out += len(text).to_bytes(4, "little") + text
    if framing:
        out.append(1)
    return bytes(out)


# How far into an Ogg file its comments are looked for: the header packets of
# every stream come before any of their data, so they are on the first few pages.
_HEADER_PAGES = 64


def read_comments(path):
    """The Vorbis comments of the Ogg file at 'path', as '{KEY: value}', keys upper case.

    The comments of every stream in it: the video's, and a soundtrack's.
    """
    found = {}
    pending = {}
    with open(path, "rb") as stream:
        for _ in range(_HEADER_PAGES):
            page = _read_page(stream)
            if page is None:
                break
            finished, unfinished = page.packets()
            if page.continued and finished:
                finished[0] = pending.pop(page.serial, b"") + finished[0]
            elif page.continued and unfinished is not None:
                unfinished = pending.pop(page.serial, b"") + unfinished
            for packet in finished:
                parsed = parse_comments(packet)
                if parsed is not None:
                    for key, value in parsed[1]:
                        found[key.upper()] = value
            if unfinished is not None:
                pending[page.serial] = unfinished
    return found


def write_comments(path, comments):
    """Set 'comments' - '[(key, value)]' - in the comment header of the video in the Ogg file at 'path'.

    Every comment already there under another key is kept. The header's page is
    rewritten in place, so the file has to be as GStreamer's Ogg muxer writes it:
    the comment header beginning a page of its own, and ending on it. The page
    keeps its number, so no other page changes.
    """
    keys = {key.upper() for key, _value in comments}
    rewritten = path + ".comments"
    done = False
    with open(path, "rb") as source, open(rewritten, "wb") as target:
        while not done:
            page = _read_page(source)
            if page is None:
                break
            finished, _unfinished = page.packets()
            parsed = parse_comments(finished[0]) if finished and not page.continued else None
            if parsed is not None and parsed[2] == COMMENT_HEADERS[0][0]:
                vendor, kept, start = parsed
                kept = [(key, value) for key, value in kept if key.upper() not in keys]
                header = build_comments(start, vendor, kept + list(comments))
                old = len(finished[0])
                lacing = _lacing(len(header)) + list(page.lacing[len(_lacing(old)) :])
                if len(lacing) > 255:
                    raise GStreamerError("The comments of '%s' do not fit on the page its header is on" % path)
                page = OggPage(page.header, bytes(lacing), header + page.body[old:])
                done = True
            # Every page but the rewritten one is copied as it was read, its
            # checksum and all.
            target.write(page.to_bytes() if done else page.raw())
        shutil.copyfileobj(source, target)
    if not done:
        os.remove(rewritten)
        raise GStreamerError("'%s' has no Theora comment header to write the video's comments into" % path)
    os.replace(rewritten, path)
