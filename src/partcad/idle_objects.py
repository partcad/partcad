#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The geometry this process keeps in memory between uses, and what goes first when memory is wanted.

What a shape built or read from the cache keeps is its envelope, on
'Shape._wrapped'; this is the list of who keeps one, in three kinds:

  * **Large** -- over 1 MB ('cacheMemoryDoubleCacheMaxEntrySize') with no
    persistent tier holding it, which is mostly an entry over the file tier's
    limit. Building it again is the only way back, so it is kept for as long as
    memory allows.
  * **Small** -- 1 MB or under, whatever holds it. Cheap to keep, and the most
    likely to be asked for again.
  * **Transient** -- over 1 MB, with a persistent tier holding it. Kept while
    anything uses it, so that the outputs of one object are made from one copy
    of it rather than each reading its own, and dropped as soon as nothing
    does: reading it back is cheap, and a second copy of it is not.

An object is in use while anything other than its shape holds its envelope: a
render waiting for a sandbox with the tree in hand, an assembly whose tree
places it. That is its reference count, which needs no bookkeeping from the
many callers of 'get_wrapped'. Freeing one in use would free nothing until its
user lets go, and would have the next asker read a second copy meanwhile.

When the admission (see 'partcad.admission') finds usage at its freeing mark it
asks 'free' for the excess: the transient objects nothing uses go first, then
the large idle ones, then the small ones, the least recently used first in each.
Each entry's size is what it was recorded at, which is only a guess at what
freeing it returns -- entries share payloads -- so the admission measures again
afterwards and asks for more if it has to.

Only what the memory tier was given is ever freed. A part made from a live shape
holds the only copy there is, and is never on a list.
"""

import sys
import threading
import weakref
from collections import OrderedDict
from typing import Optional

LARGE = "large"
SMALL = "small"
TRANSIENT = "transient"

# The order lists are freed in.
FREEING_ORDER = (TRANSIENT, LARGE, SMALL)


def _references(shape) -> int:
    """How many references 'shape''s envelope has, as counted from here."""
    return sys.getrefcount(shape._wrapped)


class _Calibration:
    pass


# What '_references' counts for an envelope only its shape holds. Measured rather
# than written down, through the same function, because what a count includes
# besides the shape's attribute -- the argument, the evaluation stack -- is the
# interpreter's business and has changed between versions.
_calibration = _Calibration()
_calibration._wrapped = {}
_IDLE_REFERENCES = _references(_calibration)
del _calibration


def in_use(shape) -> bool:
    """Whether anything but 'shape' itself holds the envelope it keeps."""
    return _references(shape) > _IDLE_REFERENCES


class _Entry:
    __slots__ = ("shape", "envelope_id", "size", "kind")

    def __init__(self, shape, envelope, size: int, kind: str):
        self.shape = weakref.ref(shape)
        self.envelope_id = id(envelope)
        self.size = size
        self.kind = kind


class IdleObjects:
    """The three lists, least recently used first in each."""

    def __init__(self):
        self._lock = threading.Lock()
        self._lists = {kind: OrderedDict() for kind in FREEING_ORDER}
        self._kind_of = {}

    def keep(self, shape, envelope, size: int, kind: str) -> None:
        """'shape' now keeps 'envelope', of 'size' bytes, as an object of 'kind'."""
        key = id(shape)
        with self._lock:
            self._discard_locked(key)
            self._lists[kind][key] = _Entry(shape, envelope, size, kind)
            self._kind_of[key] = kind

    def touch(self, shape) -> None:
        """'shape''s object was asked for: it is the most recently used of its list."""
        key = id(shape)
        with self._lock:
            kind = self._kind_of.get(key)
            if kind is not None:
                self._lists[kind].move_to_end(key)

    def forget(self, shape) -> None:
        """'shape' keeps nothing any more, or keeps it for a reason of its own."""
        with self._lock:
            self._discard_locked(id(shape))

    def _discard_locked(self, key) -> None:
        kind = self._kind_of.pop(key, None)
        if kind is not None:
            self._lists[kind].pop(key, None)

    def held(self) -> dict:
        """How many objects and bytes each list holds."""
        with self._lock:
            return {
                kind: {"objects": len(entries), "bytes": sum(e.size for e in entries.values())}
                for kind, entries in self._lists.items()
            }

    def free(self, excess: int, kinds=FREEING_ORDER) -> int:
        """Let go of idle objects until about 'excess' bytes are freed; return the bytes let go of.

        Transient objects nothing uses are let go of whatever 'excess' is: they
        were only kept while used.
        """
        freed = 0
        with self._lock:
            for kind in kinds:
                entries = self._lists[kind]
                for key in list(entries.keys()):
                    if kind != TRANSIENT and freed >= excess:
                        return freed
                    entry = entries[key]
                    outcome = self._release_locked(entry)
                    if outcome is None:
                        continue
                    del entries[key]
                    self._kind_of.pop(key, None)
                    freed += outcome
        return freed

    def sweep(self) -> int:
        """Let go of the transient objects nothing uses any more; return the bytes let go of.

        The entries of shapes that are gone, or keep something else now, go too,
        from every list: nothing else would take them off one that is not
        freeing.
        """
        with self._lock:
            for kind in (LARGE, SMALL):
                entries = self._lists[kind]
                for key in [key for key, entry in entries.items() if self._stale(entry)]:
                    del entries[key]
                    self._kind_of.pop(key, None)
        return self.free(0, kinds=(TRANSIENT,))

    @staticmethod
    def _stale(entry: _Entry) -> bool:
        shape = entry.shape()
        return shape is None or shape._wrapped is None or id(shape._wrapped) != entry.envelope_id

    @staticmethod
    def _release_locked(entry: _Entry) -> Optional[int]:
        """The bytes let go of with 'entry', 0 for an entry gone stale, None for one in use."""
        shape = entry.shape()
        if shape is None:
            return 0
        # Looked at without holding on to it, which would be one more user.
        if shape._wrapped is None or id(shape._wrapped) != entry.envelope_id:
            # Its shape keeps something else now, or nothing: the entry is stale.
            return 0
        if in_use(shape):
            return None
        shape._wrapped = None
        return entry.size


# The one this process keeps. Shapes of every context are on it: what is freed
# is decided by this process's memory, not by which context holds the shape.
idle_objects = IdleObjects()
