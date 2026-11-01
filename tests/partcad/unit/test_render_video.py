#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for the shaded pictures and the video file types of '//builtin/render'.

Three modules make a video: 'render_raster.py' draws each frame in its shaded
style ('raster_scene.py' is what draws it the way the Digital Thread's 3D view
does) - the very picture a PNG asked for 'style: shaded' is - 'video_encode.py'
builds and runs the GStreamer pipelines, and 'render_video.py' reads the file
type's fields and puts the two together. All of them are imported here by path,
as the sandbox imports them. What needs GStreamer is skipped on a machine without it; the rest - the
options, the pipelines as text, the frames as pixels - needs only the CAD stack
this environment already has.
"""

import math
import os
import re
import sys

import numpy as np
import pytest
import yaml

import partcad as pc
from partcad import output, sandbox_versions

RENDER_DIR = output.BUILTIN_PATHS[output.BUILTIN_PACKAGES[output.RENDER]]
WRAPPERS_DIR = os.path.join(os.path.dirname(pc.__file__), "wrappers")
for directory in (WRAPPERS_DIR, RENDER_DIR):
    if directory not in sys.path:
        sys.path.append(directory)

import raster_scene  # noqa: E402
import render_png  # noqa: E402
import render_raster  # noqa: E402
import render_svg  # noqa: E402
import render_video  # noqa: E402
import video_encode  # noqa: E402
import viewpoint  # noqa: E402

VIDEO_TYPES = ("mp4", "m4v", "mov", "qt", "mkv", "webm", "avi", "wmv", "asf", "ogv")

needs_gstreamer = pytest.mark.skipif(
    video_encode.find_tool(video_encode.LAUNCH) is None or video_encode.find_tool(video_encode.DISCOVERER) is None,
    reason="GStreamer ('gst-launch-1.0' and 'gst-discoverer-1.0') is not installed here",
)


def _builtin_render():
    with open(os.path.join(RENDER_DIR, "partcad.yaml")) as stream:
        return yaml.safe_load(stream)


def _box(x=40, y=20, z=10):
    import build123d as b3d

    return b3d.Box(x, y, z).wrapped


# ---------------------------------------------------------------------------
# The declarations
# ---------------------------------------------------------------------------


def test_every_video_type_is_declared_against_the_renderer():
    """Each video file type runs 'render_video.py', in a container the encoder knows, in the GStreamer image."""
    render = _builtin_render()["render"]
    for name in VIDEO_TYPES:
        config = render[name]
        assert config["path"] == "render_video.py", name
        assert config["container_format"] in video_encode.CONTAINERS, name
        # Not 'container', which is the protocol's: it would run the script in
        # an image of that name.
        assert "container" not in config, name
        assert config["dockerImage"] == "ghcr.io/partcad/partcad-container-python:{version}-py{python}-gstreamer"
        assert config["size"] in render_raster.SIZES, name
        assert config["style"] == "shaded", name
        assert config["preset"] in video_encode.PRESETS, name


def test_the_gstreamer_image_is_built_for_the_interpreter_videos_run_in():
    """CI builds the GStreamer flavour for one interpreter, and it has to be the one '//builtin/render' runs in."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    with open(os.path.join(root, ".github", "workflows", "test.yml")) as stream:
        workflow = stream.read()
    declared = set(re.findall(r'GSTREAMER_PYTHON: "([0-9.]+)"', workflow))
    assert declared == {sandbox_versions.DEFAULT_PYTHON_VERSION}


def test_the_docker_image_is_filled_in_and_keyed_as_declared():
    """'{version}' and '{python}' are this release and the sandbox's interpreter; the key is the declaration."""
    from partcad_utils import container_image

    impl = output.Implementation(output.RENDER, "mp4", {})
    impl.project = type(
        "Project",
        (),
        {
            "config_obj": _builtin_render(),
            "python_version_declared": None,
            "docker_image_declared": None,
        },
    )()
    expected = "ghcr.io/partcad/partcad-container-python:%s-py%s-gstreamer" % (
        container_image.image_tag(pc.__version__),
        sandbox_versions.DEFAULT_PYTHON_VERSION,
    )
    assert impl.docker_image == container_image.image_name(expected)
    assert "{version}" in impl.docker_image_declared


def test_expand_leaves_a_reference_without_placeholders_alone(monkeypatch):
    from partcad_utils import container_image

    # A CI run that builds the images exports the tag it built them under, and
    # '{version}' is that tag rather than the release.
    monkeypatch.delenv(container_image.ENV_VAR, raising=False)
    assert container_image.expand("ghcr.io/example/solver:1a2b") == "ghcr.io/example/solver:1a2b"
    assert container_image.expand("x/y/z:{version}", release="1.2.3") == "x/y/z:1.2.3"
    assert container_image.expand("x/y/z:py{python}", python="3.12") == "x/y/z:py3.12"
    monkeypatch.setenv(container_image.ENV_VAR, "1.2.3-branch-abc")
    assert container_image.expand("x/y/z:{version}", release="1.2.3") == "x/y/z:1.2.3-branch-abc"


# ---------------------------------------------------------------------------
# The options
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "size, expected",
    [
        (None, (1080, 1920)),
        ("reels", (1080, 1920)),
        ("Shorts", (1080, 1920)),
        ("square", (1080, 1080)),
        ("portrait", (1080, 1350)),
        ("youtube", (1920, 1080)),
        ("4k", (3840, 2160)),
        ("1281x721", (1280, 720)),
        ([640, 480], (640, 480)),
    ],
)
def test_video_size(size, expected):
    assert render_video.video_size({"size": size}) == expected


def test_width_and_height_override_the_size():
    assert render_video.video_size({"size": "reels", "width": 720}) == (720, 1920)


@pytest.mark.parametrize("size", ["huge", "10x10", "100000x100", "axb"])
def test_a_size_that_is_not_one_is_refused(size):
    with pytest.raises(render_video.OptionError):
        render_video.video_size({"size": size})


def test_a_video_is_one_turn_long_unless_it_says_otherwise():
    assert render_video.duration_of({}, (0, 0, 30)) == pytest.approx(12.0)
    assert render_video.duration_of({}, (10, -45, 0)) == pytest.approx(8.0)
    assert render_video.duration_of({}, (0, 0, 0)) == render_video.STILL_DURATION
    assert render_video.duration_of({"duration": 3}, (0, 0, 30)) == 3
    with pytest.raises(render_video.OptionError):
        render_video.duration_of({"duration": 0}, (0, 0, 30))


def test_one_number_is_a_speed_about_z():
    assert render_video._vector({"speed": 15}, "speed", render_video.DEFAULT_SPEED) == (0.0, 0.0, 15.0)
    assert render_video._vector({"speed": "1,2,3"}, "speed", render_video.DEFAULT_SPEED) == (1.0, 2.0, 3.0)
    assert render_video._vector({}, "speed", render_video.DEFAULT_SPEED) == (0.0, 0.0, 30.0)
    with pytest.raises(render_video.OptionError):
        render_video._vector({"speed": [1, 2]}, "speed", render_video.DEFAULT_SPEED)


def test_the_cli_reads_a_speed_and_a_turn_the_way_the_renderer_does():
    import rich_click as click

    from partcad_cli.click.viewport import turn_vector

    assert turn_vector(None, None, None) is None
    assert turn_vector(None, None, "15") == [0.0, 0.0, 15.0]
    assert turn_vector(None, None, "1,2 3") == [1.0, 2.0, 3.0]
    for value in ("fast", "1,2"):
        with pytest.raises(click.BadParameter):
            turn_vector(None, None, value)


def test_a_request_hands_on_only_the_video_options_it_gives():
    from partcad_service_json_rpc.core.operations import _video

    assert _video({}) == {}
    # 'append' is a flag: false is the same as not asking.
    assert _video({"size": "square", "fps": None, "append": False, "quality": 0}) == {"size": "square", "quality": 0}
    assert _video({"append": True, "speed": [0, 0, 90]}) == {"append": True, "speed": [0, 0, 90]}
    # A picture's fields go the same way: a PNG and a video both read them.
    assert _video({"style": "shaded", "background": "#000000"}) == {"style": "shaded", "background": "#000000"}


def test_angles_stay_within_a_turn():
    assert render_video.angles_at((0, 0, 350), (0, 0, 30), 1.0) == pytest.approx((0, 0, 20))


def test_filters_are_elements_and_nothing_else():
    assert render_video.video_filters({"filters": "videobalance saturation=1.3"}) == [
        ["videobalance", "saturation=1.3"]
    ]
    for entry in ("videobalance ! filesink location=/etc/passwd", "filesink location=x", "videotestsrc", "a.b"):
        with pytest.raises(render_video.OptionError):
            render_video.video_filters({"filters": [entry]})


def test_text_is_timed_by_a_subtitle_file(tmp_path):
    elements, sources = render_video.text_overlays(
        {"text": ["throughout", {"text": "later", "start": 2, "end": 4, "position": "top-left", "color": "#FF0000"}]},
        1080,
        1920,
        12.0,
        str(tmp_path),
    )
    assert len(elements) == len(sources) == 2
    assert elements[1][1] == "name=text1"
    assert "valignment=top" in elements[1] and "halignment=left" in elements[1]
    assert "color=0xFFFF0000" in elements[1]
    # The size is a fraction of the frame's height, in pixels.
    assert 'font-desc="Sans Bold %dpx"' % round(render_video.DEFAULT_TEXT_SIZE * 1920) in elements[0]
    with open(tmp_path / "text1.srt") as stream:
        assert stream.read() == "1\n00:00:02,000 --> 00:00:04,000\nlater\n\n"
    with open(tmp_path / "text0.srt") as stream:
        assert "00:00:00,000 --> 00:00:12,000" in stream.read()


def test_a_text_that_ends_before_it_starts_is_refused(tmp_path):
    with pytest.raises(render_video.OptionError):
        render_video.text_overlays({"text": {"text": "x", "start": 3, "end": 2}}, 100, 100, 5.0, str(tmp_path))


def test_a_logo_is_placed_in_its_corner_and_keeps_its_shape(tmp_path):
    from PIL import Image

    Image.new("RGBA", (200, 100)).save(tmp_path / "logo.png")
    element = render_video.logo_overlay(
        {"logo": {"path": "logo.png", "width": 0.25}, "package_dir": str(tmp_path)}, 1000, 2000
    )
    margin = round(render_video.DEFAULT_MARGIN * 1000)
    assert "overlay-width=250" in element and "overlay-height=125" in element
    assert "offset-x=%d" % (1000 - 250 - margin) in element
    assert "offset-y=%d" % margin in element


def test_a_missing_file_is_named(tmp_path):
    with pytest.raises(render_video.OptionError, match="not a file"):
        render_video.media_path("nowhere.mp3", {"package_dir": str(tmp_path)}, "audio")


def test_a_package_the_sandbox_was_not_sent_names_no_file(tmp_path):
    """A 'remote' sandbox is sent the package when a field names a file in it; not sent, there was no such file."""
    elsewhere = str(tmp_path / "on-the-client")
    with pytest.raises(render_video.OptionError, match="'music.mp3', which is not a file of the package"):
        render_video.media_path("music.mp3", {"package_dir": elsewhere}, "audio")
    # An absolute path is not read from the package, and is found wherever it is.
    music = tmp_path / "music.mp3"
    music.write_bytes(b"")
    assert render_video.media_path(str(music), {"package_dir": elsewhere}, "audio") == str(music)


def test_the_healthcheck_asks_after_the_discoverer(monkeypatch):
    """Debian packages 'gst-discoverer-1.0' apart from 'gst-launch-1.0', and an append needs it."""
    import types

    from partcad.healthcheck import gstreamer

    encode = types.SimpleNamespace(
        LAUNCH=video_encode.LAUNCH,
        DISCOVERER=video_encode.DISCOVERER,
        ENV_VAR=video_encode.ENV_VAR,
        MISSING=video_encode.MISSING,
        find_tool=lambda name: "/usr/bin/gst-launch-1.0" if name == video_encode.LAUNCH else None,
        has_element=lambda name: True,
    )
    monkeypatch.setattr(gstreamer, "_video_encode", lambda: encode)
    monkeypatch.setattr(gstreamer.pc_runtime, "docker_enabled", lambda: True)

    def choose(sandbox):
        # The fields behind 'python_sandbox': its setter also marks it
        # declared, which undoing a patch of the property would not unmark.
        monkeypatch.setattr(gstreamer.user_config, "_python_sandbox", sandbox)
        monkeypatch.setattr(gstreamer.user_config, "_python_sandbox_declared", True)
        check = gstreamer.GStreamerCheck()
        check.test()
        return check.findings

    # Docker running does not help a sandbox its owner chose to be the host.
    findings = choose("venv")
    assert len(findings) == 1 and "gstreamer1.0-plugins-base-apps" in findings[0]

    # 'docker' and 'remote' encode in PartCAD's image, so nothing here is asked after.
    assert choose("docker") == []
    assert choose("remote") == []


def test_the_healthcheck_wants_a_local_gstreamer_for_a_host_sandbox(monkeypatch):
    """Docker running is no GStreamer for a sandbox that renders on the host."""
    import types

    from partcad.healthcheck import gstreamer

    encode = types.SimpleNamespace(
        LAUNCH=video_encode.LAUNCH,
        ENV_VAR=video_encode.ENV_VAR,
        MISSING=video_encode.MISSING,
        find_tool=lambda name: None,
    )
    monkeypatch.setattr(gstreamer, "_video_encode", lambda: encode)
    monkeypatch.setattr(gstreamer.pc_runtime, "docker_enabled", lambda: True)
    monkeypatch.setattr(gstreamer.user_config, "_python_sandbox", "conda")
    monkeypatch.setattr(gstreamer.user_config, "_python_sandbox_declared", True)
    check = gstreamer.GStreamerCheck()
    check.test()
    assert len(check.findings) == 1 and video_encode.LAUNCH in check.findings[0]

    # Nothing declared: Docker is what PartCAD picks, and it has the image.
    monkeypatch.setattr(gstreamer.user_config, "_python_sandbox_declared", False)
    monkeypatch.setattr(gstreamer.user_config, "use_docker_python_declared", False, raising=False)
    check = gstreamer.GStreamerCheck()
    check.test()
    assert check.findings == []

    # Nor Docker: the sandbox PartCAD falls back to renders on the host.
    monkeypatch.setattr(gstreamer.pc_runtime, "docker_enabled", lambda: False)
    check = gstreamer.GStreamerCheck()
    check.test()
    assert len(check.findings) == 1


def test_fades_mix_toward_their_colour():
    image = np.full((2, 2, 3), 200, dtype=np.uint8)
    first = render_video.faded(image, 0, 10, 100, 1.0, 0.0, (0, 0, 0))
    assert first.max() == 0
    halfway = render_video.faded(image, 5, 10, 100, 1.0, 0.0, (0, 0, 0))
    assert halfway.max() == 100
    assert render_video.faded(image, 50, 10, 100, 1.0, 1.0, (0, 0, 0)) is image
    last = render_video.faded(image, 99, 10, 100, 0.0, 1.0, (255, 255, 255))
    assert last.min() == 255


# ---------------------------------------------------------------------------
# The encoder
# ---------------------------------------------------------------------------


def test_quality_is_a_crf_for_x264():
    tokens = video_encode.video_encoder("x264enc", "medium", 65, None, 30, 1080, 1920)
    assert tokens[:2] == ["x264enc", "speed-preset=medium"]
    assert "pass=qual" in tokens and "quantizer=18" in tokens
    assert "key-int-max=60" in tokens


def test_a_bitrate_asks_for_a_bitrate():
    assert "bitrate=4000" in video_encode.video_encoder("x264enc", "fast", 65, 4000, 30, 1080, 1920)
    vp9 = video_encode.video_encoder("vp9enc", "fast", 65, 4000, 30, 1080, 1920)
    assert "end-usage=vbr" in vp9 and "target-bitrate=4000000" in vp9


def test_every_preset_reaches_every_encoder():
    for element in ("x264enc", "x265enc", "vp8enc", "vp9enc", "theoraenc", "openh264enc", "jpegenc", "avenc_wmv2"):
        for preset in video_encode.PRESETS:
            assert video_encode.video_encoder(element, preset, 50, None, 25, 640, 480)[0] == element
    with pytest.raises(ValueError):
        video_encode.preset_index("ludicrous")
    with pytest.raises(ValueError):
        video_encode.quality_of(101)


def test_a_container_carries_what_it_carries():
    assert video_encode.codec_for("webm", None, "video") == "vp9"
    assert video_encode.codec_for("mp4", "H265", "video") == "h265"
    with pytest.raises(ValueError):
        video_encode.codec_for("mp4", "vp9", "video")
    # ASF carries no sound here: see 'CONTAINERS'.
    with pytest.raises(ValueError):
        video_encode.codec_for("asf", None, "audio")


def test_the_state_reads_back():
    text = video_encode.state_text((12.5, -3, 359.999), 360, 30)
    assert video_encode.parse_state("tags:\n  comment: %s\n" % text) == pytest.approx((12.5, -3, 359.999))
    assert video_encode.parse_state("comment: somebody else's") is None


def test_the_state_reads_back_from_vorbis_comments():
    comments = dict(video_encode.state_comments((12.5, -3, 359.999), 360, 30))
    assert comments == {
        "PARTCAD_VIDEO": "1",
        "PARTCAD_ANGLES": "12.5,-3,359.999",
        "PARTCAD_FRAMES": "360",
        "PARTCAD_FPS": "30",
    }
    assert video_encode.comments_state(comments) == pytest.approx((12.5, -3, 359.999))
    # Another version of what the pairs mean is not read as this one.
    assert video_encode.comments_state(dict(comments, PARTCAD_VIDEO="2")) is None
    assert video_encode.comments_state({"PARTCAD_VIDEO": "1", "PARTCAD_ANGLES": "1,2"}) is None


def test_ogg_pages_are_checked_with_oggs_own_crc():
    """Not zlib's: the polynomial 0x04C11DB7, from nought, neither reflected nor inverted."""
    assert video_encode.ogg_crc(b"123456789") == 0x89A1897F


def test_a_comment_header_is_built_and_read_back():
    header = video_encode.build_comments(b"\x81theora", b"vendor", [("TITLE", "a = b"), ("PARTCAD_FPS", "30")])
    assert video_encode.parse_comments(header) == (
        b"vendor",
        [("TITLE", "a = b"), ("PARTCAD_FPS", "30")],
        b"\x81theora",
    )
    # Vorbis's ends in a framing bit; Theora's does not.
    assert video_encode.build_comments(b"\x03vorbis", b"", []).endswith(b"\x01")
    assert not header.endswith(b"\x01")
    with pytest.raises(ValueError):
        video_encode.build_comments(b"\x81theora", b"", [("A=B", "c")])


@needs_gstreamer
def test_comments_are_written_into_a_theora_stream(tmp_path):
    """GStreamer writes Theora's comment header empty; the page holding it is rewritten, and only that page."""
    path = str(tmp_path / "turn.ogv")
    video_encode.Pipeline(path, "ogg", 64, 48, 10).run(np.zeros((5, 48, 64, 3), dtype=np.uint8))
    before = open(path, "rb").read()
    video_encode.write_comments(path, [("TITLE", "first"), ("PARTCAD_FPS", "10")])
    video_encode.write_comments(path, [("TITLE", 'a "title" = ünicode')])
    comments = video_encode.read_comments(path)
    assert comments["TITLE"] == 'a "title" = ünicode'
    assert comments["PARTCAD_FPS"] == "10"
    after = open(path, "rb").read()
    # Every page but the one is the bytes it was, and every page's checksum holds.
    assert after.endswith(before[-1000:])
    with open(path, "rb") as stream:
        while True:
            page = video_encode._read_page(stream)
            if page is None:
                break
            assert page.to_bytes() == page.raw()
    assert len(list(video_encode.decode_frames(path, 64, 48, 10, limit=20))) == 5


def test_quoting_survives_what_a_title_may_hold():
    assert video_encode.prop("title", 'a "b", \\c') == 'title="a \\"b\\", \\\\c"'


def test_srt_and_colours():
    assert video_encode.srt_time(3723.5) == "01:02:03,500"
    assert video_encode.argb("#123456") == "0xFF123456"
    assert video_encode.argb("#12345680") == "0x80123456"


def test_audio_is_cut_padded_looped_and_faded():
    rate = video_encode.AUDIO_RATE
    one = np.ones((rate, 2), dtype=np.float32)
    assert len(video_encode.fit_audio(one, 0.5)) == rate // 2
    padded = video_encode.fit_audio(one, 2.0)
    assert len(padded) == 2 * rate and padded[-1].max() == 0
    looped = video_encode.fit_audio(one, 2.0, loop=True)
    assert looped[-1].min() == 1
    faded = video_encode.fade_audio(one.copy(), fade_in=0.5, fade_out=0.5, volume=0.5)
    assert faded[0].max() == 0 and faded[-1].max() == 0 and faded[rate // 2].max() == pytest.approx(0.5)


def test_a_pipeline_appending_puts_the_old_frames_first(monkeypatch):
    """The frames before the new ones arrive over a socket and go first into 'concat', then one segment."""
    monkeypatch.setattr(video_encode, "launcher", lambda: "gst-launch-1.0")
    monkeypatch.setattr(video_encode, "has_element", lambda name: True)
    pipeline = video_encode.Pipeline(
        "/out/x y.mp4",
        "mp4",
        1080,
        1920,
        30,
        video=[["textoverlay", "name=text0"]],
        sources=[["filesrc", "location=a.srt", "!", "subparse", "!", "text0.text_sink"]],
        prefix=True,
        audio="/tmp/sound.wav",
        tags={"comment": video_encode.state_text((0, 0, 30), 30, 30)},
    )
    pipeline.port = 4321
    argv = pipeline.argv()
    text = " ".join(argv)
    assert argv.index("tcpclientsrc") < argv.index("fdsrc") < argv.index("concat")
    assert "port=4321" in argv
    # The overlay is on the new frames' branch only.
    assert argv.index("fdsrc") < argv.index("textoverlay") < argv.index("concat")
    assert "identity single-segment=true" in text
    assert "mp4mux name=mux faststart=true" in text
    assert 'location="/out/x y.mp4"' in argv
    assert "avenc_aac" in argv and argv[-6:] == ["filesrc", "location=a.srt", "!", "subparse", "!", "text0.text_sink"]
    assert any(token.startswith("tags=") and "partcad-video/1" in token for token in argv)


# ---------------------------------------------------------------------------
# The frames
# ---------------------------------------------------------------------------


def test_neutral_tone_mapping_leaves_ordinary_colours_alone():
    color = np.array([[0.5, 0.3, 0.2]])
    assert raster_scene.neutral_tone_mapping(color) == pytest.approx(color - 0.04)
    bright = raster_scene.neutral_tone_mapping(np.array([[3.0, 3.0, 3.0]]))
    assert bright.max() < 1.0


def test_the_edge_colour_is_the_ides():
    assert raster_scene.edge_color(raster_scene.DEFAULT_COLOR) == raster_scene.DEFAULT_EDGE_COLOR
    # Darkened by a quarter of its lightness, and a dark one lightened.
    assert sum(raster_scene.edge_color((200, 50, 50))) < 300
    assert sum(raster_scene.edge_color((10, 10, 10))) > 30


def test_the_ides_colour_is_appearances():
    import appearance

    assert "#%02X%02X%02X" % raster_scene.DEFAULT_COLOR == appearance.DEFAULT_COLOR


def test_a_triangle_covers_half_its_square():
    """Pixels are sampled at their centres, so a half of a square covers about half of its pixels."""
    sx = np.array([[0.0, 100.0, 0.0]])
    sy = np.array([[0.0, 0.0, 100.0]])
    depth = np.ones((1, 3))
    planes = raster_scene.Planes(sx, sy, depth)
    zbuffer = np.empty(100 * 100, dtype=np.float32)
    owner = np.empty(100 * 100, dtype=np.int64)
    raster_scene.rasterize(sx, sy, planes, 100, 100, 0.01, zbuffer, owner)
    assert abs(int((owner == 0).sum()) - 5000) <= 100
    assert zbuffer[owner == 0] == pytest.approx(1.0)


def test_the_nearer_of_two_triangles_wins():
    sx = np.array([[0.0, 50.0, 0.0], [0.0, 50.0, 0.0]])
    sy = np.array([[0.0, 0.0, 50.0], [0.0, 0.0, 50.0]])
    depth = np.array([[2.0, 2.0, 2.0], [1.0, 1.0, 1.0]])
    planes = raster_scene.Planes(sx, sy, depth)
    zbuffer = np.empty(50 * 50, dtype=np.float32)
    owner = np.empty(50 * 50, dtype=np.int64)
    raster_scene.rasterize(sx, sy, planes, 50, 50, 0.01, zbuffer, owner)
    assert set(np.unique(owner)) == {-1, 1}


def test_turning_the_object_is_turning_the_camera_the_other_way():
    camera = raster_scene.Camera(distance=10.0)
    turn = raster_scene.rotation((0, 0, 90))
    basis, eye = camera.turned(turn)
    # A point the turn carries in front of the camera is where the camera,
    # turned the other way, sees it.
    point = np.array([1.0, 2.0, 3.0])
    still = (turn @ point - camera.basis[2] * 10.0) @ camera.basis.T
    moved = (point - eye) @ basis.T
    assert moved == pytest.approx(still)


def test_a_box_is_drawn_in_goldenrod_on_the_background():
    scene = raster_scene.Scene([("#DAA520", _box())], 200)
    # Two triangles a face, each split until no edge is longer than 'MAX_EDGE'.
    assert scene.triangle_count > 12
    camera = raster_scene.Camera(distance=raster_scene.frame_distance(scene.sphere, 1.0))
    frame = raster_scene.Painter(scene, camera, 120, 120, (0x1F, 0x1F, 0x1F), supersample=2).draw(np.eye(3))
    assert frame.shape == (120, 120, 3) and frame.dtype == np.uint8
    assert tuple(frame[0, 0]) == (0x1F, 0x1F, 0x1F)
    middle = frame[60, 60].astype(int)
    # Gold: red over green over blue, and well clear of the background.
    assert middle[0] > middle[1] > middle[2] and middle[0] > 150


def test_every_box_normal_points_out():
    points, normals, corners = raster_scene.triangles(_box(), 0.1)
    centroids = points[corners].mean(axis=1)
    assert np.all(np.sum(normals[corners[:, 0]] * centroids, axis=1) > 0)
    # And the corners turn counter-clockwise about it, seen from outside.
    a, b, c = points[corners[:, 0]], points[corners[:, 1]], points[corners[:, 2]]
    assert np.all(np.sum(np.cross(b - a, c - a) * normals[corners[:, 0]], axis=1) > 0)


def test_large_triangles_are_split_and_still_meet():
    """A face's two triangles become many, with no edge longer than asked, covering the same area."""
    points, normals, corners = raster_scene.triangles(_box(40, 40, 40), 0.1)
    refined_points, refined_normals, refined = raster_scene.refine(points, normals, corners, 5.0)

    def area(p, c):
        return 0.5 * np.linalg.norm(np.cross(p[c[:, 1]] - p[c[:, 0]], p[c[:, 2]] - p[c[:, 0]]), axis=1).sum()

    assert len(refined) > len(corners)
    assert area(refined_points, refined) == pytest.approx(area(points, corners))
    edges = [refined_points[refined[:, i]] - refined_points[refined[:, j]] for i, j in ((0, 1), (1, 2), (2, 0))]
    assert max(np.linalg.norm(edge, axis=1).max() for edge in edges) <= 5.0
    assert np.linalg.norm(refined_normals, axis=1) == pytest.approx(1.0)


def test_a_sketch_of_lines_is_drawn_as_lines():
    import build123d as b3d

    lines = b3d.Compound([b3d.Line((0, 0), (30, 0)), b3d.Line((30, 0), (30, 20))]).wrapped
    scene = raster_scene.Scene([("#DAA520", lines)], 100)
    assert scene.triangle_count == 0 and len(scene.segments) >= 2
    camera = raster_scene.Camera(distance=raster_scene.frame_distance(scene.sphere, 1.0))
    frame = raster_scene.Painter(scene, camera, 100, 100, (0, 0, 0), line_width=2).draw(np.eye(3))
    assert (frame.reshape(-1, 3) == raster_scene.DEFAULT_EDGE_COLOR).all(axis=1).any()


def test_nothing_to_draw_is_said():
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    empty = TopoDS_Compound()
    BRep_Builder().MakeCompound(empty)
    with pytest.raises(ValueError, match="nothing to draw"):
        raster_scene.Scene([("#DAA520", empty)], 100)


# ---------------------------------------------------------------------------
# Shaded pictures, the turn, and a frame as a picture
# ---------------------------------------------------------------------------


def _pixels(path):
    from PIL import Image

    with Image.open(path) as image:
        return np.asarray(image.convert("RGB"))


def test_a_turn_is_the_camera_turned_back():
    """The front of an object turned a quarter about Z is what its left side was."""
    origin, up = viewpoint.turned((0, -100, 0), (0, 0, 1), (0, 0, 90))
    assert origin == pytest.approx((-100, 0, 0), abs=1e-9)
    assert up == pytest.approx((0, 0, 1), abs=1e-9)
    # No turn is the viewport exactly as it was, so a picture that asks for none
    # comes out byte for byte as it did before there was a turn to ask for.
    assert viewpoint.turned((100, -100, 100), (0, 0, 1), (0, 0, 0)) == ((100, -100, 100), (0, 0, 1))
    assert viewpoint.turn_of({"turn": 45}) == (0.0, 0.0, 45.0)
    assert viewpoint.turn_of({"turn": "10, 20, 30"}) == (10.0, 20.0, 30.0)
    assert viewpoint.turn_of({}) == (0.0, 0.0, 0.0)
    for value in ([1, 2], "x", True, [0, float("nan"), 0]):
        with pytest.raises(ValueError):
            viewpoint.turn_of({"turn": value})


def test_the_projection_is_drawn_turned(tmp_path):
    """The SVG (and so DXF and a PNG of lines) says it looked from where the turn put its camera."""
    result = render_svg.process(
        str(tmp_path / "box.svg"),
        {"wrapped": _box(), "viewport_origin": [0, -100, 0], "viewport_up": [0, 0, 1], "turn": [0, 0, 90]},
    )
    assert result["success"], result.get("exception")
    assert result["viewport"]["viewport_origin"] == pytest.approx([-100, 0, 0], abs=1e-9)


def test_a_shaded_png_is_a_lit_picture(tmp_path):
    path = str(tmp_path / "box.png")
    result = render_png.process(path, {"wrapped": _box(), "style": "shaded", "size": "96x64", "antialias": 1})
    assert result["success"], result.get("exception")
    assert result["files"] == []
    pixels = _pixels(path)
    assert pixels.shape == (64, 96, 3)
    # On white, as a PNG of lines is; goldenrod in the middle, lit.
    assert (pixels[0, 0] == 255).all()
    middle = pixels[32, 48].astype(int)
    assert middle[0] > middle[2] + 40
    # Where it was looked at from: the 3D view's direction, as a projection says it.
    assert result["viewport"]["viewport_origin"] == pytest.approx(list(raster_scene.VIEW_DIRECTION))


def _margins(path):
    """How many pixels of the picture are left empty on each side: (left, right, top, bottom), and its size."""
    pixels = _pixels(path).astype(int)
    background = pixels[0, 0]
    ink = (np.abs(pixels - background) > 6).any(axis=2)
    ys, xs = np.nonzero(ink)
    height, width = ink.shape
    return (xs.min(), width - 1 - xs.max(), ys.min(), height - 1 - ys.max()), (width, height)


def test_a_drawing_of_lines_is_padded_alike_on_every_side():
    """7.5% of the picture's larger side, so the drawing spans 85% of it, as a product picture is held to."""
    import types

    tall = types.SimpleNamespace(width=50.0, height=100.0)
    scale, pad = render_raster.scale_for(tall, {"size": "512x512"}, render_raster.DEFAULT_MARGIN)
    assert pad == pytest.approx(render_raster.DEFAULT_MARGIN * 512)
    assert tall.height * scale == pytest.approx((1 - 2 * render_raster.DEFAULT_MARGIN) * 512)
    # The narrower side is padded as much, and is narrower for it.
    assert tall.width * scale + 2 * pad == pytest.approx(256 * 0.85 + 2 * pad)
    # No margin is the drawing edge to edge, as it was.
    assert render_raster.scale_for(tall, {"size": "512x512"}) == (5.12, 0.0)


@pytest.mark.parametrize("turn", [(0, 0, 0), (0, 0, 45), (30, 60, 90)])
def test_a_shaded_picture_keeps_the_object_inside_its_margin_at_any_turn(tmp_path, turn):
    """Framed on the sphere about the object, so that no turn of it - no frame of a video - leaves the picture."""
    path = str(tmp_path / "cube.png")
    request = {"wrapped": _box(20, 20, 20), "style": "shaded", "size": "160x90", "antialias": 1, "turn": list(turn)}
    result = render_png.process(path, request)
    assert result["success"], result.get("exception")
    margins, (width, height) = _margins(path)
    # The narrower side is the bound: its margins at least the default's.
    assert min(margins[2], margins[3]) >= render_raster.DEFAULT_MARGIN * height - 1
    assert min(margins[0], margins[1]) > 0


def test_a_margin_of_nought_frames_the_sphere_edge_to_edge(tmp_path):
    """Without perspective, a sphere framed with no margin spans the narrower side exactly."""
    camera_height = raster_scene.frame_height(10.0, 2.0, margin=0.0)
    assert camera_height == pytest.approx(10.0)
    assert raster_scene.frame_height(10.0, 0.5, margin=0.25) == pytest.approx(40.0)
    # In perspective, the sphere's outline is the cone what is left of the side subtends.
    distance = raster_scene.frame_distance(10.0, 1.0, fov=90.0, margin=0.0)
    assert distance == pytest.approx(10.0 / math.sin(math.radians(45.0)))
    with pytest.raises(render_raster.OptionError):
        render_raster.margin_of({"margin": 0.5})


def test_a_picture_style_that_is_not_one_is_refused(tmp_path):
    result = render_png.process(str(tmp_path / "box.png"), {"wrapped": _box(), "style": "painted"})
    assert not result["success"] and "'style' is one of lines, shaded" in result["exception"]


def test_without_perspective_what_is_further_is_as_large(tmp_path):
    """Two equal cubes, one behind the other's plane: as wide as each other without perspective, not with it."""
    import build123d as b3d

    near = b3d.Pos(-15, -20, 0) * b3d.Box(10, 10, 10)
    far = b3d.Pos(15, 20, 0) * b3d.Box(10, 10, 10)
    request = {
        "wrapped": b3d.Compound([near, far]).wrapped,
        "style": "shaded",
        "size": "200x100",
        "antialias": 1,
        "viewport_origin": [0, -100, 0],
        "viewport_up": [0, 0, 1],
    }

    def widths(perspective):
        path = str(tmp_path / ("p%g.png" % perspective))
        result = render_png.process(path, dict(request, perspective=perspective))
        assert result["success"], result.get("exception")
        covered = (_pixels(path) != 255).any(axis=2).any(axis=0)
        return int(covered[:100].sum()), int(covered[100:].sum())

    left, right = widths(0)
    assert abs(left - right) <= 1
    left, right = widths(50)
    assert left > right + 2


def test_a_shaded_picture_leaves_no_mesh_on_the_shape():
    """The files of one object may share a decoding: a shaded picture must neither use nor leave a mesh there."""
    from OCP.BRep import BRep_Tool
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS

    shape = _box()
    render_raster.Shaded({"wrapped": shape}, 64, 64).build([])
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        assert BRep_Tool.Triangulation_s(TopoDS.Face_s(explorer.Current()), TopLoc_Location()) is None
        explorer.Next()


def test_a_frame_of_a_video_is_the_picture_pc_render_draws(monkeypatch, tmp_path):
    """Frame k is the PNG of the fields the video reports, turned by 'speed' times k / fps more: to the pixel."""
    captured = []

    class Pipeline:
        def __init__(self, output, *args, **kwargs):
            self.output = output

        def run(self, frames, prefix=()):
            captured.extend(frame.copy() for frame in frames)
            with open(self.output, "wb") as stream:
                stream.write(b"video")
            return 0, len(captured)

    monkeypatch.setattr(video_encode, "launcher", lambda: "gst-launch-1.0")
    monkeypatch.setattr(video_encode, "has_element", lambda name: True)
    monkeypatch.setattr(video_encode, "Pipeline", Pipeline)
    shape = _box()
    result = render_video.process(
        str(tmp_path / "turn.mp4"),
        {
            "wrapped": shape,
            "container_format": "mp4",
            "size": "64x48",
            "fps": 4,
            "duration": 1,
            "speed": [0, 0, 45],
            "turn": [10, 0, 0],
            "antialias": 1,
            "threads": 2,
        },
    )
    assert result["success"], result.get("exception")
    picture = result["video"]["picture"]
    assert picture["style"] == "shaded" and picture["size"] == "64x48" and picture["background"] == "#1F1F1F"
    assert len(captured) == 4
    for index in (0, 3):
        turn = render_video.angles_at(picture["turn"], result["video"]["speed"], index / 4.0)
        path = str(tmp_path / ("frame%d.png" % index))
        drawn = render_png.process(path, {"wrapped": shape, **picture, "turn": list(turn)})
        assert drawn["success"], drawn.get("exception")
        assert (_pixels(path) == captured[index]).all(), index


def test_a_video_is_not_drawn_in_lines(tmp_path):
    result = render_video.process(
        str(tmp_path / "x.mp4"), {"wrapped": _box(), "container_format": "mp4", "style": "lines"}
    )
    assert not result["success"] and "'shaded' style" in result["exception"]


# ---------------------------------------------------------------------------
# With GStreamer
# ---------------------------------------------------------------------------


@needs_gstreamer
@pytest.mark.parametrize("name", VIDEO_TYPES)
def test_a_video_is_written_and_appended_to(tmp_path, name):
    """Every file type writes a video, and one appended to it carries on its turn where it can say where."""
    declared = dict(_builtin_render()["render"][name])
    request = {
        **{key: value for key, value in declared.items() if key not in output.RESERVED_KEYS},
        "wrapped": _box(),
        "size": "160x120",
        "fps": 10,
        "duration": 1,
        "antialias": 1,
        "threads": 2,
        "text": "PartCAD",
    }
    path = str(tmp_path / ("turn." + declared["extension"]))
    first = render_video.process(path, dict(request))
    assert first["success"], first.get("exception")
    assert first["files"] == []
    assert first["video"]["frames"] == 10
    assert first["video"]["end_angle"] == pytest.approx([0, 0, 30])

    second = render_video.process(path, dict(request, append=True))
    assert second["success"], second.get("exception")
    # Read a file, so it is not remembered.
    assert second["files"] is None
    assert second["video"]["appended_to"] == 10
    # Every container keeps where the turn stopped: in a tag, or in Ogg's
    # Vorbis comments.
    assert video_encode.keeps_state(declared["container_format"])
    assert second["video"]["start_angle"] == pytest.approx([0, 0, 30])
    assert second["video"]["end_angle"] == pytest.approx([0, 0, 60])
    assert video_encode.read_state(path, video_encode.discover(path)["text"]) == pytest.approx((0, 0, 60))
    assert not second.get("warnings")
    frames = list(video_encode.decode_frames(path, 160, 120, 10, limit=100))
    assert len(frames) == 20


@needs_gstreamer
def test_an_append_is_never_remembered(tmp_path):
    """Its first run has nothing to append to, and remembered, it was what every later run got back."""
    path = str(tmp_path / "turn.mp4")
    request = {
        "wrapped": _box(),
        "container_format": "mp4",
        "size": "64x48",
        "fps": 10,
        "duration": 0.5,
        "antialias": 1,
        "append": True,
    }
    first = render_video.process(path, dict(request))
    assert first["success"], first.get("exception")
    assert first["video"]["appended_to"] is None
    assert first["files"] is None


@needs_gstreamer
def test_a_soundtrack_is_cut_to_the_video(tmp_path):
    sound = tmp_path / "tone.wav"
    rate = video_encode.AUDIO_RATE
    tone = np.sin(np.arange(rate * 3) * 2 * math.pi * 440 / rate).astype(np.float32)[:, None].repeat(2, axis=1)
    video_encode.write_wav(str(sound), tone * 0.5)
    path = str(tmp_path / "turn.mp4")
    result = render_video.process(
        path,
        {
            "wrapped": _box(),
            "container_format": "mp4",
            "size": "160x120",
            "fps": 10,
            "duration": 1,
            "antialias": 1,
            "audio": {"path": "tone.wav", "start": 1, "fade_out": 0.2},
            "package_dir": str(tmp_path),
        },
    )
    assert result["success"], result.get("exception")
    found = video_encode.discover(path)
    assert found["audio"] and found["duration"] == pytest.approx(1.0, abs=0.1)


def test_without_gstreamer_nothing_is_drawn(monkeypatch, tmp_path):
    """A machine without GStreamer hears so before any frame is drawn, and how to get it."""
    monkeypatch.setattr(video_encode, "find_tool", lambda name=None, environ=None: None)
    monkeypatch.setattr(raster_scene, "Scene", lambda *args, **kwargs: pytest.fail("drew without GStreamer"))
    result = render_video.process(str(tmp_path / "x.mp4"), {"wrapped": None, "container_format": "mp4"})
    assert not result["success"]
    assert "GStreamer is not installed" in result["exception"] and "gstreamer1.0-plugins-good" in result["exception"]


def test_the_encoder_imports_where_a_frozen_bundle_does():
    """'pc healthcheck' loads 'video_encode.py' in the PartCAD that runs it, which may be a frozen bundle.

    A bundle carries only the standard library modules its own code imports, and
    this file is data to it, so a module only the sandbox side needs - 'wave' - is
    absent there: imported at the top, it took 'pc healthcheck' down in every
    bundle. And a wheel declares no numpy.
    """
    import subprocess

    script = (
        "import sys\n"
        "sys.modules['numpy'] = None\n"
        "sys.modules['wave'] = None\n"
        "sys.path.insert(0, %r)\n"
        "import video_encode\n"
        "video_encode.find_tool(video_encode.LAUNCH)\n" % RENDER_DIR
    )
    run = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr


@pytest.mark.skipif(os.name == "nt", reason="an executable is a file with an extension on Windows")
def test_find_tool_looks_where_it_is_told(tmp_path):
    tool = tmp_path / video_encode.LAUNCH
    tool.write_text("#!/bin/sh\n")
    tool.chmod(0o755)
    environ = {video_encode.ENV_VAR: str(tmp_path), "PATH": ""}
    assert video_encode.find_tool(video_encode.LAUNCH, environ=environ) == str(tool)
    environ = {video_encode.ENV_VAR: str(tool), "PATH": ""}
    assert video_encode.find_tool(video_encode.LAUNCH, environ=environ) == str(tool)
