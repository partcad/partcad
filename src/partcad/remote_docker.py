#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""One container per image, shared by everyone who asks for that image.

This is the part of ``partcad-service-remote-docker`` worth testing: which
container a request lands in, when a new one is started, and when an idle one is
retired. Talking to Docker is a detail the pool is handed rather than one it
performs, so all of that can be decided without a daemon.

The service exists so that the machine running PartCAD and the machine running
the containers need not be the same one. A client using the ``remote`` sandbox
sends its directories and its command over JSON-RPC; the service picks the
container for the image named in the request and forwards it there. That is the
whole of the difference from the ``docker`` sandbox, which mounts the files
instead and therefore needs the two machines to be one.

Keyed on the **image**, and nothing else. Two callers asking for the same image
get the same container -- which is the point: starting one costs seconds and a
few hundred megabytes of page cache, and a tree of parts would otherwise pay
that per part. Two callers asking for different images get different containers,
because an image is what a caller chose it for.
"""

import threading
import time
from typing import Callable, Optional

# How long a container may sit unused before the service retires it. Long
# enough that a person moving between two commands does not pay the start
# twice, short enough that a machine that has stopped being used stops holding
# containers open.
DEFAULT_IDLE_SECONDS = 30 * 60

# What PartCAD's own cleanup recognises. The same labels the images carry, for
# the same reason -- see 'partcad.docker_prune'.
LABELS = {"partcad.container": "1", "partcad.remote": "1"}


class Lease:
    """A container the service is holding for an image."""

    def __init__(self, image: str, container, endpoint: str):
        self.image = image
        self.container = container
        self.endpoint = endpoint
        self.used_at = time.monotonic()
        # How many requests are inside this container right now. Retirement
        # looks at it, so that a long analysis is not shut down underneath
        # itself by a sweep that fires while it runs.
        self.in_flight = 0

    def __repr__(self):
        return "<Lease %s at %s, %d in flight>" % (self.image, self.endpoint, self.in_flight)


class ContainerPool:
    """The containers this service is holding, one per image.

    ``start`` is what actually creates one, and is supplied rather than written
    here: the service passes something that talks to Docker, and a test passes
    something that does not.
    """

    def __init__(self, start: Callable[[str], Lease], idle_seconds: float = DEFAULT_IDLE_SECONDS):
        self._start = start
        self._idle_seconds = idle_seconds
        self._leases = {}
        # One lock over the map, and a per-image lock under it, so that two
        # requests for two images do not queue behind each other while one of
        # them pulls half a gigabyte. Starting a container is the slow thing
        # here, and it is exactly the thing that must not happen twice.
        self._lock = threading.Lock()
        self._starting = {}

    def acquire(self, image: str) -> Lease:
        """The container for ``image``, started if this is the first ask.

        Returns a lease with its in-flight count already raised: the caller
        releases it when the request is done, and until then no sweep will
        retire it.
        """
        with self._lock:
            lease = self._leases.get(image)
            if lease is not None:
                lease.used_at = time.monotonic()
                lease.in_flight += 1
                return lease
            gate = self._starting.setdefault(image, threading.Lock())

        # Outside the map lock: starting is slow, and holding the map lock
        # through it would stop every other image being served.
        with gate:
            with self._lock:
                lease = self._leases.get(image)
                if lease is not None:
                    lease.used_at = time.monotonic()
                    lease.in_flight += 1
                    return lease

            started = self._start(image)

            with self._lock:
                # Whoever is already in the map wins, so a race cannot leave two
                # leases for one image with only one of them ever released.
                lease = self._leases.setdefault(image, started)
                lease.used_at = time.monotonic()
                lease.in_flight += 1
                return lease

    def release(self, lease: Lease) -> None:
        """Say a request has finished with this container."""
        with self._lock:
            lease.in_flight = max(0, lease.in_flight - 1)
            lease.used_at = time.monotonic()

    def retire(self, now: Optional[float] = None) -> list:
        """Remove the containers nothing has used lately, and return them.

        A container with a request inside it is never retired, however long ago
        it was last *acquired*: a long analysis holds its lease for the whole of
        its run, and a sweep that fired in the middle would take the container
        out from under it.
        """
        if now is None:
            now = time.monotonic()

        retired = []
        with self._lock:
            for image, lease in list(self._leases.items()):
                if lease.in_flight > 0:
                    continue
                if now - lease.used_at < self._idle_seconds:
                    continue
                del self._leases[image]
                retired.append(lease)

        for lease in retired:
            try:
                lease.container.remove(force=True)
            except Exception:
                # A container somebody already removed is the outcome asked for.
                pass
        return retired

    def leases(self) -> list:
        with self._lock:
            return list(self._leases.values())

    def shutdown(self) -> list:
        """Retire everything, whatever its age. What the service does on the way out."""
        with self._lock:
            leases = list(self._leases.values())
            self._leases.clear()

        for lease in leases:
            try:
                lease.container.remove(force=True)
            except Exception:
                pass
        return leases
