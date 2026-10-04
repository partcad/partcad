#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Unit tests for where the port and interface names go on a projection.

'label_layout' runs inside the render sandbox but is pure Python and imports
nothing, so it is exercised here directly rather than through a render.
"""

import math
import os
import random
import sys

import partcad as pc

sys.path.append(os.path.join(os.path.dirname(pc.__file__), "wrappers"))
import label_layout  # noqa: E402

OBJECT = (0.0, 0.0, 60.0, 100.0)


def _crowd(count, width=40.0, height=3.5):
    """'count' names for ports scattered over the object, crowded the way the
    ports of a real part crowd: several of them on the very same spot."""
    labels = []
    for index in range(count):
        angle = 2 * math.pi * index / count
        target = (30.0 + 20.0 * math.cos(angle * 3), 50.0 + 30.0 * math.sin(angle * 2))
        labels.append(label_layout.Label(width + index % 3 * 10, height, [target, (30.0, 50.0)][: 1 + index % 2]))
    return labels


def _overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def test_nothing_to_place_is_nothing():
    assert label_layout.layout([], OBJECT) == []


def test_no_name_is_written_over_the_object():
    for count in (1, 2, 5, 12, 30):
        for label in label_layout.layout(_crowd(count), OBJECT):
            assert not _overlap(label.box(), OBJECT), count


def test_no_name_is_written_over_another():
    for count in (2, 5, 12, 30):
        labels = label_layout.layout(_crowd(count), OBJECT)
        for index, label in enumerate(labels):
            for other in labels[index + 1 :]:
                assert not _overlap(label.box(), other.box()), (count, index)


def test_no_leader_runs_through_another_name():
    labels = label_layout.layout(_crowd(20), OBJECT)
    for label in labels:
        for other in labels:
            if other is label:
                continue
            for target in label.targets:
                assert not label_layout._segment_hits_box(label.attach, target, other.box()), (label.targets, target)


def test_a_name_goes_on_the_side_its_port_is_on():
    right = label_layout.Label(30.0, 3.0, [(58.0, 50.0)])
    left = label_layout.Label(30.0, 3.0, [(2.0, 50.0)])
    label_layout.layout([right, left], OBJECT)
    assert right.box()[0] >= OBJECT[2]
    assert left.box()[2] <= OBJECT[0]


def test_the_names_go_all_the_way_around():
    """Spread around the object, not piled up on the side the ports favour."""
    labels = [label_layout.Label(20.0, 3.0, [(55.0, 50.0 + index)]) for index in range(8)]
    label_layout.layout(labels, OBJECT)
    assert any(label.box()[0] >= OBJECT[2] for label in labels)
    assert any(label.box()[2] <= OBJECT[0] for label in labels)


def test_a_leader_is_drawn_from_the_name_to_every_target():
    label = label_layout.Label(30.0, 3.0, [(10.0, 10.0), (50.0, 90.0)])
    label_layout.layout([label], OBJECT)
    box = label.box(label.height)
    # The leaders start at the edge of the name's own box.
    assert box[0] <= label.attach[0] <= box[2] and box[1] <= label.attach[1] <= box[3]


def test_a_target_off_the_object_is_kept_clear_too():
    """A port out in space - past the end of a shaft - is not written over."""
    far = (200.0, 50.0)
    labels = [label_layout.Label(30.0, 3.0, [far])] + _crowd(6)
    for label in label_layout.layout(labels, OBJECT):
        u0, v0, u1, v1 = label.box()
        assert not (u0 <= far[0] <= u1 and v0 <= far[1] <= v1)


def test_the_layout_is_the_same_every_time():
    """The drawings that carry these names are checked in."""
    first = [label.position for label in label_layout.layout(_crowd(15), OBJECT)]
    second = [label.position for label in label_layout.layout(_crowd(15), OBJECT)]
    assert first == second


def _faults(labels):
    """Every name written over another, and every leader run through one."""
    faults = []
    for index, label in enumerate(labels):
        for other_index, other in enumerate(labels):
            if other is label:
                continue
            if index < other_index and _overlap(label.box(), other.box()):
                faults.append((index, other_index, "name"))
            for target in label.targets:
                if label_layout._segment_hits_box(label.attach, target, other.box()):
                    faults.append((index, other_index, "leader"))
    return faults


def _random_crowd(seed):
    """Twenty to forty names, long and short, some of them interfaces leading
    to several ports scattered over and around the object."""
    rng = random.Random(seed)
    return [
        label_layout.Label(
            rng.choice([20, 40, 80, 150, 300]),
            rng.choice([2, 3.5, 6]),
            [(rng.uniform(-10, 70), rng.uniform(-10, 110)) for _ in range(rng.choice([1, 1, 1, 2, 4]))],
        )
        for _ in range(rng.randint(20, 40))
    ]


def test_a_crowd_of_long_names_never_falls_back_to_an_unchecked_spot():
    """Once every spot near a name's own slot is taken, the rest of the ring is
    searched, and the names with the most leaders are placed first - rather
    than a name being put down wherever its slot happened to be. Each of these
    seeds left a name or a leader on top of another before that."""
    for seed in (0, 4, 5, 6, 9, 10, 11):
        assert _faults(label_layout.layout(_random_crowd(seed), OBJECT)) == [], seed
