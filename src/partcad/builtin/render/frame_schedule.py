#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The frames of a video, drawn on several threads, handed out in order, within a memory budget.

A frame is a picture 'raster_scene.Painter' draws, and drawing one is three
steps of very unequal size: its setup - the object projected and lit as the
turned camera sees it, a few per cent of the work - then its rows, then those
rows shrunk into the picture. The rows are almost all of it, and a band of them
is drawn exactly as the whole picture is (see 'raster_scene.rasterize'), so the
work is cut into **units**: a frame's setup, and each band of its rows.

**The earliest frame first.** The units wait in one queue, the setup of every
frame admitted first - it is short, and its bands cannot start without it - and
then the bands, the earliest frame's first. Every thread takes the unit at the
head, so they all work on the frame the encoder needs next while it has bands
left, and spill over onto the next one only as it runs out: frames come out
nearly in the order they are needed, and are handed out strictly in it.

**Within the budget.** A frame being drawn holds its buffers - several bytes
for every sample of it, at the size it is sampled at (see
'raster_scene.FrameBuffers') - and its setup; and a thread drawing a band
holds that band's working arrays. 'plan' fits as many threads and as many
frames at once as the budget holds, cutting a frame into bands small enough
that a thread's working memory is bounded however large the picture is; and a
frame is let in only while there is room for it. Frames done before the
encoder asks for them wait as pictures, a few at most (see 'Plan.lookahead').

**Never on disk.** A frame goes from its buffers into the encoder and is
dropped: nothing here keeps a frame anywhere, in a cache or a file - a video's
frames are big and will not be asked for again. What every frame is drawn
from - the scene - is built once and shared by all of them.
"""

import heapq
import math
import threading

import numpy as np

# How many samples a band of a frame holds, at most: what bounds the memory a
# thread drawing a band works in, however large the frame. Below a frame's
# size, so that the threads have bands of one frame to share; and large enough
# that what is worked out per band - which triangles reach it - stays a small
# part of drawing it.
BAND_SAMPLES = 1 << 19

# The memory a thread drawing a band works in, beyond the frame's buffers, is
# the larger of two things it does one after the other, as measured on a
# 1080x1920 frame at 'antialias: 2':
#
# - shading: per sample of the band a triangle covers, the colour worked out in
#   single precision with the weights, the corners and the offsets it is
#   blended from (see 'raster_scene._shade') - 92 bytes, with every sample
#   covered;
SHADE_BYTES = 96
# - rasterizing: per candidate pixel it looks at in one go, about forty bytes,
#   and never more than 'raster_scene.CHUNK' of them at once - however many
#   surfaces lie one behind another (ten nested boxes, twenty surfaces deep,
#   peaked at 42 MB a band where one box did at 36).
RASTER_BYTES = 48

# A frame's setup, per triangle: the corners on the screen, the planes they are
# interpolated with, their bounds and the colour each corner is lit to.
SETUP_BYTES = 175


class Plan:
    """How a video's frames are drawn: by how many threads, in bands of how many rows, how many at a time.

    'workers' threads; bands of 'band_rows' sampled rows, 'bands' to a frame;
    at most 'frames' frames drawn at once, and at most 'lookahead' frames
    started ahead of the one the encoder takes next. 'budget' is the memory it
    was fitted into (None: as much as it likes), and 'needed' the least a frame
    can be drawn in; 'fits' is whether the budget held even that.
    """

    def __init__(self, workers, band_rows, bands, frames, lookahead, budget, needed, frame_bytes, unit_bytes):
        self.workers = workers
        self.band_rows = band_rows
        self.bands = bands
        self.frames = frames
        self.lookahead = lookahead
        self.budget = budget
        self.needed = needed
        self.frame_bytes = frame_bytes
        self.unit_bytes = unit_bytes

    @property
    def fits(self):
        return self.budget is None or self.needed <= self.budget

    def peak(self):
        """The most memory the frames take at once, as planned: see 'plan'."""
        return self.frames * self.frame_bytes + self.workers * self.unit_bytes

    def describe(self):
        return "%d thread(s), %d band(s) of %d rows a frame, up to %d frame(s) at once (%.0f MB)" % (
            self.workers,
            self.bands,
            self.band_rows,
            self.frames,
            self.peak() / 1e6,
        )


def plan(painter, workers, budget=None, band_samples=BAND_SAMPLES):
    """The 'Plan' for drawing frames of 'painter' on up to 'workers' threads, within 'budget' bytes (None: no bound).

    Every thread and every frame is let in only while the budget has room for
    it, and never fewer than one of each: a budget too small for even one frame
    still gets its frames, one band at a time, and 'Plan.fits' says it did not
    fit.
    """
    import raster_scene

    ss = painter.ss
    width, height = painter.sampled_width, painter.sampled_height
    rows = max(ss, (max(1, band_samples // width) // ss) * ss)
    rows = min(rows, height)
    bands = int(math.ceil(height / float(rows)))
    samples = rows * width
    # What each thread takes on top of the frames: the band it draws, and a
    # picture done ahead of the encoder (see 'lookahead' below).
    unit_bytes = max(SHADE_BYTES * samples, RASTER_BYTES * raster_scene.CHUNK) + painter.width * painter.height * 3
    frame_bytes = painter.frame_bytes() + SETUP_BYTES * painter.scene.triangle_count
    needed = frame_bytes + unit_bytes

    workers = max(1, int(workers))
    if budget is not None:
        workers = max(1, min(workers, int((budget - frame_bytes) // unit_bytes)))
    if workers == 1:
        # One thread draws one frame at a time, in one set of buffers.
        frames = 1
    else:
        # Enough frames at once that every thread has a band to draw - and one
        # more, whose setup is worked out while the last bands of the one before
        # are drawn.
        frames = int(math.ceil(workers / float(bands))) + 1
        if budget is not None:
            frames = max(1, min(frames, int((budget - workers * unit_bytes) // frame_bytes)))
    lookahead = frames + workers
    return Plan(workers, rows, bands, frames, lookahead, budget, needed, frame_bytes, unit_bytes)


class _Frame:
    """One frame being drawn: its buffers, its setup once it is worked out, its picture, and how many bands are left."""

    def __init__(self, index, buffers, bands):
        self.index = index
        self.buffers = buffers
        self.setup = None
        self.picture = None
        self.left = bands


def frames(painter, count, turn_of, the_plan):
    """The 'count' pictures 'painter' draws of the object turned by 'turn_of(index)', in order, as the plan says.

    A generator: each picture is drawn while the ones before it are being
    taken, and a picture is let go of as soon as it has been handed out. Stops
    the threads it started when it is closed or garbage collected, whatever
    stopped it - the encoder failing, say - and raises what a thread raised.
    """
    if the_plan.workers == 1:
        yield from _one_at_a_time(painter, count, turn_of, the_plan)
        return

    height = painter.sampled_height
    rows = the_plan.band_rows
    bands = [(first, min(first + rows, height)) for first in range(0, height, rows)]

    condition = threading.Condition()
    queue = []
    pool = []
    state = {"allocated": 0, "admitted": 0, "taken": 0, "error": None, "stop": False}
    drawing = {}
    done = {}

    def admit():
        # Under 'condition': let in frames while there are buffers for them and
        # the encoder is not too far behind.
        while state["admitted"] < count and state["admitted"] - state["taken"] < the_plan.lookahead:
            if pool:
                buffers = pool.pop()
            elif state["allocated"] < the_plan.frames:
                buffers = painter.new_buffers()
                state["allocated"] += 1
            else:
                break
            index = state["admitted"]
            drawing[index] = _Frame(index, buffers, len(bands))
            # A setup ranks before every band: see the header.
            heapq.heappush(queue, (0, index, -1))
            state["admitted"] += 1
        condition.notify_all()

    def work():
        while True:
            with condition:
                while not queue and not state["stop"] and state["error"] is None:
                    condition.wait()
                if state["stop"] or state["error"] is not None:
                    return
                kind, index, band = heapq.heappop(queue)
                frame = drawing[index]
            try:
                if kind == 0:
                    frame.setup = painter.setup(turn_of(index))
                    frame.picture = np.empty((painter.height, painter.width, 3), dtype=np.uint8)
                    with condition:
                        for number in range(len(bands)):
                            heapq.heappush(queue, (1, index, number))
                        condition.notify_all()
                    continue
                first, end = bands[band]
                painter.draw_band(frame.setup, frame.buffers, first, end)
                painter.shrink_band(frame.buffers, frame.picture, first, end)
                with condition:
                    frame.left -= 1
                    if not frame.left:
                        # Its picture is all it needs now; the buffers go to the
                        # next frame, and so does the room the setup took.
                        done[index] = frame.picture
                        pool.append(frame.buffers)
                        del drawing[index]
                        admit()
            except BaseException as e:  # pylint: disable=broad-except
                with condition:
                    if state["error"] is None:
                        state["error"] = e
                    condition.notify_all()
                return

    threads = [threading.Thread(target=work, name="partcad-frame-%d" % n, daemon=True) for n in range(the_plan.workers)]
    with condition:
        admit()
    for thread in threads:
        thread.start()
    try:
        for index in range(count):
            with condition:
                while index not in done and state["error"] is None:
                    condition.wait()
                if state["error"] is not None:
                    raise state["error"]
                picture = done.pop(index)
                state["taken"] = index + 1
                admit()
            yield picture
    finally:
        with condition:
            state["stop"] = True
            condition.notify_all()
        for thread in threads:
            thread.join()


def _one_at_a_time(painter, count, turn_of, the_plan):
    """'frames' on the one thread asking: each frame drawn band after band, in the one set of buffers."""
    height = painter.sampled_height
    rows = the_plan.band_rows
    buffers = painter.new_buffers()
    for index in range(count):
        setup = painter.setup(turn_of(index))
        picture = np.empty((painter.height, painter.width, 3), dtype=np.uint8)
        for first in range(0, height, rows):
            end = min(first + rows, height)
            painter.draw_band(setup, buffers, first, end)
            painter.shrink_band(buffers, picture, first, end)
        yield picture
