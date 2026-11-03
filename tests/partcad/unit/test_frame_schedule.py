#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The frames of a video, drawn in bands on several threads, in order, within a memory budget.

'frame_schedule.py' cuts every frame into its setup and bands of its rows, and
has threads draw them the earliest frame first; 'raster_scene.Painter' draws a
band exactly as it draws the whole picture. None of it may change a pixel: a
frame drawn in bands, on any number of threads, in any budget, is the frame
drawn whole on one. And the scene the frames are drawn from is handed back to
PartCAD and handed in again (see 'output.VIDEO_EXTENSIONS'), which must not
change one either. Imported by path, as the sandbox imports them.
"""

import os
import sys
import threading

import numpy as np
import pytest

import partcad as pc
from partcad import output

RENDER_DIR = output.BUILTIN_PATHS[output.BUILTIN_PACKAGES[output.RENDER]]
WRAPPERS_DIR = os.path.join(os.path.dirname(pc.__file__), "wrappers")
for directory in (WRAPPERS_DIR, RENDER_DIR):
    if directory not in sys.path:
        sys.path.append(directory)

import frame_schedule  # noqa: E402
import raster_scene  # noqa: E402
import render_raster  # noqa: E402
import render_video  # noqa: E402
import video_encode  # noqa: E402


def _plate():
    import build123d as b3d

    body = b3d.fillet(b3d.Box(60, 40, 20).edges(), 3)
    for x in (-20, 0, 20):
        body -= b3d.Pos(x, 0, 0) * b3d.Cylinder(5, 40)
    return body.wrapped


def _wire():
    import build123d as b3d

    return b3d.Polyline((-40, -30, 15), (40, -30, 15), (40, 30, 15), (0, 45, 25)).wrapped


def _box():
    import build123d as b3d

    return b3d.Box(20, 20, 20).wrapped


SCENES = {
    "solid": lambda: [("#C0C0C0", _plate())],
    # A surface behind another that lets it show through: the second layer.
    "see-through": lambda: [("#C0C0C0", _box()), ("#3080FF80", _plate())],
    # Lines among the faces, which reach across the rows of a band.
    "lines": lambda: [("#C0C0C0", _plate()), ("#FF0000", _wire())],
}


def _painter(groups, width=90, height=120, supersample=2):
    scene = raster_scene.Scene(groups, max(width, height))
    camera = raster_scene.Camera(distance=scene.sphere * 3, fov=50, height=scene.sphere)
    return raster_scene.Painter(scene, camera, width, height, (31, 31, 31), supersample=supersample, line_width=2)


def _turn(index):
    return raster_scene.rotation((10, 20, 37 * index))


# ---------------------------------------------------------------------------
# A band is drawn as the whole picture is
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(SCENES))
@pytest.mark.parametrize("supersample", (1, 2))
def test_a_frame_drawn_in_bands_is_the_frame_drawn_whole(name, supersample):
    """Bands of any height, drawn in any order into one set of buffers, make every pixel the whole picture makes."""
    painter = _painter(SCENES[name](), supersample=supersample)
    for index in range(3):
        whole = painter.draw(_turn(index))
        assert (whole != 31).any(), "nothing was drawn, so nothing is compared"
        setup = painter.setup(_turn(index))
        buffers = painter.new_buffers()
        for rows in (supersample, 7 * supersample, painter.sampled_height):
            picture = np.zeros_like(whole)
            bands = [(f, min(f + rows, painter.sampled_height)) for f in range(0, painter.sampled_height, rows)]
            for first, end in reversed(bands):
                painter.draw_band(setup, buffers, first, end)
                painter.shrink_band(buffers, picture, first, end)
            assert np.array_equal(picture, whole), (name, index, rows)


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------


def test_a_band_holds_whole_samples_of_pixels_and_no_more_than_it_may():
    painter = _painter(SCENES["solid"](), width=300, height=400, supersample=2)
    the_plan = frame_schedule.plan(painter, 4, band_samples=600 * 50)
    # A band is a whole number of pixel rows, sampled.
    assert the_plan.band_rows % 2 == 0
    assert the_plan.band_rows * painter.sampled_width <= 600 * 50
    assert the_plan.bands * the_plan.band_rows >= painter.sampled_height
    assert (the_plan.bands - 1) * the_plan.band_rows < painter.sampled_height


def test_without_a_budget_every_thread_has_a_band_and_the_next_frame_is_started():
    painter = _painter(SCENES["solid"](), width=300, height=400)
    the_plan = frame_schedule.plan(painter, 8, band_samples=600 * 100)
    assert the_plan.workers == 8 and the_plan.fits
    assert the_plan.frames * the_plan.bands >= the_plan.workers
    assert the_plan.lookahead == the_plan.frames + the_plan.workers


def test_a_budget_is_never_planned_over():
    painter = _painter(SCENES["solid"](), width=300, height=400)
    unbounded = frame_schedule.plan(painter, 8)
    for share in (0.2, 0.5, 0.8, 1.0, 3.0):
        budget = int(unbounded.peak() * share)
        the_plan = frame_schedule.plan(painter, 8, budget)
        if the_plan.fits and the_plan.peak() > budget:
            pytest.fail("planned %d bytes in a budget of %d" % (the_plan.peak(), budget))
        assert 1 <= the_plan.workers <= 8 and the_plan.frames >= 1


def test_a_budget_too_small_for_one_frame_still_draws_it_and_says_so():
    painter = _painter(SCENES["solid"]())
    the_plan = frame_schedule.plan(painter, 8, budget=1)
    assert not the_plan.fits
    assert the_plan.workers == 1 and the_plan.frames == 1
    assert "1 thread(s)" in the_plan.describe()


# ---------------------------------------------------------------------------
# The frames
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("workers", (1, 2, 5))
def test_frames_come_out_in_order_each_the_picture_drawn_alone(workers):
    painter = _painter(SCENES["see-through"]())
    alone = [painter.draw(_turn(index)) for index in range(7)]
    the_plan = frame_schedule.plan(painter, workers, band_samples=painter.sampled_width * 16)
    assert the_plan.bands > 1
    drawn = list(frame_schedule.frames(painter, 7, _turn, the_plan))
    assert len(drawn) == 7
    for index, (picture, expected) in enumerate(zip(drawn, alone)):
        assert np.array_equal(picture, expected), index


def test_a_budget_for_one_frame_at_a_time_draws_the_same_frames():
    painter = _painter(SCENES["solid"]())
    unbounded = frame_schedule.plan(painter, 4, band_samples=painter.sampled_width * 16)
    tight = frame_schedule.plan(
        painter, 4, unbounded.frame_bytes + 4 * unbounded.unit_bytes, painter.sampled_width * 16
    )
    assert tight.frames == 1 and tight.workers == 4
    assert [p.tobytes() for p in frame_schedule.frames(painter, 5, _turn, tight)] == [
        p.tobytes() for p in frame_schedule.frames(painter, 5, _turn, unbounded)
    ]


def test_no_more_frames_are_drawn_at_once_than_planned(monkeypatch):
    painter = _painter(SCENES["solid"]())
    the_plan = frame_schedule.plan(painter, 4, band_samples=painter.sampled_width * 8)
    the_plan.frames = 2
    made = []
    new_buffers = painter.new_buffers

    def counted():
        made.append(1)
        return new_buffers()

    monkeypatch.setattr(painter, "new_buffers", counted)
    assert len(list(frame_schedule.frames(painter, 9, _turn, the_plan))) == 9
    assert len(made) == 2


def _frame_threads():
    return [t for t in threading.enumerate() if t.name.startswith("partcad-frame-")]


def test_a_frame_that_fails_stops_the_others_and_says_why():
    painter = _painter(SCENES["solid"]())
    the_plan = frame_schedule.plan(painter, 3, band_samples=painter.sampled_width * 16)

    def turn_of(index):
        if index == 4:
            raise ValueError("frame four cannot be turned")
        return _turn(index)

    taken = []
    with pytest.raises(ValueError, match="frame four"):
        for picture in frame_schedule.frames(painter, 10, turn_of, the_plan):
            taken.append(picture)
    assert len(taken) <= 4
    assert not _frame_threads()


def test_an_encoder_that_stops_taking_frames_stops_the_threads():
    painter = _painter(SCENES["solid"]())
    the_plan = frame_schedule.plan(painter, 3, band_samples=painter.sampled_width * 16)
    frames = frame_schedule.frames(painter, 50, _turn, the_plan)
    next(frames)
    assert _frame_threads()
    frames.close()
    assert not _frame_threads()


# ---------------------------------------------------------------------------
# How many threads, in how much memory
# ---------------------------------------------------------------------------


def test_threads_are_what_the_request_says_or_one_per_core():
    assert render_video.threads_of({"threads": 3}) == 3
    assert 1 <= render_video.threads_of({}) <= 64
    with pytest.raises(render_raster.OptionError):
        render_video.threads_of({"threads": 1000})


def test_memory_is_what_the_request_says_or_a_share_of_what_is_free(monkeypatch):
    assert render_video.memory_budget({"memory": 300}) == 300 << 20
    monkeypatch.setattr(render_video, "available_memory", lambda: 8 << 30)
    assert render_video.memory_budget({}) == int(render_video.MEMORY_SHARE * (8 << 30))
    monkeypatch.setattr(render_video, "available_memory", lambda: None)
    assert render_video.memory_budget({}) == int(render_video.MEMORY_SHARE * render_video.MEMORY_UNKNOWN)


def test_this_machine_says_how_much_memory_is_free():
    free = render_video.available_memory()
    assert free is None or free > 0


# ---------------------------------------------------------------------------
# The scene, kept between videos
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(SCENES))
def test_a_scene_read_back_draws_every_picture_the_scene_drew(name):
    scene = raster_scene.Scene(SCENES[name](), 120, ["a warning building it gave"])
    data = scene.to_bytes(["a warning building it gave"])
    read, warnings = raster_scene.Scene.from_bytes(data)
    assert warnings == ["a warning building it gave"]
    assert read.pixels == 120 and read.triangle_count == scene.triangle_count
    camera = raster_scene.Camera(distance=scene.sphere * 3, fov=50, height=scene.sphere)
    for index in range(3):
        a = raster_scene.Painter(scene, camera, 90, 120, supersample=2, line_width=2).draw(_turn(index))
        b = raster_scene.Painter(read, camera, 90, 120, supersample=2, line_width=2).draw(_turn(index))
        assert np.array_equal(a, b), index


@pytest.mark.parametrize(
    "data, reason",
    (
        (b"", "not an .npz archive"),
        (b"nonsense", "not an .npz archive"),
        (np.zeros(3).tobytes(), "not an .npz archive"),
        ("a string", "not an .npz archive"),
        (b"PK\x03\x04 not an archive", "not a scene"),
    ),
)
def test_what_is_not_a_scene_is_refused(data, reason):
    # Bytes that are not an archive at all are refused as that, not as the
    # pickle NumPy would otherwise take them for.
    with pytest.raises(ValueError, match=reason):
        raster_scene.Scene.from_bytes(data)


def test_a_scene_naming_a_point_it_does_not_have_is_refused():
    scene = raster_scene.Scene(SCENES["solid"](), 120)
    scene.corners = scene.corners.copy()
    scene.corners[0, 0] = len(scene.points)
    with pytest.raises(ValueError, match="does not have"):
        raster_scene.Scene.from_bytes(scene.to_bytes())


def test_a_scene_of_another_format_is_refused(monkeypatch):
    scene = raster_scene.Scene(SCENES["solid"](), 120)
    monkeypatch.setattr(raster_scene.Scene, "FORMAT", 0)
    data = scene.to_bytes()
    monkeypatch.undo()
    with pytest.raises(ValueError, match="another format"):
        raster_scene.Scene.from_bytes(data)


def test_a_picture_is_drawn_from_the_scene_handed_in_only_when_it_is_for_that_size():
    request = {"wrapped": _plate(), "antialias": 1}
    built = render_raster.Shaded(request, 60, 80).build([])
    assert not built.reused
    data = built.scene_bytes()
    assert render_raster.Shaded(request, 60, 80).build([], scene=data).reused
    assert not render_raster.Shaded(request, 80, 100).build([], scene=data).reused
    assert not render_raster.Shaded(request, 60, 80).build([], scene=b"nonsense").reused


def _video(monkeypatch, tmp_path, **fields):
    """'render_video.process' with an encoder that keeps the frames rather than encoding them."""
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
    request = {
        "wrapped": _plate(),
        "container_format": "mp4",
        "size": "64x48",
        "fps": 4,
        "duration": 1,
        "antialias": 1,
        **fields,
    }
    result = render_video.process(str(tmp_path / "turn.mp4"), request)
    assert result["success"], result.get("exception")
    return result, captured


def test_a_video_hands_back_the_scene_it_built_when_asked_and_draws_the_same_from_it(monkeypatch, tmp_path):
    first, frames = _video(monkeypatch, tmp_path, scene_wanted=True, threads=3)
    scene = first.pop("scene")
    assert isinstance(scene, bytes) and not first["video"]["scene_reused"]
    assert first["video"]["threads"] == 3

    second, again = _video(monkeypatch, tmp_path, scene=scene, scene_wanted=False, threads=1)
    assert "scene" not in second and second["video"]["scene_reused"]
    assert second["video"]["threads"] == 1
    assert len(frames) == len(again) == 4
    for index, (a, b) in enumerate(zip(frames, again)):
        assert np.array_equal(a, b), index

    # Not asked for, not handed back: a scene is bytes nobody wants otherwise.
    third, _ = _video(monkeypatch, tmp_path)
    assert "scene" not in third
