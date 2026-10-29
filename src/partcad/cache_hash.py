#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-17
#
# Licensed under Apache License, Version 2.0.
#

import functools
import hashlib
import json
import os
import sys
import threading
import time
import uuid

from . import logging as pc_logging

# The format of what the caches store, mixed into every hash so that a change
# to it moves every entry to a new key instead of letting an old entry be read
# back under the new rules. Nothing is deleted: the stale files stay on disk
# until the cache is cleaned, they are simply never looked up again.
#
# Bump this whenever the bytes behind a cache key change meaning:
#   1: BREP payloads are zstd-compressed before being base64-encoded
#      (see wrappers/ocp_serialize.py).
#   2: the shape cache stores the payload alone - the outer layer (name, label,
#      placement) is stripped on write and wrapped back on read (see
#      cache_shape.py), and a lone shape is stored as raw BREP bytes.
#   3: a shape's key covers its whole configuration bar the keys that only
#      describe it, instead of 'parameters'/'offset'/'scale' alone (see
#      _NON_GEOMETRIC_CONFIG_KEYS in shape.py). Entries written under 2 were
#      keyed on too little - parts that differ only in a key the allow-list did
#      not name shared one - so none of them may be read back.
#   4: a shape entry carries what was recorded about the geometry as it was
#      built - its measurements, what its source file stated, what that file
#      said about individual elements - in the entry itself rather than in
#      sibling entries keyed on the same hash with a suffix (see cache_shape.py).
#      An entry written under 3 holds the geometry and nothing else, and there
#      is no way to tell that from one whose producer recorded nothing; reading
#      one back would report a part as having no size rather than as one nobody
#      has measured.
#   5: the tree an assembly is stored as changed shape twice over. An ASSY file's
#      root node is the assembly itself rather than a container inside it, so a
#      tree written under 4 has a level in it that nobody declared; and every node
#      now carries what its object declares about connections, which an entry
#      written under 4 has nowhere to have recorded (see shape_envelope.py). Both
#      are the payload's shape rather than the key's, so nothing about a
#      declaration changes when PartCAD does and an old entry would go on being
#      served: a viewer showing an assembly with two roots and no ports in it.
#   6: every value is hashed with a type tag and a length in front of it, rather
#      than as its bare bytes run together (see '_frame'). Under 5 the values
#      of a list, a dictionary's keys and values, and the files a shape depends
#      on were simply concatenated, so 'offset: [1, 23, 0]' and
#      'offset: [12, 3, 0]' were one key - two different parts, one entry.
#      A file is hashed by its size and a sample of its content rather than by
#      all of it (since replaced by a digest of all of it, which moved every
#      key with a file in it by itself - see 'add_filename'). The keys an
#      extrude, a sweep, a compound part and an ASSY assembly are stored under
#      also cover the keys of what they are built from now, so an entry written
#      under 5 was keyed on less than it needed to be.
#   7: a child node's "label" is what the assembly addresses the child by, and
#      nothing else: its own name, or - for a child nothing named - its position
#      in that assembly (see 'Assembly.link_name'). Under 6 such a child was
#      labelled after the object it held, which an ASSY file's unnamed 'links:'
#      made "<assembly>:links" - a label two of them shared, and not a name
#      anything could address. The label is now what a 'connect:', a 'map:' and
#      a filter name, so a reader of the tree can compose a request out of it.
#      The same case as 5, and for the same reason: it is the payload's shape
#      rather than the key's, so nothing about a declaration changes when
#      PartCAD does and an entry written under 6 would go on being served - a
#      panel offering to select links by names the daemon does not know.
#   8: a node placed by a connection that keeps a degree of freedom carries its
#      joint (see 'shape_envelope.KEY_JOINT' and 'partcad.joint'), which an
#      entry written under 7 has nowhere to have recorded. The same case as 5
#      and 7: the payload's shape rather than the key's, so an old entry would
#      go on being served - and an exporter of the mechanism would be handed
#      one with no joints in it, silently.
#   9: a shape's measurements carry where its volume is and how it is spread -
#      its centroid and its inertia at unit density (see 'shape_envelope') -
#      which is what a part's mass, centre of mass and inertia are worked out
#      from. An entry written under 8 measured the volume and nothing else, and
#      reading one back would give a part a mass with no centre and no inertia:
#      a URDF link that weighs what it should and turns as if it were a point.
#  10: every node an assembly or a scene places says what it holds - a part,
#      an assembly or a scene - and so does the root of every assembly and
#      scene; a scene's element marked 'fixed: true' says so too (see
#      'shape_envelope.KEY_KIND' and 'KEY_FIXED'). Those are what decide which
#      nodes are rigid bodies (docs/design/simulation.md, section 7). The same
#      case as 5, 7 and 8: the payload's shape rather than the key's, and an
#      entry written under 9 would go on being served with neither - a scene
#      placed in a scene read as one product, and a table bolted to the floor
#      read as free to fall.
#  11: a node placed by a rigid connection says what it is connected to (see
#      'shape_envelope.KEY_ATTACHED'), and a node a URDF places carries the
#      joint its URDF states. The same case as 5, 7, 8 and 10: an entry written
#      under 10 would go on being served without either - a part bolted to a
#      turning arm read as bolted to the base, and a robot read as one body.
#  12: a joint is what the native joint types make of its declaration
#      (docs/design/simulation.md, section 8.13): its bounds are the
#      parameter's range with 'limits:' laid over it side by side, a ball's
#      turns carry no range and the joint its one bound ('turnLimit'), a
#      'continuous' or '.inf' side is open, and a source says when 'limits:'
#      ran the other way to its parameter ("reversed"). The same case as 5, 7,
#      8, 10 and 11: an entry written under 11 would go on being served with
#      the old joints - a ball read as a composite for the ranges its turns
#      still carried, and a start against its stop said nowhere.
#  13: a joint's freedoms are in their declared order, whatever order
#      'toParams' names them in, and only a joint that is a ball carries a
#      ball's bound. The same case again: an entry written under 12 would go
#      on being served with a floating joint posed by a move first read as a
#      composite, and a revolute carrying the bound of the ball it overrode.
#  14: a 'motion:' that a more specific one overrides still brings along the
#      parameters it implies, as adjustments, so a locked joint ('connect:
#      {motion: fixed}') is welded where its 'toParams' start it. An entry
#      written under 13 would go on being served with the value dropped and
#      the part at nought.
#  15: a BREP payload is OCCT's binary format and carries no triangulation but
#      that of a face with no surface (see 'ocp_serialize.shape_to_brep'), and
#      a shape's measurements say how many of its shells no solid bounds
#      ('shape_envelope.METADATA_FREE_SHELLS'). This release could read an
#      entry written under 14, because it tells the formats apart by their
#      headers; an earlier release handed an entry written now could not, and
#      its sandbox would fail the shape. A tier shared across releases is
#      where the two meet, so they are kept apart.
#  16: an edge in no face whose only geometry is a 3D polygon keeps it in a
#      BREP payload ('ocp_serialize._holds_lone_polygon'). Under 15 it was
#      written without one, and an entry written then would go on being
#      served with an edge of nothing at all.
VERSION = 16

# What the version contributes to a hash. Namespaced so that it cannot be
# confused with the data hashed after it.
_VERSION_TAG = ("partcad-cache-v%d" % VERSION).encode()

# A file a shape is built from is keyed on a digest of all of its content
# ('file_digest'), and on nothing else about it. Not its path, nor its
# modification time, deliberately: both differ between two clones of one
# repository, and a key that covered either would never be found by another
# machine in a shared tier.
#
# It used to be the file's size and its first and last half megabyte, which
# kept a large STEP file from being read every time a key was asked for, at the
# price of every edit in between that kept the size: the part went on being
# served as it was before the edit, until '--cache-bypass'. The digest of the
# whole file is remembered instead, for as long as the file looks the same from
# outside ('file_identity'), so a file is read once per change rather than once
# per question - and a large one once per change on this machine, rather than
# once per process (see 'PERSIST_MIN_SIZE').
_DIGEST = hashlib.sha256
_READ_SIZE = 1 << 20

# How recently a file may have changed and still be trusted to look different
# the next time it changes: two writes inside one tick of the file system's
# clock can leave its size and every timestamp as they were. Two seconds is the
# coarsest clock a file system PartCAD runs on keeps (FAT); one more is margin.
# This is git's "racy" index entry, and 'source_key' goes by it too.
RACY_NS = 3 * 1_000_000_000

# Files at least this big have their digest kept on disk as well, under the
# cache directory, one small file per file hashed. Reading a big file is what a
# process starting cold would otherwise pay for every one of them, every time:
# a 200 MB STEP file is half a second of SHA-256 on a machine without the
# instructions for it, where a new process with nothing else to do loads
# PartCAD in about one. A small file is cheaper to hash again than the memo is
# to read, which is also where the old sample stopped and read the whole file.
PERSIST_MIN_SIZE = 1 << 20


def _header(tag: bytes, length: int) -> bytes:
    """What goes in front of every value: its type, and how long it is.

    Without it the hash is of the values run together, and different values
    run together into the same bytes: ["1", "23"] and ["12", "3"], a key "ab"
    with the value "c" and a key "a" with the value "bc". The length is what
    says where one value ends; the tag is what keeps 1 apart from "1".
    """
    return tag + length.to_bytes(8, "big")


def _frame(tag: bytes, data: bytes) -> bytes:
    return _header(tag, len(data)) + data


def _scalar(val) -> bytes:
    """A value that holds no others, framed with a tag saying what type it is."""
    if isinstance(val, str):
        return _frame(b"s", val.encode())
    if val is None:
        return _header(b"n", 0)
    if isinstance(val, bool):
        # Before 'int': a bool is one, and True is not 1 here.
        return _frame(b"t", str(val).encode())
    if isinstance(val, int):
        return _frame(b"i", str(val).encode())
    if isinstance(val, float):
        return _frame(b"r", repr(val).encode())
    return _frame(b"o", str(val).encode())


def file_stat(filename: str):
    """What a file looks like from outside, to tell later whether it changed.

    Modification time and size, which is what 'make' trusts too: a stat, not a
    read. None for a file that is not there.
    """
    try:
        st = os.stat(filename)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


# Python before 3.12 reports a file's creation time as its 'st_ctime' on
# Windows, from 'os.stat()' and 'os.fstat()' alike, and a creation time is not a
# change time: a file rewritten in place keeps it, and so - through NTFS's
# tunnelling - does one deleted and created again under the same name. There the
# change time is asked of Windows itself (see '_windows_change_time_ns').
_WINDOWS_CREATION_CTIME = os.name == "nt" and sys.version_info < (3, 12)

# 1601-01-01, where a Windows FILETIME counts from, to 1970-01-01, in its 100 ns.
_FILETIME_TO_UNIX = 116444736000000000


@functools.lru_cache(maxsize=None)
def _windows_basic_info():
    """'GetFileInformationByHandleEx' and the FILE_BASIC_INFO it fills, bound once."""
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class FileBasicInfo(ctypes.Structure):
        _fields_ = [
            ("CreationTime", ctypes.c_int64),
            ("LastAccessTime", ctypes.c_int64),
            ("LastWriteTime", ctypes.c_int64),
            ("ChangeTime", ctypes.c_int64),
            ("FileAttributes", wintypes.DWORD),
        ]

    function = ctypes.WinDLL("kernel32", use_last_error=True).GetFileInformationByHandleEx
    function.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    function.restype = wintypes.BOOL
    return ctypes, msvcrt, FileBasicInfo, function


def _windows_change_time_ns(fd: int):
    """NTFS's change time of the open file 'fd', in nanoseconds since the epoch, or None.

    What Python reports as 'st_ctime' from 3.12 on, through 'os.fstat()'. None
    whenever it cannot be had - the call fails, or the file system keeps no
    change time and answers nought - which leaves the file with no identity.
    """
    try:
        ctypes, msvcrt, FileBasicInfo, function = _windows_basic_info()
        info = FileBasicInfo()
        # 0 is FileBasicInfo in FILE_INFO_BY_HANDLE_CLASS.
        if not function(msvcrt.get_osfhandle(fd), 0, ctypes.byref(info), ctypes.sizeof(info)):
            return None
        if info.ChangeTime <= 0:
            return None
        return (info.ChangeTime - _FILETIME_TO_UNIX) * 100
    except Exception:  # pylint: disable=broad-except
        return None


def file_identity(f):
    """What says, without reading it, that the open file 'f' is still the one that was read - or None.

    The device and the inode say which file it is, and the size and the
    modification time that it was not written since. The change time covers
    what those can miss when a value worked out from the content is kept for
    long: a file deleted and created again can be given the same inode number
    back, and a tool that restores timestamps - tar, unzip, 'rsync -t', 'cp -p'
    - can give it the same modification time, while every write, rename and
    restore moves the change time to now. git's index keeps it for the same
    reason.

    Always of an open file, through 'os.fstat()', and never of a path through
    'os.stat()': the two do not agree on Windows. From Python 3.12 'os.stat()'
    goes on reporting the creation time as 'st_ctime', for compatibility, where
    'os.fstat()' reports NTFS's change time - so an identity kept from one and
    looked up with the other never matched on one runner, and on another, whose
    clock had given the file one timestamp for both, matched a file rewritten in
    place with its modification time put back. An identity taken the one way
    every time cannot disagree with itself.

    None where the change time cannot be had (see '_WINDOWS_CREATION_CTIME'):
    such a file has no identity, and nothing about it is remembered.
    """
    stat = os.fstat(f.fileno())
    changed = stat.st_ctime_ns
    if _WINDOWS_CREATION_CTIME:
        changed = _windows_change_time_ns(f.fileno())
        if changed is None:
            return None
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, changed)


def _now_ns() -> int:
    return time.time_ns()


def settled(identity: tuple) -> bool:
    """Whether 'identity' is old enough that the next change to the file will show in it (see RACY_NS)."""
    return _now_ns() - max(identity[3], identity[4]) > RACY_NS


class FileMemo:
    """Something worked out from a file's content, remembered for as long as the file looks the same.

    'compute' is handed the file, open for reading in binary, and what it
    returns is kept against the file's identity ('file_identity'): asked again
    while the file has not changed, the answer is the kept one and the file is
    opened but not read. Three things are never kept, so that a change is never
    hidden behind an answer about the file as it was:

    * an answer about a file that changed while it was being read - its
      identity before and after the read differ;
    * an answer about a file that changed so recently that the next change
      could leave it looking the same ('settled');
    * an answer about a file that has no identity on this platform.

    Either is worked out again next time, which costs only the file somebody
    is writing right now. 'load' and 'store', when given, are a second memory
    behind this one, asked before the file is read and told what was read.
    """

    def __init__(self, compute, load=None, store=None) -> None:
        self._compute = compute
        self._load = load
        self._store = store
        self._lock = threading.Lock()
        # absolute path -> (identity, value)
        self._known = {}

    def get(self, filename: str):
        """'compute' of 'filename', or the kept answer. Raises what open() raises."""
        path = os.path.abspath(filename)
        with open(path, "rb") as f:
            # Every identity of the file here is taken from this one handle,
            # the lookup's as much as the kept one's (see 'file_identity').
            before = file_identity(f)
            if before is not None:
                with self._lock:
                    known = self._known.get(path)
                if known is not None and known[0] == before:
                    return known[1]
                value = self._load(path, before) if self._load is not None else None
                if value is not None:
                    with self._lock:
                        self._known[path] = (before, value)
                    return value
            value = self._compute(f)
            after = file_identity(f)
        if before is None or after != before or not settled(after):
            return value
        if self._store is not None:
            self._store(path, after, value)
        with self._lock:
            self._known[path] = (after, value)
        return value

    def forget(self) -> None:
        """Drop every kept answer. For tests, which have to start from a cold process."""
        with self._lock:
            self._known.clear()


def _digest_of(f) -> bytes:
    hasher = _DIGEST()
    buffer = bytearray(_READ_SIZE)
    view = memoryview(buffer)
    while True:
        count = f.readinto(buffer)
        if not count:
            break
        hasher.update(view[:count])
    return hasher.digest()


def _digests_dir() -> str:
    """Where the digests of large files are kept between processes.

    Beside the cache tiers' own directories under the internal state directory
    - the process's, because a digest says what a file holds whoever asks, and
    so does not depend on the configuration a request was made with.
    """
    from .user_config import user_config

    return os.path.join(user_config.internal_state_dir, "cache", "digests")


def _digest_entry(path: str) -> str:
    name = hashlib.sha256(path.encode("utf-8", "surrogateescape")).hexdigest()[:32]
    return os.path.join(_digests_dir(), name)


def _load_digest(path: str, identity: tuple):
    """The digest kept on disk for 'path' as it is now, or None.

    The entry names the path and the identity it was read at, and is believed
    only when both are this file's now; anything else - another file whose
    path hashed the same, a file that has changed, an entry that is not one -
    is a miss and the file is read.
    """
    if identity[2] < PERSIST_MIN_SIZE:
        return None
    try:
        with open(_digest_entry(path), "r", encoding="utf-8") as f:
            entry = json.load(f)
        if entry.get("path") == path and tuple(entry.get("identity", ())) == identity:
            return bytes.fromhex(entry["digest"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return None


def _store_digest(path: str, identity: tuple, digest: bytes) -> None:
    if identity[2] < PERSIST_MIN_SIZE:
        return
    entry = _digest_entry(path)
    # Through a temporary file, as the files tier writes: another process may be
    # reading this entry, or writing it too.
    tmp = "%s.%s.tmp" % (entry, uuid.uuid4().hex)
    try:
        os.makedirs(os.path.dirname(entry), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"path": path, "identity": list(identity), "digest": digest.hex()}, f)
        os.replace(tmp, entry)
    except OSError as e:
        pc_logging.debug("Cannot keep the digest of %s: %s" % (path, e))
        try:
            os.unlink(tmp)
        except OSError:
            pass


_file_digests = FileMemo(_digest_of, load=_load_digest, store=_store_digest)


def file_digest(filename: str) -> bytes:
    """The SHA-256 of all of the content of 'filename'.

    Of the content only: the same bytes at another path, written at another
    time, on another machine, have the same digest, which is what lets a shared
    tier be shared. Read once per change of the file (see FileMemo), and for a
    large file once per change on this machine. Raises FileNotFoundError for a
    file that is not there.
    """
    return _file_digests.get(filename)


class CacheHash:
    def __init__(self, name: str, algo="md5", hasher=None, cache=False):
        self.name = name
        self.is_empty = True
        self.is_used = False
        # Set before the early return below: get() walks this list, and it is
        # reached with caching disabled too (a disabled hash still answers
        # None, it just never hashes anything).
        self.dependencies = []
        if not cache:
            # Caching is disabled, no initialization needed
            self.hasher = None
            return

        if hasher is not None:
            # Continues a hash that already carries the version below
            self.hasher = hasher.copy()
        else:
            if algo == "md5":
                self.hasher = hashlib.md5()
            elif algo == "sha1":
                self.hasher = hashlib.sha1()
            elif algo == "sha256":
                self.hasher = hashlib.sha256()
            else:
                raise ValueError(f"Unknown hash algorithm: {algo}")

            # Every hash starts from the cache format version. Deliberately not
            # a touch(): the version alone is not data to cache, so a hash that
            # got nothing else must still report itself as empty.
            self.hasher.update(_VERSION_TAG)

    def touch(self):
        if self.is_used:
            pc_logging.warning(f"Hash update after being used: {self.name}")
        self.is_empty = False

    # TODO(clairbee): do not "add_" anything to the hash immediately.
    # Instead, add the data to a list and then add it to the hash when needed.

    def add_dict(self, data: dict):
        if not self.hasher:
            # Caching is disabled
            return
        if data is None or len(data.keys()) == 0:
            # Do not consider it not being empty
            return

        def recurse(val):
            if isinstance(val, dict):
                self.hasher.update(_header(b"d", len(val)))
                # Keys framed with their type like any other value, so that
                # 1 and "1" are two keys here as they are to whoever reads the
                # dictionary - and sorted by that, which is total whatever the
                # keys are, where comparing the keys themselves is not.
                for encoded, k in sorted(((_scalar(k), k) for k in val.keys()), key=lambda pair: pair[0]):
                    self.hasher.update(encoded)
                    recurse(val[k])
            elif isinstance(val, (list, tuple)):
                self.hasher.update(_header(b"l", len(val)))
                for item in val:
                    recurse(item)
            elif isinstance(val, (set, frozenset)):
                self.hasher.update(_header(b"l", len(val)))
                for encoded in sorted(_scalar(item) for item in val):
                    self.hasher.update(encoded)
            else:
                self.hasher.update(_scalar(val))

        recurse(data)
        self.touch()

    def add_string(self, string: str):
        if not self.hasher:
            # Caching is disabled
            return
        if string is None:
            # Do not consider it not being empty
            return

        self.hasher.update(_frame(b"s", string.encode()))
        self.touch()

    def add_bytes(self, bytes: bytes):
        if not self.hasher:
            # Caching is disabled
            return
        if bytes is None or len(bytes) == 0:
            # Do not consider it not being empty
            return

        self.hasher.update(_frame(b"b", bytes))
        self.touch()

    def add_filename(self, filename: str):
        if filename is None:
            # Do not consider it not being empty
            return

        if not self.hasher:
            # Caching is disabled
            return

        try:
            # All of the content, by its digest (see 'file_digest'), which is
            # all a key needs of it and the same wherever the file is.
            self.hasher.update(_frame(b"h", file_digest(filename)))
        except FileNotFoundError:
            # Hashed as missing rather than skipped: skipped, a dependency that
            # is not there and one that is empty or absent from the list are all
            # the same key, and the entry built without the file goes on being
            # served once the file appears.
            self.hasher.update(_header(b"m", 0))
        self.touch()

    def set_dependencies(self, dependencies: list[str]) -> None:
        self.dependencies = dependencies

    def get(self) -> str | None:
        if not self.is_used:
            # TODO(clairbee): make I/O asynchronous and parallel, but maintain the order of hashing
            for filename in self.dependencies:
                self.add_filename(filename)

        self.is_used = True
        if self.is_empty:
            return None

        return self.hasher.hexdigest()
