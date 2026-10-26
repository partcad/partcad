#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What the work of this process costs the machine, and what the machine has.

Two numbers decide whether PartCAD starts another task (see 'partcad.admission'):

  * The **capacity**: RAM, plus swap unless told to leave it out, or the limit
    of the cgroup this process runs in where that is smaller. Linux charges a
    cgroup more than the processes in it account for -- the page cache, kernel
    memory -- and the share of the capacity a daemon aims for is what absorbs
    that, as it absorbs other processes on an ordinary machine.

  * The **footprint**: this process, the processes it started (the sandboxes
    every wrapper runs in, and whatever they started), and the containers it
    runs work in. A process counts with what it holds of its own, which is
    where geometry lives: libraries mapped from files are shared between the
    sandboxes and held once by the page cache, and the share absorbs them.

This process is counted less what its allocators hold for reuse. Python gives
memory back to the system only when a whole arena of its small-object allocator
is empty, and C's 'malloc' when a free block is at the top of its heap; what
else is freed stays in the process, available to the next allocation and to
nothing else. So a daemon that frees the trees it no longer needs does not see
its resident size fall, and counted that way it would go on believing itself
full: admission would never resume. What 'reusable()' finds is counted as
available instead -- the next tree the daemon loads goes into it. 'release()'
first gives back what can be given back, after a collection: then what is left
is what the allocators really keep.

Nothing here is a guess about what a task will need. Every number is measured,
when it is asked for.
"""

import ctypes
import ctypes.util
import gc
import os
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional

import psutil

from . import logging as pc_logging

# The largest block glibc's 'malloc' serves from its heap rather than with a
# mapping of its own. glibc moves the threshold up each time a mapped block is
# freed, as far as 32 MB, so a process that has once freed a large block serves
# every later one of that size from the heap -- where freeing it keeps it in the
# process. Fixed, a large payload is unmapped the moment it is freed.
MMAP_THRESHOLD = 256 * 1024

# How often the containers' usage is asked of Docker at most. It is a request to
# the Docker daemon per container, which is cheap but not free, and what goes on
# in a container changes no faster than what goes on in a sandbox.
CONTAINER_REFRESH_SECONDS = 2.0

_M_MMAP_THRESHOLD = -3


@dataclass
class Footprint:
    """What this process's work holds, measured once."""

    # This process, as the kernel counts it.
    own: int
    # What of 'own' its allocators hold free for reuse.
    reusable: int
    # The processes it started, and theirs.
    children: int
    # The containers it runs work in.
    containers: int

    @property
    def usage(self) -> int:
        return max(0, self.own - self.reusable) + self.children + self.containers

    def describe(self) -> str:
        return "%s (this process %s, of it %s free for reuse; sandboxes %s; containers %s)" % (
            size(self.usage),
            size(self.own),
            size(self.reusable),
            size(self.children),
            size(self.containers),
        )


def size(value: int) -> str:
    """A number of bytes the way a person reads one."""
    if value >= 1024**3:
        return "%.1f GB" % (value / 1024**3)
    return "%d MB" % round(value / 1024**2)


# ---- capacity ----------------------------------------------------------------


def _read_int(path: str) -> Optional[int]:
    """The number in a cgroup file, or None for "max", a missing file or nonsense."""
    try:
        with open(path) as f:
            text = f.read().strip()
    except OSError:
        return None
    if not text or text == "max":
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _cgroup_paths(proc_cgroup: str = "/proc/self/cgroup") -> Dict[str, str]:
    """The cgroup this process is in, per hierarchy: '' for v2, 'memory' for v1's."""
    paths = {}
    try:
        with open(proc_cgroup) as f:
            lines = f.read().splitlines()
    except OSError:
        return paths
    for line in lines:
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        _, controllers, path = parts
        if controllers == "":
            paths[""] = path
        elif "memory" in controllers.split(","):
            paths["memory"] = path
    return paths


def _ancestors(root: str, path: str):
    """'root'/'path' and each directory above it, up to and including 'root'."""
    path = path.strip("/")
    while True:
        yield os.path.join(root, path) if path else root
        if not path:
            return
        path = os.path.dirname(path)


def cgroup_limits(root: str = "/sys/fs/cgroup", proc_cgroup: str = "/proc/self/cgroup"):
    """The memory and swap this process's cgroup allows: (memory, swap), None where unlimited.

    The tightest limit on the way up, since a cgroup is held to its parents'
    limits as well as its own. Inside a container with a cgroup namespace the
    path reads "/" and the root is the container's own cgroup, which the walk
    reads like any other.
    """
    paths = _cgroup_paths(proc_cgroup)
    memory = swap = None

    def tighter(current, value):
        return value if current is None or (value is not None and value < current) else current

    if "memory" in paths and os.path.isdir(os.path.join(root, "memory")):
        # v1: 'memsw' is memory and swap together, and a value past any machine
        # (the kernel's "unlimited" is a page short of 2**63) is no limit.
        for directory in _ancestors(os.path.join(root, "memory"), paths["memory"]):
            limit = _read_int(os.path.join(directory, "memory.limit_in_bytes"))
            if limit is not None and limit < 2**62:
                memory = tighter(memory, limit)
            both = _read_int(os.path.join(directory, "memory.memsw.limit_in_bytes"))
            if both is not None and both < 2**62 and limit is not None:
                swap = tighter(swap, max(0, both - limit))
        return memory, swap
    if "" in paths:
        for directory in _ancestors(root, paths[""]):
            memory = tighter(memory, _read_int(os.path.join(directory, "memory.max")))
            swap = tighter(swap, _read_int(os.path.join(directory, "memory.swap.max")))
    return memory, swap


def capacity(count_swap: bool = True) -> int:
    """RAM, plus swap when 'count_swap' says so, within the limits of this process's cgroup.

    On macOS swap has no fixed size -- the system creates swap files as it needs
    them -- so the swap counted there is what is allocated at the moment.
    """
    ram = psutil.virtual_memory().total
    swap = psutil.swap_memory().total if count_swap else 0
    if sys.platform.startswith("linux"):
        memory_limit, swap_limit = cgroup_limits()
        if memory_limit is not None:
            ram = min(ram, memory_limit)
        if swap_limit is not None:
            swap = min(swap, swap_limit)
    return ram + swap


# ---- the allocators ----------------------------------------------------------


class _Allocators:
    """C's and Python's allocators, reached through ctypes where the platform has them.

    Everything here degrades to "nothing known": a platform or a build without
    one of these functions reports nothing reusable and releases nothing, which
    is the footprint as the kernel counts it.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._libc = None
        self._mallinfo2 = None
        self._malloc_trim = None
        self._mallopt = None
        self._zone_statistics = None
        self._zone_relief = None
        self._pymalloc_stats = None
        self._memstream = None
        self._configured = False
        # glibc's free chunks right after the last trim. 'malloc_trim' gives
        # back the pages inside free chunks but leaves the chunks, so what it
        # reports free from then on is part resident and part not; only what has
        # been freed since is known to be resident.
        self._trimmed_free = 0
        self._load()

    def _load(self):
        try:
            libc = ctypes.CDLL(None) if os.name != "nt" else None
        except OSError:
            libc = None
        self._libc = libc
        if libc is None:
            return
        if hasattr(libc, "mallinfo2"):

            class _Mallinfo2(ctypes.Structure):
                _fields_ = [
                    (name, ctypes.c_size_t)
                    for name in (
                        "arena",
                        "ordblks",
                        "smblks",
                        "hblks",
                        "hblkhd",
                        "usmblks",
                        "fsmblks",
                        "uordblks",
                        "fordblks",
                        "keepcost",
                    )
                ]

            libc.mallinfo2.restype = _Mallinfo2
            libc.mallinfo2.argtypes = []
            self._mallinfo2 = libc.mallinfo2
        if hasattr(libc, "malloc_trim"):
            libc.malloc_trim.restype = ctypes.c_int
            libc.malloc_trim.argtypes = [ctypes.c_size_t]
            self._malloc_trim = libc.malloc_trim
        if hasattr(libc, "mallopt"):
            libc.mallopt.restype = ctypes.c_int
            libc.mallopt.argtypes = [ctypes.c_int, ctypes.c_int]
            self._mallopt = libc.mallopt
        if sys.platform == "darwin" and hasattr(libc, "malloc_zone_statistics"):

            class _ZoneStatistics(ctypes.Structure):
                _fields_ = [
                    ("blocks_in_use", ctypes.c_uint),
                    ("size_in_use", ctypes.c_size_t),
                    ("max_size_in_use", ctypes.c_size_t),
                    ("size_allocated", ctypes.c_size_t),
                ]

            self._zone_statistics_type = _ZoneStatistics
            libc.malloc_zone_statistics.restype = None
            libc.malloc_zone_statistics.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ZoneStatistics)]
            self._zone_statistics = libc.malloc_zone_statistics
            if hasattr(libc, "malloc_zone_pressure_relief"):
                libc.malloc_zone_pressure_relief.restype = ctypes.c_size_t
                libc.malloc_zone_pressure_relief.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
                self._zone_relief = libc.malloc_zone_pressure_relief
        # Python's own statistics, written to a stream in memory rather than to
        # standard error ('sys._debugmallocstats' writes there, and borrowing
        # the descriptor would swallow whatever another thread logged meanwhile).
        stats = getattr(ctypes.pythonapi, "_PyObject_DebugMallocStats", None)
        if stats is not None and hasattr(libc, "open_memstream") and hasattr(libc, "fclose"):
            stats.argtypes = [ctypes.c_void_p]
            stats.restype = ctypes.c_int
            libc.open_memstream.restype = ctypes.c_void_p
            libc.open_memstream.argtypes = [ctypes.POINTER(ctypes.c_char_p), ctypes.POINTER(ctypes.c_size_t)]
            libc.fclose.argtypes = [ctypes.c_void_p]
            libc.fclose.restype = ctypes.c_int
            libc.free.argtypes = [ctypes.c_void_p]
            libc.free.restype = None
            self._pymalloc_stats = stats
            self._memstream = libc.open_memstream

    def configure(self) -> None:
        """Fix glibc's mmap threshold, once, so that a freed payload is given back at once."""
        with self._lock:
            if self._configured:
                return
            self._configured = True
            if self._mallopt is not None and sys.platform.startswith("linux"):
                try:
                    self._mallopt(_M_MMAP_THRESHOLD, MMAP_THRESHOLD)
                except Exception:  # pylint: disable=broad-except
                    pass

    def pymalloc_free(self) -> int:
        """Bytes in free blocks and free pools of Python's small-object arenas."""
        if self._pymalloc_stats is None:
            return 0
        buf = ctypes.c_char_p()
        length = ctypes.c_size_t()
        with self._lock:
            stream = self._memstream(ctypes.byref(buf), ctypes.byref(length))
            if not stream:
                return 0
            try:
                self._pymalloc_stats(stream)
            finally:
                self._libc.fclose(stream)
            try:
                text = ctypes.string_at(buf, length.value).decode("utf-8", "replace")
            finally:
                self._libc.free(buf)
        return parse_pymalloc_free(text)

    def c_free(self) -> int:
        """Bytes C's allocator holds free, of those known to be resident."""
        if self._mallinfo2 is not None:
            info = self._mallinfo2()
            return max(0, info.fordblks - self._trimmed_free)
        if self._zone_statistics is not None:
            stats = self._zone_statistics_type()
            self._zone_statistics(None, ctypes.byref(stats))
            return max(0, stats.size_allocated - stats.size_in_use)
        return 0

    def trim(self) -> None:
        """Give back to the system what C's allocator can give back."""
        if self._malloc_trim is not None:
            self._malloc_trim(0)
            if self._mallinfo2 is not None:
                self._trimmed_free = self._mallinfo2().fordblks
        elif self._zone_relief is not None:
            self._zone_relief(None, 0)


def parse_pymalloc_free(text: str) -> int:
    """Free bytes in Python's arenas, from what '_PyObject_DebugMallocStats' writes.

    The free blocks of pools in use, and the pools no size class is using, both
    of which Python hands out again before it asks the system for more:

        # bytes in available blocks        =            6,608,512
        36 unused pools * 16384 bytes      =              589,824
    """
    free = 0
    for line in text.splitlines():
        if "=" not in line:
            continue
        label, _, value = line.partition("=")
        label = label.strip()
        if label == "# bytes in available blocks" or (label.endswith("bytes") and "unused pools" in label):
            try:
                free += int(value.strip().replace(",", ""))
            except ValueError:
                pass
    return free


_allocators = None
_allocators_lock = threading.Lock()


def allocators() -> _Allocators:
    global _allocators
    if _allocators is None:
        with _allocators_lock:
            if _allocators is None:
                _allocators = _Allocators()
    return _allocators


def configure_allocator() -> None:
    """Make this process give large blocks back as soon as they are freed (see MMAP_THRESHOLD)."""
    allocators().configure()


def reusable() -> int:
    """What this process's allocators hold free for its own next allocations."""
    found = allocators()
    try:
        return found.pymalloc_free() + found.c_free()
    except Exception:  # pylint: disable=broad-except
        return 0


def release() -> None:
    """Collect garbage, then give back to the system what the allocators can give back."""
    gc.collect()
    try:
        allocators().trim()
    except Exception:  # pylint: disable=broad-except
        pass


# ---- the footprint -----------------------------------------------------------


def _private(pid: int) -> Optional[int]:
    """A process's anonymous and shared-memory pages, from '/proc/<pid>/status', or None where there are none."""
    total = None
    try:
        with open("/proc/%d/status" % pid, "rb") as f:
            for line in f:
                if line.startswith((b"RssAnon:", b"RssShmem:")):
                    total = (total or 0) + int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return total


def process_size(process: psutil.Process) -> int:
    """What one process holds of its own: its private memory where the system says, its RSS otherwise.

    On Linux that is its anonymous memory (and shared memory it made), which is
    where geometry lives; the libraries mapped from files are left out, since
    the sandboxes share them and the page cache holds them once whoever counts
    them. PSS would count those once between the sandboxes too, but reading it
    walks the whole of a process's page tables -- 24 ms for a 3 GB sandbox, four
    of them twice a second -- where this is a few microseconds. On Windows it
    is the private bytes.
    """
    if sys.platform.startswith("linux"):
        private = _private(process.pid)
        if private is not None:
            return private
    try:
        info = process.memory_info()
    except (psutil.Error, OSError):
        return 0
    return getattr(info, "private", None) or info.rss


def children_size(process: Optional[psutil.Process] = None) -> int:
    """What every process this one started holds, theirs included."""
    process = process or psutil.Process()
    total = 0
    try:
        children = process.children(recursive=True)
    except (psutil.Error, OSError):
        return 0
    for child in children:
        total += process_size(child)
    return total


class _ContainerUsage:
    """What the containers this process runs work in hold, asked of Docker now and then.

    A process in a container is not this process's descendant on the host, and
    on a machine where Docker runs in a virtual machine it is not on the host at
    all, so it is measured the way 'docker stats' measures it: the container's
    memory less the file cache in it.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._at = 0.0
        self._value = 0

    def get(self, now: float) -> int:
        with self._lock:
            if now - self._at < CONTAINER_REFRESH_SECONDS:
                return self._value
            self._at = now
        value = self._measure()
        with self._lock:
            self._value = value
        return value

    @staticmethod
    def _measure() -> int:
        try:
            from partcad_utils import containers
        except ImportError:
            return 0
        total = 0
        for container in containers.in_use():
            total += container_size(container)
        return total


def container_size(container) -> int:
    """A container's memory less its file cache, as 'docker stats' reports it; 0 when unknown."""
    try:
        stats = container.client.api.stats(container.id, stream=False, one_shot=True)
    except Exception:  # pylint: disable=broad-except
        return 0
    memory = (stats or {}).get("memory_stats") or {}
    usage = memory.get("usage") or 0
    details = memory.get("stats") or {}
    cache = details.get("inactive_file")
    if cache is None:
        cache = details.get("total_inactive_file", 0)
    return max(0, usage - (cache or 0))


_containers = _ContainerUsage()


def footprint(now: Optional[float] = None) -> Footprint:
    """What this process's work holds now: itself less what it can reuse, its sandboxes, its containers."""
    if now is None:
        now = time.monotonic()
    me = psutil.Process()
    own = process_size(me)
    return Footprint(
        own=own,
        reusable=min(own, reusable()),
        children=children_size(me),
        containers=_containers.get(now),
    )


class Budget:
    """A share of the machine, measured against what this process's work holds.

    'measure' returns a 'Footprint' and 'capacity' a number of bytes; both are
    parameters so that the admission can be tested with scripted numbers.
    """

    def __init__(
        self,
        share: float,
        count_swap: bool = True,
        measure: Callable[[], Footprint] = None,
        capacity_of: Callable[[bool], int] = None,
    ):
        self.share = share
        self.count_swap = count_swap
        self._measure = measure or footprint
        self._capacity_of = capacity_of or capacity
        self._capacity = None

    @property
    def capacity(self) -> int:
        if self._capacity is None:
            try:
                self._capacity = int(self._capacity_of(self.count_swap))
            except Exception as e:  # pylint: disable=broad-except
                pc_logging.debug("The machine's memory could not be read: %s" % e)
                self._capacity = 0
        return self._capacity

    @property
    def limit(self) -> int:
        """The bytes this process's work aims to stay under."""
        return int(self.capacity * self.share)

    def measure(self) -> Footprint:
        return self._measure()
