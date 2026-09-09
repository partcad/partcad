#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Which container a request lands in, and when one is started or retired.

The whole reason `remote_docker.ContainerPool` takes a `start` callable rather
than talking to Docker is so that this can be decided without a daemon: what is
worth pinning is the routing and the lifecycle, and neither has anything to do
with whether a container really came up.

Two rules under all of it. One container per image, because starting one costs
seconds and a tree of parts would otherwise pay that per part; and a container
with a request inside it is never retired, because a sweep that fired in the
middle of a long analysis would take the container out from under it.
"""

import types

from partcad import remote_docker


def _pool(idle_seconds=60):
    """A pool whose containers are counters rather than containers."""
    started = []

    def start(image):
        container = types.SimpleNamespace(removed=False, image=image)
        container.remove = lambda force=False: setattr(container, "removed", True)
        started.append(image)
        return remote_docker.Lease(image, container, "127.0.0.1:%d" % (5000 + len(started)))

    pool = remote_docker.ContainerPool(start, idle_seconds=idle_seconds)
    pool.started = started
    return pool


# --------------------------------------------------------------------------- #
# One container per image                                                      #
# --------------------------------------------------------------------------- #


def test_the_same_image_is_the_same_container():
    """Starting one costs seconds; a tree of parts must not pay that per part."""
    pool = _pool()
    first = pool.acquire("ghcr.io/x/solver:abc")
    second = pool.acquire("ghcr.io/x/solver:abc")

    assert first is second
    assert pool.started == ["ghcr.io/x/solver:abc"]


def test_different_images_are_different_containers():
    """An image is what a caller chose it for."""
    pool = _pool()
    one = pool.acquire("ghcr.io/x/solver:abc")
    two = pool.acquire("ghcr.io/x/other:def")

    assert one is not two
    assert one.endpoint != two.endpoint
    assert len(pool.started) == 2


def test_acquiring_counts_the_request_and_releasing_uncounts_it():
    pool = _pool()
    lease = pool.acquire("ghcr.io/x/solver:abc")
    pool.acquire("ghcr.io/x/solver:abc")
    assert lease.in_flight == 2

    pool.release(lease)
    pool.release(lease)
    assert lease.in_flight == 0

    # Never negative, however many times somebody says they are done.
    pool.release(lease)
    assert lease.in_flight == 0


# --------------------------------------------------------------------------- #
# Retirement                                                                   #
# --------------------------------------------------------------------------- #


def test_an_idle_container_is_retired():
    pool = _pool(idle_seconds=60)
    lease = pool.acquire("ghcr.io/x/solver:abc")
    pool.release(lease)

    retired = pool.retire(now=lease.used_at + 61)
    assert retired == [lease]
    assert lease.container.removed is True
    assert pool.leases() == []


def test_a_container_still_working_is_never_retired():
    """However long ago it was acquired. A long analysis holds its lease throughout."""
    pool = _pool(idle_seconds=60)
    lease = pool.acquire("ghcr.io/x/solver:abc")  # acquired, not released

    assert pool.retire(now=lease.used_at + 100000) == []
    assert lease.container.removed is False
    assert pool.leases() == [lease]


def test_a_container_used_recently_is_kept():
    pool = _pool(idle_seconds=60)
    lease = pool.acquire("ghcr.io/x/solver:abc")
    pool.release(lease)

    assert pool.retire(now=lease.used_at + 59) == []
    assert lease.container.removed is False


def test_a_retired_image_is_started_again_when_asked_for():
    """Retirement is not a refusal."""
    pool = _pool(idle_seconds=60)
    first = pool.acquire("ghcr.io/x/solver:abc")
    pool.release(first)
    pool.retire(now=first.used_at + 61)

    second = pool.acquire("ghcr.io/x/solver:abc")
    assert second is not first
    assert pool.started == ["ghcr.io/x/solver:abc"] * 2


def test_a_container_nobody_can_remove_is_still_forgotten():
    """The service must not hold a lease it cannot use because removal failed."""
    pool = _pool(idle_seconds=60)
    lease = pool.acquire("ghcr.io/x/solver:abc")
    pool.release(lease)

    def refuse(force=False):
        raise RuntimeError("container is gone already")

    lease.container.remove = refuse
    assert pool.retire(now=lease.used_at + 61) == [lease]
    assert pool.leases() == []


# --------------------------------------------------------------------------- #
# Shutting down                                                                #
# --------------------------------------------------------------------------- #


def test_shutdown_takes_everything():
    """Whatever its age, and whatever is in flight: the service is going away."""
    pool = _pool(idle_seconds=100000)
    one = pool.acquire("ghcr.io/x/a:1")
    two = pool.acquire("ghcr.io/x/b:1")

    assert set(pool.shutdown()) == {one, two}
    assert one.container.removed and two.container.removed
    assert pool.leases() == []


# --------------------------------------------------------------------------- #
# Starting one at a time                                                       #
# --------------------------------------------------------------------------- #


def test_one_image_is_started_once_under_concurrency():
    """Starting is the slow thing, and is exactly what must not happen twice.

    Two threads asking for one image at once must not both pull it. The second
    waits on the first and then finds the lease already in the map.
    """
    import threading

    barrier = threading.Barrier(2)
    started = []

    def start(image):
        started.append(image)
        barrier.wait(timeout=5)  # both callers are inside acquire() by now
        container = types.SimpleNamespace(removed=False)
        container.remove = lambda force=False: None
        return remote_docker.Lease(image, container, "127.0.0.1:5000")

    pool = remote_docker.ContainerPool(start)
    results = []

    def ask():
        results.append(pool.acquire("ghcr.io/x/solver:abc"))

    threads = [threading.Thread(target=ask) for _ in range(2)]
    for thread in threads:
        thread.start()
    # The first caller is blocked in start(); let the barrier through so it can
    # finish, and the second then finds what it produced.
    barrier.wait(timeout=5)
    for thread in threads:
        thread.join(timeout=10)

    assert len(started) == 1, "the image was started more than once"
    assert results[0] is results[1]
    assert results[0].in_flight == 2
